"""Phase 8 UNIT tests. These use STUBS/MOCKS (a fake model and tokenizer) - they do not prove the real
checkpoint works; see tests/integration/test_classifier_real.py for the real-artifact tests."""
import math

import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")

from ai_core.classifier import LABELS, MAX_LENGTH, THRESHOLD, InvalidInputError, InvalidOutputError, ModelArtifactError
from ai_core.classifier.loader import ClassifierConfig, SessionClassifier


class StubTokenizer:
    def __call__(self, texts, truncation=True, max_length=None, padding=False, return_tensors=None, verbose=True):
        rows = [[101] + [5] * min(len(t.split()), (max_length or 10**6) - 2 if truncation else 10**6) + [102] for t in texts]
        if return_tensors is None:
            return {"input_ids": rows}
        L = max(map(len, rows))
        ids = torch.zeros(len(rows), L, dtype=torch.long)
        am = torch.zeros_like(ids)
        for i, r in enumerate(rows):
            ids[i, :len(r)] = torch.tensor(r)
            am[i, :len(r)] = 1
        return {"input_ids": ids, "attention_mask": am}


class StubModel:
    def __init__(self, logits):
        self.logits, self.calls = logits, 0

    def __call__(self, ids, mask):
        self.calls += 1
        n = ids.shape[0]
        return torch.tensor([self.logits] * n, dtype=torch.float32)


def make(logits):
    return SessionClassifier(StubModel(logits), StubTokenizer(), "stub@v0")


def test_label_contract_is_the_trained_alphabetical_order():
    assert LABELS == ("Defense Evasion", "Discovery", "Execution", "Harmless", "Impact", "Other", "Persistence")
    assert len(LABELS) == 7 and MAX_LENGTH == 128 and THRESHOLD == 0.5


def test_sigmoid_not_softmax_and_scores_keyed_by_label():
    # logits [0]*7 -> sigmoid 0.5 for every label (softmax would give 1/7)
    p = make([0.0] * 7).predict("ls")
    assert list(p.scores) == list(LABELS)
    assert all(math.isclose(v, 0.5) for v in p.scores.values())


def test_threshold_is_inclusive_and_global():
    logits = [0.0, 1.0, -1.0, 0.0, -5.0, 5.0, 0.0]
    p = make(logits).predict("ls")
    assert p.predicted_labels == ("Defense Evasion", "Discovery", "Harmless", "Other", "Persistence")  # 0.5 >= 0.5 included
    assert p.threshold == 0.5


@pytest.mark.parametrize("bad", ["", "   ", "\n\t"])
def test_empty_input_rejected(bad):
    with pytest.raises(InvalidInputError):
        make([0.0] * 7).predict(bad)


@pytest.mark.parametrize("bad", [None, 5, b"ls", ["ls"]])
def test_non_string_rejected(bad):
    with pytest.raises(InvalidInputError):
        make([0.0] * 7).predict(bad)


@pytest.mark.parametrize("texts", ["ls", [], ()])
def test_batch_must_be_nonempty_sequence(texts):
    with pytest.raises(InvalidInputError):
        make([0.0] * 7).predict_batch(texts)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_logits_rejected(bad):
    with pytest.raises(InvalidOutputError):
        make([0.0, 0.0, bad, 0.0, 0.0, 0.0, 0.0]).predict("ls")


def test_wrong_output_dimension_rejected():
    with pytest.raises(InvalidOutputError):
        make([0.0] * 6).predict("ls")


def test_truncation_flag_and_token_count_from_stub():
    p = make([0.0] * 7).predict("a " * 500)
    assert p.truncated and p.token_count == MAX_LENGTH
    q = make([0.0] * 7).predict("a b")
    assert not q.truncated and q.token_count == 4


def test_batch_returns_one_prediction_per_text_and_model_called_once():
    c = make([0.0] * 7)
    out = c.predict_batch(["ls", "pwd", "id"])
    assert len(out) == 3 and c._model.calls == 1


def test_missing_artifacts_give_actionable_error(tmp_path):
    with pytest.raises(ModelArtifactError) as e:
        SessionClassifier.load(ClassifierConfig(model_dir=tmp_path))
    msg = str(e.value)
    assert "RESCUED_checkpoint.pth" in msg and "vocab.txt" in msg and "MODEL_DIR" in msg


def test_config_from_env_is_configurable_not_hardcoded(tmp_path):
    cfg = ClassifierConfig.from_env({"MODEL_DIR": str(tmp_path), "MODEL_CHECKPOINT": "x.pth",
                                     "MODEL_TOKENIZER_DIR": "tok", "MODEL_SHA256": "ab", "MODEL_TORCH_THREADS": "2"})
    assert cfg.checkpoint_path == tmp_path / "x.pth" and cfg.tokenizer_dir == tmp_path / "tok"
    assert cfg.expected_sha256 == "ab" and cfg.num_threads == 2
    assert ClassifierConfig.from_env({}).checkpoint_name == "RESCUED_checkpoint.pth"
