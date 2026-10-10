from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from ..governance import research_gate as gate

router = APIRouter(prefix="/api/research", tags=["research-status"])


class ProvenanceIn(BaseModel):
    """Everything the person must state about where the dataset came from. There is deliberately NO field for the verification
    result or the research status: those are computed on the backend, and unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")

    data_origin: str
    dataset_name: str = ""
    source_description: str = ""
    collecting_site: str = ""
    ethics_reference: str = ""
    collection_start: str = ""
    collection_end: str = ""
    reference_sao2_method: str = ""
    skin_colour_instrument: str = ""
    perfusion_source: str = ""
    registered_by: str = ""
    generator_version: str | None = None       # synthetic / simulated data: which generator and version produced it
    source_device: str | None = None
    declaration: bool = False


@router.get("/status")
def status():
    """The one authoritative research-status decision, with every check. The frontend only displays this."""
    return gate.evaluate()


@router.get("/provenance")
def provenance():
    from ..ml.paths import get_paths
    p = gate.read_provenance(get_paths())
    return {"registered": p is not None, "provenance": p, "origins": list(gate.ORIGINS), "required_fields": list(gate.REQUIRED_FIELDS)}


@router.post("/provenance")
def register(body: ProvenanceIn):
    """Register (or replace) the provenance of the built research dataset. The result is always re-checked by the gate."""
    try:
        rec = gate.register_provenance(body.model_dump())
    except gate.ProvenanceError as exc:
        return JSONResponse(status_code=422, content={"errors": exc.errors})
    return {"provenance": rec, "status": gate.evaluate()}
