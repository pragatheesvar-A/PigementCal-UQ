import math

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.pigmentation import calculate_ita, compute_ita, summarize_participant
from app.services.validation import InputValidationError

client = TestClient(app)


def errs(fn, *a, **kw):
    with pytest.raises(InputValidationError) as e:
        fn(*a, **kw)
    return {x["field"]: x for x in e.value.errors}


# ---- ITA maths ----
@pytest.mark.parametrize("L,b,expected", [
    (70, 20, 45.0), (60, 10, 45.0), (50, 20, 0.0), (40, 20, math.degrees(math.atan(-10 / 20))),
    (60, 0, 90.0),           # b* = 0: explicit +90 for L* > 50
    (40, 0, -90.0),          # ... and -90 for L* < 50
    (60, -10, -45.0),        # b* < 0: standard arctan keeps (-90, 90); atan2 would give 135
    (60, -5, math.degrees(math.atan(10 / -5))),   # about -63.4, not 116
])
def test_compute_ita(L, b, expected):
    assert compute_ita(L, b) == pytest.approx(expected)


def test_ita_matches_arctan_ratio_when_b_positive():
    assert compute_ita(65, 15) == pytest.approx(math.degrees(math.atan((65 - 50) / 15)))


# ---- single measurement ----
def test_calculate_valid():
    r = calculate_ita({"L": 62, "a": 12, "b": 18})
    assert r["ita"] == pytest.approx(math.degrees(math.atan(12 / 18)), abs=1e-3)
    assert r["pigmentation_group"] == "Medium" and "not race" in r["label"]
    assert r["usable_for_reliability"] is True and r["warnings"] == []


@pytest.mark.parametrize("L,b,g", [(70, 20, "Light"), (68, 20, "Light"), (66, 20, "Medium"), (60, 20, "Medium"), (50, 20, "Dark"), (40, 20, "Dark")])
def test_category(L, b, g):
    assert calculate_ita({"L": L, "a": 10, "b": b})["pigmentation_group"] == g


def test_category_boundaries_follow_config():
    # ITA exactly 45 > 41 -> Light; exactly 10 -> Dark (<= 10); just above 10 -> Medium
    assert calculate_ita({"L": 70, "a": 0, "b": 20})["pigmentation_group"] == "Light"
    L = 50 + 20 * math.tan(math.radians(10))
    assert calculate_ita({"L": L, "a": 0, "b": 20})["pigmentation_group"] == "Dark"
    assert calculate_ita({"L": L + 0.1, "a": 0, "b": 20})["pigmentation_group"] == "Medium"


def test_missing_values_reported_together():
    e = errs(calculate_ita, {})
    assert {"L", "a", "b"} == set(e) and all(x["code"] == "missing" for x in e.values())


@pytest.mark.parametrize("bad", ["abc", "", [], {}, True, math.nan, math.inf, -math.inf])
def test_invalid_or_nonfinite_values(bad):
    e = errs(calculate_ita, {"L": bad, "a": 5, "b": 10})
    assert e["L"]["code"] in ("invalid_type", "missing")


@pytest.mark.parametrize("raw,field", [({"L": 120, "a": 0, "b": 10}, "L"), ({"L": -1, "a": 0, "b": 10}, "L"),
                                       ({"L": 60, "a": 200, "b": 10}, "a"), ({"L": 60, "a": 0, "b": -300}, "b")])
def test_out_of_range(raw, field):
    assert errs(calculate_ita, raw)[field]["code"] == "out_of_range"


def test_negative_b_warns_but_stays_inside_the_supported_range():
    r = calculate_ita({"L": 60, "a": 5, "b": -10})
    assert r["ita"] == pytest.approx(-45.0) and r["usable_for_reliability"] is True and len(r["warnings"]) == 1 and "zero or negative" in r["warnings"][0]


def test_location_validation_and_echo():
    assert calculate_ita({"L": 60, "a": 5, "b": 10, "location": "Forehead"})["location"] == "Forehead"
    assert calculate_ita({"L": 60, "a": 5, "b": 10})["location"] == "Not specified"
    assert "location" in errs(calculate_ita, {"L": 60, "a": 5, "b": 10, "location": "Elbow"})


# ---- repeated measurements ----
def M(L, b=20, loc=None):
    return {"L": L, "a": 8, "b": b, **({"location": loc} if loc else {})}


def test_median_is_of_itas_odd():
    r = summarize_participant([M(70), M(60), M(55)])  # ITA 45, 26.6, 14.0
    assert r["median_ita"] == pytest.approx(compute_ita(60, 20), abs=1e-3) and r["n"] == 3
    assert r["pigmentation_group"] == "Medium"


def test_median_even_is_mean_of_middle_two():
    r = summarize_participant([M(70), M(60), M(55), M(50)])
    mid = sorted(compute_ita(L, 20) for L in (70, 60, 55, 50))
    assert r["median_ita"] == pytest.approx((mid[1] + mid[2]) / 2, abs=1e-3)


def test_median_robust_to_outlier():
    r = summarize_participant([M(60), M(60.5), M(75)])
    assert r["median_ita"] == pytest.approx(compute_ita(60.5, 20), abs=1e-3)


def test_single_measurement_participant():
    r = summarize_participant([M(60)])
    assert r["median_ita"] == pytest.approx(compute_ita(60, 20), abs=1e-3) and r["warnings"] == []


