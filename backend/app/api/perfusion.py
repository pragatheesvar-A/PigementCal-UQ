from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..services.perfusion import calculate_pi, direct_pi, ita_pi_matrix
from ..services.validation import InputValidationError

router = APIRouter(prefix="/api/perfusion", tags=["perfusion"])


class AcDcRequest(BaseModel):
    """Fields are typed Any so non-numeric input reaches the service and gets a clear message."""

    ac_ir: Any = None
    dc_ir: Any = None
    source: str | None = None  # 'ac_dc' (default, manual entry) or 'ppg' (derived from the PPG module)


class DirectRequest(BaseModel):
    pi: Any = None


def _run(fn, payload):
    try:
        return fn(payload)
    except InputValidationError as exc:
        return JSONResponse(status_code=422, content={"errors": exc.errors})


@router.post("/calculate")
def calculate(req: AcDcRequest):
    """PI = (AC_IR / DC_IR) x 100, with perfusion state and warnings."""
    return _run(calculate_pi, req.model_dump())


@router.post("/direct")
def direct(req: DirectRequest):
    """Directly entered PI (manual mode)."""
    return _run(direct_pi, req.model_dump())


@router.get("/matrix")
def matrix():
    """Structure of the planned ITA x PI cells (preview only, no calibration)."""
    return ita_pi_matrix()
