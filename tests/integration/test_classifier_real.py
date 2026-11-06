"""Phase 8 REAL-ARTIFACT integration tests (CPU). They load the actual RESCUED_checkpoint.pth and the
local tokenizer/config from MODEL_DIR (default models/models). They are skipped, loudly, only if the
artifacts are absent. Tests marked MOCKED patch torch.load / hashing to inject faults."""
import json
import logging
import os
import pickle
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
np = pytest.importorskip("numpy")
pytest.importorskip("transformers")

from ai_core.classifier import LABELS, ModelArtifactError, InvalidInputError
from ai_core.classifier import loader as L
from ai_core.classifier.loader import ClassifierConfig, SessionClassifier
from ai_core.sessions.fullsession import build_full_session

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/model/reference_samples.jsonl"
CFG = ClassifierConfig.from_env({"MODEL_DIR": os.environ.get("MODEL_DIR", str(ROOT / "models/models"))})
TOL = 1e-5  # observed max |diff| vs the original pipeline is 1.8e-7 (see docs/phases/evidence/phase8_parity.json)

pytestmark = pytest.mark.skipif(
    not (CFG.checkpoint_path.is_file() and (CFG.tokenizer_dir / "vocab.txt").is_file()),
    reason=f"real model artifacts not found under {CFG.model_dir}")


@pytest.fixture(scope="module")
def clf():
    return SessionClassifier.load(CFG)


@pytest.fixture(scope="module")
def samples():
    return [json.loads(l) for l in open(FIXTURE)]


# ---- artifacts / loader ---------------------------------------------------
def test_required_artifacts_present_and_checked():
    SessionClassifier.check_artifacts(CFG)


def test_loads_on_cpu_in_eval_mode_without_grad(clf):
    params = list(clf._model.parameters())
    assert all(p.device.type == "cpu" and not p.requires_grad for p in params)
    assert not clf._model.training
    assert clf.model_version.startswith("RESCUED_checkpoint.pth@sha256:")


def test_label_order_matches_saved_training_label_encoder():
    pytest.importorskip("sklearn")
    mlb = pickle.load(open(ROOT / "models/data/processed/mlb.pkl", "rb"))
    assert tuple(mlb.classes_) == LABELS


def test_strict_load_every_checkpoint_key_matches(clf):
    ck = torch.load(CFG.checkpoint_path, map_location="cpu", weights_only=True, mmap=True)
    assert ck["num_labels"] == 7
    assert set(ck["model_state_dict"]) == set(clf._model.state_dict())


def test_repeated_inference_does_not_reload(monkeypatch, clf):
    def boom(*a, **k):
        raise AssertionError("model/tokenizer reloaded during inference")
    monkeypatch.setattr(L.torch, "load", boom)
    monkeypatch.setattr(L.DistilBertModel, "from_pretrained", boom, raising=False)
    monkeypatch.setattr(L.DistilBertTokenizer, "from_pretrained", boom)
    monkeypatch.setattr(L, "sha256_file", boom)
    for _ in range(5):
        clf.predict("uname -a ls")


def test_wrong_sha256_fails_explicitly():
    bad = ClassifierConfig(model_dir=CFG.model_dir, expected_sha256="0" * 64)
    with pytest.raises(ModelArtifactError, match="sha256 mismatch"):
        SessionClassifier.load(bad)


def test_corrupt_checkpoint_fails_explicitly(tmp_path):
    (tmp_path / "bad.pth").write_bytes(b"not a checkpoint")
    tok = tmp_path / "distilbert-base-uncased"
    tok.symlink_to(CFG.tokenizer_dir)
    with pytest.raises(ModelArtifactError, match="cannot read checkpoint"):
        SessionClassifier.load(ClassifierConfig(model_dir=tmp_path, checkpoint_name="bad.pth"))


def test_missing_weight_key_fails_strict_load_MOCKED(monkeypatch):
    real = torch.load

    def fake(*a, **k):
        ck = real(*a, **k)
        ck["model_state_dict"].pop("distilbert.transformer.layer.0.attention.q_lin.bias")
        return ck
    monkeypatch.setattr(L.torch, "load", fake)
    with pytest.raises(ModelArtifactError, match="incompatible"):
        SessionClassifier.load(CFG)


