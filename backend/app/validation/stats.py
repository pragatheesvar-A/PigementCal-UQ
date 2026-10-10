"""Participant-level (cluster) bootstrap. Readings from one participant are correlated, so participants — not rows —
are resampled with replacement. A CI is reported only when enough participants exist; otherwise it is None with the reason.

Each metric is computed from per-participant sufficient statistics, so thousands of replicates are cheap and exact.
"""

import numpy as np
import pandas as pd

from ..config import VALIDATION_CONFIG, ValidationConfig

ERROR_COLS = ["n", "abs", "sq", "err", "y", "y2"]


def error_stats(df: pd.DataFrame, pred: str) -> pd.DataFrame:
    """Per-participant sums for an error metric. error = prediction - sao2 (positive = over-estimates)."""
    e = df[pred].to_numpy(float) - df["sao2"].to_numpy(float)
    y = df["sao2"].to_numpy(float)
    t = pd.DataFrame({"participant_id": df["participant_id"].to_numpy(), "n": 1.0, "abs": np.abs(e), "sq": e ** 2, "err": e, "y": y, "y2": y ** 2})
    return t.groupby("participant_id")[ERROR_COLS].sum()


def _err_metrics(tot: np.ndarray) -> dict[str, np.ndarray]:
    """tot: (..., 6) totals in ERROR_COLS order."""
    n = tot[..., 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        ss_tot = tot[..., 5] - tot[..., 4] ** 2 / n
        return {"MAE": tot[..., 1] / n, "RMSE": np.sqrt(tot[..., 2] / n), "Bias": tot[..., 3] / n,
                "R²": np.where(ss_tot > 0, 1 - tot[..., 2] / ss_tot, np.nan)}


COVER_COLS = ["n", "covered", "width", "below"]


def coverage_stats(df: pd.DataFrame) -> pd.DataFrame:
    """Per-participant sums over rows that HAVE an interval (abstained rows are excluded, as in the coverage tables)."""
    d = df[df["lower_bound"].notna()]
    covered = ((d["sao2"] >= d["lower_bound"]) & (d["sao2"] <= d["upper_bound"])).astype(float)
    t = pd.DataFrame({"participant_id": d["participant_id"].to_numpy(), "n": 1.0, "covered": covered.to_numpy(),
                      "width": (d["upper_bound"] - d["lower_bound"]).to_numpy(), "below": (d["sao2"] < d["lower_bound"]).astype(float).to_numpy()})
    return t.groupby("participant_id")[COVER_COLS].sum()


def _cov_metrics(tot: np.ndarray) -> dict[str, np.ndarray]:
    n = tot[..., 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        return {"Coverage": tot[..., 1] / n, "Mean interval width": tot[..., 2] / n, "Lower-bound violation rate": tot[..., 3] / n}


def bootstrap(stats: pd.DataFrame, metrics_fn, names: list[str], cfg: ValidationConfig = VALIDATION_CONFIG) -> list[dict]:
    """For each metric: estimate, 95 % CI (None when too few participants), n_obs, n_participants, ci_status."""
    S = stats.to_numpy(float)
    P = len(S)
    n_obs = int(S[:, 0].sum()) if P else 0
    est = {k: (float(v) if np.isfinite(v) else None) for k, v in metrics_fn(S.sum(axis=0)).items()} if P and n_obs else {k: None for k in names}
    rows = []
    ci = None
    if P >= cfg.min_ci_participants and n_obs:
        rng = np.random.default_rng(cfg.seed)
        counts = rng.multinomial(P, np.full(P, 1.0 / P), size=cfg.bootstrap_reps)          # participants drawn with replacement
        reps = metrics_fn(counts @ S)
        a = (1 - cfg.level) / 2 * 100
        ci = {k: (np.nanpercentile(v, [a, 100 - a]) if np.isfinite(v).sum() > 10 else None) for k, v in reps.items()}
    for k in names:
        c = None if ci is None else ci.get(k)
        rows.append({"metric": k, "estimate": est.get(k), "ci_low": None if c is None else float(c[0]), "ci_high": None if c is None else float(c[1]),
                     "n_obs": n_obs, "n_participants": P,
                     "ci_status": "ok" if c is not None else (f"not reported: only {P} participant(s) (minimum {cfg.min_ci_participants})" if P < cfg.min_ci_participants else "not reported: metric undefined")})
    return rows


def error_metrics(df: pd.DataFrame, pred: str, names=("MAE", "RMSE", "Bias", "R²"), cfg: ValidationConfig = VALIDATION_CONFIG) -> list[dict]:
    return bootstrap(error_stats(df, pred), _err_metrics, list(names), cfg)


def coverage_metrics(df: pd.DataFrame, cfg: ValidationConfig = VALIDATION_CONFIG) -> list[dict]:
    return bootstrap(coverage_stats(df), _cov_metrics, ["Coverage", "Mean interval width", "Lower-bound violation rate"], cfg)
