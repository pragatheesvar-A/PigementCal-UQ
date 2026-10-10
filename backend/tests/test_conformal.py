"""Conformal reliability layer (CQR + Mondrian ITA x PI calibration).

Everything here uses TEST-ONLY data in temporary folders: it checks the maths and the safeguards, and makes no research
claim. The project itself has no real data, so it has no calibration and no coverage numbers.
"""

import json
import math
import shutil
from dataclasses import replace

import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.collection import ingest, merge
from app.config import CONFORMAL_CONFIG, COVERAGE_WORDING
from app.conformal import core
from app.conformal import fit as cfit
from app.conformal import predict as cpredict
from app.main import app
from app.ml.data import GROUP_COL, ModelError
from app.ml.paths import Paths, set_paths
from app.pipeline import pipeline as pl
from app.services.validation import InputValidationError

CFG = replace(CONFORMAL_CONFIG, min_cell_participants=6, min_cell_rows=10)          # smaller cells for small test data


def make_paths(root) -> Paths:
    return Paths(processed=root / "processed", raw=root / "raw", models=root / "models", results=root / "results")


# =================================================================== the maths
def test_conformal_quantile_uses_the_finite_sample_rank():
    s = np.arange(1, 11)                                   # n = 10
    assert core.conformal_quantile(s, 0.10) == 10          # ceil(11 * 0.9) = 10th smallest
    assert core.conformal_quantile(s, 0.20) == 9           # ceil(11 * 0.8) = 9th
    assert core.conformal_quantile(s, 0.50) == 6           # ceil(11 * 0.5) = 6th
    assert core.conformal_quantile(np.array([3.0, 1.0, 2.0]), 0.5) == 2.0     # unsorted input


def test_conformal_quantile_refuses_when_coverage_is_impossible():
    assert core.conformal_quantile(np.arange(5), 0.10) is None        # ceil(6 * 0.9) = 6 > 5
    assert core.conformal_quantile([], 0.10) is None


def test_cqr_score_is_the_larger_signed_distance_outside_the_band():
    y, lo, hi = np.array([5.0, 0.0, 12.0, 10.0]), np.array([4.0, 4.0, 4.0, 4.0]), np.array([8.0, 8.0, 8.0, 8.0])
    assert list(core.cqr_scores(y, lo, hi)) == [-1.0, 4.0, 4.0, 2.0]   # inside (negative) / below / above / above


def test_crossing_quantiles_are_ordered():
    lo, hi = core.order_quantiles([5.0, 3.0], [4.0, 6.0])
    assert list(lo) == [4.0, 3.0] and list(hi) == [5.0, 6.0]


def test_interval_is_clipped_to_the_physical_range_and_never_inverted():
    lower, upper = core.make_interval(np.array([96.0, 2.0]), np.array([99.0, 5.0]), 3.0)
    assert list(lower) == [93.0, 0.0] and list(upper) == [100.0, 8.0]
    lower, upper = core.make_interval(np.array([90.0]), np.array([91.0]), -5.0)       # over-covering quantiles can give a negative Q
    assert upper[0] >= lower[0]


@pytest.mark.parametrize("ita,pi,g", [(41.1, 1.0, ("Light", "Normal")), (41.0, 0.99, ("Medium", "Low")), (10.0, 5, ("Dark", "Normal")), (10.1, 0.2, ("Medium", "Low"))])
def test_groups_use_the_shared_configured_thresholds(ita, pi, g):
    assert core.assign_groups([ita], [pi]) == ([g[0]], [g[1]])


def test_coverage_guarantee_holds_in_simulation():
    """Exchangeable calibration/test draws: mean empirical coverage of CQR must sit at or just above 1 - alpha."""
    rng = np.random.default_rng(0)
    covs = []
    for _ in range(300):
        cal = rng.normal(0, 1.5, 200)
        q = core.conformal_quantile(core.cqr_scores(cal, np.full(200, -1.0), np.full(200, 1.0)), 0.10)
        test = rng.normal(0, 1.5, 4000)
        covs.append(np.mean((test >= -1 - q) & (test <= 1 + q)))
    assert 0.895 <= np.mean(covs) <= 0.93


