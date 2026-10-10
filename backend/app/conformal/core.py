"""Conformalized quantile regression (CQR) with Mondrian calibration cells — the math, with no I/O.

CQR (Romano, Patterson & Candès 2019):
    score   E_i = max( q_lo(x_i) - y_i ,  y_i - q_hi(x_i) )          on CALIBRATION data only
    Q       = the ceil((n+1)(1-alpha))-th smallest score             (finite-sample correction)
    interval [ q_lo(x) - Q ,  q_hi(x) + Q ]
Under exchangeability of the calibration data and a new reading (within the calibration cell) the interval covers the
truth with probability >= 1 - alpha, averaged over the calibration draw. That is a procedure-level statement, not a
statement that this individual's value lies in this interval with 95 % (or any) probability.

Mondrian: calibrate separately inside each cell (ITA group x PI group). A cell with too few calibration participants/rows
is NEVER filled in: it is merged only by the documented rule, otherwise it is INSUFFICIENT CALIBRATION DATA.
"""

import math

import numpy as np
import pandas as pd

from ..config import CONFORMAL_CONFIG, RELIABILITY_CONFIG, ConformalConfig, ReliabilityConfig
from ..services.features import classify_ita, classify_pi

ITA_GROUPS = ("Light", "Medium", "Dark")
PI_GROUPS = ("Low", "Normal")
CELLS = [(a, b) for a in ITA_GROUPS for b in PI_GROUPS]
CALIBRATED, MERGED, INSUFFICIENT = "CALIBRATED", "MERGED", "INSUFFICIENT"
INSUFFICIENT_TEXT = "INSUFFICIENT CALIBRATION DATA"


def cell_key(ita_group: str, pi_group: str) -> str:
    return f"{ita_group}|{pi_group}"


def cell_label(ita_group: str, pi_group: str) -> str:
    return f"{ita_group} × {pi_group} PI"


def conformal_quantile(scores, alpha: float) -> float | None:
    """The ceil((n+1)(1-alpha))-th smallest score, or None when n is too small for coverage 1-alpha to be possible."""
    s = np.sort(np.asarray(scores, dtype=float))
    n = len(s)
    k = math.ceil((n + 1) * (1 - alpha))
    if n == 0 or k > n:
        return None
    return float(s[k - 1])


def cqr_scores(y, lo, hi) -> np.ndarray:
    y, lo, hi = (np.asarray(v, dtype=float) for v in (y, lo, hi))
    return np.maximum(lo - y, y - hi)


def order_quantiles(lo, hi) -> tuple[np.ndarray, np.ndarray]:
    """Independently fitted quantile models can cross; use the smaller as lower and the larger as upper."""
    lo, hi = np.asarray(lo, dtype=float), np.asarray(hi, dtype=float)
    return np.minimum(lo, hi), np.maximum(lo, hi)


def make_interval(lo, hi, q: float, floor: float = 0.0, ceiling: float = 100.0):
    """[lo - Q, hi + Q], clipped to the physical range of SaO2 (clipping cannot reduce coverage) and never inverted."""
    lower = np.clip(np.asarray(lo, dtype=float) - q, floor, ceiling)
    upper = np.clip(np.asarray(hi, dtype=float) + q, floor, ceiling)
    return lower, np.maximum(upper, lower)


def assign_groups(ita, pi, rcfg: ReliabilityConfig = RELIABILITY_CONFIG) -> tuple[list[str], list[str]]:
    """Objective pigmentation group and perfusion group from the SAME configured thresholds used everywhere else."""
    return [classify_ita(float(v), rcfg) for v in ita], [classify_pi(float(v), rcfg) for v in pi]


def _pool(frame: pd.DataFrame, cfg: ConformalConfig) -> dict:
    n_part = int(frame["participant_id"].nunique()) if len(frame) else 0
    q = conformal_quantile(frame["score"], cfg.alpha) if len(frame) else None
    ok = n_part >= cfg.min_cell_participants and len(frame) >= cfg.min_cell_rows and q is not None
    return {"n_rows": int(len(frame)), "n_participants": n_part, "q": q, "sufficient": bool(ok)}


