from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..pipeline.pipeline import dataset_info, process_dataset, read_quality
from ..ml.paths import get_paths
from ..pipeline.schema import PipelineError

router = APIRouter(prefix="/api/dataset", tags=["dataset"])


def _fail(exc: PipelineError, status: int = 422):
    return JSONResponse(status_code=status, content={"errors": [exc.as_error()], **exc.extra})


@router.get("/status")
def status():
    """What dataset (if any) is loaded. Nothing is assumed or generated."""
    info = dataset_info()
    from ..ml.data import research_quality
    q = research_quality(get_paths())
    readiness = (q or {}).get("readiness") or {"status": "NOT READY", "reasons": ["There are no valid real records."]}
    ready = readiness["status"] == "READY FOR TRAINING"
    return {**info, "readiness": readiness, "training_available": ready,
            "training_message": None if ready else "Training unavailable \u2014 real research dataset is not ready.",
            "status": "Loaded" if info["loaded"] else "No dataset loaded",
            "type": "LOADED DATASET" if info["loaded"] else "NONE"}


@router.get("/summary")
def summary():
    info = dataset_info()
    return {"Rows": info["rows"], "Participants": info["participants"], "Devices": info["devices"]}


@router.get("/quality")
def quality():
    q = read_quality()
    return q if q is not None else {"available": False, "message": "No processing run yet."}


@router.post("/process")
def process():
    """Validate, clean (reporting every dropped row), engineer features and split by participant."""
    try:
        return process_dataset()
    except PipelineError as exc:
        return _fail(exc)


@router.get("/limits")
def limits():
    return {"split": "60 / 20 / 20 by participant, stratified by ITA tertile",
            "data_source": "Build the research dataset on the Data Collection page (/api/collection)."}
