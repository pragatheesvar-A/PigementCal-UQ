"""Column mapping for the four upload kinds. Column names are never assumed: headers are matched by name and
the person can correct the mapping. Race / ethnicity labels have no field here — they are never used."""

import re

from .rules import CollectionError

KINDS = ("ppg", "reference", "pigmentation", "combined")

# field -> normalized header aliases (lower-case, letters and digits only)
ALIASES: dict[str, list[str]] = {
    "participant_id": ["participantid", "participant", "subjectid", "subject", "pid", "patientid", "patient"],
    "session_id": ["sessionid", "session", "recordingid", "recording", "visitid", "visit"],
    "timestamp": ["timestamp", "time", "times", "t", "ts", "tms", "timems", "timestampms", "datetime", "elapsed", "elapseds", "elapsedtime", "seconds", "sec", "timesec", "tsec"],
    "ir": ["ir", "infrared", "irraw", "ppgir", "ppg", "pleth", "signal", "ppgsignal", "irled", "ledir"],
    "red": ["red", "redraw", "ppgred", "redled", "ledred"],
    "ax": ["ax", "accx", "accelx", "accelerationx", "accelerometerx"],
    "ay": ["ay", "accy", "accely", "accelerationy", "accelerometery"],
    "az": ["az", "accz", "accelz", "accelerationz", "accelerometerz"],
    "accel": ["accel", "accelerometer", "acc", "accmag", "accelmagnitude", "motionmagnitude"],
    "spo2": ["spo2", "spo2pct", "spo2reading", "spo2device", "oximeterspo2", "pulseox"],
    "sao2": ["sao2", "sao2pct", "sao2ref", "referencesao2", "arterialsao2", "abgsao2", "abg", "cooximetry"],
    "pi": ["pi", "perfusionindex", "perfusion"],
    "ita": ["ita", "individualtypologyangle"],
    "L": ["l", "lstar", "labl", "cielabl"],
    "a": ["a", "astar", "laba", "cielaba"],
    "b": ["b", "bstar", "labb", "cielabb"],
    "sqi": ["sqi", "signalquality", "signalqualityindex"],
    "motion": ["motion", "motionscore"],
    "device_id": ["deviceid", "device", "devicename", "oximeter"],
    "location": ["location", "site", "measurementlocation"],
}

ALLOWED = {
    "ppg": ["participant_id", "session_id", "timestamp", "ir", "red", "ax", "ay", "az", "accel", "spo2", "device_id"],
    "reference": ["participant_id", "session_id", "timestamp", "sao2"],
    "pigmentation": ["participant_id", "session_id", "ita", "L", "a", "b", "location"],
    "combined": ["participant_id", "session_id", "timestamp", "spo2", "sao2", "pi", "ita", "L", "a", "b", "sqi", "motion", "device_id"],
}
REQUIRED = {
    "ppg": ["ir"],
    "reference": ["participant_id", "session_id", "sao2"],
    "pigmentation": ["participant_id"],
    "combined": ["participant_id", "spo2", "sao2"],
}
LABELS = {
    "participant_id": "Participant ID (anonymous)", "session_id": "Session ID", "timestamp": "Timestamp / time",
    "ir": "PPG infrared", "red": "PPG red", "ax": "Accelerometer X (g)", "ay": "Accelerometer Y (g)", "az": "Accelerometer Z (g)",
    "accel": "Accelerometer magnitude (g)", "spo2": "SpO₂ (oximeter reading)", "sao2": "SaO₂ (arterial reference)",
    "pi": "Perfusion index (%)", "ita": "ITA (°)", "L": "L*", "a": "a*", "b": "b*", "sqi": "Signal quality (SQI)",
    "motion": "Motion", "device_id": "Device ID", "location": "Measurement location",
}


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def propose(columns: list[str], kind: str) -> dict[str, str]:
    by_norm: dict[str, str] = {}
    for c in columns:
        by_norm.setdefault(_norm(c), c)
    out: dict[str, str] = {}
    used: set[str] = set()
    for field in ALLOWED[kind]:
        for alias in ALIASES[field]:
            src = by_norm.get(alias)
            if src is not None and src not in used:
                out[field] = src
                used.add(src)
                break
    return out


def resolve(columns: list[str], kind: str, user: dict | None) -> dict[str, str]:
    """Automatic proposal overridden by the user's choices; raises CollectionError listing what is missing."""
    proposed = propose(columns, kind)
    user = {k: v for k, v in (user or {}).items() if v}
    for k, v in user.items():
        if k not in ALLOWED[kind]:
            raise CollectionError("unknown_field", f"'{k}' is not a field of a {kind} upload.", "mapping")
        if v not in columns:
            raise CollectionError("unknown_column", f"Column '{v}' (for {LABELS[k]}) is not in the file.", "mapping", {"detected_columns": columns})
    applied = {**proposed, **user}
    missing = [f for f in REQUIRED[kind] if f not in applied]
    if kind == "pigmentation" and "ita" not in applied and not all(k in applied for k in ("L", "a", "b")):
        missing.append("ita (or L, a and b)")
    if kind == "ppg":
        axes = [f in applied for f in ("ax", "ay", "az")]
        if any(axes) and not all(axes):
            missing.append("ax, ay and az together")
    if missing:
        raise CollectionError(
            "missing_columns", "Could not find: " + ", ".join(LABELS.get(m, m) for m in missing) + ". Choose the matching columns in the mapping.",
            "mapping", {"detected_columns": columns, "proposed_mapping": proposed, "missing_fields": missing,
                        "fields": [{"id": f, "label": LABELS[f], "required": f in REQUIRED[kind]} for f in ALLOWED[kind]]})
    return applied


def field_list(kind: str) -> list[dict]:
    return [{"id": f, "label": LABELS[f], "required": f in REQUIRED[kind]} for f in ALLOWED[kind]]
