"""Feature engineering and group assignment (pure functions, no I/O)."""

import math

from ..config import RELIABILITY_CONFIG, ReliabilityConfig


def classify_ita(ita: float, cfg: ReliabilityConfig = RELIABILITY_CONFIG) -> str:
    """Objective pigmentation category from ITA (degrees). Never a racial label."""
    if ita > cfg.ita_light_above:
        return "Light"
    if ita <= cfg.ita_dark_at_most:
        return "Dark"
    return "Medium"


def classify_pi(pi: float, cfg: ReliabilityConfig = RELIABILITY_CONFIG) -> str:
    """Perfusion group from PI (%). Configured threshold — not clinically validated."""
    return "Low" if pi < cfg.pi_low_below else "Normal"


def engineer_features(spo2: float, pi: float, ita: float) -> dict:
    """Features used by the bias/uncertainty models.

    d = 100 - SpO2 (desaturation); log_pi is the natural log of PI (%).
    The three interactions mirror the planned bias model terms.
    """
    d = 100.0 - spo2
    log_pi = math.log(pi)
    return {
        "spo2": spo2,
        "d": d,
        "pi": pi,
        "log_pi": log_pi,
        "ita": ita,
        "ita_x_d": ita * d,
        "log_pi_x_d": log_pi * d,
        "ita_x_log_pi": ita * log_pi,
    }
