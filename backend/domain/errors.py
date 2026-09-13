class AppError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class Conflict(AppError):
    def __init__(self, code: str, message: str):
        super().__init__(code, message, 409)
