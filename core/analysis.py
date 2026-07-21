"""
core/analysis.py

Pure data-processing functions for the Brookfield DV1 Viscosity Logger.
No Qt imports here -- keeps this testable and reusable outside the GUI.

Spindle and model constants below are transcribed directly from the official
Brookfield AMETEK DV1 Operating Instructions manual (Manual No. M14-023-A0416),
Appendix D ("Spindle Entry Codes and SMC/SRC Values") and Table D-2 (Torque
Constants). Source:
https://www.brookfieldengineering.com/-/media/ametekbrookfield/product-manuals/dv1-viscometer-operations-manual-m14-023.pdf

If you are using non-standard spindles/accessories not listed here (e.g. a
specific Small Sample Adapter or Cone/Plate variant), double check the SMC/SRC
values against your own printed manual before trusting calculated values --
transcription errors are possible and Brookfield occasionally issues
addenda for specific spindle sets.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean, pstdev
from typing import Optional


# ---------------------------------------------------------------------------
# Spindle table: entry code -> (name, SMC, SRC)
# SMC = Spindle Multiplier Constant (viscosity / shear stress)
# SRC = Shear Rate Constant (shear rate / shear stress). 0 means N/A on DV1.
# ---------------------------------------------------------------------------
SPINDLE_TABLE = {
    "RV1": {"code": "01", "smc": 1, "src": 0},
    "RV2": {"code": "02", "smc": 4, "src": 0},
    "RV3": {"code": "03", "smc": 10, "src": 0},
    "RV4": {"code": "04", "smc": 20, "src": 0},
    "RV5": {"code": "05", "smc": 40, "src": 0},
    "RV6": {"code": "06", "smc": 100, "src": 0},
    "RV7": {"code": "07", "smc": 400, "src": 0},
    "HA1": {"code": "01", "smc": 1, "src": 0},
    "HA2": {"code": "02", "smc": 4, "src": 0},
    "HA3": {"code": "03", "smc": 10, "src": 0},
    "HA4": {"code": "04", "smc": 20, "src": 0},
    "HA5": {"code": "05", "smc": 40, "src": 0},
    "HA6": {"code": "06", "smc": 100, "src": 0},
    "HA7": {"code": "07", "smc": 400, "src": 0},
    "HB1": {"code": "01", "smc": 1, "src": 0},
    "HB2": {"code": "02", "smc": 4, "src": 0},
    "HB3": {"code": "03", "smc": 10, "src": 0},
    "HB4": {"code": "04", "smc": 20, "src": 0},
    "HB5": {"code": "05", "smc": 40, "src": 0},
    "HB6": {"code": "06", "smc": 100, "src": 0},
    "HB7": {"code": "07", "smc": 400, "src": 0},
    "LV1": {"code": "61", "smc": 6.4, "src": 0},
    "LV2": {"code": "62", "smc": 32, "src": 0},
    "LV3": {"code": "63", "smc": 128, "src": 0},
    "LV4": {"code": "64", "smc": 640, "src": 0},
    "LV5": {"code": "65", "smc": 1280, "src": 0},
    "LV-2C": {"code": "66", "smc": 32, "src": 0.212},
    "LV-3C": {"code": "67", "smc": 128, "src": 0.210},
    "SA-70": {"code": "70", "smc": 105, "src": 0.677},
    "T-A": {"code": "91", "smc": 20, "src": 0},
    "T-B": {"code": "92", "smc": 40, "src": 0},
    "T-C": {"code": "93", "smc": 100, "src": 0},
    "T-D": {"code": "94", "smc": 200, "src": 0},
    "T-E": {"code": "95", "smc": 500, "src": 0},
    "T-F": {"code": "96", "smc": 1000, "src": 0},
    "ULA": {"code": "00", "smc": 0.64, "src": 1.223},
    "HT-DIN-81": {"code": "81", "smc": 3.7, "src": 1.29},
    "SC4-DIN-82": {"code": "82", "smc": 3.75, "src": 1.29},
    "SC4-DIN-83": {"code": "83", "smc": 12.09, "src": 1.29},
    "DIN-85": {"code": "85", "smc": 1.22, "src": 1.29},
    "DIN-86": {"code": "86", "smc": 3.65, "src": 1.29},
    "DIN-87": {"code": "87", "smc": 12.13, "src": 1.29},
    "SC4-14": {"code": "14", "smc": 125, "src": 0.40},
    "SC4-15": {"code": "15", "smc": 50, "src": 0.48},
    "SC4-16": {"code": "16", "smc": 128, "src": 0.29},
    "SC4-18": {"code": "18", "smc": 3.2, "src": 1.32},
    "SC4-21": {"code": "21", "smc": 5, "src": 0.93},
    "SC4-25": {"code": "25", "smc": 512, "src": 0.22},
    "SC4-27": {"code": "27", "smc": 25, "src": 0.34},
    "SC4-28": {"code": "28", "smc": 50, "src": 0.28},
    "SC4-29": {"code": "29", "smc": 100, "src": 0.25},
    "SC4-31": {"code": "31", "smc": 32, "src": 0.34},
    "SC4-34": {"code": "34", "smc": 64, "src": 0.28},
    "CPA-40Z": {"code": "40", "smc": 0.327, "src": 7.5},
    "CPA-41Z": {"code": "41", "smc": 1.228, "src": 2.0},
    "CPA-42Z": {"code": "42", "smc": 0.64, "src": 3.84},
    "CPA-51Z": {"code": "51", "smc": 5.178, "src": 3.84},
    "CPA-52Z": {"code": "52", "smc": 9.922, "src": 2.0},
    "V-71": {"code": "71", "smc": 2.62, "src": 0},
    "V-72": {"code": "72", "smc": 11.1, "src": 0},
    "V-73": {"code": "73", "smc": 53.5, "src": 0},
    "V-74": {"code": "74", "smc": 543, "src": 0},
    "V-75": {"code": "75", "smc": 213, "src": 0},
}

# Model -> Torque Constant (TK), from Table D-2
MODEL_TABLE = {
    "DV1MLV": 0.09375,
    "DV1M3 (2.5LV)": 0.234375,
    "DV1M5 (5LV)": 0.46875,
    "DV1MRQ (1/4RV)": 0.25,
    "DV1MRH (1/2RV)": 0.5,
    "DV1MRV": 1.0,
    "DV1MHA": 2.0,
    "DV1MA2 (2HA)": 4.0,
    "DV1MA3 (2.5HA)": 5.0,
    "DV1MHB": 8.0,
}

VALID_SPEEDS_RPM = [
    0.0, 0.3, 0.5, 0.6, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0,
    10.0, 12.0, 20.0, 30.0, 50.0, 60.0, 100.0,
]


def full_scale_range_cp(model: str, spindle: str, rpm: float) -> Optional[float]:
    """
    Full Scale Viscosity Range [cP] = TK * SMC * 10000 / RPM
    Per Appendix D of the DV1 manual. Returns None if inputs are invalid
    or rpm is 0 (undefined / motor off).
    """
    if rpm is None or rpm <= 0:
        return None
    tk = MODEL_TABLE.get(model)
    spindle_info = SPINDLE_TABLE.get(spindle)
    if tk is None or spindle_info is None:
        return None
    return tk * spindle_info["smc"] * 10000.0 / rpm


def shear_rate_per_sec(spindle: str, rpm: float) -> Optional[float]:
    """Shear Rate (1/sec) = SRC * RPM. Returns None if SRC is 0 (N/A on DV1) or inputs invalid."""
    spindle_info = SPINDLE_TABLE.get(spindle)
    if spindle_info is None or rpm is None:
        return None
    src = spindle_info["src"]
    if src == 0:
        return None
    return src * rpm


def recommend_spindle_speed(
    model: str,
    expected_viscosity_cp: float,
    target_torque_pct: float = 50.0,
    top_n: int = 5,
) -> list[dict]:
    """
    Suggest spindle/speed combinations to try BEFORE taking a reading, given a
    ballpark expected viscosity for the sample (e.g. from a spec sheet, a prior
    batch, or a quick guess).

    This does not add any new physics -- it inverts the same Full Scale Range
    relationship used by full_scale_range_cp() and the same 10-100% torque
    window already enforced by percent_torque_status() elsewhere in this app,
    both from the DV1 Operating Instructions manual (M14-023-A0416), Appendix D:
    https://www.brookfieldengineering.com/-/media/ametekbrookfield/product-manuals/dv1-viscometer-operations-manual-m14-023.pdf

        FSR = TK * SMC * 10000 / RPM
        predicted %torque = expected_viscosity_cp / FSR * 100

    Candidates are kept only if predicted %torque falls in Brookfield's
    recommended 10-100% window, then ranked by closeness to `target_torque_pct`
    (defaults to 50%, the middle of that window -- Brookfield's guidance notes
    accuracy is best away from both the 10% floor and the 100% ceiling).

    This is still a *prediction* based on your estimated viscosity, not a
    measurement -- treat the top result as a starting point, take a reading,
    and adjust spindle/speed if the actual %torque lands outside 10-100%.
    """
    if expected_viscosity_cp is None or expected_viscosity_cp <= 0:
        return []
    tk = MODEL_TABLE.get(model)
    if tk is None:
        return []

    candidates = []
    for spindle, info in SPINDLE_TABLE.items():
        for rpm in VALID_SPEEDS_RPM:
            if rpm <= 0:
                continue
            fsr = tk * info["smc"] * 10000.0 / rpm
            if fsr <= 0:
                continue
            predicted_torque = expected_viscosity_cp / fsr * 100.0
            if 10.0 <= predicted_torque <= 100.0:
                candidates.append({
                    "spindle": spindle,
                    "rpm": rpm,
                    "predicted_torque_pct": predicted_torque,
                    "fsr_cp": fsr,
                })

    candidates.sort(key=lambda c: abs(c["predicted_torque_pct"] - target_torque_pct))
    return candidates[:top_n]


def shear_stress_dyn_cm2(viscosity_cp: Optional[float], shear_rate_1_per_s: Optional[float]) -> Optional[float]:
    """
    Shear Stress [dyn/cm^2] = viscosity [Poise] * shear rate [1/s]
    This is just the definition of (Newtonian) viscosity, tau = eta * shear_rate,
    in cgs units (1 Poise = 1 dyn*s/cm^2, and 1 cP = 0.01 Poise) -- not a
    Brookfield-specific formula, but the same relationship Appendix D uses
    when it tabulates Shear Stress alongside Shear Rate.
    Returns None if either input is missing (e.g. spindle has no SRC on DV1).
    """
    if viscosity_cp is None or shear_rate_1_per_s is None:
        return None
    return (viscosity_cp / 100.0) * shear_rate_1_per_s


def percent_torque_status(percent_torque: Optional[float]) -> str:
    """
    Brookfield recommends readings be taken between 10-100% torque.
    Returns a short status string used to flag out-of-range readings in the UI/export.
    """
    if percent_torque is None:
        return "unknown"
    if percent_torque < 10:
        return "below 10% - accuracy not guaranteed"
    if percent_torque > 100:
        return "above 100% - out of range, re-select spindle/speed"
    return "ok"


@dataclass
class Reading:
    """A single logged data point, whether entered manually or received over serial."""
    timestamp: datetime
    viscosity_cp: Optional[float] = None
    percent_torque: Optional[float] = None
    temperature_c: Optional[float] = None
    rpm: Optional[float] = None
    spindle: Optional[str] = None
    model: Optional[str] = None
    source: str = "manual"  # "manual" or "serial"
    notes: str = ""
    product: str = ""
    batch: str = ""

    def torque_status(self) -> str:
        return percent_torque_status(self.percent_torque)

    def shear_rate(self) -> Optional[float]:
        if self.spindle is None or self.rpm is None:
            return None
        return shear_rate_per_sec(self.spindle, self.rpm)

    def shear_stress(self) -> Optional[float]:
        return shear_stress_dyn_cm2(self.viscosity_cp, self.shear_rate())

    def fsr(self) -> Optional[float]:
        if self.spindle is None or self.model is None or self.rpm is None:
            return None
        return full_scale_range_cp(self.model, self.spindle, self.rpm)


def summarize(readings: list[Reading]) -> dict:
    """Basic descriptive statistics over a list of Readings. Ignores None values per-field."""
    def _vals(attr):
        return [getattr(r, attr) for r in readings if getattr(r, attr) is not None]

    out = {}
    for field_name in ("viscosity_cp", "percent_torque", "temperature_c", "rpm"):
        vals = _vals(field_name)
        if vals:
            out[field_name] = {
                "n": len(vals),
                "mean": mean(vals),
                "stdev": pstdev(vals) if len(vals) > 1 else 0.0,
                "min": min(vals),
                "max": max(vals),
            }
        else:
            out[field_name] = None

    out["n_total"] = len(readings)
    out["n_below_10pct_torque"] = sum(
        1 for r in readings if r.percent_torque is not None and r.percent_torque < 10
    )
    out["n_above_100pct_torque"] = sum(
        1 for r in readings if r.percent_torque is not None and r.percent_torque > 100
    )
    return out


def power_law_fit(readings: list[Reading]) -> Optional[dict]:
    """
    Fit the Ostwald-de Waele power law model to logged readings that have both
    a viscosity and a shear rate: apparent_viscosity = K * shear_rate^(n-1),
    equivalently shear_stress = K * shear_rate^n.

    This is the standard model used to characterize shear-thinning/thickening
    fluids like polymer solutions and gels (see e.g. Steffe, "Rheological
    Methods in Food Process Engineering", Ch. 2) -- not a Brookfield-specific
    formula. Fit is done as a linear regression of ln(viscosity) vs
    ln(shear_rate), since ln(eta) = ln(K) + (n-1)*ln(shear_rate).

    Returns None if fewer than 2 points have both a positive viscosity and a
    positive shear rate (need a spindle with a defined Shear Rate Constant,
    e.g. LV-2C/LV-3C/SA-70/ULA/the DIN or SC4 spindles -- plain RV/HA/HB/T
    spindles have no SRC on the DV1 and won't contribute).

    Dict keys: n (flow behavior index), k (consistency index, in cP * s^(n-1)),
    r_squared, n_points. n < 1 => shear-thinning (pseudoplastic, typical of
    polymer solutions/gels), n = 1 => Newtonian, n > 1 => shear-thickening.
    """
    import math

    pts = [
        (r.shear_rate(), r.viscosity_cp)
        for r in readings
        if r.shear_rate() is not None and r.shear_rate() > 0
        and r.viscosity_cp is not None and r.viscosity_cp > 0
    ]
    if len(pts) < 2:
        return None

    xs = [math.log(sr) for sr, _ in pts]
    ys = [math.log(v) for _, v in pts]
    n_pts = len(pts)
    x_mean = sum(xs) / n_pts
    y_mean = sum(ys) / n_pts
    sxy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    sxx = sum((x - x_mean) ** 2 for x in xs)
    if sxx == 0:
        return None
    slope = sxy / sxx  # = n - 1
    intercept = y_mean - slope * x_mean  # = ln(K)

    y_pred = [intercept + slope * x for x in xs]
    ss_res = sum((y - yp) ** 2 for y, yp in zip(ys, y_pred))
    ss_tot = sum((y - y_mean) ** 2 for y in ys)
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0

    return {
        "n": slope + 1.0,
        "k": math.exp(intercept),
        "r_squared": r_squared,
        "n_points": n_pts,
    }
