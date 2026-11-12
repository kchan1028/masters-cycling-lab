class ServiceError(Exception):
    """An expected failure with a stable code and a message that is safe to show to the user."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class NotFound(ServiceError):
    pass


class Conflict(ServiceError):
    pass


class UnsupportedFile(ServiceError):
    pass


class UploadTooLarge(ServiceError):
    pass
