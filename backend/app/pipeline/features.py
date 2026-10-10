
import logging
import math
from typing import Dict, Any

def engineer_features(data: Dict[str, Any]) -> Dict[str, Any]:
    spo2 = data.get("spo2")
    pi = data.get("pi")
    ita = data.get("ita")
    sqi = data.get("sqi")
    motion = data.get("motion")

    out = {}
    if spo2 is not None:
        out["spo2"] = spo2
        out["d"] = 100 - spo2
    
    if pi is not None:
        out["pi"] = pi
        if pi > 0:
            out["log_pi"] = math.log(pi)
        else:
            out["log_pi"] = None
            logging.warning("PI <= 0, log_pi set to None")
    
    if ita is not None:
        out["ita"] = ita
    
    if sqi is not None:
        out["sqi"] = sqi
        
    if motion is not None:
        out["motion"] = motion
        
    if "d" in out and "ita" in out:
        out["ita_x_d"] = out["ita"] * out["d"]
        
    if "d" in out and out.get("log_pi") is not None:
        out["log_pi_x_d"] = out["log_pi"] * out["d"]
        
    if "ita" in out and out.get("log_pi") is not None:
        out["ita_x_log_pi"] = out["ita"] * out["log_pi"]

    return out
