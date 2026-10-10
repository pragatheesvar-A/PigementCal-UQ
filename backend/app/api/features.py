
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from ..pipeline.features import engineer_features

router = APIRouter(prefix="/api/features", tags=["features"])

class FeatureInput(BaseModel):
    spo2: Optional[float] = None
    pi: Optional[float] = None
    ita: Optional[float] = None
    sqi: Optional[float] = None
    motion: Optional[float] = None

@router.post("/engineer")
def engineer(payload: FeatureInput):
    res = engineer_features(payload.model_dump(exclude_unset=True))
    # Fill in input values to match output format expectations
    if payload.spo2 is not None: res['spo2'] = payload.spo2
    if payload.pi is not None: res['pi'] = payload.pi
    if payload.ita is not None: res['ita'] = payload.ita
    if payload.sqi is not None: res['sqi'] = payload.sqi
    if payload.motion is not None: res['motion'] = payload.motion
    return res
