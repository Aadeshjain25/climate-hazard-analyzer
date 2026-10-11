import numpy as np
import pandas as pd

from app.services import cleaning


def _raw(start=2000, end=2004, units=None):
    idx = pd.date_range(f"{start}-01-01", f"{end}-12-31", freq="D")
    doy = idx.dayofyear.to_numpy()
    rng = np.random.default_rng(1)
    tmax = 28 + 6 * np.cos(2 * np.pi * (doy - 120) / 365.25) + rng.normal(0, 1, len(idx))
    df = pd.DataFrame({"tmax": tmax, "tmin": tmax - 9, "precip": 1.0}, index=idx)
    df.attrs["units"] = units or {"tmax": "°C", "tmin": "°C", "precip": "mm"}
    return df


def test_reindexes_missing_dates_and_counts_them():
    df = _raw().drop(pd.date_range("2001-03-01", "2001-03-10"))
    out, rep = cleaning.clean(df, 2000, 2004)
    assert len(out) == len(pd.date_range("2000-01-01", "2004-12-31"))
    assert rep.missing_raw["tmax"] == 10
    # 10-day gap is too long to interpolate -> stays missing
    assert out.loc["2001-03-01":"2001-03-10", "tmax"].isna().all()


def test_short_gaps_are_interpolated_long_gaps_are_not():
    df = _raw()
    df.loc["2002-07-01":"2002-07-02", "tmax"] = np.nan  # 2-day gap -> fill
    df.loc["2002-08-01":"2002-08-04", "tmax"] = np.nan  # 4-day gap -> keep NaN (no partial fill!)
    out, rep = cleaning.clean(df, 2000, 2004)
    assert out.loc["2002-07-01":"2002-07-02", "tmax"].notna().all()
    assert out.loc["2002-08-01":"2002-08-04", "tmax"].isna().all()
    assert rep.interpolated["tmax"] == 2


def test_fahrenheit_is_converted():
    df = _raw()
    df["tmax"] = df["tmax"] * 9 / 5 + 32
    df["tmin"] = df["tmin"] * 9 / 5 + 32
    df.attrs["units"] = {"tmax": "°F", "tmin": "°F", "precip": "mm"}
    out, rep = cleaning.clean(df, 2000, 2004)
    assert 10 < out["tmax"].mean() < 40
    assert "tmax: °F -> °C" in rep.unit_conversions


def test_physical_bounds_and_negative_precip():
    df = _raw()
    df.loc["2001-01-05", "tmax"] = 75.0
    df.loc["2001-01-06", "precip"] = -0.3
    df.loc["2001-01-07", "precip"] = -50.0
    out, rep = cleaning.clean(df, 2000, 2004)
    assert rep.out_of_range["tmax"] == 1 and rep.negative_precip_zeroed == 1 and rep.out_of_range["precip"] == 1
    assert out.loc["2001-01-06", "precip"] == 0.0 and np.isnan(out.loc["2001-01-07", "precip"])


def test_isolated_spike_removed_but_real_heatwave_kept():
    df = _raw()
    df.loc["2003-02-10", "tmax"] += 20  # one-day jump up and straight back down -> glitch
    df.loc["2003-05-01":"2003-05-07", "tmax"] += 9  # persistent heat -> real event
    out, rep = cleaning.clean(df, 2000, 2004)
    assert rep.spikes_removed >= 1
    assert out.loc["2003-05-01":"2003-05-07", "tmax"].notna().all()
    assert out.loc["2003-05-03", "tmax"] > 35


def test_inconsistent_tmax_tmin_dropped():
    df = _raw()
    df.loc["2000-06-01", "tmin"] = df.loc["2000-06-01", "tmax"] + 5
    out, rep = cleaning.clean(df, 2000, 2004)
    assert rep.inconsistent_tmax_tmin == 1


def test_low_coverage_year_excluded():
    df = _raw()
    df.loc["2002-04-01":"2002-06-30", "tmax"] = np.nan  # ~25% of 2002 missing
    out, rep = cleaning.clean(df, 2000, 2004)
    valid = cleaning.valid_years(out["tmax"], rep)
    assert 2002 not in valid and rep.excluded_years == [2002]


def test_aggregate_requires_half_the_cells():
    idx = pd.date_range("2000-01-01", periods=3)
    a = pd.DataFrame({"tmax": [1.0, np.nan, np.nan], "tmin": 0.0, "precip": 0.0}, index=idx)
    b = pd.DataFrame({"tmax": [3.0, 5.0, np.nan], "tmin": 0.0, "precip": 0.0}, index=idx)
    c = pd.DataFrame({"tmax": [5.0, np.nan, 7.0], "tmin": 0.0, "precip": 0.0}, index=idx)
    out = cleaning.aggregate_cells([a, b, c])
    assert out["tmax"].iloc[0] == 3.0
    assert np.isnan(out["tmax"].iloc[1])  # only 1 of 3 cells -> not representative