def _cal(n_per_cell: dict, rng=None, participants_per_cell: dict | None = None):
    """Calibration rows: n_per_cell[(ita, pi)] rows spread over participants_per_cell[...] participants."""
    rng = rng or np.random.default_rng(1)
    s, ig, pg, pid = [], [], [], []
    for (a, b), n in n_per_cell.items():
        k = (participants_per_cell or {}).get((a, b), n)
        s += list(rng.uniform(0, 1, n)); ig += [a] * n; pg += [b] * n; pid += [f"{a}{b}{i % max(k, 1)}" for i in range(n)]
    return s, ig, pg, pid


FULL = {c: 40 for c in core.CELLS}


def test_every_cell_with_enough_data_is_calibrated_on_its_own():
    cal = core.calibrate(*_cal(FULL), cfg=CFG)
    assert all(c["status"] == core.CALIBRATED and c["q"] is not None and c["source"] == "own cell" for c in cal["cells"].values())
    assert len(cal["cells"]) == 6 and cal["cells"]["Dark|Low"]["label"] == "Dark × Low PI"


def test_a_cell_with_no_data_is_insufficient_and_never_filled_in():
    counts = {**FULL, ("Dark", "Low"): 0, ("Dark", "Normal"): 0}
    cal = core.calibrate(*_cal(counts), cfg=CFG)
    for k in ("Dark|Low", "Dark|Normal"):
        c = cal["cells"][k]
        assert c["status"] == core.INSUFFICIENT and c["q"] is None and c["n_rows"] == 0 and c["merged_with"] == []
    assert cal["cells"]["Light|Low"]["status"] == core.CALIBRATED


def test_participants_not_just_rows_decide_sufficiency():
    cal = core.calibrate(*_cal({**FULL, ("Medium", "Low"): 60}, participants_per_cell={("Medium", "Low"): 3}), cfg=replace(CFG, merge_rule="none"))
    c = cal["cells"]["Medium|Low"]
    assert c["n_rows"] == 60 and c["n_participants"] == 3 and c["status"] == core.INSUFFICIENT


def test_small_cell_is_merged_only_by_the_documented_rule():
    counts = {**FULL, ("Light", "Low"): 4}                           # too small alone, but the Light group pooled is large enough
    cal = core.calibrate(*_cal(counts), cfg=CFG)
    c = cal["cells"]["Light|Low"]
    assert c["status"] == core.MERGED and c["q"] is not None and c["merged_with"] == ["Light × Normal PI"] and "documented merge rule" in c["source"]
    assert cal["cells"]["Light|Normal"]["status"] == core.CALIBRATED          # the healthy neighbour keeps its own Q
    assert cal["cells"]["Medium|Low"]["status"] == core.CALIBRATED             # other groups are never pooled in
    none = core.calibrate(*_cal(counts), cfg=replace(CFG, merge_rule="none"))
    assert none["cells"]["Light|Low"]["status"] == core.INSUFFICIENT and none["cells"]["Light|Low"]["q"] is None


def test_merging_never_crosses_ita_groups_and_cannot_rescue_an_empty_group():
    counts = {**FULL, ("Dark", "Low"): 2, ("Dark", "Normal"): 3}
    cal = core.calibrate(*_cal(counts), cfg=CFG)
    assert cal["cells"]["Dark|Low"]["status"] == core.INSUFFICIENT and cal["cells"]["Dark|Normal"]["status"] == core.INSUFFICIENT


def test_q_for_returns_none_for_insufficient_cells():
    cal = core.calibrate(*_cal({**FULL, ("Dark", "Low"): 0, ("Dark", "Normal"): 0}), cfg=CFG)
    assert core.q_for(cal, "Dark", "Low")[0] is None and core.q_for(cal, "Light", "Normal")[0] is not None


def test_group_metrics_known_values_and_abstentions_are_excluded():
    df = pd.DataFrame({"participant_id": list("aabbc"), "y": [95.0, 90.0, 93.0, 99.0, 90.0],
                       "lower": [94.0, 91.0, 92.0, 94.0, np.nan], "upper": [96.0, 93.0, 95.0, 98.0, np.nan]})
    m = core.group_metrics(df, CONFORMAL_CONFIG)
    assert m["n_total"] == 5 and m["n_abstained"] == 1 and m["n_obs"] == 4 and m["n_participants"] == 2
    assert m["coverage"] == pytest.approx(0.5)                                  # rows 0 and 2 are inside
    assert m["mean_width"] == pytest.approx((2 + 2 + 3 + 4) / 4)
    assert m["lower_bound_violation_rate"] == pytest.approx(0.25)               # only y=90 < lower=91
    assert m["low_n"] is True                                                    # 2 participants < 5


