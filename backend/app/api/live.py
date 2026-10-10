from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import LIVE_CONFIG
from ..services.live import analyze_live
from ..services.validation import InputValidationError

router = APIRouter(prefix="/api/live", tags=["live"])


class LiveRequest(BaseModel):
    """A rolling window of recent samples. Items are typed Any so bad values get a clear message."""

    ir: list[Any] | None = None          # infrared (or the single camera / recording channel)
    red: list[Any] | None = None         # optional second channel for the ratio-of-ratios SpO2 estimate
    t: list[Any] | None = None           # optional per-sample times in seconds (needed for irregular sources)
    fs: float | None = None              # sampling rate in Hz if t is not given
    accel: list[Any] | None = None       # optional motion: magnitude per sample, or [ax, ay, az] in g
    source: str | None = None            # 'esp32' | 'virtual' (software simulation) | 'camera' | 'file'
    invert: bool | None = None           # override the source's default signal polarity


@router.post("/analyze")
def analyze(req: LiveRequest):
    """Signal quality, PI, motion, pulse rate and (with a red channel) an uncalibrated SpO2 estimate for one window."""
    try:
        return analyze_live(req.model_dump())
    except InputValidationError as exc:
        return JSONResponse(status_code=422, content={"errors": exc.errors})


@router.get("/config")
def config():
    """Acquisition settings the client uses (window length, analysis interval)."""
    c = LIVE_CONFIG
    return {"window_seconds": c.window_seconds, "min_window_seconds": c.min_window_seconds,
            "analysis_interval_s": c.analysis_interval_s, "spo2_note": c.spo2_note,
            "invert_default": c.invert_default, "serial_protocol": "# comment lines, then <millis>,<red>,<ir>[,<ax>,<ay>,<az>] per sample (accelerometer in g)"}
