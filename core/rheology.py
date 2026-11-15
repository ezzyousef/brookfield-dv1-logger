"""Flow-curve models fitted to logged readings, with the checks that decide whether a model is
supported by the data at all. No Qt.

Models (eta = apparent viscosity in cP = mPa·s, gamma = shear rate in 1/s, tau = shear stress):

    Newtonian           eta = mu
    Power law           eta = K * gamma^(n-1)                    (tau = K gamma^n)
    Bingham             eta = 1000 * tau0 / gamma + mu_p          (tau = tau0 + mu_p gamma)
    Herschel-Bulkley    eta = 1000 * tau0 / gamma + K gamma^(n-1) (tau = tau0 + K gamma^n)
    Cross               eta = eta0 / (1 + (lambda gamma)^m)       (eta_inf fixed at 0)
    Carreau             eta = eta0 * (1 + (lambda gamma)^2)^((n-1)/2)   (eta_inf fixed at 0)

Units: mu, mu_p, eta0 in cP; K in mPa·s^n (numerically cP·s^(n-1), as the app has always
reported it); tau0 in Pa; lambda in s. The factor 1000 converts Pa·s to cP.

Every model is fitted by least squares on the LOG residuals ln(eta_obs) - ln(eta_model), so
each point counts by its relative error (readings span decades) and AICc values are comparable
between models. 95 % confidence intervals come from the covariance s²(JᵀJ)⁻¹ and Student's t
with N - p degrees of freedom; for parameters fitted on a log scale the interval is
exponentiated and therefore asymmetric. These are local (linearised) intervals.

A model is fitted only when the data can support it (enough points, enough distinct shear
rates, enough decades of shear rate, and for Cross/Carreau a visible low-shear plateau). When
it is not, the result says why instead of inventing parameters. Fitted parameters describe
the measured range only; they are not measurements.

Shear rates come from Brookfield's Shear Rate Constants, which are exact for Newtonian fluids
in that geometry. For strongly non-Newtonian samples they are approximations, so K, n, tau0
etc. are apparent values for that spindle.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np

from core.analysis import Reading

PA_S_TO_CP = 1000.0

# ----------------------------------------------------------------------------- statistics helpers


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the regularised incomplete beta function (modified Lentz)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, 400):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def _betainc(a: float, b: float, x: float) -> float:
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    lbt = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(lbt) * _betacf(a, b, x) / a
    return 1.0 - math.exp(lbt) * _betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    x = df / (df + t * t)
    tail = 0.5 * _betainc(df / 2.0, 0.5, x)
    return 1.0 - tail if t > 0 else tail


def t_ppf(p: float, df: float) -> float:
    """Quantile of Student's t (bisection on the CDF; accurate to ~1e-12)."""
    if not 0.0 < p < 1.0 or df <= 0:
        raise ValueError("t_ppf needs 0 < p < 1 and df > 0")
    if p == 0.5:
        return 0.0
    lo, hi = -1.0, 1.0
    while t_cdf(lo, df) > p:
        lo *= 2.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-13 * max(1.0, abs(mid)):
            break
    return 0.5 * (lo + hi)


# ----------------------------------------------------------------------------- data selection
@dataclass
class FlowData:
    shear_rate: np.ndarray            # 1/s
    viscosity: np.ndarray             # cP
    excluded: list[tuple[int, str]] = field(default_factory=list)   # (reading number, reason)
    spindles: tuple = ()

    @property
    def n(self) -> int:
        return int(self.shear_rate.size)

    @property
    def shear_stress_pa(self) -> np.ndarray:
        return self.viscosity / PA_S_TO_CP * self.shear_rate

    @property
    def decades(self) -> float:
        if self.n < 2:
            return 0.0
        return float(np.log10(self.shear_rate.max() / self.shear_rate.min()))


def flow_data(readings: Sequence[Reading], *, torque_window: bool = True) -> FlowData:
    """Points usable for a flow curve, and the reason each other reading was left out."""
    xs, ys, excluded, spindles = [], [], [], []
    for k, r in enumerate(readings, start=1):
        rate = r.shear_rate()
        if rate is None:
            excluded.append((k, f"spindle {r.spindle or '?'} has no shear-rate constant on the DV1"))
        elif rate <= 0:
            excluded.append((k, "speed is 0"))
        elif r.viscosity_cp is None or not r.viscosity_cp > 0:
            excluded.append((k, "no positive viscosity"))
        elif torque_window and r.percent_torque is not None and not 10.0 <= r.percent_torque <= 100.0:
            excluded.append((k, f"torque {r.percent_torque:g} % outside 10-100 %"))
        else:
            xs.append(float(rate))
            ys.append(float(r.viscosity_cp))
            if r.spindle not in spindles:
                spindles.append(r.spindle)
    return FlowData(np.array(xs, dtype=float), np.array(ys, dtype=float), excluded, tuple(spindles))


