"""Shared machinery for hazard detectors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str
    description: str
    higher_is_worse: bool = True


@dataclass
class DetectionResult:
    threshold: dict[str, Any]
    annual: list[dict[str, Any]]
    events: list[dict[str, Any]]
    variable: str
    extra: dict[str, Any] = field(default_factory=dict)


def find_runs(mask: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Return (start, end_inclusive) index pairs of True-runs with length >= min_len.

    `mask` must already be False wherever data is missing: a NaN day ends a run,
    so a data gap can never be bridged into one long fake heatwave.
    """
    if mask.size == 0:
        return []
    padded = np.concatenate([[False], mask.astype(bool), [False]])
    diff = np.diff(padded.astype(np.int8))
    starts = np.flatnonzero(diff == 1)
    ends = np.flatnonzero(diff == -1) - 1
    return [(int(s), int(e)) for s, e in zip(starts, ends) if e - s + 1 >= min_len]


def percentile_threshold_fixed(series: pd.Series, baseline_years: set[int], pct: float) -> float:
    base = series[series.index.year.isin(list(baseline_years))].dropna()
    if base.empty:
        raise ValueError("No valid data in the baseline period to compute a threshold.")
    return float(np.percentile(base.to_numpy(), pct))


def percentile_threshold_calendar(
    series: pd.Series, baseline_years: set[int], pct: float, half_window: int = 7
) -> pd.Series:
    """Calendar-day percentile (ETCCDI style): for each day-of-year, the percentile of
    all baseline values within +-half_window days of it. Returns a threshold aligned
    to `series.index`."""
    base = series[series.index.year.isin(list(baseline_years))].dropna()
    if base.empty:
        raise ValueError("No valid data in the baseline period to compute a threshold.")
    base_doy = base.index.dayofyear.to_numpy()
    vals = base.to_numpy()
    thr = np.empty(367)
    for d in range(1, 367):
        dist = np.abs(base_doy - d)
        dist = np.minimum(dist, 366 - dist)  # circular: Dec 30 is close to Jan 2
        window = vals[dist <= half_window]
        thr[d] = np.percentile(window, pct) if window.size else np.nan
    return pd.Series(thr[series.index.dayofyear.to_numpy()], index=series.index)


def r(v: Any, nd: int = 2) -> Any:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    if np.isnan(f):
        return None
    return round(f, nd)
