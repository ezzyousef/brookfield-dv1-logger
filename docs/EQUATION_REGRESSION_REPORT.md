# Equation regression report

Every conversion and flow model in the app, checked against values worked out independently. Tests: `tests/test_oracle_rheology.py` (40 tests). Run: `py -3 -m pytest -q -p no:cacheprovider tests/test_oracle_rheology.py`. Last run 2026-11-15: **40 passed**.

There are three kinds of check:

- **Manual**: numbers typed into the test from the DV1 manual's constants, worked out by hand.
- **Recovery**: data built from a model with known parameters (the formula is written in the test, not imported from the app); the app must return those parameters.
- **Independent implementation**: SciPy (`curve_fit`, `scipy.stats.t`) solves the same problem with its own arithmetic. SciPy is used only by the tests. The app has its own Student-t and Levenberg–Marquardt code, so the installed app does not need SciPy.

## Conversions (core/analysis.py)

| Quantity | Inputs | Expected (by hand) | App |
|---|---|---|---|
| Full-scale range, FSR = TK·SMC·10 000/rpm | DV1MLV (TK 0.09375), LV1 (SMC 6.4), 60 rpm | 100 cP (the familiar LV #1 at 60 rpm) | 100 cP |
| FSR | DV1MRV (TK 1), RV3 (SMC 10), 10 rpm | 10 000 cP | 10 000 cP |
| FSR | DV1MLV, LV4 (SMC 640), 0.3 rpm | 2 000 000 cP | 2 000 000 cP |
| FSR | DV1MHB (TK 8), HB7 (SMC 400), 0.5 rpm | 64 000 000 cP | 64 000 000 cP |
| FSR | DV1MHA (TK 2), SC4-21 (SMC 5), 100 rpm | 1 000 cP | 1 000 cP |
| Shear rate = SRC·rpm | SC4-18 (SRC 1.32) at 10 rpm; ULA (1.223) at 60; CPA-40Z (7.5) at 2; LV-2C (0.212) at 100 | 13.2; 73.38; 15; 21.2 s⁻¹ | equal (1e-12) |
| Shear stress | 1000 cP at 13.2 s⁻¹ | 1 Pa·s × 13.2 = 13.2 Pa = 132 dyn/cm² | 132 dyn/cm², 13.2 Pa |
| Viscosity from torque = %/100 · FSR | LV1 at 60 rpm, 50 %; RV3 at 10 rpm, 37.5 % | 50 cP; 3750 cP | 50; 3750 cP |
| Torque in dyne·cm = TK · 7187 · %/100 | LV, 100 %; HB, 50 % | 673.78; 28 748 dyne·cm | equal |

The spindle and model constants are the ones transcribed from manual M14-023-A0416 (Appendix D) by the original author. The tests check the arithmetic and that the app's table holds the values typed into the test. They cannot check the transcription against the printed manual: no copy of the manual is in the repository. The 7187 dyne·cm RV spring torque is a literature value. It is used only for an informative readout, and the LV/HA/HB ratios in the TK table agree with it.

## Student-t quantile (core/rheology.py)

| df | Printed t table, 0.975 | App | SciPy |
|---|---|---|---|
| 1 | 12.7062 | 12.7062 | equal (1e-10) |
| 2 | 4.3027 | 4.3027 | equal |
| 5 | 2.5706 | 2.5706 | equal |
| 10 | 2.2281 | 2.2281 | equal |
| 30 | 2.0423 | 2.0423 | equal |

## Flow models: recovery from exact data

Synthetic data: 13 shear rates, log-spaced over 0.01 to 100 s⁻¹. Each model is fitted to data built from itself.

| Model | Truth | Recovered (rel. 1e-6) |
|---|---|---|
| Newtonian | μ = 850 cP | 850 |
| Power law | K = 4200 mPa·sⁿ, n = 0.62 | 4200, 0.62 |
| Bingham | τ₀ = 2.5 Pa, μp = 120 cP | 2.5, 120 |
| Herschel–Bulkley | τ₀ = 1.5 Pa, K = 3000 mPa·sⁿ, n = 0.5 | 1.5, 3000, 0.5 |
| Cross (η∞ = 0) | η₀ = 5000 cP, λ = 0.8 s, m = 0.9 | 5000, 0.8, 0.9 |
| Carreau (η∞ = 0) | η₀ = 8000 cP, λ = 2 s, n = 0.4 | 8000, 2, 0.4 |
| Power law, worked by hand | η = 1000, 500, 250, 125 cP at 1, 10, 100, 1000 s⁻¹ | n = 1 − log₁₀2 = 0.698970, K = 1000 |

## Flow models: noisy data against SciPy

The same data with 3 % log-normal noise (seed 4). Values and 95 % intervals from the app, and the SciPy estimate from the same log-residual least squares. Tolerances: values 1e-4, interval ends 1e-3 relative.

| Model | App estimate [95 % CI] | SciPy | True value inside CI? |
|---|---|---|---|
| Power law | K = 4201 [4123, 4281], n = 0.6217 [0.6151, 0.6283] | 4201, 0.6217 | yes |
| Bingham | τ₀ = 2.482 [2.426, 2.538], μp = 123.5 [117.0, 130.3] | 2.482, 123.5 | yes |
| Herschel–Bulkley | τ₀ = 1.546 [1.432, 1.659], K = 2897 [2690, 3120], n = 0.513 [0.491, 0.535] | equal | yes |
| Cross | η₀ = 5039 [4867, 5217], λ = 0.844 [0.757, 0.942], m = 0.884 [0.861, 0.907] | equal | yes |
| Carreau | η₀ = 8028 [7787, 8276], λ = 2.146 [1.895, 2.429], n = 0.412 [0.395, 0.430] | equal | yes |

For parameters fitted on a log scale (K, μ, μp, η₀, λ), the interval is computed on ln(value) and exponentiated, so it is asymmetric. All intervals are local (linearised) intervals.

## Data-support rules (tested)

- A power-law fit to pure power-law data passes. Cross and Carreau are **refused** ("no low-shear plateau"), so the app never invents η₀ and λ.
- Herschel–Bulkley with 4 points is refused (it needs 5). Five readings at one shear rate are refused ("different shear rates"). A power law over 10 to 13 s⁻¹ is refused (less than 0.3 decade), while Newtonian is allowed.
- Readings without a shear-rate constant (RV3), outside 10–100 % torque, or without a viscosity are left out, each with its reason.
- AICc picks the model the data came from: Newtonian (1 % noise), Herschel–Bulkley (0.5 % noise) and power law (1 % noise).
- Herschel–Bulkley fitted to data without a yield stress puts τ₀ at its bound 0 and flags it as "not resolved". A Newtonian fit to shear-thinning data is flagged as a systematic misfit.

## Replicates, hysteresis, QC (core/compare.py, core/qc.py)

| Check | Data | Expected (by hand) | App |
|---|---|---|---|
| Replicates | 100, 102, 98 cP | mean 100, s = 2, CV 2 %, u = 2/√3 = 1.1547, U95 = 4.3027 × 1.1547 = 4.968 | equal |
| Hysteresis loop | up η = 2000 cP, down η = 1500 cP at 1/2/5 rpm, turning point at 10 rpm, SC4-18 | trapezoid of τ_up − τ_down over γ̇ = 1.32, 2.64, 6.6, 13.2 s⁻¹ | equal; 25 % drop at each shared speed |
| Transcription QC | LV1, 60 rpm, 50 % torque → 50 cP; 55 cP entered | flagged "expected 50 cP"; 50.5 cP not flagged (2 % tolerance) | equal |

## What this does not cover

- No real DV1 data was supplied. Every test uses synthetic data or the values above.
- The shear-rate constants assume Newtonian flow in the spindle geometry. For non-Newtonian samples the app says that parameters are *apparent* values. No correction (for example Krieger) is applied.
- The 2 % / 0.1 %-of-full-scale tolerance of the transcription check is an app heuristic, not a Brookfield accuracy specification.
