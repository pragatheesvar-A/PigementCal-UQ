"""Identifier, privacy and time rules for collected data."""

import re

import numpy as np
import pandas as pd

from ..config import COLLECTION_CONFIG

ID_RE = re.compile(COLLECTION_CONFIG.id_pattern)
# Columns that look like personal data are never read or stored: only anonymous participant IDs are used.
PRIVATE_RE = re.compile(r"(name|phone|mobile|email|mail|address|street|postcode|zip|birth|dob|ssn|mrn|passport|aadhaar)", re.I)
MISSING_TOKENS = {"", "nan", "none", "null", "na", "n/a"}


class CollectionError(Exception):
    """A user-fixable problem with an upload, with a stable code and a human-readable message."""

    def __init__(self, code: str, message: str, field: str = "file", extra: dict | None = None):
        super().__init__(message)
        self.code, self.message, self.field, self.extra = code, message, field, extra or {}

    def as_error(self) -> dict:
        return {"field": self.field, "code": self.code, "message": self.message}


def is_missing(v) -> bool:
    return v is None or (isinstance(v, float) and np.isnan(v)) or str(v).strip().lower() in MISSING_TOKENS


def id_problem(value) -> str | None:
    """None if `value` is an acceptable anonymous identifier, otherwise why not."""
    if is_missing(value):
        return "missing"
    s = str(value).strip()
    if "@" in s:
        return "looks like an email address — use an anonymous ID such as P001"
    if re.fullmatch(r"[+\d\s().\-]+", s) and len(re.sub(r"\D", "", s)) >= 9:
        return "looks like a phone number — use an anonymous ID such as P001"
    if not ID_RE.match(s):
        return "must be 1–64 characters (letters, digits, '_', '-', '.'; no spaces) such as P001 or P001_S01"
    return None


_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_filename(name) -> str:
    """Display/provenance name only (files are stored under generated ids, never under this name): no directories, no control
    characters, no leading spreadsheet-formula character, at most 120 characters."""
    base = str(name or "upload.csv").replace("\\", "/").split("/")[-1]
    base = "".join(ch for ch in base if ch.isprintable())[:120].strip() or "upload.csv"
    return "_" + base if base.startswith(_FORMULA_START) else base


def csv_safe_frame(df):
    """CSV-injection guard for files a person may open in a spreadsheet: any text cell that starts with = + - @ (or a tab / CR)
    is prefixed with an apostrophe so it is shown as text, never run as a formula. Numeric columns are untouched."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object or str(out[c].dtype).startswith("str"):
            out[c] = out[c].map(lambda v: "'" + v if isinstance(v, str) and v.startswith(_FORMULA_START) else v)
    return out


def private_columns(columns: list[str], mapped: set[str]) -> list[str]:
    """Columns that look like personal data and are not mapped to a research field."""
    return [c for c in columns if c not in mapped and PRIVATE_RE.search(c)]


def numeric(series: pd.Series) -> pd.Series:
    """Strings -> floats; anything non-numeric / non-finite becomes NaN (never guessed)."""
    out = pd.to_numeric(series.where(~series.map(is_missing), np.nan), errors="coerce")
    return out.where(np.isfinite(out))


def parse_times(values: pd.Series, header: str = "") -> tuple[np.ndarray, str]:
    """Parse a time column into seconds. Returns (seconds, basis):
    basis 'relative' = seconds since the start of the recording; 'absolute' = Unix seconds (UTC).
    Raises CollectionError if the column is neither numeric nor date-times."""
    num = numeric(values)
    if num.notna().all():
        x = num.to_numpy(float)
        if x.max() > 1e11:
            return x / 1000.0, "absolute"            # epoch milliseconds
        if x.max() > 1e9:
            return x, "absolute"                      # epoch seconds
        scale = 1000.0 if re.search(r"ms|milli", header, re.I) else 1.0
        return x / scale, "relative"
    dt = pd.to_datetime(values, errors="coerce", utc=True, format="mixed")
    if dt.notna().all():
        return (dt - pd.Timestamp("1970-01-01", tz="UTC")).dt.total_seconds().to_numpy(float), "absolute"
    bad = int(dt.isna().sum())
    raise CollectionError("bad_timestamp", f"{bad} timestamp value(s) could not be read as numbers (seconds) or date-times (e.g. 2026-10-07T10:15:00Z).", "timestamp")


def parse_start(text: str | None) -> float | None:
    """Recording start (date-time) -> Unix seconds, or None."""
    if text is None or str(text).strip() == "":
        return None
    t = pd.to_datetime(str(text), errors="coerce", utc=True)
    if pd.isna(t):
        raise CollectionError("bad_start", "Recording start must be a date-time such as 2026-10-07T10:15:00Z.", "recording_start")
    return float(t.timestamp())


def fmt_time(seconds: float, basis: str) -> str:
    if seconds is None or (isinstance(seconds, float) and np.isnan(seconds)):
        return ""
    if basis == "absolute":
        return pd.Timestamp(seconds, unit="s", tz="UTC").strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    return f"{seconds:.3f}"
