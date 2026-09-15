"""Viscometer formulas, sessions and statistics — no Qt."""
from __future__ import annotations

import pytest

from core.analysis import (MODEL_TABLE, SPINDLE_TABLE, full_scale_range_cp, percent_torque_status,
                           power_law_fit, recommend_spindle_speed, shear_rate_per_sec, summarize)
from core.data_io import READING_COLUMNS, export_to_csv, load_session_json, readings_to_dataframe, save_session_json

from conftest import make_readings


def test_full_scale_range_follows_the_manual_formula():
    model = next(iter(MODEL_TABLE))
    expected = MODEL_TABLE[model] * SPINDLE_TABLE["LV2"]["smc"] * 10000.0 / 12.0
    assert full_scale_range_cp(model, "LV2", 12.0) == pytest.approx(expected)
    assert full_scale_range_cp(model, "LV2", 0) is None
    assert full_scale_range_cp("no such model", "LV2", 12) is None


def test_shear_rate_needs_a_shear_rate_constant():
    assert shear_rate_per_sec("RV1", 10) is None             # SRC = 0 on the DV1
    assert shear_rate_per_sec("SC4-18", 10) == pytest.approx(10 * SPINDLE_TABLE["SC4-18"]["src"])


@pytest.mark.parametrize("torque,ok", [(50, True), (9.9, False), (100.5, False), (None, True)])
def test_torque_status(torque, ok):
    assert (percent_torque_status(torque) in ("ok", "unknown")) is ok


def test_power_law_fit_recovers_n_and_k():
    fit = power_law_fit(make_readings(n_value=0.62, k_value=4200.0))
    assert fit["n"] == pytest.approx(0.62, abs=1e-9)
    assert fit["k"] == pytest.approx(4200.0, rel=1e-9)
    assert fit["r_squared"] == pytest.approx(1.0) and fit["n_points"] == 6


def test_power_law_fit_needs_two_shear_rates():
    assert power_law_fit(make_readings(spindle="RV1")) is None
    assert power_law_fit(make_readings(rpms=(10.0,))) is None


def test_advisor_keeps_predictions_inside_the_torque_window():
    model = next(iter(MODEL_TABLE))
    picks = recommend_spindle_speed(model, 5000.0, top_n=5)
    assert 0 < len(picks) <= 5
    assert all(10 <= p["predicted_torque_pct"] <= 100 for p in picks)
    distances = [abs(p["predicted_torque_pct"] - 50) for p in picks]
    assert distances == sorted(distances)
    assert recommend_spindle_speed(model, 0) == []


def test_summary_counts_torque_flags():
    readings = make_readings()
    readings[0].percent_torque = 5.0
    readings[1].percent_torque = 120.0
    s = summarize(readings)
    assert s["n_total"] == 6 and s["n_below_10pct_torque"] == 1 and s["n_above_100pct_torque"] == 1
    empty = summarize([])
    assert empty["viscosity_cp"] is None and empty["n_total"] == 0


def test_session_json_round_trips_exactly(tmp_path):
    readings = make_readings(product="Gel · 5 wt%", batch="Ä-1")
    readings[2].temperature_c = None
    readings[3].notes = "bubbles"
    path = tmp_path / "session.json"
    save_session_json(readings, str(path))
    assert load_session_json(str(path)) == readings


def test_csv_and_dataframe_have_every_column(tmp_path):
    readings = make_readings()
    frame = readings_to_dataframe(readings)
    assert list(frame.columns) == READING_COLUMNS and len(frame) == 6
    path = tmp_path / "r.csv"
    export_to_csv(readings, str(path))
    header = path.read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.split(",")[:3] == READING_COLUMNS[:3]
    assert frame["shear_rate_1_per_s"].notna().all()