def test_large_spread_warns():
    r = summarize_participant([M(80), M(52)])
    assert any("differ by more than" in w for w in r["warnings"])


def test_mixed_locations_not_silently_combined():
    r = summarize_participant([M(70, loc="Finger dorsal"), M(52, loc="Forehead"), M(53, loc="Forehead")])
    assert r["mixed_locations"] and r["median_ita"] is None and r["pigmentation_group"] is None
    assert set(r["by_location"]) == {"Finger dorsal", "Forehead"} and r["by_location"]["Forehead"]["n"] == 2
    assert any("different locations" in w for w in r["warnings"])


def test_location_filter_gives_single_value():
    rows = [M(70, loc="Finger dorsal"), M(52, loc="Forehead"), M(53, loc="Forehead")]
    r = summarize_participant(rows, location="Forehead")
    assert r["n_used"] == 2 and r["location"] == "Forehead" and r["median_ita"] is not None


def test_location_filter_with_no_rows_is_error():
    assert "location" in errs(summarize_participant, [M(70, loc="Forehead")], location="Other")


def test_invalid_row_reports_row_number_and_nothing_dropped():
    e = errs(summarize_participant, [M(60), {"L": "x", "a": 1, "b": 2}, {"a": 1, "b": 2}])
    assert "Measurement 2" in e["measurements[1].L"]["message"] and "Measurement 3" in e["measurements[2].L"]["message"]


def test_empty_measurements():
    assert "measurements" in errs(summarize_participant, [])
    assert "measurements" in errs(summarize_participant, None)


# ---- API ----
def test_api_calculate_shape():
    r = client.post("/api/ita/calculate", json={"L": 62, "a": 12, "b": 18})
    assert r.status_code == 200
    b = r.json()
    for k in ("L", "a", "b", "ita", "pigmentation_group"):
        assert k in b
    assert b["pigmentation_group"] == "Medium" and b["thresholds"]["light_above"] == 41


def test_api_calculate_errors():
    r = client.post("/api/ita/calculate", json={"L": 62, "a": 12})
    assert r.status_code == 422 and "b* is required" in r.json()["errors"][0]["message"]
    r = client.post("/api/ita/calculate", json={"L": "dark", "a": 12, "b": 3})
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "L"


def test_api_participant():
    r = client.post("/api/ita/participant", json={"measurements": [M(70), M(60), M(55)]})
    assert r.status_code == 200 and r.json()["median_ita"] is not None and r.json()["n"] == 3
    assert client.post("/api/ita/participant", json={"measurements": []}).status_code == 422
    assert client.post("/api/ita/participant", json={}).status_code == 422


def test_ita_flows_into_reliability():
    ita = client.post("/api/ita/calculate", json={"L": 55, "a": 10, "b": 25}).json()
    body = {"spo2": 94, "pi": 0.4, "ita": ita["ita"], "signal_quality": "MODERATE", "motion": "LOW",
            "device": "ESP32 + MAX30102", "ita_source": "pigmentation_module"}
    r = client.post("/api/reliability/predict", json=body).json()
    assert r["pigmentation_group"] == ita["pigmentation_group"] == "Medium"
    assert r["ita_source"] == "pigmentation_module" and r["ita"] == ita["ita"]


def test_reliability_group_changes_with_ita():
    base = {"spo2": 94, "pi": 0.4, "signal_quality": "MODERATE", "motion": "LOW", "device": "ESP32 + MAX30102"}
    groups = {client.post("/api/reliability/predict", json={**base, "ita": v}).json()["pigmentation_group"] for v in (60, 25, 0)}
    assert groups == {"Light", "Medium", "Dark"}


# ---- ITA definition: validation and edge cases (single shared definition) ----
def test_compute_ita_rejects_undefined_and_non_finite_inputs():
    for L, b in ((float("nan"), 10), (60, float("nan")), (float("inf"), 10), (60, float("-inf"))):
        with pytest.raises(ValueError):
            compute_ita(L, b)
    with pytest.raises(ValueError):
        compute_ita(50, 0)                                     # arctan(0/0) is undefined


def test_ita_stays_inside_minus90_plus90_for_any_sign_of_b():
    for L in (0, 20, 49.9, 50.1, 80, 100):
        for b in (-60, -5, -0.001, 0.0, 0.001, 5, 60):
            assert -90.0 <= compute_ita(L, b) <= 90.0


def test_ita_api_rejects_bad_colour_values_with_422_and_a_message():
    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)
    for body in ({"L": 101, "a": 10, "b": 20}, {"L": -1, "a": 10, "b": 20}, {"L": 60, "a": 10, "b": 500}, {"L": "abc", "a": 10, "b": 20},
                 {"L": 50, "a": 10, "b": 0}, {"a": 10, "b": 20}):
        r = c.post("/api/ita/calculate", json=body)
        assert r.status_code == 422 and r.json()["errors"][0]["message"], body
    ok = c.post("/api/ita/calculate", json={"L": 60, "a": 10, "b": -5})
    assert ok.status_code == 200 and ok.json()["ita"] == pytest.approx(math.degrees(math.atan(10 / -5)), abs=1e-3)
    assert any("zero or negative" in w for w in ok.json()["warnings"])
