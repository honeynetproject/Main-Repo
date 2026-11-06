"""Offline CPU inference for the trained DistilBERT multi-label classifier.

Architecture, tokenisation and activation reproduce the training notebook
(models/section4_language_model_exploration.ipynb): DistilBertModel + a
Linear(768, 7) head on the first-token output, sigmoid probabilities.
The model is loaded once, in SessionClassifier.load().
"""
from __future__ import annotations

import hashlib
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import torch
from transformers import DistilBertConfig, DistilBertModel, DistilBertTokenizer

from .contract import HIDDEN_SIZE, LABELS, MAX_LENGTH, PREPROCESSING_VERSION, THRESHOLD
from .errors import InvalidInputError, InvalidOutputError, ModelArtifactError

log = logging.getLogger("ai_core.classifier")

DEFAULT_CHECKPOINT = "RESCUED_checkpoint.pth"
DEFAULT_TOKENIZER_DIR = "distilbert-base-uncased"
_TOKENIZER_FILES = ("vocab.txt", "config.json")


@dataclass(frozen=True)
class ClassifierConfig:
    model_dir: Path
    checkpoint_name: str = DEFAULT_CHECKPOINT
    tokenizer_dirname: str = DEFAULT_TOKENIZER_DIR
    expected_sha256: Optional[str] = None   # verified at load when set
    num_threads: Optional[int] = None       # torch intra-op threads; None = torch default

    @classmethod
    def from_env(cls, env=None) -> "ClassifierConfig":
        env = os.environ if env is None else env
        threads = env.get("MODEL_TORCH_THREADS")
        return cls(
            model_dir=Path(env.get("MODEL_DIR", "models/models")),
            checkpoint_name=env.get("MODEL_CHECKPOINT", DEFAULT_CHECKPOINT),
            tokenizer_dirname=env.get("MODEL_TOKENIZER_DIR", DEFAULT_TOKENIZER_DIR),
            expected_sha256=env.get("MODEL_SHA256") or None,
            num_threads=int(threads) if threads else None,
        )

    @property
    def checkpoint_path(self) -> Path:
        return self.model_dir / self.checkpoint_name

    @property
    def tokenizer_dir(self) -> Path:
        return self.model_dir / self.tokenizer_dirname


class CustomDistilBERTModel(torch.nn.Module):
    """Same structure and parameter names as the training class (so the state dict loads strictly)."""

    def __init__(self, distilbert_model: DistilBertModel, num_labels: int):
        super().__init__()
        self.distilbert = distilbert_model
        self.classifier = torch.nn.Linear(distilbert_model.config.hidden_size, num_labels)

    def forward(self, input_ids, attention_mask):
        out = self.distilbert(input_ids=input_ids, attention_mask=attention_mask)
        return self.classifier(out.last_hidden_state[:, 0, :])


