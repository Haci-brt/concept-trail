class ApiError(Exception):
    """An error with a user-facing (Turkish) message and an HTTP status."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message
