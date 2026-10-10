"""Compatibility entry point so `uvicorn main:app` (run from backend/) starts the same application as `uvicorn app.main:app`."""

from app.main import app  # noqa: F401
