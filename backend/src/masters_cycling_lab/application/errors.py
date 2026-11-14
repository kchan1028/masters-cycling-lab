"""Expected failures that the API turns into error responses. api/errors.py maps each class to an HTTP status."""


class ServiceError(Exception):
    """An expected failure with a stable code and a message that is safe to show to the user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotFound(ServiceError):
    """The thing asked for doesn't exist, or the document was deleted."""

    pass


class Conflict(ServiceError):
    """The request clashes with the current state, for example a reindex while one is already queued."""

    pass


class UnsupportedFile(ServiceError):
    """The upload is not a PDF."""

    pass


class UploadTooLarge(ServiceError):
    """The upload is larger than MAX_UPLOAD_BYTES."""

    pass


class ProviderUnavailable(ServiceError):
    """Answer generation is not configured or the provider failed. A service error, never an abstention."""


class GenerationFailed(ServiceError):
    """The model kept replying in a shape that failed validation."""
