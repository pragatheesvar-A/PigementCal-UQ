"""Regression metrics and test-set subgroup errors (conformal coverage is reported by the conformal layer).

Error convention everywhere: error = prediction - sao2, so a positive bias means the model
(or the pulse-oximeter reading) over-estimates SaO2 on average.
"""

import numpy as np
import pandas as pd

from ..config import MODEL_CONFIG, RELIABILITY_CONFIG, ModelConfig, ReliabilityConfig
from ..services.features import classify_ita, classify_pi
from .data import GROUP_COL

ITA_GROUPS = ("Light", "Medium", "Dark")
PI_GROUPS = ("Low", "Normal")


def regression_metrics(y_true, y_pred, groups=None) -> dict:
    """MAE, RMSE, bias (mean error) and R^2, plus observation / participant counts.

    R^2 is None when it is undefined (fewer than 2 observations or constant truth)."""
    y = np.asarray(y_true, dtype=float)
    p = np.asarray(y_pred, dtype=float)
    if y.shape != p.shape or y.ndim != 1:
        raise ValueError("y_true and y_pred must be 1-D arrays of equal length")
    n = int(len(y))
    out = {"n_obs": n, "n_participants": int(pd.Series(groups).nunique()) if groups is not None else None,
           "mae": None, "rmse": None, "bias": None, "r2": None}
    if n == 0:
        return out
    err = p - y
    out["mae"] = float(np.mean(np.abs(err)))
    out["rmse"] = float(np.sqrt(np.mean(err ** 2)))
    out["bias"] = float(np.mean(err))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if n >= 2 and ss_tot > 0:
        out["r2"] = float(1.0 - np.sum(err ** 2) / ss_tot)
    return out


def _cell(df: pd.DataFrame, pred_cols: dict[str, str], cfg: ModelConfig, **labels) -> dict:
    n_part = int(df[GROUP_COL].nunique()) if len(df) else 0
    models = {}
    enough = n_part >= cfg.min_subgroup_participants
    for key, col in pred_cols.items():
        if len(df) == 0 or not enough:                       # INSUFFICIENT DATA: no value is reported, so none can be over-read
            models[key] = {"mae": None, "bias": None}
        else:
            err = df[col].to_numpy(float) - df["sao2"].to_numpy(float)
            models[key] = {"mae": float(np.mean(np.abs(err))), "bias": float(np.mean(err))}
    return {**labels, "n_obs": int(len(df)), "n_participants": n_part,
            "sufficient": enough, "status": "OK" if enough else "INSUFFICIENT DATA", "models": models}


def subgroup_errors(frame: pd.DataFrame, pred_cols: dict[str, str], rcfg: ReliabilityConfig = RELIABILITY_CONFIG,
                    cfg: ModelConfig = MODEL_CONFIG) -> dict:
    """Test-set MAE (and bias) by ITA group, PI group and ITA x PI cell.

    `frame` needs columns: participant_id, ita, pi, sao2 and the prediction columns in `pred_cols`
    (model key -> column name). Groups come from the shared configuration thresholds. Empty groups are
    still listed (n_obs = 0, MAE None) so a missing group is visible rather than silently absent."""
    df = frame.copy()
    df["ita_group"] = [classify_ita(v, rcfg) for v in df["ita"]]
    df["pi_group"] = [classify_pi(v, rcfg) for v in df["pi"]]
    return {
        "ita": [_cell(df[df.ita_group == g], pred_cols, cfg, group=g) for g in ITA_GROUPS],
        "pi": [_cell(df[df.pi_group == g], pred_cols, cfg, group=g) for g in PI_GROUPS],
        "ita_x_pi": [_cell(df[(df.ita_group == a) & (df.pi_group == b)], pred_cols, cfg, ita_group=a, pi_group=b)
                     for a in ITA_GROUPS for b in PI_GROUPS],
        "min_participants": cfg.min_subgroup_participants,
        "note": "Test-set error only. Cells with few participants are flagged and should not be over-interpreted; coverage is reported separately by the conformal layer.",
    }