def test_coverage_report_lists_every_group_including_empty_ones():
    df = pd.DataFrame({"participant_id": ["a", "b"], "y": [95.0, 94.0], "lower": [94.0, 90.0], "upper": [96.0, 93.0],
                       "ita_group": ["Light", "Medium"], "pi_group": ["Normal", "Low"]})
    r = core.coverage_report(df)
    assert r["target_coverage"] == pytest.approx(0.9) and r["overall"]["coverage"] == 0.5
    assert [g["group"] for g in r["ita"]] == ["Light", "Medium", "Dark"] and [g["group"] for g in r["pi"]] == ["Low", "Normal"] and len(r["ita_x_pi"]) == 6
    dark = r["ita"][2]
    assert dark["n_total"] == 0 and dark["coverage"] is None and dark["mean_width"] is None


# =================================================================== end to end on test-only data
ATT = {"attested_real": True, "filename": "study.csv"}


def study_csv(n=150, seed=3) -> bytes:
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        ita = rng.uniform(12, 60)                              # no Dark participants -> Dark cells have no calibration data
        for s in (1, 2):
            spo2, pi = rng.uniform(88, 99), float(np.exp(rng.uniform(np.log(0.3), np.log(5))))
            low = pi < 1
            sao2 = spo2 - 0.6 * (1 + (30 - ita) / 60) - 1.0 * low + rng.normal(0, 0.5 + 1.0 * low)
            rows.append({"participant_id": f"P{i:03d}", "session_id": f"P{i:03d}_S0{s}", "timestamp": 60.0 * s, "spo2": round(spo2, 1),
                         "sao2": round(float(np.clip(sao2, 50, 100)), 1), "pi": round(pi, 3), "ita": round(ita, 1),
                         "sqi": round(rng.uniform(60, 100), 1), "motion": round(rng.uniform(0, 30), 1), "device_id": "OximeterX"})
    return pd.DataFrame(rows).to_csv(index=False).encode()


def build_env(root, n=150, seed=3) -> Paths:
    paths = make_paths(root)
    ingest.add_upload("combined", study_csv(n, seed), ATT, paths)
    merge.build_research_dataset(paths)
    pl.process_dataset(paths)
    return paths


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    paths = build_env(tmp_path_factory.mktemp("conformal"))
    return paths, cfit.fit_conformal(paths, CFG)


READING = {"spo2": 94.0, "pi": 2.0, "ita": 35.0, "signal_quality": "GOOD", "motion": "LOW", "device": "Phone camera", "sqi": 85, "motion_score": 5}


def test_fit_saves_every_artifact_and_reports_the_three_quantile_models(env):
    paths, r = env
    assert r["status"] == "fitted" and r["data_provenance"]["kind"] == "LOADED" and r["target_coverage"] == pytest.approx(0.9)
    for f in ("cqr_models.joblib",):
        assert (paths.models / f).exists()
    for f in ("conformal_calibration.json", "conformal_metrics.json", "conformal_test_predictions.csv"):
        assert (paths.results / f).exists()
    q = r["quantile_models"]
    assert q["lo"]["quantile"] == pytest.approx(0.05) and q["median"]["quantile"] == 0.5 and q["hi"]["quantile"] == pytest.approx(0.95)
    assert "TRAIN split only" in q["lo"]["cv_scheme"] and r["features"][-2:] == ["sqi", "motion"]


def test_the_test_split_is_only_used_for_evaluation(env):
    paths, r = env
    assert "never used to fit or calibrate" in r["dataset"]["test_use"]
    sets = {k: set(pd.read_csv(paths.processed / f"{k}.csv")[GROUP_COL]) for k in ("train", "calibration", "test")}
    assert not (sets["train"] & sets["calibration"]) and not (sets["train"] & sets["test"]) and not (sets["calibration"] & sets["test"])


