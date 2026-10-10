"""Phase 10: participant-level bootstrap, validation report and explainability. TEST-ONLY synthetic data in temp folders."""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.config import VALIDATION_CONFIG, XAI_NOTICE
from app.conformal import fit as cfit
from app.main import app
from app.ml import train
from app.ml.paths import set_paths
from app.validation import report, stats

from .test_conformal import CFG, build_env

FAST = replace(VALIDATION_CONFIG, bootstrap_reps=300)


def _df(n_part, per=4, seed=0, spread=1.0):
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(n_part):
        shift = rng.normal(0, spread)
        for _ in range(per):
            y = rng.uniform(85, 99)
            rows.append({"participant_id": f"P{p}", "sao2": y, "pred": y + shift + rng.normal(0, 0.5)})
    return pd.DataFrame(rows)


def test_estimates_match_direct_computation():
    d = _df(20)
    m = {r["metric"]: r for r in stats.error_metrics(d, "pred", cfg=FAST)}
    e = d["pred"] - d["sao2"]
    assert m["MAE"]["estimate"] == pytest.approx(e.abs().mean())
    assert m["RMSE"]["estimate"] == pytest.approx(np.sqrt((e ** 2).mean()))
    assert m["Bias"]["estimate"] == pytest.approx(e.mean())
    assert m["R²"]["estimate"] == pytest.approx(1 - (e ** 2).sum() / ((d["sao2"] - d["sao2"].mean()) ** 2).sum())
    assert m["MAE"]["ci_low"] <= m["MAE"]["estimate"] <= m["MAE"]["ci_high"] and m["MAE"]["n_participants"] == 20 and m["MAE"]["n_obs"] == 80


def test_bootstrap_is_deterministic():
    d = _df(15)
    assert stats.error_metrics(d, "pred", cfg=FAST) == stats.error_metrics(d, "pred", cfg=FAST)


def test_ci_is_withheld_below_the_participant_minimum():
    r = stats.error_metrics(_df(5), "pred", cfg=FAST)
    assert all(x["ci_low"] is None and x["ci_high"] is None and x["estimate"] is not None and "only 5" in x["ci_status"] for x in r)


def test_empty_group_has_no_numbers():
    r = stats.error_metrics(_df(5).iloc[:0], "pred", cfg=FAST)
    assert all(x["estimate"] is None and x["ci_low"] is None for x in r)


def test_cluster_bootstrap_is_wider_than_a_row_bootstrap_when_participants_differ():
    d = _df(30, per=8, seed=2, spread=2.0)
    cl = {r["metric"]: r for r in stats.error_metrics(d, "pred", cfg=FAST)}["Bias"]
    rng = np.random.default_rng(1)
    e = (d["pred"] - d["sao2"]).to_numpy()
    rows = [rng.choice(e, len(e)).mean() for _ in range(500)]
    assert (cl["ci_high"] - cl["ci_low"]) > np.subtract(*np.percentile(rows, [97.5, 2.5]))


# ------------------------------------------------------------------ end to end
@pytest.fixture(scope="module")
def env(tmp_path_factory):
    paths = build_env(tmp_path_factory.mktemp("validation"))
    train.train_models(paths)
    cfit.fit_conformal(paths, CFG)
    return paths


def test_report_has_every_required_section(env):
    r = report.build_report(env, FAST)
    assert r["available"] and not r["stale"] and "TEST split only" in r["split"]
    for name in ("ridge", "lightgbm", "spo2_as_is"):
        assert {x["metric"] for x in r["overall"][name]} == {"MAE", "RMSE", "Bias", "R²"}
    assert [g["group"] for g in r["subgroups"]["ita"]] == ["Light", "Medium", "Dark"]
    assert [g["group"] for g in r["subgroups"]["pi"]] == ["Low", "Normal"]
    assert len(r["subgroups"]["ita_x_pi"]) == 6
    assert r["conformal"]["available"] and {x["metric"] for x in r["conformal"]["overall"]["metrics"]} == {"Coverage", "Mean interval width", "Lower-bound violation rate"}
    assert r["plots"]["scatter"] and r["plots"]["error_hist"]["counts"].keys() == {"SpO₂ reading", "Ridge", "LightGBM"}
    assert sum(g["n_obs"] for g in r["subgroups"]["ita"]) == r["sample"]["test_observations"]


def test_empty_subgroup_is_reported_without_invented_numbers(env):
    dark = next(g for g in report.build_report(env, FAST)["subgroups"]["ita"] if g["group"] == "Dark")      # test data has no Dark participants
    assert dark["n_obs"] == 0 and dark["ridge"] == []


def test_small_subgroups_get_no_ci(env):
    r = report.build_report(env, replace(FAST, min_ci_participants=10_000))
    assert all(x["ci_low"] is None for x in r["overall"]["ridge"])


def test_xai_is_consistent_with_the_models(env):
    x = report.build_xai(env)
    assert x["notice"] == XAI_NOTICE and XAI_NOTICE in x["explanation"]
    assert {r["feature"] for r in x["ridge"]["rows"]} == set(x["features"])
    for r in x["ridge"]["rows"]:
        assert np.sign(r["coef_per_unit"]) == np.sign(r["coef_standardized"])
    assert sum(r["gain_importance"] for r in x["lightgbm"]["rows"]) == pytest.approx(1.0)
    assert x["lightgbm"]["rows"][0]["mean_abs_shap"] >= x["lightgbm"]["rows"][-1]["mean_abs_shap"]


def test_shap_contributions_add_up_to_the_prediction(env):
    import joblib
    test = pd.read_csv(env.processed / "test.csv")
    art = joblib.load(env.models / train.LGBM_FILE)
    X = test[art["features"]]
    c = art["model"].booster_.predict(X, pred_contrib=True)
    assert np.allclose(c.sum(axis=1), art["model"].predict(X), atol=1e-6)


def test_api_available_and_not_available(env, tmp_path):
    set_paths(env)
    c = TestClient(app)
    assert c.get("/api/validation/report").status_code == 200 and c.get("/api/xai/report").json()["available"]
    from .test_conformal import make_paths
    set_paths(make_paths(tmp_path))
    for p in ("/api/validation/report", "/api/xai/report"):
        r = c.get(p)
        assert r.status_code == 200 and r.json()["available"] is False
    assert "verified" in c.get("/api/health").json()["dataset"]


def test_insufficient_groups_carry_no_values_and_enough_groups_do(env):
    r = report.build_report(env, FAST)
    seen = set()
    for g in r["subgroups"]["ita"] + r["subgroups"]["pi"] + r["subgroups"]["ita_x_pi"]:
        seen.add(g["status"])
        if g["status"] == "INSUFFICIENT DATA":
            assert g["ridge"] == [] and g["lightgbm"] == [] and g["spo2_as_is"] == []
        else:
            assert g["n_participants"] >= 5 and g["ridge"][0]["estimate"] is not None
    assert "INSUFFICIENT DATA" in seen                                 # the test data has no Dark participants
    c = r["conformal"]
    for g in [c["overall"]] + c["ita"] + c["pi"] + c["ita_x_pi"]:
        assert (g["status"] == "OK") == bool(g["metrics"]) and (g["median_width"] is not None) == (g["status"] == "OK" and g["n_obs"] > 0)


def test_health_reports_conformal_state_and_no_demo_artifacts_are_assumed(tmp_path):
    from tests.test_conformal import make_paths
    set_paths(make_paths(tmp_path))
    h = TestClient(app).get("/api/health").json()
    assert h["conformal"] == {"calibrated": False} and h["model"]["trained"] is False and h["dataset"]["loaded"] is False
