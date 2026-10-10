import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from ..collection import ingest, mapping as mp, merge, store
from ..collection.rules import CollectionError
from ..config import COLLECTION_CONFIG, CONSENT_NOTICE, LIVE_CONFIG
from ..ml.paths import get_paths

router = APIRouter(prefix="/api/collection", tags=["data-collection"])

TEMPLATES = {   # header rows only: no example values are provided, so nothing can be mistaken for data
    "ppg": "t_s,ir,red,ax,ay,az\n",
    "reference": "participant_id,session_id,timestamp,sao2\n",
    "pigmentation": "participant_id,session_id,L,a,b,ITA\n",
    "combined": "participant_id,session_id,timestamp,spo2,sao2,pi,ita,L,a,b,sqi,motion,device_id\n",
}


def _fail(exc: CollectionError, status: int = 422):
    return JSONResponse(status_code=status, content={"errors": [exc.as_error()], **exc.extra})


@router.get("/status")
def status():
    """What is staged, and how much REAL (built, validated) research data exists. Staged files are never called research data."""
    paths = get_paths()
    uploads = store.manifest(paths)
    q = merge.read_quality(paths)
    staged, problems = {}, []
    for k in store.TABLES:
        try:
            staged[k] = int(len(store.table(paths, k)))
        except (OSError, ValueError) as exc:
            staged[k] = 0
            problems.append({"table": k, "code": "staging_unreadable", "message": f"The staged {k} table could not be read ({type(exc).__name__}). Remove the affected upload and upload it again."})
    built_ids = {s["id"] for s in q["sources"]} if q else set()
    stale = bool(q) and built_ids != {u["id"] for u in uploads}
    n_valid = q["valid_records"] if q else 0
    # Records the research gate classifies as software-test / simulated data are never counted as real data.
    from ..governance import research_gate
    g = research_gate.evaluate(paths) if n_valid else None
    test_kind = bool(g) and (g["state"] in ("SOFTWARE_TEST_DATA", "SIMULATED_HARDWARE_DATA") or g.get("name_markers_found"))
    test_data = {"records": n_valid, "participants": q["participants"], "sessions": q["sessions"], "label": f"{n_valid} software-test records (not real data)"} if test_kind else None
    if test_kind:
        n_valid = 0
    return {
        "real_data": {"records": n_valid, "participants": 0 if test_kind else (q["participants"] if q else 0), "sessions": 0 if test_kind else (q["sessions"] if q else 0),
                      "label": f"REAL DATA: {n_valid} records" if n_valid == 0 else f"{n_valid} valid records"},
        "test_data": test_data,
        "built": q is not None, "stale": stale, "last_build": q, "problems": problems,
        "staged": {"ppg_windows": staged["ppg"], "reference_rows": staged["reference"], "pigmentation_rows": staged["pigmentation"], "combined_rows": staged["combined"]},
        "uploads": [{k: v for k, v in u.items() if k != "sha256"} for u in uploads],
        "model_training": q["model_training"] if q else {"blocked": True, "reasons": ["There are no valid real records.", "Model training is never started automatically."]},
        "settings": {"match_tolerance_s": COLLECTION_CONFIG.match_tolerance_s, "window_s": LIVE_CONFIG.window_seconds, "hop_s": COLLECTION_CONFIG.hop_seconds,
                     "max_upload_mb": COLLECTION_CONFIG.max_upload_mb},
        "consent_notice": CONSENT_NOTICE,
    }


@router.get("/fields/{kind}")
def fields(kind: str):
    if kind not in mp.KINDS:
        return _fail(CollectionError("bad_kind", f"Upload kind must be one of: {', '.join(mp.KINDS)}.", "kind"), 404)
    return {"kind": kind, "fields": mp.field_list(kind)}


@router.get("/template/{kind}")
def template(kind: str):
    if kind not in TEMPLATES:
        return _fail(CollectionError("bad_kind", "Unknown upload kind.", "kind"), 404)
    return PlainTextResponse(TEMPLATES[kind], media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{kind}_template.csv"'})


@router.post("/upload/{kind}")
async def upload(kind: str, request: Request, filename: str | None = Query(None), mapping: str | None = Query(None),
                 attested_real: bool = Query(False), participant_id: str | None = Query(None), session_id: str | None = Query(None),
                 device_id: str | None = Query(None), source: str | None = Query(None), fs: float | None = Query(None),
                 recording_start: str | None = Query(None)):
    """Stage a CSV (raw request body). `mapping` is optional JSON {field: "your column"}; `attested_real` must be true."""
    try:
        m = json.loads(mapping) if mapping else None
        if m is not None and not isinstance(m, dict):
            raise ValueError
    except ValueError:
        return _fail(CollectionError("bad_mapping", "mapping must be a JSON object of field -> column name.", "mapping"))
    params = {"filename": filename, "mapping": m, "attested_real": attested_real, "participant_id": participant_id, "session_id": session_id,
              "device_id": device_id, "source": source, "fs": fs, "recording_start": recording_start}
    try:
        return ingest.add_upload(kind, await request.body(), params)
    except CollectionError as exc:
        return _fail(exc)


@router.delete("/uploads/{upload_id}")
def remove(upload_id: str):
    paths = get_paths()
    entry = store.remove_upload(paths, upload_id)
    if entry is None:
        return _fail(CollectionError("not_found", f"No upload '{upload_id}'.", "upload_id"), 404)
    if not store.manifest(paths):
        merge.clear_outputs(paths)        # nothing staged any more: no research data may remain
    return {"removed": upload_id, "filename": entry["filename"], "note": "Rebuild the research dataset to apply this change."}


@router.post("/build")
def build():
    """Merge the staged sources, validate every record and write research_dataset.csv and research_data_quality.json."""
    try:
        return merge.build_research_dataset()
    except CollectionError as exc:
        return _fail(exc)


@router.get("/quality")
def quality():
    q = merge.read_quality(get_paths())
    return q if q is not None else {"available": False, "message": "The research dataset has not been built yet."}


@router.get("/report")
def report():
    r = merge.read_report(get_paths())
    return r if r is not None else {"available": False, "message": "The research dataset has not been built yet."}
