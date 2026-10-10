import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .api.ita import router as ita_router
from .api.perfusion import router as perfusion_router
from .api.reliability import router as reliability_router
from .api.signal import router as signal_router
from .api.collection import router as collection_router
from .api.conformal import router as conformal_router
from .api.validation import router as validation_router
from .api.research import router as research_router
from .api.dataset import router as dataset_router
from .api.features import router as features_router
from .api.live import router as live_router
from .api.model import router as model_router
from .ml.service import health_brief
from .pipeline.pipeline import dataset_info
from .config import APP_NAME, APP_VERSION, DISCLAIMER

app = FastAPI(title=f"{APP_NAME} API", version=APP_VERSION, description=DISCLAIMER)
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1)(:\d+)?$",          # local dev / preview servers on any port
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(reliability_router)
app.include_router(signal_router)
app.include_router(ita_router)
app.include_router(perfusion_router)
app.include_router(dataset_router)
app.include_router(collection_router)
app.include_router(conformal_router)
app.include_router(validation_router)
app.include_router(research_router)
app.include_router(features_router)
app.include_router(model_router)
app.include_router(live_router)


log = logging.getLogger("pigmentcal")


@app.exception_handler(Exception)
async def unexpected(_: Request, exc: Exception):
    """Last resort: always answer in JSON with an actionable message (never an HTML/plain 500), and log the cause."""
    log.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"errors": [{"field": "server", "code": "internal_error",
        "message": f"The service hit an unexpected problem ({type(exc).__name__}). Check the backend log for details."}]})


@app.exception_handler(RequestValidationError)
async def bad_request_shape(_: Request, exc: RequestValidationError):
    """Malformed bodies (wrong types) get the same human-readable shape as service errors."""
    errors = [{"field": str(e["loc"][-1]), "code": "invalid_type",
               "message": f"Invalid value for '{e['loc'][-1]}'."} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"errors": errors})


def _research_brief() -> dict:
    from .governance import research_gate
    g = research_gate.evaluate()
    return {k: g[k] for k in ("state", "label", "results_allowed", "verified_data", "failed_checks")}


def _conformal_brief() -> dict:
    from .conformal import fit as cfit
    try:
        return {"calibrated": bool(cfit.status()["fitted"])}
    except Exception:                                   # never let a status probe break the health check
        return {"calibrated": False}


@app.get("/api/health")
def health() -> dict:
    """Liveness plus the real dataset / model state. Nothing is generated or assumed. A part that cannot be read is reported
    under `problems` (status 'degraded') instead of failing the whole check or being reported as healthy."""
    problems: list[dict] = []

    def safe(name, fn, default):
        try:
            return fn()
        except Exception as exc:                                   # noqa: BLE001 - reported, never swallowed silently
            log.exception("health: %s failed", name)
            problems.append({"part": name, "message": f"{type(exc).__name__}: {exc}"[:200]})
            return default

    info = safe("dataset", dataset_info, {"loaded": False, "rows": 0, "participants": 0, "verified": False})
    if info.get("error"):
        problems.append({"part": "dataset", "message": info["error"]})
    note = (info["error"] if info.get("error") else f"Dataset loaded: {info.get('file')}") if info.get("loaded") else "No research dataset loaded."
    return {
        "status": "degraded" if problems else "ok",
        "app": APP_NAME,
        "version": APP_VERSION,
        "dataset": {"loaded": info["loaded"], "verified": info.get("verified", False), "rows": info["rows"], "participants": info["participants"], "note": note},
        "research_status": safe("research_status", _research_brief,
                                {"state": "UNVERIFIED_DATA", "label": "UNVERIFIED DATA — NOT A RESEARCH RESULT", "results_allowed": False, "verified_data": False, "failed_checks": ["status_unavailable"]}),
        "model": safe("model", health_brief, {"trained": False, "note": "Model status could not be read."}),
        "conformal": safe("conformal", _conformal_brief, {"calibrated": False}),
        "problems": problems,
        "disclaimer": DISCLAIMER,
    }
