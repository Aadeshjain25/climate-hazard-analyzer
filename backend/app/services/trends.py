"""Trend statistics for annual hazard indicators.

We report three complementary views of the same series:

* Rolling mean (5-yr, centred)  - for the eye; smooths year-to-year noise.
* OLS linear regression         - familiar slope + R² + p-value, but assumes
                                  normally distributed residuals, which count data
                                  like "heatwave days per year" (many zeros, skewed)
                                  usually violates.
* Mann-Kendall + Sen's slope    - non-parametric, rank-based, robust to outliers
                                  and non-normality. This is the standard test in
                                  climate-extremes literature, so it is what our
                                  headline insight is based on.

Mann-Kendall is implemented here (not imported) so every line can be explained.
"""
from __future__ import annotations

import math

import numpy as np
from scipy import stats

ALPHA = 0.05


def _clean_xy(years, values) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(years, dtype=float)
    y = np.asarray([np.nan if v is None else v for v in values], dtype=float)
    mask = ~np.isnan(y)
    return x[mask], y[mask]


def mann_kendall(years, values) -> dict | None:
    """Two-sided Mann-Kendall trend test with tie correction.

    S   = sum over all pairs i<j of sign(y_j - y_i)
    Var = [n(n-1)(2n+5) - sum_t t(t-1)(2t+5)] / 18      (t = size of each tie group)
    Z   = (S-1)/sqrt(Var) if S>0, (S+1)/sqrt(Var) if S<0, else 0   (continuity correction)
    p   = 2 * (1 - Phi(|Z|))
    tau = S / (n(n-1)/2)
    """
    x, y = _clean_xy(years, values)
    n = len(y)
    if n < 8:
        return None
    s = 0
    for i in range(n - 1):
        s += int(np.sign(y[i + 1 :] - y[i]).sum())
    _, counts = np.unique(y, return_counts=True)
    tie_term = float(sum(t * (t - 1) * (2 * t + 5) for t in counts if t > 1))
    var_s = (n * (n - 1) * (2 * n + 5) - tie_term) / 18.0
    if var_s <= 0:  # e.g. every value identical (all zeros)
        return {"s": 0, "var_s": 0.0, "z": 0.0, "p_value": 1.0, "tau": 0.0, "trend": "no trend", "n": n}
    if s > 0:
        z = (s - 1) / math.sqrt(var_s)
    elif s < 0:
        z = (s + 1) / math.sqrt(var_s)
    else:
        z = 0.0
    p = 2 * (1 - stats.norm.cdf(abs(z)))
    tau = s / (n * (n - 1) / 2)
    trend = "no trend"
    if p < ALPHA:
        trend = "increasing" if z > 0 else "decreasing"
    return {
        "s": int(s),
        "var_s": round(var_s, 3),
        "z": round(float(z), 4),
        "p_value": round(float(p), 5),
        "tau": round(float(tau), 4),
        "trend": trend,
        "n": n,
    }


def sens_slope(years, values) -> dict | None:
    """Theil-Sen estimator: median of all pairwise slopes. Uses actual years as x,
    so excluded (low-coverage) years don't distort the spacing."""
    x, y = _clean_xy(years, values)
    if len(y) < 3:
        return None
    i, j = np.triu_indices(len(x), k=1)
    slopes = (y[j] - y[i]) / (x[j] - x[i])
    slope = float(np.median(slopes))
    intercept = float(np.median(y - slope * x))
    return {"slope_per_year": round(slope, 5), "slope_per_decade": round(slope * 10, 4), "intercept": round(intercept, 4)}


def ols(years, values) -> dict | None:
    x, y = _clean_xy(years, values)
    if len(y) < 3 or np.all(y == y[0]):
        return None
    res = stats.linregress(x, y)
    return {
        "slope_per_year": round(float(res.slope), 5),
        "slope_per_decade": round(float(res.slope) * 10, 4),
        "intercept": round(float(res.intercept), 4),
        "r2": round(float(res.rvalue**2), 4),
        "p_value": round(float(res.pvalue), 5),
    }


def lag1_autocorrelation(values) -> float | None:
    _, y = _clean_xy(range(len(values)), values)
    if len(y) < 8 or np.std(y) == 0:
        return None
    return round(float(np.corrcoef(y[:-1], y[1:])[0, 1]), 4)


def rolling_mean(years, values, window: int = 5) -> list[float | None]:
    arr = np.array([np.nan if v is None else v for v in values], dtype=float)
    out: list[float | None] = []
    half = window // 2
    for k in range(len(arr)):
        w = arr[max(0, k - half) : k + half + 1]
        w = w[~np.isnan(w)]
        out.append(round(float(w.mean()), 3) if len(w) >= max(3, window // 2 + 1) else None)
    return out


def analyse(years, values) -> dict:
    return {
        "mann_kendall": mann_kendall(years, values),
        "sens_slope": sens_slope(years, values),
        "ols": ols(years, values),
        "lag1_autocorrelation": lag1_autocorrelation(values),
        "rolling_mean_5y": rolling_mean(years, values),
    }
