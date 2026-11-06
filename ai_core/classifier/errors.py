class ClassifierError(Exception):
    """Base class; Phase 9 can catch this to route to a fallback."""


class ModelArtifactError(ClassifierError):
    """A required artifact is missing, unreadable, corrupt or incompatible."""


class InvalidInputError(ClassifierError):
    """The session text is empty or not a string."""


class InvalidOutputError(ClassifierError):
    """The model produced non-finite or wrongly shaped output."""
