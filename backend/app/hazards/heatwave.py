"""Heatwave detection.

Definition (from the brief, made precise):
    A heatwave is a run of >= `min_duration` (default 3) consecutive days on which the
    daily maximum temperature is STRICTLY ABOVE the region's `percentile` (default 95th)
    of daily Tmax, computed over the baseline period.

Decisions worth defending:
  * Threshold is RELATIVE to the region (percentile), not an absolute 40 °C, so the
    same rule works in Bengaluru and in Oslo.
  * Baseline defaults to the analysed period. That makes the threshold self-consistent,
    but if the climate is warming, a later baseline raises the bar and hides some of the
    trend. Users can pin a fixed baseline (e.g. 1961-1990 / 1991-2020) to compare fairly.
  * Two threshold methods:
      - "fixed"    : one percentile over all days of the year (what the brief describes).
                     Captures dangerous absolute heat -> heatwaves fall in the hot season.
      - "calendar" : percentile per calendar day (+-7 day window), the ETCCDI/WMO
                     "warm spell" style. Detects unusually hot spells in ANY season.
  * Missing days are never "hot": a gap breaks a run.
  * An event belongs to the year it STARTS in (matters for Southern-Hemisphere
    Dec->Jan events).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import (
    DetectionResult,
    Metric,
    find_runs,
    percentile_threshold_calendar,
    percentile_threshold_fixed,
    r,
)

NAME = "heatwave"
LABEL = "Heatwave"
VARIABLE = "tmax"
DEFAULTS = {"percentile": 95.0, "min_duration": 3, "threshold_method": "fixed"}

METRICS = [
    Metric("days", "Heatwave days", "days/yr", "Days per year that are part of a heatwave event."),
    Metric("events", "Heatwave events", "events/yr", "Number of distinct heatwave events starting in the year."),
    Metric("max_duration", "Longest heatwave", "days", "Duration of the longest event in the year (0 if none)."),
    Metric("mean_intensity", "Mean intensity", "°C above threshold", "Mean excess of Tmax over the threshold on heatwave days."),
    Metric("cumulative_excess", "Cumulative heat", "°C·days", "Sum of (Tmax - threshold) over all heatwave days: frequency x intensity."),
    Metric("hottest_day", "Hottest day", "°C", "Annual maximum of daily Tmax."),
    Metric("mean_tmax", "Mean Tmax", "°C", "Annual mean of daily maximum temperature (context, not a hazard)."),
]
PRIMARY_METRIC = "days"


def detect(df: pd.DataFrame, years: list[int], valid: set[int], baseline: set[int], params: dict) -> DetectionResult:
    pct = float(params["percentile"])
    min_dur = int(params["min_duration"])
    method = params["threshold_method"]
    tmax = df["tmax"]

    if method == "calendar":
        thr = percentile_threshold_calendar(tmax, baseline, pct)
        threshold_info = {
            "method": "calendar",
            "percentile": pct,
            "min_c": r(thr.min()),
            "max_c": r(thr.max()),
            "unit": "°C",
            "by_day_of_year": [r(v) for v in thr.groupby(thr.index.dayofyear).first().reindex(range(1, 367))],
        }
    else:
        t = percentile_threshold_fixed(tmax, baseline, pct)
        thr = pd.Series(t, index=tmax.index)
        threshold_info = {"method": "fixed", "percentile": pct, "value_c": r(t), "unit": "°C"}

    values = tmax.to_numpy()
    thr_v = thr.to_numpy()
    hot = np.where(np.isnan(values) | np.isnan(thr_v), False, values > thr_v)
    excess = values - thr_v

    events = []
    for s, e in find_runs(hot, min_dur):
        seg = slice(s, e + 1)
        start = tmax.index[s]
        events.append(
            {
                "start": start.date().isoformat(),
                "end": tmax.index[e].date().isoformat(),
                "year": int(start.year),
                "day_of_year": int(start.dayofyear),
                "duration": int(e - s + 1),
                "peak": r(np.nanmax(values[seg])),
                "mean_excess": r(np.nanmean(excess[seg])),
                "cumulative_excess": r(np.nansum(excess[seg])),
            }
        )

    by_year: dict[int, list[dict]] = {}
    for ev in events:
        by_year.setdefault(ev["year"], []).append(ev)

    yearly_tmax = tmax.groupby(tmax.index.year)
    annual = []
    for y in years:
        if y not in valid:
            annual.append({"year": y, "valid": False, **{m.key: None for m in METRICS}})
            continue
        evs = by_year.get(y, [])
        days = sum(e["duration"] for e in evs)
        cum = sum(e["cumulative_excess"] or 0 for e in evs)
        annual.append(
            {
                "year": y,
                "valid": True,
                "events": len(evs),
                "days": days,
                "max_duration": max((e["duration"] for e in evs), default=0),
                "mean_intensity": r(cum / days) if days else None,
                "cumulative_excess": r(cum),
                "hottest_day": r(yearly_tmax.get_group(y).max()) if y in yearly_tmax.groups else None,
                "mean_tmax": r(yearly_tmax.get_group(y).mean()) if y in yearly_tmax.groups else None,
            }
        )
    return DetectionResult(threshold=threshold_info, annual=annual, events=events, variable=VARIABLE)
