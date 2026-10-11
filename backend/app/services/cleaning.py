"""Quality control for noisy daily weather series.

Pipeline (each step is counted in the QualityReport so the UI can show it):

 1. Reindex onto a complete daily calendar  -> missing dates become explicit NaN.
 2. Unit normalisation                      -> °F -> °C, inch -> mm (we request metric,
                                               but we verify instead of trusting).
 3. Physical-range checks                   -> values outside plausible Earth limits -> NaN.
                                               Tiny negative precip (-0.x mm, a common
                                               rounding artefact) -> 0.
 4. Internal consistency                    -> Tmax < Tmin (by >0.5 °C) -> both NaN.
 5. Isolated spike removal                  -> a day that is an extreme outlier vs its
                                               calendar-day climatology (robust z > 6)
                                               AND jumps >10 °C from BOTH neighbours.
                                               Real heat is persistent; a one-day jump
                                               up and straight back down is a glitch.
                                               Using both tests avoids deleting real
                                               record-breaking heatwaves.
 6. Short-gap interpolation (temperature)   -> gaps <= 2 days linearly interpolated.
                                               Longer gaps stay NaN and BREAK heatwave
                                               runs (we never invent a hot day).
                                               Precip is never interpolated (not smooth).
 7. Year coverage                           -> a year with <90% valid days is excluded
                                               from annual stats & trends, because a
                                               missing summer would look like "fewer
                                               heatwaves".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

BOUNDS = {"tmax": (-90.0, 60.0), "tmin": (-95.0, 50.0), "precip": (0.0, 1000.0)}
MAX_INTERP_GAP_DAYS = 2
SPIKE_Z = 6.0
SPIKE_JUMP_C = 10.0
MIN_YEAR_COVERAGE = 0.90


@dataclass
class QualityReport:
    total_days: int = 0
    missing_raw: dict = field(default_factory=dict)
    unit_conversions: list = field(default_factory=list)
    out_of_range: dict = field(default_factory=dict)
    negative_precip_zeroed: int = 0
    inconsistent_tmax_tmin: int = 0
    spikes_removed: int = 0
    interpolated: dict = field(default_factory=dict)
    missing_after_cleaning: dict = field(default_factory=dict)
    cells_used: int = 1
    excluded_years: list = field(default_factory=list)
    year_coverage: dict = field(default_factory=dict)

    def merge(self, other: "QualityReport") -> None:
        """Sum per-cell reports (for multi-cell bounding boxes)."""
        self.total_days = max(self.total_days, other.total_days)
        for attr in ("missing_raw", "out_of_range", "interpolated", "missing_after_cleaning"):
            mine, theirs = getattr(self, attr), getattr(other, attr)
            for k, v in theirs.items():
                mine[k] = mine.get(k, 0) + v
        for conv in other.unit_conversions:
            if conv not in self.unit_conversions:
                self.unit_conversions.append(conv)
        self.negative_precip_zeroed += other.negative_precip_zeroed
        self.inconsistent_tmax_tmin += other.inconsistent_tmax_tmin
        self.spikes_removed += other.spikes_removed

    def to_dict(self) -> dict:
        return asdict(self)


def _normalise_units(df: pd.DataFrame, units: dict, report: QualityReport) -> pd.DataFrame:
    for col in ("tmax", "tmin"):
        u = (units or {}).get(col, "°C")
        if u in ("°F", "F", "fahrenheit"):
            df[col] = (df[col] - 32.0) * 5.0 / 9.0
            report.unit_conversions.append(f"{col}: °F -> °C")
        elif u in ("K", "kelvin"):
            df[col] = df[col] - 273.15
            report.unit_conversions.append(f"{col}: K -> °C")
    u = (units or {}).get("precip", "mm")
    if u in ("inch", "in", "inches"):
        df["precip"] = df["precip"] * 25.4
        report.unit_conversions.append("precip: inch -> mm")
    return df


def _remove_spikes(s: pd.Series) -> tuple[pd.Series, int]:
    if s.notna().sum() < 365:
        return s, 0
    doy = s.index.dayofyear
    # Calendar-day climatology using median/MAD (robust: the outliers we hunt don't skew it).
    clim_med = s.groupby(doy).transform("median")
    abs_dev = (s - clim_med).abs()
    mad = abs_dev.groupby(doy).transform("median")
    # Smooth MAD over +-7 days so a single calendar day with few samples isn't over-sensitive.
    mad_by_doy = mad.groupby(doy).first().reindex(range(1, 367)).interpolate(limit_direction="both")
    mad_smooth = mad_by_doy.rolling(15, center=True, min_periods=1).mean()
    robust_sigma = 1.4826 * pd.Series(mad_smooth.loc[doy].to_numpy(), index=s.index).clip(lower=0.5)
    z = (s - clim_med) / robust_sigma
    jump_prev = (s - s.shift(1)).abs()
    jump_next = (s - s.shift(-1)).abs()
    spike = (z.abs() > SPIKE_Z) & (jump_prev > SPIKE_JUMP_C) & (jump_next > SPIKE_JUMP_C)
    n = int(spike.sum())
    if n:
        s = s.mask(spike)
    return s, n


def clean(df: pd.DataFrame, start_year: int, end_year: int) -> tuple[pd.DataFrame, QualityReport]:
    report = QualityReport()
    units = df.attrs.get("units", {})
    full_idx = pd.date_range(f"{start_year}-01-01", f"{end_year}-12-31", freq="D")
    df = df.reindex(full_idx).astype("float64")
    report.total_days = len(full_idx)
    report.missing_raw = {c: int(df[c].isna().sum()) for c in ("tmax", "tmin", "precip")}

    df = _normalise_units(df, units, report)

    # Tiny negative precipitation is a rounding artefact, not a sensor failure.
    small_neg = (df["precip"] < 0) & (df["precip"] > -1)
    report.negative_precip_zeroed = int(small_neg.sum())
    df.loc[small_neg, "precip"] = 0.0

    for col, (lo, hi) in BOUNDS.items():
        bad = (df[col] < lo) | (df[col] > hi)
        report.out_of_range[col] = int(bad.sum())
        df.loc[bad, col] = np.nan

    inconsistent = (df["tmax"] < df["tmin"] - 0.5)
    report.inconsistent_tmax_tmin = int(inconsistent.sum())
    df.loc[inconsistent, ["tmax", "tmin"]] = np.nan

    spikes = 0
    for col in ("tmax", "tmin"):
        df[col], n = _remove_spikes(df[col])
        spikes += n
    report.spikes_removed = spikes

    for col in ("tmax", "tmin"):
        before = df[col].isna()
        # limit_area="inside" -> never extrapolate at the series edges.
        filled = df[col].interpolate(method="linear", limit=MAX_INTERP_GAP_DAYS, limit_area="inside")
        # pandas' `limit` fills the first N days of a long gap too; undo that so a long
        # gap stays fully missing instead of getting partially invented edges.
        gap_id = before.ne(before.shift()).cumsum()
        gap_len = before.groupby(gap_id).transform("sum")
        filled = filled.mask(before & (gap_len > MAX_INTERP_GAP_DAYS))
        report.interpolated[col] = int((before & filled.notna()).sum())
        df[col] = filled

    report.missing_after_cleaning = {c: int(df[c].isna().sum()) for c in ("tmax", "tmin", "precip")}
    return df, report


def aggregate_cells(frames: list[pd.DataFrame]) -> pd.DataFrame:
    """Area-mean of several cleaned cell series (bounding-box regions).

    A day is kept only if at least half of the cells have a value, so a single
    surviving cell can't masquerade as the regional mean.
    """
    if len(frames) == 1:
        return frames[0]
    out = {}
    for col in ("tmax", "tmin", "precip"):
        stacked = pd.concat([f[col] for f in frames], axis=1)
        enough = stacked.notna().sum(axis=1) >= max(1, len(frames) / 2)
        out[col] = stacked.mean(axis=1, skipna=True).where(enough)
    return pd.DataFrame(out)


def year_coverage(series: pd.Series) -> dict[int, float]:
    valid = series.notna().groupby(series.index.year).mean()
    return {int(y): round(float(v), 4) for y, v in valid.items()}


def valid_years(series: pd.Series, report: QualityReport) -> set[int]:
    cov = year_coverage(series)
    report.year_coverage = cov
    report.excluded_years = sorted(y for y, v in cov.items() if v < MIN_YEAR_COVERAGE)
    return {y for y, v in cov.items() if v >= MIN_YEAR_COVERAGE}
