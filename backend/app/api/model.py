from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..governance import research_gate
from ..ml import service, train
from ..ml.data import ModelError
from ..services.validation import InputValidationError

router = APIRouter(prefix="/api/model", tags=["model"])


class PredictRequest(BaseModel):
    """Raw (pre-engineering) inputs, on the same scales as the processed training data.
    Typed Any so non-numeric text reaches the validator and gets a clear message."""

    spo2: Any = None
    pi: Any = None
    ita: Any = None
    sqi: Any = None
    motion: Any = None
    model: str | None = None  # 'ridge' | 'lightgbm' | 'both' (default)


def _errors(status: int, errors: list[dict]):
    return JSONResponse(status_code=status, content={"errors": errors})


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ModelError as exc:
        return _errors(422, [exc.as_error()])
    except InputValidationError as exc:
        return _errors(422, exc.errors)


@router.post("/train")
def train_endpoint():
    """Train Ridge and LightGBM on the processed TRAIN split, evaluate on TEST only, save artifacts."""
    return _guard(train.train_models)


@router.get("/status")
def status_endpoint():
    return service.status()


@router.get("/metrics")
def metrics_endpoint():
    """Saved metrics from the last training run (model_metrics.json)."""
    try:
        return {**service.read_metrics(), "research_status": research_gate.brief()}
    except ModelError as exc:                        # not trained yet is a normal state, not an HTTP error
        return {"available": False, "errors": [exc.as_error()]}


@router.get("/predictions")
def predictions_endpoint(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
    """Saved test-set predictions (test_predictions.csv), paged."""
    try:
        return {**service.read_predictions(limit, offset), "research_status": research_gate.brief()}
    except ModelError as exc:
        return {"available": False, "errors": [exc.as_error()]}


@router.post("/predict")
def predict_endpoint(req: PredictRequest):
    """Model estimate of SaO2 for one reading."""
    return _guard(service.predict_one, req.model_dump())
