"""Errors for the dataset processing step. Column mapping now lives in app/collection (one entry point for data)."""


class PipelineError(Exception):
    """A user-fixable dataset problem with a stable code and a human-readable message."""

    def __init__(self, code: str, message: str, field: str = "dataset", extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.field, self.extra = code, message, field, extra or {}

    def as_error(self) -> dict:
        return {"field": self.field, "code": self.code, "message": self.message}
