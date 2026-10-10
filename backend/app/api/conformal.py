from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..governance import research_gate
from ..conformal import fit as cfit
from ..conformal import predict as cpredict
from ..ml.data import ModelError
from ..services.validation import InputValidationError

router = APIRouter(prefix="/api/conformal", tags=["conformal"])


class ConformalRequest(BaseModel):
    """Same inputs as the reliability check, plus the numeric SQI (0-100) and motion score (0-100) when the fitted models use them."""

    spo2: float | None = None
    pi: float | None = None
    ita: float | None = None
    signal_quality: str | None = None
    motion: str | None = None
    device: str | None = None
    sqi: Any = None
    motion_score: Any = None


def _errors(status: int, errors: list[dict]):
    return JSONResponse(status_code=status, content={"errors": errors})


@router.get("/status")
def status():
    return cfit.status()


@router.post("/calibrate")
@router.post("/fit")
def fit():
    """Fit the quantile models on TRAIN, calibrate on CALIBRATION, evaluate coverage on TEST. Explicit, never automatic."""
    try:
        return cfit.fit_conformal()
    except ModelError as exc:
        return _errors(422, [exc.as_error()])


@router.post("/predict")
def predict(req: ConformalRequest):
    """Conformal interval, lower bound and reliability state for one reading (ABSTAIN when evidence is insufficient)."""
    try:
        return cpredict.predict_one(req.model_dump())
    except ModelError as exc:
        if exc.code == "not_calibrated":                      # a normal state before calibration, not an error
            return JSONResponse(status_code=200, content={"available": False, "errors": [exc.as_error()]})
        return _errors(422, [exc.as_error()])
    except InputValidationError as exc:
        return _errors(422, exc.errors)


@router.get("/metrics")
def metrics():
    """Everything from the last fit: quantile models, calibration cells, coverage on the TEST split."""
    try:
        return {**cfit.read_metrics(), "research_status": research_gate.brief()}
    except ModelError as exc:                        # not calibrated yet is a normal state, not an HTTP error
        return {"available": False, "errors": [exc.as_error()]}


@router.get("/coverage")
def coverage():
    """Test-set coverage and mean width: overall, by ITA group, by PI group and by ITA × PI cell, with the calibration cell table."""
    try:
        m = cfit.read_metrics()
    except ModelError as exc:
        return {"available": False, "errors": [exc.as_error()]}
    return {**m["coverage"], "calibration": m["calibration"], "wording": m["wording"], "alpha": m["config"]["alpha"], "research_status": research_gate.brief()}