def test_changing_test_labels_changes_nothing_that_was_fitted_or_calibrated(env, tmp_path):
    paths_a, ra = env
    b_root = tmp_path / "b"
    shutil.copytree(paths_a.processed.parent, b_root)
    paths_b = make_paths(b_root)
    t = pd.read_csv(paths_b.processed / "test.csv")
    t["sao2_target"] = np.random.default_rng(9).permutation(t["sao2_target"].to_numpy()) - 4.0
    t.to_csv(paths_b.processed / "test.csv", index=False)
    rb = cfit.fit_conformal(paths_b, CFG)
    assert rb["calibration"] == ra["calibration"]                                              # Q's identical
    X = pd.read_csv(paths_a.processed / "train.csv")[ra["features"]].head(30)
    ma, mb = joblib.load(paths_a.models / "cqr_models.joblib")["models"], joblib.load(paths_b.models / "cqr_models.joblib")["models"]
    for k in ("lo", "median", "hi"):
        assert np.allclose(ma[k].predict(X), mb[k].predict(X))
    assert rb["coverage"]["mondrian"]["overall"]["coverage"] != ra["coverage"]["mondrian"]["overall"]["coverage"]   # but the evaluation does see them


def test_changing_calibration_labels_changes_Q_but_not_the_quantile_models(env, tmp_path):
    paths_a, ra = env
    b_root = tmp_path / "c"
    shutil.copytree(paths_a.processed.parent, b_root)
    paths_b = make_paths(b_root)
    c = pd.read_csv(paths_b.processed / "calibration.csv")
    c["sao2_target"] = c["sao2_target"] - 6.0
    c.to_csv(paths_b.processed / "calibration.csv", index=False)
    rb = cfit.fit_conformal(paths_b, CFG)
    X = pd.read_csv(paths_a.processed / "train.csv")[ra["features"]].head(30)
    ma, mb = joblib.load(paths_a.models / "cqr_models.joblib")["models"], joblib.load(paths_b.models / "cqr_models.joblib")["models"]
    for k in ("lo", "median", "hi"):
        assert np.allclose(ma[k].predict(X), mb[k].predict(X))                                 # fitting never saw calibration data
    qa = [c["q"] for c in ra["calibration"]["cells"].values() if c["q"] is not None]
    qb = [c["q"] for c in rb["calibration"]["cells"].values() if c["q"] is not None]
    assert qa != qb


def test_calibration_table_documents_every_cell_and_never_invents_data(env):
    _, r = env
    cells = r["calibration"]["cells"]
    assert list(cells) == ["Light|Low", "Light|Normal", "Medium|Low", "Medium|Normal", "Dark|Low", "Dark|Normal"]
    for k in ("Dark|Low", "Dark|Normal"):                                                       # the data has no Dark participants at all
        assert cells[k]["status"] == "INSUFFICIENT" and cells[k]["q"] is None and cells[k]["n_participants"] == 0
    for c in cells.values():
        assert c["status"] in ("CALIBRATED", "MERGED", "INSUFFICIENT") and c["requirement"].startswith("≥ 6 participants")
        if c["status"] == "MERGED":
            assert c["merged_with"] and "documented merge rule" in c["source"]
    assert r["calibration"]["merge_rule"] == "ita_group"


def test_test_intervals_are_valid_and_consistent_with_the_saved_predictions(env):
    paths, r = env
    p = pd.read_csv(paths.results / "conformal_test_predictions.csv")
    assert list(p.columns) == ["participant_id", "spo2", "sao2", "predicted_sao2", "lower_bound", "upper_bound", "interval_width", "covered",
                               "ita_group", "pi_group", "calibration_status"]
    has = p["lower_bound"].notna()
    assert has.any() and (p.loc[has, "lower_bound"] <= p.loc[has, "upper_bound"]).all() and p.loc[has, "upper_bound"].le(100).all() and p.loc[has, "lower_bound"].ge(0).all()
    inside = (p.loc[has, "sao2"] >= p.loc[has, "lower_bound"]) & (p.loc[has, "sao2"] <= p.loc[has, "upper_bound"])
    assert list(p.loc[has, "covered"].astype(str)) == list(inside.astype(str))
    assert np.allclose(p.loc[has, "interval_width"], p.loc[has, "upper_bound"] - p.loc[has, "lower_bound"])
    assert (p.loc[~has, "calibration_status"] == "INSUFFICIENT").all()
    assert r["coverage"]["mondrian"]["overall"]["n_obs"] == int(has.sum())


