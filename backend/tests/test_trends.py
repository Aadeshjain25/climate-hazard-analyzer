import numpy as np
import pytest
from scipy import stats

from app.services import trends


def test_mann_kendall_detects_monotonic_increase():
    years = list(range(1990, 2021))
    vals = [y - 1990 for y in years]
    mk = trends.mann_kendall(years, vals)
    assert mk["trend"] == "increasing"
    assert mk["tau"] == pytest.approx(1.0)
    assert mk["p_value"] < 0.001


def test_mann_kendall_tau_matches_scipy_without_ties():
    rng = np.random.default_rng(42)
    years = list(range(1980, 2020))
    vals = list(rng.normal(size=len(years)) + np.linspace(0, 1, len(years)))
    mk = trends.mann_kendall(years, vals)
    tau, _ = stats.kendalltau(years, vals)
    assert mk["tau"] == pytest.approx(tau, abs=1e-3)


def test_mann_kendall_all_ties_is_no_trend():
    mk = trends.mann_kendall(list(range(2000, 2020)), [0] * 20)
    assert mk["trend"] == "no trend" and mk["p_value"] == 1.0


def test_mann_kendall_skips_missing_and_needs_8_points():
    assert trends.mann_kendall(range(5), [1, 2, 3, 4, 5]) is None
    mk = trends.mann_kendall(range(12), [1, None, 3, 4, None, 6, 7, 8, 9, 10, 11, 12])
    assert mk["n"] == 10


def test_sens_slope_on_line_and_robust_to_outlier():
    years = list(range(2000, 2020))
    vals = [2 * (y - 2000) + 1 for y in years]
    vals[5] = 500  # one wild outlier
    sen = trends.sens_slope(years, vals)
    assert sen["slope_per_year"] == pytest.approx(2.0)
    ols = trends.ols(years, vals)
    assert abs(ols["slope_per_year"] - 2.0) > 1  # OLS is dragged by the outlier, Sen is not


def test_rolling_mean_handles_gaps():
    rm = trends.rolling_mean(range(10), [1, 2, 3, None, 5, 6, 7, 8, 9, 10])
    assert len(rm) == 10 and rm[4] == pytest.approx((3 + 5 + 6 + 7) / 4)  # None skipped