@dataclass(frozen=True)
class Prediction:
    scores: Dict[str, float]            # label name -> sigmoid probability
    predicted_labels: Tuple[str, ...]   # labels with score >= threshold, in model order
    threshold: float
    token_count: int                    # tokens fed to the model, incl. [CLS]/[SEP]
    truncated: bool                     # input exceeded MAX_LENGTH tokens
    model_version: str
    preprocessing_version: str
    latency_ms: float                   # tokenisation + forward + activation


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class SessionClassifier:
    def __init__(self, model, tokenizer, model_version: str, threshold: float = THRESHOLD):
        self._model = model
        self._tokenizer = tokenizer
        self.model_version = model_version
        self.threshold = threshold
        self.preprocessing_version = PREPROCESSING_VERSION

    # ---- loading -------------------------------------------------------
    @staticmethod
    def check_artifacts(cfg: ClassifierConfig) -> None:
        missing = [str(p) for p in [cfg.checkpoint_path] + [cfg.tokenizer_dir / n for n in _TOKENIZER_FILES]
                   if not p.is_file()]
        if missing:
            raise ModelArtifactError(
                "missing model artifact(s): " + ", ".join(missing)
                + f" (MODEL_DIR={cfg.model_dir}; set MODEL_DIR / MODEL_CHECKPOINT / MODEL_TOKENIZER_DIR)")
        for p in (cfg.checkpoint_path, cfg.tokenizer_dir / "vocab.txt", cfg.tokenizer_dir / "config.json"):
            if not os.access(p, os.R_OK):
                raise ModelArtifactError(f"model artifact not readable: {p}")

    @classmethod
    def load(cls, cfg: Optional[ClassifierConfig] = None) -> "SessionClassifier":
        cfg = cfg or ClassifierConfig.from_env()
        t0 = time.perf_counter()
        cls.check_artifacts(cfg)
        if cfg.num_threads:
            torch.set_num_threads(cfg.num_threads)
        digest = sha256_file(cfg.checkpoint_path)
        if cfg.expected_sha256 and digest != cfg.expected_sha256.lower():
            raise ModelArtifactError(
                f"checkpoint sha256 mismatch: expected {cfg.expected_sha256}, got {digest}")
        try:
            hf_cfg = DistilBertConfig.from_pretrained(str(cfg.tokenizer_dir), local_files_only=True)
            tokenizer = DistilBertTokenizer.from_pretrained(str(cfg.tokenizer_dir), local_files_only=True)
        except Exception as exc:  # noqa: BLE001 - re-raised as a typed artifact error
            raise ModelArtifactError(f"cannot load tokenizer/config from {cfg.tokenizer_dir}: {exc}") from exc
        if hf_cfg.model_type != "distilbert" or hf_cfg.dim != HIDDEN_SIZE:
            raise ModelArtifactError(
                f"incompatible base config: model_type={hf_cfg.model_type} dim={hf_cfg.dim}")
        try:
            # weights_only=True: the checkpoint holds only tensors/dicts/lists/ints.
            ckpt = torch.load(cfg.checkpoint_path, map_location="cpu", weights_only=True, mmap=True)
        except Exception as exc:  # noqa: BLE001
            raise ModelArtifactError(f"cannot read checkpoint {cfg.checkpoint_path}: {exc}") from exc
        state = ckpt.get("model_state_dict", ckpt) if isinstance(ckpt, dict) else None
        if not isinstance(state, dict) or "classifier.weight" not in state:
            raise ModelArtifactError("checkpoint has no model_state_dict/classifier.weight")
        if any(k.startswith("_orig_mod.") for k in state):
            raise ModelArtifactError("checkpoint has torch.compile '_orig_mod.' prefixes; not the verified artifact")
        shape = tuple(state["classifier.weight"].shape)
        if shape != (len(LABELS), HIDDEN_SIZE):
            raise ModelArtifactError(
                f"classifier head shape {shape} != ({len(LABELS)}, {HIDDEN_SIZE}) required by the label contract")
        model = CustomDistilBERTModel(DistilBertModel(hf_cfg), len(LABELS))
        try:
            model.load_state_dict(state, strict=True)   # the notebook used strict=False; we do not
        except RuntimeError as exc:
            raise ModelArtifactError(f"checkpoint incompatible with architecture: {exc}") from exc
        del ckpt, state
        model.eval()
        for p in model.parameters():
            p.requires_grad_(False)
        version = f"{cfg.checkpoint_name}@sha256:{digest[:16]}"
        log.info("classifier loaded model_version=%s load_s=%.2f threads=%d",
                 version, time.perf_counter() - t0, torch.get_num_threads())
        return cls(model, tokenizer, version)

    # ---- inference -----------------------------------------------------
    def predict(self, text: str) -> Prediction:
        return self.predict_batch([text])[0]

    def predict_batch(self, texts: Sequence[str]) -> List[Prediction]:
        if isinstance(texts, (str, bytes)) or not isinstance(texts, Sequence) or len(texts) == 0:
            raise InvalidInputError("texts must be a non-empty sequence of strings")
        for t in texts:
            if not isinstance(t, str):
                raise InvalidInputError(f"session text must be str, got {type(t).__name__}")
            if not t.strip():
                raise InvalidInputError("empty session text; nothing to classify")
        t0 = time.perf_counter()
        # Training tokenised without padding, then padded per batch to the longest row (right side,
        # pad id 0) with an attention mask; padding=True reproduces that.
        full = self._tokenizer(list(texts), truncation=False, verbose=False)["input_ids"]
        enc = self._tokenizer(list(texts), truncation=True, max_length=MAX_LENGTH,
                              padding=True, return_tensors="pt")
        with torch.inference_mode():
            logits = self._model(enc["input_ids"], enc["attention_mask"])
        if tuple(logits.shape) != (len(texts), len(LABELS)):
            raise InvalidOutputError(f"unexpected logits shape {tuple(logits.shape)}")
        if not bool(torch.isfinite(logits).all()):
            raise InvalidOutputError("non-finite logits; refusing to return a prediction")
        probs = torch.sigmoid(logits).tolist()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        out: List[Prediction] = []
        for row, ids_full, mask in zip(probs, full, enc["attention_mask"]):
            if not all(math.isfinite(p) and 0.0 <= p <= 1.0 for p in row):
                raise InvalidOutputError("probability outside [0,1] or non-finite")
            out.append(Prediction(
                scores=dict(zip(LABELS, row)),
                predicted_labels=tuple(l for l, p in zip(LABELS, row) if p >= self.threshold),
                threshold=self.threshold,
                token_count=int(mask.sum()),
                truncated=len(ids_full) > MAX_LENGTH,
                model_version=self.model_version,
                preprocessing_version=self.preprocessing_version,
                latency_ms=elapsed_ms / len(texts),
            ))
        return out