# ----------------------------------------------------------------------------- models
@dataclass(frozen=True)
class Param:
    name: str
    unit: str
    log: bool = False          # fitted as ln(value), value > 0
    lower: float = -math.inf   # bound on the fitted (internal) value when not log


@dataclass(frozen=True)
class Model:
    key: str
    title: str
    equation: str
    params: tuple
    eta: Callable                         # eta(gamma, *natural_params) -> cP
    min_decades: float = 0.0
    needs_plateau: bool = False
    yield_stress: bool = False

    @property
    def p(self) -> int:
        return len(self.params)

    @property
    def min_points(self) -> int:
        return self.p + 2                  # leaves N - p - 1 > 0 for AICc and >= 2 dof for the CI


def _eta_newton(g, mu):
    return np.full_like(g, mu, dtype=float)


def _eta_power(g, k, n):
    return k * g ** (n - 1.0)


def _eta_bingham(g, tau0, mu_p):
    return PA_S_TO_CP * tau0 / g + mu_p


def _eta_hb(g, tau0, k, n):
    return PA_S_TO_CP * tau0 / g + k * g ** (n - 1.0)


def _eta_cross(g, eta0, lam, m):
    return eta0 / (1.0 + (lam * g) ** m)


def _eta_carreau(g, eta0, lam, n):
    return eta0 * (1.0 + (lam * g) ** 2) ** ((n - 1.0) / 2.0)


MODELS = {
    "newtonian": Model("newtonian", "Newtonian", "η = μ", (Param("μ", "cP", log=True),), _eta_newton),
    "power_law": Model("power_law", "Power law", "η = K·γ̇ⁿ⁻¹",
                       (Param("K", "mPa·sⁿ", log=True), Param("n", "-")), _eta_power, min_decades=0.3),
    "bingham": Model("bingham", "Bingham", "τ = τ₀ + μp·γ̇",
                     (Param("τ₀", "Pa", lower=0.0), Param("μp", "cP", log=True)), _eta_bingham,
                     min_decades=0.3, yield_stress=True),
    "herschel_bulkley": Model("herschel_bulkley", "Herschel–Bulkley", "τ = τ₀ + K·γ̇ⁿ",
                              (Param("τ₀", "Pa", lower=0.0), Param("K", "mPa·sⁿ", log=True), Param("n", "-")),
                              _eta_hb, min_decades=0.5, yield_stress=True),
    "cross": Model("cross", "Cross (η∞ = 0)", "η = η₀ / (1 + (λγ̇)ᵐ)",
                   (Param("η₀", "cP", log=True), Param("λ", "s", log=True), Param("m", "-", lower=1e-3)),
                   _eta_cross, min_decades=1.5, needs_plateau=True),
    "carreau": Model("carreau", "Carreau (η∞ = 0)", "η = η₀·(1 + (λγ̇)²)^((n−1)/2)",
                     (Param("η₀", "cP", log=True), Param("λ", "s", log=True), Param("n", "-", lower=-1.0)),
                     _eta_carreau, min_decades=1.5, needs_plateau=True),
}

MAX_CONDITION = 1e14         # JᵀJ condition number above which intervals are not reported
MAX_LOG_HALF_WIDTH = math.log(1e3)   # log-scale half-width above which an interval is "not resolved"
PLATEAU_SLOPE = -0.15       # local d ln(eta)/d ln(gamma) above this at the low-rate end = a plateau
PLATEAU_CONTRAST = 0.15     # and the high-rate end must be at least this much steeper


@dataclass
class ParamResult:
    name: str
    unit: str
    value: float
    ci_low: Optional[float]
    ci_high: Optional[float]
    note: str = ""