def test_coverage_report_has_every_required_breakdown_and_comparisons(env):
    _, r = env
    cov = r["coverage"]
    for name in ("mondrian", "marginal", "uncalibrated_quantiles"):
        rep = cov[name]
        assert {"overall", "ita", "pi", "ita_x_pi"} <= set(rep) and len(rep["ita_x_pi"]) == 6
        assert rep["overall"]["coverage"] is not None and rep["overall"]["mean_width"] > 0 and rep["overall"]["lower_bound_violation_rate"] is not None
    assert cov["target_coverage"] == pytest.approx(0.9)
    assert 0.6 <= cov["mondrian"]["overall"]["coverage"] <= 1.0                                  # sanity only: small test split
    assert r["wording"] == COVERAGE_WORDING and "not a probability" in r["wording"]


def test_refuses_without_verified_real_data(tmp_path):
    paths = make_paths(tmp_path)
    with pytest.raises(ModelError) as e:
        cfit.fit_conformal(paths, CFG)
    assert e.value.code == "no_dataset"
    paths.raw.mkdir(parents=True)
    pd.DataFrame({GROUP_COL: ["a"]}).to_csv(paths.raw / "dataset.csv", index=False)
    with pytest.raises(ModelError) as e:
        cfit.fit_conformal(paths, CFG)
    assert e.value.code == "unverified_data" and "UNVERIFIED DATA — NOT A RESEARCH RESULT" in e.value.message
    assert not paths.models.exists() and not paths.results.exists()


def test_status_before_and_after(env, tmp_path):
    s0 = cfit.status(make_paths(tmp_path))
    assert s0["fitted"] is False and s0["can_fit"] is False and s0["blockers"]
    paths, r = env
    s = cfit.status(paths)
    assert s["fitted"] and s["stale"] is False and s["can_fit"] and s["target_coverage"] == pytest.approx(0.9)
    cells = r["calibration"]["cells"].values()
    assert s["calibration_summary"]["insufficient"] == sum(c["status"] == "INSUFFICIENT" for c in cells) >= 2


# =================================================================== prediction + reliability state
def test_prediction_gives_an_interval_lower_bound_and_state(env):
    paths, r = env
    out = cpredict.predict_one(READING, paths, CFG)
    assert out["reliability_state"] in ("GREEN", "AMBER", "RED") and out["ita_group"] == "Medium" and out["pi_group"] == "Normal"
    i = out["interval"]
    assert i["lower"] <= out["predicted_sao2"] <= i["upper"] and i["width"] == pytest.approx(i["upper"] - i["lower"], abs=0.02) and out["lower_bound"] == i["lower"]
    assert out["cell"]["label"] == "Medium × Normal PI" and out["cell"]["status"] in ("CALIBRATED", "MERGED")
    assert out["target_coverage"] == pytest.approx(0.9) and out["method"].startswith("CQR + Mondrian")
    assert any(x["code"] in ("calibrated_cell", "merged_cell") for x in out["reasons"])


def test_prediction_wording_never_claims_individual_probability_or_clinical_validation(env):
    out = cpredict.predict_one(READING, env[0], CFG)
    text = json.dumps(out)
    assert "95%" not in text and "95 %" not in text and "clinically validated" in out["wording"] and "not a probability" in out["wording"]
    assert "targets the stated coverage under the calibration assumptions" in out["wording"]


@pytest.mark.parametrize("changes,code", [({"signal_quality": "POOR"}, "poor_signal"), ({"motion": "HIGH"}, "high_motion")])
def test_poor_signal_or_high_motion_abstains_without_an_interval(env, changes, code):
    out = cpredict.predict_one({**READING, **changes}, env[0], CFG)
    assert out["reliability_state"] == "ABSTAIN" and out["interval"] is None and out["lower_bound"] is None and out["predicted_sao2"] is None
    assert any(x["code"] == code for x in out["reasons"]) and any(x["code"] == "abstain" for x in out["reasons"])


def test_input_outside_the_fitted_range_abstains(env):
    out = cpredict.predict_one({**READING, "spo2": 75.0}, env[0], CFG)
    assert out["reliability_state"] == "ABSTAIN" and out["interval"] is None
    r = next(x for x in out["reasons"] if x["code"] == "outside_range")
    assert r["title"] == "OUTSIDE VALIDATION RANGE" and "spo2 = 75" in r["text"]
    assert cpredict.predict_one({**READING, "ita": -30.0}, env[0], CFG)["reliability_state"] == "ABSTAIN"


