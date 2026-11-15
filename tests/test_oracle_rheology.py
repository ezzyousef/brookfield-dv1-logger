"""Independent numerical oracles for every conversion and model in the app.

Expected values come from first principles written out here (constants transcribed from the
DV1 manual table into the test, formulas typed independently), or from an independent
implementation (SciPy's curve_fit and Student-t), never from the code under test.
Worked numbers are collected in docs/EQUATION_REGRESSION_REPORT.md.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from core import analysis as A
from core.analysis import Reading
from core.compare import hysteresis, replicate_table
from core.qc import qc_flags
from core.rheology import MODELS, FlowData, compare_models, fit_model, flow_data, t_cdf, t_ppf
from core.session import ExperimentNotebook

scipy_optimize = pytest.importorskip("scipy.optimize")
scipy_stats = pytest.importorskip("scipy.stats")


# ----------------------------------------------------------------------------- conversions
@pytest.mark.parametrize("model,tk,spindle,smc,rpm,expected", [
    # TK (Table D-2) x SMC (Appendix D) x 10 000 / rpm, typed in from the manual's table
    ("DV1MLV", 0.09375, "LV1", 6.4, 60.0, 100.0),          # the classic LV #1 at 60 rpm = 100 cP
    ("DV1MRV", 1.0, "RV3", 10.0, 10.0, 10_000.0),          # RV #3 at 10 rpm = 10 000 cP
    ("DV1MLV", 0.09375, "LV4", 640.0, 0.3, 2_000_000.0),
    ("DV1MHB", 8.0, "HB7", 400.0, 0.5, 64_000_000.0),
    ("DV1MHA", 2.0, "SC4-21", 5.0, 100.0, 1_000.0),
])
def test_full_scale_range(model, tk, spindle, smc, rpm, expected):
    assert tk * smc * 10_000.0 / rpm == pytest.approx(expected)       # the arithmetic itself
    assert A.full_scale_range_cp(model, spindle, rpm) == pytest.approx(expected, rel=1e-12)


@pytest.mark.parametrize("spindle,src,rpm", [("SC4-18", 1.32, 10.0), ("ULA", 1.223, 60.0),
                                             ("CPA-40Z", 7.5, 2.0), ("LV-2C", 0.212, 100.0)])
def test_shear_rate_is_src_times_rpm(spindle, src, rpm):
    assert A.shear_rate_per_sec(spindle, rpm) == pytest.approx(src * rpm, rel=1e-12)


def test_shear_stress_units():
    # 1000 cP = 1 Pa·s; at 13.2 1/s, tau = 13.2 Pa = 132 dyn/cm² (1 dyn/cm² = 0.1 Pa)
    assert A.shear_stress_dyn_cm2(1000.0, 13.2) == pytest.approx(132.0)
    assert A.shear_stress_pa(1000.0, 13.2) == pytest.approx(13.2)
    assert A.dyn_cm2_to_pa(132.0) == pytest.approx(13.2)
    assert A.cp_to_pa_s(1.0) == pytest.approx(1e-3)


def test_viscosity_from_torque_and_torque_in_dyne_cm():
    assert A.viscosity_from_torque_cp("DV1MLV", "LV1", 60.0, 50.0) == pytest.approx(50.0)
    assert A.viscosity_from_torque_cp("DV1MRV", "RV3", 10.0, 37.5) == pytest.approx(3750.0)
    # LV spring = 0.09375 of the RV spring's 7187 dyne·cm
    assert A.torque_dyne_cm("DV1MLV", 100.0) == pytest.approx(673.78125)
    assert A.torque_dyne_cm("DV1MHB", 50.0) == pytest.approx(0.5 * 8 * 7187.0)


# ----------------------------------------------------------------------------- Student t
@pytest.mark.parametrize("df,expected", [(1, 12.7062), (2, 4.3027), (5, 2.5706), (10, 2.2281), (30, 2.0423)])
def test_t_quantile_matches_tables_and_scipy(df, expected):
    assert t_ppf(0.975, df) == pytest.approx(expected, abs=1e-4)               # printed t tables
    assert t_ppf(0.975, df) == pytest.approx(scipy_stats.t.ppf(0.975, df), rel=1e-10)
    assert t_cdf(1.3, df) == pytest.approx(scipy_stats.t.cdf(1.3, df), rel=1e-10)
    assert t_ppf(0.025, df) == pytest.approx(-t_ppf(0.975, df), rel=1e-10)


# ----------------------------------------------------------------------------- model recovery
GAMMA = np.logspace(-2, 2, 13)          # 0.01 … 100 1/s, four decades


def _flow(eta):
    return FlowData(GAMMA.copy(), np.asarray(eta, dtype=float))


TRUTH = {
    "newtonian": ({"μ": 850.0}, lambda g: np.full_like(g, 850.0)),
    "power_law": ({"K": 4200.0, "n": 0.62}, lambda g: 4200.0 * g ** (0.62 - 1)),
    # tau in Pa, eta in cP = 1000 * tau / gamma
    "bingham": ({"τ₀": 2.5, "μp": 120.0}, lambda g: 1000 * (2.5 + 0.120 * g) / g),
    "herschel_bulkley": ({"τ₀": 1.5, "K": 3000.0, "n": 0.5}, lambda g: 1000 * (1.5 + 3.0 * g ** 0.5) / g),
    "cross": ({"η₀": 5000.0, "λ": 0.8, "m": 0.9}, lambda g: 5000.0 / (1 + (0.8 * g) ** 0.9)),
    "carreau": ({"η₀": 8000.0, "λ": 2.0, "n": 0.4}, lambda g: 8000.0 * (1 + (2.0 * g) ** 2) ** ((0.4 - 1) / 2)),
}


@pytest.mark.parametrize("key", list(TRUTH))
def test_each_model_recovers_the_parameters_its_data_were_built_from(key):
    params, eta = TRUTH[key]
    fit = fit_model(key, _flow(eta(GAMMA)))
    assert fit.supported, fit.reason
    for name, value in params.items():
        assert fit.value(name) == pytest.approx(value, rel=1e-6), name
    assert fit.rms_pct < 1e-6


def _noisy(key, seed=4, pct=3.0):
    rng = np.random.default_rng(seed)
    return TRUTH[key][1](GAMMA) * np.exp(rng.normal(0, pct / 100, GAMMA.size))


def _scipy_fit(key, data):
    """The same log-residual least squares, solved by SciPy, with its own CI arithmetic."""
    forms = {
        "power_law": (lambda g, lk, n: lk + (n - 1) * np.log(g), [8.0, 0.6]),
        "bingham": (lambda g, t0, lmu: np.log(1000 * t0 / g + np.exp(lmu)), [1.0, 4.0]),
        "herschel_bulkley": (lambda g, t0, lk, n: np.log(1000 * t0 / g + np.exp(lk) * g ** (n - 1)), [1.0, 8.0, 0.5]),
        "cross": (lambda g, le0, ll, m: le0 - np.log1p((np.exp(ll) * g) ** m), [8.5, 0.0, 1.0]),
        "carreau": (lambda g, le0, ll, n: le0 + (n - 1) / 2 * np.log1p((np.exp(ll) * g) ** 2), [9.0, 0.5, 0.5]),
    }
    f, p0 = forms[key]
    popt, pcov = scipy_optimize.curve_fit(f, data.shear_rate, np.log(data.viscosity), p0=p0, maxfev=20000)
    half = scipy_stats.t.ppf(0.975, data.n - len(popt)) * np.sqrt(np.diag(pcov))
    return popt, half


@pytest.mark.parametrize("key,log_params", [
    ("power_law", (True, False)), ("bingham", (False, True)), ("herschel_bulkley", (False, True, False)),
    ("cross", (True, True, False)), ("carreau", (True, True, False)),
])
def test_noisy_fits_and_intervals_agree_with_scipy(key, log_params):
    data = _flow(_noisy(key))
    fit = fit_model(key, data)
    assert fit.supported, fit.reason
    popt, half = _scipy_fit(key, data)
    for p, is_log, est, h in zip(fit.params, log_params, popt, half):
        natural = math.exp(est) if is_log else est
        assert p.value == pytest.approx(natural, rel=1e-4), p.name
        lo, hi = (math.exp(est - h), math.exp(est + h)) if is_log else (est - h, est + h)
        assert p.ci_low == pytest.approx(lo, rel=1e-3, abs=1e-9), p.name
        assert p.ci_high == pytest.approx(hi, rel=1e-3, abs=1e-9), p.name


def test_hand_worked_power_law_example():
    # eta halves per decade of shear rate: ln-slope = ln(0.5)/ln(10) = -0.301030 -> n = 0.698970, K = 1000
    fit = fit_model("power_law", FlowData(np.array([1.0, 10.0, 100.0, 1000.0]),
                                          np.array([1000.0, 500.0, 250.0, 125.0])))
    assert fit.value("n") == pytest.approx(1 - math.log10(2), abs=1e-9)
    assert fit.value("K") == pytest.approx(1000.0, rel=1e-9)


def test_new_power_law_fit_matches_the_existing_one(readings):
    old = A.power_law_fit(readings)
    new = compare_models(readings, ["power_law"]).fits[0]
    assert new.value("n") == pytest.approx(old["n"], rel=1e-9)
    assert new.value("K") == pytest.approx(old["k"], rel=1e-9)


# ----------------------------------------------------------------------------- data support
def test_cross_and_carreau_need_a_visible_plateau():
    pure_power_law = _flow(TRUTH["power_law"][1](GAMMA))
    for key in ("cross", "carreau"):
        fit = fit_model(key, pure_power_law)
        assert not fit.supported and "plateau" in fit.reason


def test_models_need_enough_points_rates_and_decades():
    few = FlowData(np.array([1.0, 2.0, 4.0, 8.0]), np.array([100.0, 90.0, 80.0, 70.0]))
    assert "at least 5" in fit_model("herschel_bulkley", few).reason
    same_rate = FlowData(np.array([5.0, 5.0, 5.0, 5.0, 5.0]), np.array([100.0, 101, 99, 100, 102]))
    assert "different shear rates" in fit_model("power_law", same_rate).reason
    narrow = FlowData(np.array([10.0, 11.0, 12.0, 13.0]), np.array([100.0, 99, 98, 97]))
    assert "decade" in fit_model("power_law", narrow).reason
    assert fit_model("newtonian", narrow).supported


def test_unsupported_readings_are_excluded_with_reasons():
    t0 = datetime(2026, 1, 1)
    rs = [Reading(t0, 100.0, 50.0, rpm=10.0, spindle="RV3", model="DV1MRV"),          # no SRC
          Reading(t0, 100.0, 5.0, rpm=10.0, spindle="SC4-18", model="DV1MLV"),        # torque < 10 %
          Reading(t0, None, 50.0, rpm=10.0, spindle="SC4-18", model="DV1MLV"),        # no viscosity
          Reading(t0, 100.0, 50.0, rpm=10.0, spindle="SC4-18", model="DV1MLV")]
    data = flow_data(rs)
    assert data.n == 1
    reasons = " ".join(why for _, why in data.excluded)
    assert "shear-rate constant" in reasons and "outside 10-100" in reasons and "viscosity" in reasons
    assert flow_data(rs, torque_window=False).n == 2


def test_aicc_prefers_the_generating_model():
    assert compare_models_from_flow(_flow(np.full(GAMMA.size, 850.0) * np.exp(
        np.random.default_rng(1).normal(0, 0.01, GAMMA.size)))).best.model.key == "newtonian"
    assert compare_models_from_flow(_flow(_noisy("herschel_bulkley", pct=0.5))).best.model.key == "herschel_bulkley"
    assert compare_models_from_flow(_flow(_noisy("power_law", pct=1.0))).best.model.key in ("power_law",)


def compare_models_from_flow(data):
    from core.rheology import Comparison
    fits = [fit_model(m, data) for m in MODELS]
    ok = [f for f in fits if f.supported]
    best = min(f.aicc for f in ok)
    for f in ok:
        f.delta_aicc = f.aicc - best
    return Comparison(data, fits, [])


def test_yield_stress_fitted_to_data_without_one_is_flagged():
    fit = fit_model("herschel_bulkley", _flow(TRUTH["power_law"][1](GAMMA)))
    assert fit.value("τ₀") == pytest.approx(0.0, abs=1e-6)
    assert any("not resolved" in w for w in fit.warnings)


def test_systematic_misfit_is_reported():
    fit = fit_model("newtonian", _flow(TRUTH["power_law"][1](GAMMA)))
    assert any("systematic" in w for w in fit.warnings)


# ----------------------------------------------------------------------------- replicates, hysteresis
def _r(t, eta, rpm, spindle="SC4-18", **kw):
    return Reading(datetime(2026, 1, 1, 12) + timedelta(seconds=30 * t), eta, 50.0, rpm=rpm,
                   spindle=spindle, model="DV1MLV", **kw)


def test_replicate_statistics_by_hand():
    rows = replicate_table([_r(0, 100.0, 10.0, sample_id="A"), _r(1, 102.0, 10.0, sample_id="A"),
                            _r(2, 98.0, 10.0, sample_id="A"), _r(3, 500.0, 2.0, sample_id="A")])
    a = rows[0]
    assert (a.n, a.mean_cp, a.sd_cp) == (3, pytest.approx(100.0), pytest.approx(2.0))
    assert a.cv_pct == pytest.approx(2.0)
    assert a.u_mean_cp == pytest.approx(2.0 / math.sqrt(3))
    assert a.u95_cp == pytest.approx(4.302653 * 2.0 / math.sqrt(3), rel=1e-6)
    assert rows[1].n == 1 and rows[1].sd_cp is None


def test_hysteresis_loop_area_by_hand():
    # up: eta 2000 cP (tau = 2 Pa·s · g); down: 1500 cP; SC4-18 SRC 1.32; turning point at 10 rpm
    up = [_r(i, 2000.0, rpm) for i, rpm in enumerate((1.0, 2.0, 5.0, 10.0))]
    down = [_r(4 + i, 1500.0, rpm) for i, rpm in enumerate((5.0, 2.0, 1.0))]
    h = hysteresis(up + down)
    g = [1.32, 2.64, 6.6, 13.2]
    d = [0.5 * 1.32, 0.5 * 2.64, 0.5 * 6.6, 0.0]          # tau_up - tau_down in Pa
    expected = sum((g[i + 1] - g[i]) * (d[i] + d[i + 1]) / 2 for i in range(3))
    assert h.loop_area_pa_s == pytest.approx(expected)
    assert [p[0] for p in h.per_speed] == [1.0, 2.0, 5.0]
    assert all(p[3] == pytest.approx(25.0) for p in h.per_speed)


def test_no_hysteresis_without_a_down_leg_or_without_shear_rate():
    assert hysteresis([_r(i, 1000.0, rpm) for i, rpm in enumerate((1.0, 2.0, 5.0, 10.0))]) is None
    h = hysteresis([_r(i, v, rpm, spindle="RV3") for i, (v, rpm) in
                    enumerate(((900, 1.0), (800, 2.0), (700, 5.0), (750, 2.0), (850, 1.0)))])
    assert h.loop_area_pa_s is None and "shear-rate constant" in h.note and len(h.per_speed) == 2


# ----------------------------------------------------------------------------- QC flags
def test_qc_flags_catch_transcription_and_conditions():
    t0 = datetime(2026, 1, 1, 12)
    nb = ExperimentNotebook(target_temperature_c=25.0, temperature_tolerance_c=0.5,
                            calibration_date="2024-01-01", calibration_interval_months=12)
    ok = Reading(t0, 50.5, 50.0, 25.2, 60.0, "LV1", "DV1MLV")          # 50 % of FSR 100 cP = 50 cP
    assert qc_flags(ok, notebook=ExperimentNotebook()) == []
    typo = Reading(t0, 55.0, 50.0, 25.2, 60.0, "LV1", "DV1MLV")
    assert any("expected 50 cP" in f for f in qc_flags(typo))
    warm = Reading(t0, 50.0, 50.0, 26.0, 60.0, "LV1", "DV1MLV")
    flags = qc_flags(warm, previous=warm, notebook=nb, due_at=t0 - timedelta(seconds=90))
    assert any("outside 25 ± 0.5" in f for f in flags)
    assert "instrument calibration overdue" in flags
    assert any("90 s after" in f for f in flags)
    assert any("double entry" in f for f in flags)
    assert "torque below 10 %" in qc_flags(Reading(t0, 5.0, 5.0, None, 60.0, "LV1", "DV1MLV"))
    assert any("not in the DV1 speed list" in f for f in qc_flags(Reading(t0, rpm=7.0)))


def test_calibration_status():
    nb = ExperimentNotebook(calibration_date="2026-01-10", calibration_interval_months=12)
    assert nb.calibration_status(date(2026, 6, 1))[0] == "ok"
    assert nb.calibration_status(date(2027, 1, 10))[0] == "due"
    assert ExperimentNotebook(calibration_date="soon").calibration_status()[0] == "unknown"