@dataclass
class FitResult:
    model: Model
    supported: bool
    reason: str = ""                       # why it was not fitted
    params: list[ParamResult] = field(default_factory=list)
    n_points: int = 0
    ssr: float = math.nan                  # sum of squared log residuals
    aicc: float = math.nan
    delta_aicc: float = math.nan
    rms_pct: float = math.nan              # typical relative misfit, %
    max_abs_pct: float = math.nan
    residuals: np.ndarray = field(default_factory=lambda: np.array([]))
    sign_runs: int = 0
    warnings: list[str] = field(default_factory=list)
    shear_range: tuple = (math.nan, math.nan)

    def value(self, name: str) -> float:
        return next(p.value for p in self.params if p.name == name)

    def predict(self, gamma) -> np.ndarray:
        g = np.asarray(gamma, dtype=float)
        return self.model.eta(g, *[p.value for p in self.params])


def _local_slopes(data: FlowData) -> tuple[float, float]:
    order = np.argsort(data.shear_rate)
    x = np.log(data.shear_rate[order])
    y = np.log(data.viscosity[order])
    k = max(2, min(3, x.size // 3))
    lo = np.polyfit(x[:k], y[:k], 1)[0] if np.ptp(x[:k]) > 0 else 0.0
    hi = np.polyfit(x[-k:], y[-k:], 1)[0] if np.ptp(x[-k:]) > 0 else 0.0
    return float(lo), float(hi)


def support_check(model: Model, data: FlowData) -> str:
    """'' when the data can support this model, else the reason."""
    distinct = np.unique(np.round(data.shear_rate, 12)).size
    if data.n < model.min_points:
        return f"needs at least {model.min_points} usable points (have {data.n})"
    if distinct < model.p + 1:
        return f"needs at least {model.p + 1} different shear rates (have {distinct})"
    if data.decades + 1e-12 < model.min_decades:
        return (f"needs shear rates spanning at least {model.min_decades:g} decade(s) "
                f"(have {data.decades:.2f})")
    if model.needs_plateau:
        lo, hi = _local_slopes(data)
        if not (lo > PLATEAU_SLOPE and hi < lo - PLATEAU_CONTRAST):
            return ("the data show no low-shear plateau (local slope at the lowest rates "
                    f"{lo:.2f}), so η₀ and λ would be extrapolations")
    return ""


# ----------------------------------------------------------------------------- least squares
def _to_internal(model: Model, natural: Sequence[float]) -> np.ndarray:
    return np.array([math.log(v) if p.log else v for p, v in zip(model.params, natural)], dtype=float)


def _to_natural(model: Model, theta: np.ndarray) -> list[float]:
    return [math.exp(t) if p.log else float(t) for p, t in zip(model.params, theta)]


def _project(model: Model, theta: np.ndarray) -> np.ndarray:
    out = theta.copy()
    for i, p in enumerate(model.params):
        if not p.log and out[i] < p.lower:
            out[i] = p.lower
        if p.log:
            out[i] = min(max(out[i], -700.0), 700.0)
    return out


def _residuals(model: Model, data: FlowData, theta: np.ndarray) -> np.ndarray:
    with np.errstate(all="ignore"):
        pred = model.eta(data.shear_rate, *_to_natural(model, theta))
        r = np.log(data.viscosity) - np.log(pred)
    return np.where(np.isfinite(r), r, 1e6)


def _jacobian(model: Model, data: FlowData, theta: np.ndarray) -> np.ndarray:
    J = np.empty((data.n, theta.size))
    for j in range(theta.size):
        h = 1e-6 * max(1.0, abs(theta[j]))
        up, dn = theta.copy(), theta.copy()
        up[j] += h
        dn[j] -= h
        # a parameter sitting on its bound is differentiated one-sided, inside the bound
        p = model.params[j]
        if not p.log and dn[j] < p.lower:
            dn[j] = theta[j]
            J[:, j] = (_residuals(model, data, up) - _residuals(model, data, dn)) / h
            continue
        J[:, j] = (_residuals(model, data, up) - _residuals(model, data, dn)) / (2 * h)
    return J


def levenberg_marquardt(model: Model, data: FlowData, theta0: np.ndarray, max_iter: int = 500):
    theta = _project(model, np.asarray(theta0, dtype=float))
    r = _residuals(model, data, theta)
    ssr = float(r @ r)
    lam = 1e-3
    for _ in range(max_iter):
        J = _jacobian(model, data, theta)
        g = J.T @ r
        A = J.T @ J
        improved = False
        for _ in range(60):
            try:
                step = np.linalg.solve(A + lam * np.diag(np.maximum(np.diag(A), 1e-12)), -g)
            except np.linalg.LinAlgError:
                lam *= 10
                continue
            trial = _project(model, theta + step)
            rt = _residuals(model, data, trial)
            st = float(rt @ rt)
            if st < ssr:
                done = (ssr - st) <= 1e-15 * max(ssr, 1e-300) + 1e-30 or np.max(np.abs(trial - theta)) < 1e-13
                theta, r, ssr = trial, rt, st
                lam = max(lam / 10, 1e-12)
                improved = True
                if done:
                    return theta, ssr
                break
            lam *= 10
            if lam > 1e16:
                break
        if not improved:
            break
    return theta, ssr


def _starts(model: Model, data: FlowData) -> list[list[float]]:
    g, eta = data.shear_rate, data.viscosity
    lg, le = np.log(g), np.log(eta)
    slope, icpt = (np.polyfit(lg, le, 1) if np.ptp(lg) > 0 else (0.0, float(le.mean())))
    tau = data.shear_stress_pa
    key = model.key
    if key == "newtonian":
        return [[float(np.exp(le.mean()))]]
    if key == "power_law":
        return [[float(np.exp(icpt)), float(slope + 1.0)]]
    if key == "bingham":
        b, a = np.polyfit(g, tau, 1) if np.ptp(g) > 0 else (0.0, float(tau.mean()))
        mu_p = max(b * PA_S_TO_CP, 1e-6 * float(eta.min()))
        return [[max(float(a), 0.0), mu_p], [0.5 * float(tau.min()), float(eta.min())], [0.0, float(np.exp(le.mean()))]]
    if key == "herschel_bulkley":
        starts = []
        for frac in (0.0, 0.25, 0.5, 0.8, 0.95):
            t0 = frac * float(tau.min())
            rest = tau - t0
            s, c = np.polyfit(lg, np.log(rest), 1)
            starts.append([t0, float(np.exp(c)) * PA_S_TO_CP, float(s)])
        return starts
    eta0s = [float(eta.max()) * f for f in (1.0, 1.5, 3.0)]
    lams = [f / float(np.median(g)) for f in (0.01, 0.1, 1.0, 10.0, 100.0)]
    shapes = (0.5, 1.0) if key == "cross" else (0.2, 0.6)
    return [[e, l, s] for e in eta0s for l in lams for s in shapes]


def fit_model(model: Model | str, data: FlowData) -> FitResult:
    model = MODELS[model] if isinstance(model, str) else model
    reason = support_check(model, data)
    if reason:
        return FitResult(model, False, reason, n_points=data.n)
    best = None
    for start in _starts(model, data):
        if not all(math.isfinite(v) for v in start) or any(p.log and v <= 0 for p, v in zip(model.params, start)):
            continue
        theta, ssr = levenberg_marquardt(model, data, _to_internal(model, start))
        if best is None or ssr < best[1]:
            best = (theta, ssr)
    if best is None:
        return FitResult(model, False, "no valid starting values could be found", n_points=data.n)
    theta, ssr = best
    N, p = data.n, model.p
    r = _residuals(model, data, theta)
    dof = N - p
    s2 = ssr / dof
    J = _jacobian(model, data, theta)
    tq = t_ppf(0.975, dof)
    warnings = []
    JTJ = J.T @ J
    with np.errstate(all="ignore"):
        condition = float(np.linalg.cond(JTJ)) if np.all(np.isfinite(JTJ)) else math.inf
    try:
        if not condition < MAX_CONDITION:
            raise np.linalg.LinAlgError
        cov = s2 * np.linalg.inv(JTJ)
        se = np.sqrt(np.clip(np.diag(cov), 0, None))
        if not np.all(np.isfinite(se)):
            raise np.linalg.LinAlgError
    except np.linalg.LinAlgError:
        se = np.full(p, math.nan)
        warnings.append("The parameters are not separately determined by these data (ill-conditioned fit, "
                        f"condition number {condition:.2g}); no confidence intervals.")
    params = []
    for i, prm in enumerate(model.params):
        value = _to_natural(model, theta)[i]
        note = ""
        at_bound = (not prm.log) and math.isfinite(prm.lower) and theta[i] <= prm.lower + 1e-12
        if at_bound:
            lo_ci, hi_ci = None, None
            note = f"at its bound ({prm.lower:g}); no interval"
        elif not math.isfinite(se[i]):
            lo_ci, hi_ci = None, None
            note = "not resolved by these data (ill-conditioned fit); no interval"
        elif prm.log:
            half = tq * se[i]
            if half > MAX_LOG_HALF_WIDTH:
                lo_ci, hi_ci = None, None
                note = (f"not resolved by these data (interval spans more than a factor "
                        f"{math.exp(MAX_LOG_HALF_WIDTH):.0f} either way); no interval")
            else:
                try:
                    lo_ci, hi_ci = math.exp(theta[i] - half), math.exp(theta[i] + half)
                except OverflowError:
                    lo_ci, hi_ci = None, None
                    note = "not resolved by these data (interval overflows); no interval"
        else:
            lo_ci, hi_ci = theta[i] - tq * se[i], theta[i] + tq * se[i]
        params.append(ParamResult(prm.name, prm.unit, value, lo_ci, hi_ci, note))
    if model.yield_stress:
        t0 = params[0]
        if t0.note or (t0.ci_low is not None and t0.ci_low <= 0):
            warnings.append("The yield stress is not resolved by these data (its interval reaches 0); "
                            "do not report it as a measured yield stress.")
        if data.shear_rate.min() > 0:
            warnings.append(f"A yield stress is an extrapolation below the lowest measured shear rate "
                            f"({data.shear_rate.min():.3g} s⁻¹).")
    rel = np.expm1(np.abs(r)) * 100.0
    signs = np.sign(r[np.argsort(data.shear_rate)])
    signs = signs[signs != 0]
    runs = int(1 + np.sum(signs[1:] != signs[:-1])) if signs.size else 0
    if N >= 6 and runs <= 2:
        warnings.append(f"The residuals change sign only {runs - 1} time(s) along the shear-rate axis: "
                        "the model misses a systematic trend.")
    aicc = N * math.log(max(ssr, 1e-300) / N) + 2 * p + (2 * p * (p + 1)) / (N - p - 1)
    return FitResult(model, True, "", params, N, ssr, aicc, math.nan,
                     float(np.expm1(math.sqrt(ssr / N)) * 100.0), float(rel.max()), r, runs, warnings,
                     (float(data.shear_rate.min()), float(data.shear_rate.max())))


@dataclass
class Comparison:
    data: FlowData
    fits: list[FitResult]
    warnings: list[str]

    @property
    def supported(self) -> list[FitResult]:
        return [f for f in self.fits if f.supported]

    @property
    def best(self) -> Optional[FitResult]:
        ok = sorted(self.supported, key=lambda f: f.aicc)
        return ok[0] if ok else None


def compare_models(readings: Sequence[Reading], models: Sequence[str] | None = None, *,
                   torque_window: bool = True) -> Comparison:
    """Fit every requested model the data support, ranked by AICc (lower is better)."""
    data = flow_data(readings, torque_window=torque_window)
    fits = [fit_model(MODELS[k], data) for k in (models or MODELS)]
    ok = [f for f in fits if f.supported]
    if ok:
        best = min(f.aicc for f in ok)
        for f in ok:
            f.delta_aicc = f.aicc - best
    warnings = []
    if data.excluded:
        warnings.append(f"{len(data.excluded)} reading(s) left out of the fits: "
                        + "; ".join(f"#{k} {why}" for k, why in data.excluded[:6])
                        + (" …" if len(data.excluded) > 6 else ""))
    if len(data.spindles) > 1:
        warnings.append(f"Readings from {len(data.spindles)} spindles ({', '.join(map(str, data.spindles))}) are "
                        "combined; their shear-rate constants assume different geometries.")
    if data.n:
        warnings.append(f"Parameters describe {data.shear_rate.min():.3g}–{data.shear_rate.max():.3g} s⁻¹ only; "
                        "outside that range they are extrapolations.")
    pl = next((f for f in ok if f.model.key == "power_law"), None)
    if pl is not None and abs(pl.value("n") - 1.0) > 0.1:
        warnings.append("The sample is not Newtonian, but the DV1 shear-rate constants assume a Newtonian "
                        "fluid: treat shear rates and model parameters as apparent values for this spindle.")
    return Comparison(data, fits, warnings)