def test_missing_model_inputs_abstain_instead_of_guessing(env):
    no_sqi = {k: v for k, v in READING.items() if k != "sqi"}
    out = cpredict.predict_one(no_sqi, env[0], CFG)
    assert out["reliability_state"] == "ABSTAIN" and any(x["code"] == "missing_inputs" and "SQI" in x["text"] for x in out["reasons"])
    out = cpredict.predict_one({k: v for k, v in READING.items() if k != "motion_score"}, env[0], CFG)
    assert out["reliability_state"] == "ABSTAIN" and "motion score" in next(x for x in out["reasons"] if x["code"] == "missing_inputs")["text"]


def test_insufficient_calibration_cell_abstains_and_says_so(env, tmp_path):
    paths_a, _ = env
    root = tmp_path / "ins"
    shutil.copytree(paths_a.processed.parent, root)
    paths = make_paths(root)
    cfit.fit_conformal(paths, CFG)
    m = json.loads((paths.results / "conformal_metrics.json").read_text())
    m["calibration"]["cells"]["Medium|Normal"].update(status="INSUFFICIENT", q=None, n_participants=2, n_rows=3)
    (paths.results / "conformal_metrics.json").write_text(json.dumps(m))
    out = cpredict.predict_one(READING, paths, CFG)
    assert out["reliability_state"] == "ABSTAIN" and out["interval"] is None
    r = next(x for x in out["reasons"] if x["code"] == "insufficient_calibration")
    assert r["title"] == "INSUFFICIENT CALIBRATION DATA" and "2 calibration participant" in r["text"] and "No data were invented" in r["text"]
    assert out["cell"]["status"] == "INSUFFICIENT"


def test_a_merged_cell_is_flagged_not_presented_as_a_per_cell_guarantee(env):
    paths, r = env
    merged = [c for c in r["calibration"]["cells"].values() if c["status"] == "MERGED"]
    if not merged:
        pytest.skip("this fit did not need a merge")
    c = merged[0]
    ita = {"Light": 50.0, "Medium": 25.0}[c["ita_group"]]
    out = cpredict.predict_one({**READING, "ita": ita, "pi": 0.7 if c["pi_group"] == "Low" else 2.0}, paths, CFG)
    if out["reliability_state"] != "ABSTAIN":
        assert out["cell"]["status"] == "MERGED" and any(x["code"] == "merged_cell" for x in out["reasons"])


def test_reliability_state_combines_the_rule_engine_with_the_conformal_interval(env):
    paths, _ = env
    assert cpredict.predict_one({**READING, "pi": 0.6}, paths, CFG)["reliability_state"] in ("AMBER", "RED", "ABSTAIN")     # low PI never GREEN
    strict = replace(CFG, width_amber=0.0, width_red=0.0001)
    out = cpredict.predict_one(READING, paths, strict)
    assert out["reliability_state"] == "RED" and any(x["code"] == "wide_interval" and x["severity"] == "critical" for x in out["reasons"])
    lax = replace(CFG, width_amber=1000, width_red=2000, gap_amber=1000, gap_red=2000)
    assert cpredict.predict_one(READING, paths, lax)["reliability_state"] in ("GREEN", "AMBER")


def test_validation_errors_and_not_fitted(env, tmp_path):
    with pytest.raises(InputValidationError):
        cpredict.predict_one({**READING, "spo2": 105}, env[0], CFG)
    with pytest.raises(ModelError) as e:
        cpredict.predict_one(READING, make_paths(tmp_path), CFG)
    assert e.value.code == "not_calibrated"


# =================================================================== API
@pytest.fixture
def api(env):
    set_paths(env[0])
    yield TestClient(app)
    set_paths(None)


def test_api_status_metrics_coverage_predict(api):
    assert api.get("/api/conformal/status").json()["fitted"] is True
    m = api.get("/api/conformal/metrics").json()
    assert m["status"] == "fitted" and set(m["quantile_models"]) == {"lo", "median", "hi"}
    c = api.get("/api/conformal/coverage").json()
    assert {"target_coverage", "mondrian", "marginal", "uncalibrated_quantiles", "calibration", "wording", "alpha"} <= set(c) and c["alpha"] == pytest.approx(0.1)
    p = api.post("/api/conformal/predict", json=READING).json()
    assert p["reliability_state"] in ("GREEN", "AMBER", "RED") and p["interval"]["lower"] < p["interval"]["upper"]
    a = api.post("/api/conformal/predict", json={**READING, "signal_quality": "POOR"}).json()
    assert a["reliability_state"] == "ABSTAIN" and a["interval"] is None


