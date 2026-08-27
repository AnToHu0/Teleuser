"""Public, deliberately redacted errors."""


class TeleuserError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self):
        return {"code": self.code, "message": self.message, **self.details}
