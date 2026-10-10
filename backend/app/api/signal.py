from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services.ppg import analyze_ppg
from ..services.validation import InputValidationError

router = APIRouter(prefix="/api/signal", tags=["signal"])


class AnalyzeRequest(BaseModel):
    """`ppg` items are typed Any so invalid entries (null, text) reach the service, which
    counts and interpolates them and reports the count instead of rejecting the whole file."""

    ppg: list[Any] | None = None
    sampling_rate: float | None = None
    motion: str | None = None  # optional manual override: LOW / MEDIUM / HIGH


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    """Band-pass filter, detect pulses, compute SQI, estimate motion (not clinical).
    Used for recorded files; live streams use /api/live/analyze."""
    try:
        return analyze_ppg(req.ppg, req.sampling_rate, req.motion)
    except InputValidationError as exc:
        return JSONResponse(status_code=422, content={"errors": exc.errors})
