from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services.pigmentation import calculate_ita, summarize_participant
from ..services.validation import InputValidationError

router = APIRouter(prefix="/api/ita", tags=["pigmentation"])


class ItaRequest(BaseModel):
    """Fields are typed Any so non-numeric text reaches the service and gets a clear message."""

    L: Any = None
    a: Any = None
    b: Any = None
    location: str | None = None  # optional: Finger dorsal / Finger palmar / Forehead / Other


class ParticipantRequest(BaseModel):
    measurements: list[Any] | None = None  # [{L, a, b, location?}, ...]
    location: str | None = None  # optional filter (needed when locations are mixed)


@router.post("/calculate")
def calculate(req: ItaRequest):
    """ITA = arctan((L* - 50) / b*) x 180/pi, plus objective pigmentation category."""
    try:
        return calculate_ita(req.model_dump())
    except InputValidationError as exc:
        return JSONResponse(status_code=422, content={"errors": exc.errors})


@router.post("/participant")
def participant(req: ParticipantRequest):
    """Participant-level ITA = median over repeated measurements (per location)."""
    try:
        return summarize_participant(req.measurements, req.location)
    except InputValidationError as exc:
        return JSONResponse(status_code=422, content={"errors": exc.errors})