def test_api_errors_are_actionable(api, tmp_path):
    bad = api.post("/api/conformal/predict", json={**READING, "spo2": 105})
    assert bad.status_code == 422 and "OUTSIDE SUPPORTED" in bad.json()["errors"][0]["message"]
    assert api.post("/api/conformal/predict", json={}).status_code == 422
    set_paths(make_paths(tmp_path))
    try:
        c = TestClient(app)
        m = c.get("/api/conformal/metrics"); assert m.status_code == 200 and m.json()["available"] is False and m.json()["errors"][0]["code"] == "not_calibrated"
        assert c.get("/api/conformal/coverage").json()["available"] is False
        assert c.post("/api/conformal/predict", json=READING).json()["errors"][0]["code"] == "not_calibrated"
        f = c.post("/api/conformal/fit")
        assert f.status_code == 422 and f.json()["errors"][0]["code"] == "no_dataset"
        assert c.get("/api/conformal/status").json()["can_fit"] is False
    finally:
        set_paths(None)


def test_nothing_is_fitted_automatically_when_data_is_built(tmp_path):
    paths = build_env(tmp_path / "auto", n=40)
    assert not (paths.models / "cqr_models.joblib").exists() and not (paths.results / "conformal_metrics.json").exists()


# ====================================================================== Phase 14 additions
def test_median_width_and_participant_level_coverage():
    df = pd.DataFrame({"participant_id": ["a", "a", "a", "b"], "y": [1.0, 2.0, 9.0, 5.0], "lower": [0.0, 0.0, 0.0, 4.0], "upper": [3.0, 3.0, 3.0, 6.0]})
    m = core.group_metrics(df)
    assert m["median_width"] == 3.0 and m["mean_width"] == pytest.approx(2.75)
    assert m["coverage"] == pytest.approx(0.75)                       # row level: 3 of 4 covered
    assert m["participant_mean_coverage"] == pytest.approx((2 / 3 + 1.0) / 2)      # each participant counts once


def test_fit_saves_reproducibility_information(env):
    paths, r = env
    assert r["versions"]["dataset_version"] and r["versions"]["feature_version"] and r["versions"]["model_version"]
    assert r["config"]["alpha"] == 0.1 and r["target_coverage"] == pytest.approx(0.9)
    assert len(r["cell_definitions"]["cells"]) == 6 and set(r["cell_definitions"]["ita_groups"]) == {"Light", "Medium", "Dark"}
    assert r["calibration_sample_counts"]["participants"] == r["dataset"]["splits"]["calibration"]["participants"]
    saved = json.loads((paths.results / "conformal_metrics.json").read_text())
    assert saved["versions"] == r["versions"]


def test_prediction_exposes_upper_bound_and_width_and_none_when_abstaining(env):
    paths, _ = env
    ok = cpredict.predict_one(READING, paths, CFG)
    assert ok["upper_bound"] == ok["interval"]["upper"] and ok["interval_width"] == pytest.approx(ok["upper_bound"] - ok["lower_bound"], abs=0.02)
    ab = cpredict.predict_one({**READING, "signal_quality": "POOR"}, paths, CFG)
    assert ab["reliability_state"] == "ABSTAIN" and ab["upper_bound"] is None and ab["interval_width"] is None and ab["lower_bound"] is None


def test_not_available_message_and_calibrate_endpoint_without_data(tmp_path):
    set_paths(make_paths(tmp_path))
    c = TestClient(app)
    st = c.get("/api/conformal/status").json()
    assert st["available"] is False and st["message"] == "CONFORMAL MODEL NOT AVAILABLE"
    for r in (c.get("/api/conformal/metrics"), c.post("/api/conformal/predict", json=READING)):
        assert r.json()["errors"][0]["message"].startswith("CONFORMAL MODEL NOT AVAILABLE")
    r = c.post("/api/conformal/calibrate")
    assert r.status_code == 422 and r.json()["errors"][0]["message"].startswith("Training unavailable")
    assert not (tmp_path / "models" / "cqr_models.joblib").exists()


def test_calibrate_endpoint_is_the_same_as_fit(env):
    paths, _ = env
    set_paths(paths)
    r = TestClient(app).post("/api/conformal/calibrate")
    assert r.status_code == 200 and r.json()["status"] == "fitted" and r.json()["versions"]["model_version"]
