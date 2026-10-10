from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..ml.data import ARTIFACT_READ_ERRORS, ModelError
from ..validation import report

router = APIRouter(prefix="/api", tags=["validation"])


def _run(fn):
    try:
        return fn()
    except (ModelError, FileNotFoundError) as exc:
        err = exc.as_error() if isinstance(exc, ModelError) else {"field": "model", "code": "model_not_trained", "message": "Train the models first."}
        return JSONResponse(status_code=200, content={"available": False, "errors": [err]})
    except ARTIFACT_READ_ERRORS as exc:
        err = {"field": "model", "code": "artifacts_unreadable", "message": f"Saved results or models could not be read ({type(exc).__name__}). Train the models again."}
        return JSONResponse(status_code=200, content={"available": False, "errors": [err]})


@router.get("/validation/report")
def validation_report():
    """Test-split metrics with participant-level bootstrap CIs, subgroup tables, conformal coverage and plot data."""
    return _run(report.build_report)


@router.get("/xai/report")
def xai_report():
    """Ridge coefficients, LightGBM importance and exact TreeSHAP values (model behavior, not causality)."""
    return _run(report.build_xai)
