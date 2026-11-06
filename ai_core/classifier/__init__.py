"""Phase 8: verified DistilBERT inference contract and loader.

This package is importable without torch. Import the loader explicitly:
``from ai_core.classifier.loader import SessionClassifier``.
"""
from .contract import (  # noqa: F401
    LABELS, MAX_LENGTH, THRESHOLD, THRESHOLD_RULE, PREPROCESSING_VERSION, HIDDEN_SIZE,
)
from .errors import (  # noqa: F401
    ClassifierError, ModelArtifactError, InvalidInputError, InvalidOutputError,
)
