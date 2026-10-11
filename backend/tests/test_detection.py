import numpy as np
import pandas as pd
import pytest

from app.hazards import heatwave, heavy_rain
from app.hazards.base import find_runs, percentile_threshold_calendar


def test_find_runs_min_length():
    mask = np.array([1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1], dtype=bool)
    assert find_runs(mask, 3) == [(3, 5), (7, 10)]
    assert find_runs(mask, 2) == [(0, 1), (3, 5), (7, 10)]
    assert find_runs(np.array([], dtype=bool), 3) == []


def _frame(years=range(2000, 2012), base=30.0):
    idx = pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31", freq="D")
    rng = np.random.default_rng(0)
    tmax = base + rng.normal(0, 0.3, len(idx))  # flat, tiny noise -> P95 ~ base+0.5
    return pd.DataFrame({"tmax": tmax, "tmin": tmax - 10, "precip": 0.0}, index=idx)


def _params(**kw):
    p = dict(heatwave.DEFAULTS)
    p.update(kw)
    return p


def test_heatwave_detects_planted_events_and_respects_min_duration():
    df = _frame()
    df.loc["2005-05-01":"2005-05-05", "tmax"] = 40.0  # 5-day event
    df.loc["2007-06-10":"2007-06-11", "tmax"] = 40.0  # 2 days -> NOT a heatwave
    years = list(range(2000, 2012))
    res = heatwave.detect(df, years, set(years), set(years), _params())
    planted = [e for e in res.events if e["peak"] == 40.0]
    assert len(planted) == 1
    ev = planted[0]
    assert (ev["start"], ev["end"], ev["duration"]) == ("2005-05-01", "2005-05-05", 5)
    row2005 = next(r for r in res.annual if r["year"] == 2005)
    assert row2005["days"] >= 5 and row2005["max_duration"] >= 5


def test_missing_day_breaks_a_heatwave():
    df = _frame()
    df.loc["2005-05-01":"2005-05-07", "tmax"] = 40.0
    df.loc["2005-05-04", "tmax"] = np.nan  # gap in the middle -> two 3-day events, not one 7-day
    years = list(range(2000, 2012))
    res = heatwave.detect(df, years, set(years), set(years), _params())
    planted = [e for e in res.events if e["peak"] == 40.0]
    assert [e["duration"] for e in planted] == [3, 3]


def test_threshold_is_strictly_greater_than_percentile():
    years = list(range(2000, 2012))
    df = _frame()
    res = heatwave.detect(df, years, set(years), set(years), _params())
    thr = res.threshold["value_c"]
    assert thr == pytest.approx(np.percentile(df["tmax"], 95), abs=0.01)


def test_invalid_years_are_null_not_zero():
    years = list(range(2000, 2012))
    df = _frame()
    res = heatwave.detect(df, years, set(years) - {2003}, set(years), _params())
    row = next(r for r in res.annual if r["year"] == 2003)
    assert row["valid"] is False and row["days"] is None


def test_calendar_threshold_follows_the_season():
    idx = pd.date_range("2000-01-01", "2019-12-31", freq="D")
    seasonal = 25 + 10 * np.cos(2 * np.pi * (idx.dayofyear - 180) / 365.25)
    s = pd.Series(seasonal, index=idx)
    thr = percentile_threshold_calendar(s, set(range(2000, 2020)), 95)
    assert thr.loc["2010-06-29"] > thr.loc["2010-01-01"] + 15  # summer threshold >> winter threshold


def test_heavy_rain_uses_wet_day_percentile():
    years = list(range(2000, 2012))
    idx = pd.date_range("2000-01-01", "2011-12-31", freq="D")
    precip = np.where(np.arange(len(idx)) % 3 == 0, 10.0, 0.0)  # wet every 3rd day, 10 mm
    df = pd.DataFrame({"tmax": 30.0, "tmin": 20.0, "precip": precip}, index=idx)
    df.loc["2008-07-15", "precip"] = 120.0
    res = heavy_rain.detect(df, years, set(years), set(years), dict(heavy_rain.DEFAULTS))
    assert res.threshold["value_mm"] == pytest.approx(10.0)  # P95 of wet days (zeros ignored)
    assert any(e["start"] == "2008-07-15" and e["peak"] == 120.0 for e in res.events)
    row = next(r for r in res.annual if r["year"] == 2008)
    assert row["rx1day"] == 120.0
