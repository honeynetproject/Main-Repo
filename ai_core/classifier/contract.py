"""Frozen model contract constants (see docs/MODEL_CONTRACT.md).

Every value here is taken from the training notebooks or the saved artifacts,
and is re-checked at load time or by the tests. Do not change one without
re-running the parity tests.
"""
from ai_core.sessions.fullsession import RULE_ID as PREPROCESSING_VERSION  # "section0-v1"

# Order of MultiLabelBinarizer.classes_ at training time (models/data/processed/mlb.pkl),
# i.e. the order of the model's 7 output logits. It is alphabetical and differs from
# the D-010 listing; consumers must key scores by NAME, never by position.
LABELS = (
    "Defense Evasion",
    "Discovery",
    "Execution",
    "Harmless",
    "Impact",
    "Other",
    "Persistence",
)

MAX_LENGTH = 128        # tokenizer(..., truncation=True, max_length=128), head kept
THRESHOLD = 0.5         # global; section4 test_model(): pred = probs >= 0.5
THRESHOLD_RULE = "probability >= threshold"
HIDDEN_SIZE = 768
BASE_MODEL_NAME = "distilbert-base-uncased"
