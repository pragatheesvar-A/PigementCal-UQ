from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services.reliability import assess
from ..services.validation import InputValidationError

router = APIRouter(prefix="/api/reliability", tags=["reliability"])


class PredictRequest(BaseModel):
    """All fields optional at the schema level so the service can report every problem
    in a human-readable way (e.g. 'OBJECTIVE PIGMENTATION VALUE REQUIRED')."""

    spo2: float | None = None
    pi: float | None = None
    ita: float | None = None
    signal_quality: str | None = None
    motion: str | None = None
    device: str | None = None
    sqi: float | None = None  # optional 0-100 SQI from the signal module
    signal_source: str | None = None  # 'manual' or 'signal_module'
    ita_source: str | None = None  # 'manual' or 'pigmentation_module'
    pi_source: str | None = None  # 'manual', 'ac_dc' or 'ppg' (perfusion module)


@router.post("/predict")
def predict(req: PredictRequest):
    """Reliability state and reasons from signal quality, motion, perfusion and pigmentation (no uncertainty range)."""
    try:
        return assess(req.model_dump())
    except InputValidationError as exc:
        return JSONResponse(status_code=422, content={"errors": exc.errors})