def test_wrong_head_shape_rejected_MOCKED(monkeypatch):
    real = torch.load

    def fake(*a, **k):
        ck = real(*a, **k)
        ck["model_state_dict"]["classifier.weight"] = torch.zeros(6, 768)
        return ck
    monkeypatch.setattr(L.torch, "load", fake)
    with pytest.raises(ModelArtifactError, match="head shape"):
        SessionClassifier.load(CFG)


# ---- preprocessing / input ------------------------------------------------
def test_tokenisation_matches_training_cache_exactly(clf, samples):
    for s in samples:
        ids = clf._tokenizer(s["training_text"], truncation=True, max_length=128)["input_ids"]
        assert ids == s["expected_input_ids"], s["sample_id"]


def test_phase7_builder_reproduces_training_text(samples):
    from ai_core.sessions.fullsession import clean_full_session, decode_session
    for s in samples:
        assert " ".join(clean_full_session(decode_session(s["raw_session"]))) == s["training_text"], s["sample_id"]


def test_phase7_commands_to_text_equal_training_text_for_simple_session():
    # Cowrie commands -> Phase 7 full_session text is what the classifier consumes
    assert build_full_session(["uname -a", "cat /proc/cpuinfo", "ls -la /tmp"]) == "uname -a cat /proc/cpuinfo ls -la /tmp"  # '-' is kept by the training rule


def test_long_input_truncated_to_128_keeping_head(clf, samples):
    long = [s for s in samples if len(s["expected_input_ids"]) == 128 and len(s["training_text"].split()) > 200]
    assert long
    p = clf.predict(long[0]["training_text"])
    assert p.truncated and p.token_count == 128


def test_short_input_not_padded_or_truncated(clf):
    p = clf.predict("ls")
    ids = clf._tokenizer("ls")["input_ids"]       # WordPiece: [CLS] l ##s [SEP]
    assert not p.truncated and p.token_count == len(ids) == 4


def test_unicode_and_odd_whitespace_do_not_crash(clf):
    p = clf.predict("ls\té中文   \n pwd")
    assert set(p.scores) == set(LABELS)


def test_empty_input_rejected_explicitly(clf):
    with pytest.raises(InvalidInputError):
        clf.predict("")


def test_batch_padding_equals_single_inference(clf, samples):
    texts = [s["training_text"] for s in samples[:6]]
    batch = clf.predict_batch(texts)
    for t, b in zip(texts, batch):
        single = clf.predict(t)
        assert max(abs(single.scores[l] - b.scores[l]) for l in LABELS) < TOL


# ---- output / parity ------------------------------------------------------
def test_output_dimension_and_probability_range(clf, samples):
    p = clf.predict(samples[0]["training_text"])
    assert list(p.scores) == list(LABELS) and all(0.0 <= v <= 1.0 for v in p.scores.values())


def test_known_samples_match_original_training_evaluation_outputs(clf, samples):
    """Packaged path (raw session -> Phase 7 text -> tokenizer -> model) vs probabilities saved by the
    original evaluation (models/models/eval/y_pred_probs.npy), held-out TEST split."""
    from ai_core.sessions.fullsession import clean_full_session, decode_session
    worst = 0.0
    for s in samples:
        assert s["split"] == "test"
        text = " ".join(clean_full_session(decode_session(s["raw_session"])))
        p = clf.predict(text)
        got = [p.scores[l] for l in LABELS]
        worst = max(worst, max(abs(a - b) for a, b in zip(got, s["expected_probs"])))
        assert tuple(l for l, v in zip(LABELS, s["expected_probs"]) if v >= 0.5) == p.predicted_labels, s["sample_id"]
    assert worst < TOL, worst


def test_each_sample_class_is_represented(samples):
    seen = {l for s in samples for l in s["true_labels"]}
    assert seen == set(LABELS)


# ---- logging / runtime ----------------------------------------------------
def test_no_raw_session_text_in_logs(caplog, clf):
    secret = "xyzzy-secret-token-12345"
    with caplog.at_level(logging.DEBUG):
        clf.predict(f"echo {secret}")
        SessionClassifier.load(CFG)
    assert secret not in caplog.text


def test_benchmark_procedure_emits_machine_readable_percentiles(clf, samples):
    import sys
    sys.path.insert(0, str(ROOT / "scripts/phase8"))
    import benchmark
    res = benchmark.run([s["training_text"] for s in samples], warmup=2, runs=12, batch=2, clf=clf)
    for key in ("p50", "p95"):
        assert res["batch1_ms"][key] > 0
    assert res["memory"]["peak_rss_mib"] > 0 and res["includes_tokenization"] is True
    json.dumps(res)