def calibrate(scores, ita_groups, pi_groups, participants, cfg: ConformalConfig = CONFORMAL_CONFIG) -> dict:
    """Mondrian calibration. `scores` are CQR scores of the CALIBRATION rows.

    Returns {"marginal": {...}, "cells": {key: {...}}}. Each cell has status CALIBRATED (own data), MERGED (pooled with the
    other PI cell of the same ITA group, documented rule) or INSUFFICIENT (no interval may be produced)."""
    df = pd.DataFrame({"score": np.asarray(scores, dtype=float), "ita_group": list(ita_groups), "pi_group": list(pi_groups),
                       "participant_id": list(participants)})
    cells: dict[str, dict] = {}
    for a, b in CELLS:
        own = _pool(df[(df.ita_group == a) & (df.pi_group == b)], cfg)
        entry = {"ita_group": a, "pi_group": b, "label": cell_label(a, b), "n_rows": own["n_rows"], "n_participants": own["n_participants"],
                 "own_q": own["q"], "q": None, "status": INSUFFICIENT, "source": None, "merged_with": [],
                 "requirement": f"≥ {cfg.min_cell_participants} participants and ≥ {cfg.min_cell_rows} rows"}
        if own["sufficient"]:
            entry.update(q=own["q"], status=CALIBRATED, source="own cell")
        cells[cell_key(a, b)] = entry
    if cfg.merge_rule == "ita_group":
        for a in ITA_GROUPS:
            mine = [cells[cell_key(a, b)] for b in PI_GROUPS]
            if all(c["status"] == CALIBRATED for c in mine):
                continue
            pooled = _pool(df[df.ita_group == a], cfg)
            if pooled["sufficient"]:
                for c in mine:
                    if c["status"] == INSUFFICIENT:
                        c.update(q=pooled["q"], status=MERGED, source=f"{a} group pooled over PI (documented merge rule)",
                                 merged_with=[cell_label(a, b) for b in PI_GROUPS if b != c["pi_group"]],
                                 pooled_rows=pooled["n_rows"], pooled_participants=pooled["n_participants"])
    return {"marginal": _pool(df, cfg), "cells": cells, "merge_rule": cfg.merge_rule,
            "min_cell_participants": cfg.min_cell_participants, "min_cell_rows": cfg.min_cell_rows}


def q_for(calibration: dict, ita_group: str, pi_group: str) -> tuple[float | None, dict]:
    """The Mondrian Q for a reading's cell (None when INSUFFICIENT) and the cell's calibration record."""
    c = calibration["cells"][cell_key(ita_group, pi_group)]
    return (c["q"] if c["status"] != INSUFFICIENT else None), c


# ------------------------------------------------------------------ evaluation (TEST data only)
def group_metrics(df: pd.DataFrame, cfg: ConformalConfig = CONFORMAL_CONFIG) -> dict:
    """df columns: participant_id, y, lower, upper (NaN = no interval was produced, i.e. abstained)."""
    has = df["lower"].notna()
    d = df[has]
    n = int(len(d))
    out = {"n_total": int(len(df)), "n_abstained": int((~has).sum()), "n_obs": n,
           "n_participants": int(d["participant_id"].nunique()) if n else 0,
           "coverage": None, "mean_width": None, "median_width": None, "participant_mean_coverage": None,
           "lower_bound_violation_rate": None, "low_n": True}
    if n:
        covered = (d["y"] >= d["lower"]) & (d["y"] <= d["upper"])
        out.update(coverage=float(covered.mean()), mean_width=float((d["upper"] - d["lower"]).mean()),
                   median_width=float((d["upper"] - d["lower"]).median()),
                   participant_mean_coverage=float(covered.groupby(d["participant_id"].to_numpy()).mean().mean()),     # each participant counts once
                   lower_bound_violation_rate=float((d["y"] < d["lower"]).mean()),
                   low_n=out["n_participants"] < cfg.min_test_participants)
    return out


def coverage_report(df: pd.DataFrame, cfg: ConformalConfig = CONFORMAL_CONFIG) -> dict:
    """Coverage and mean width overall, by ITA group, by PI group and by ITA x PI cell. Empty groups are listed, not hidden."""
    def part(mask, **labels):
        return {**labels, **group_metrics(df[mask], cfg)}
    return {
        "target_coverage": 1 - cfg.alpha,
        "overall": group_metrics(df, cfg),
        "ita": [part(df.ita_group == g, group=g) for g in ITA_GROUPS],
        "pi": [part(df.pi_group == g, group=g) for g in PI_GROUPS],
        "ita_x_pi": [part((df.ita_group == a) & (df.pi_group == b), ita_group=a, pi_group=b, label=cell_label(a, b)) for a, b in CELLS],
    }
