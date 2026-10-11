"""Heavy-rainfall detection (secondary hazard, same framework as heatwaves).

Definition (ETCCDI R95p-style):
  * Wet day: precipitation >= 1 mm (drizzle/trace values are excluded so the
    percentile isn't dragged down by thousands of 0.1 mm days).
  * Threshold: the `percentile` (default 95th) of WET-day precipitation in the baseline.
  * Heavy-rain day: precipitation strictly above the threshold.
  * Event: a run of >= `min_duration` (default 1) consecutive heavy-rain days.

Caveat shown to users: ERA5 is a ~28 km grid; it smooths convective downpours, so
absolute extremes are underestimated vs rain gauges. Relative trends are still informative.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .base import DetectionResult, Metric, find_runs, r

NAME = "heavy_rain"
LABEL = "Heavy rainfall"
VARIABLE = "precip"
WET_DAY_MM = 1.0
DEFAULTS = {"percentile": 95.0, "min_duration": 1, "threshold_method": "fixed"}

METRICS = [
    Metric("days", "Heavy-rain days", "days/yr", "Days per year with precipitation above the wet-day percentile."),
    Metric("events", "Heavy-rain events", "events/yr", "Distinct runs of consecutive heavy-rain days."),
    Metric("heavy_total", "Heavy-rain total", "mm/yr", "Precipitation falling on heavy-rain days (R95pTOT-style)."),
    Metric("rx1day", "Wettest day", "mm", "Annual maximum 1-day precipitation (Rx1day)."),
    Metric("heavy_share", "Share from heavy days", "%", "Percent of the annual total falling on heavy-rain days."),
    Metric("annual_total", "Annual precipitation", "mm/yr", "Total annual precipitation (context)."),
]
PRIMARY_METRIC = "days"


def detect(df: pd.DataFrame, years: list[int], valid: set[int], baseline: set[int], params: dict) -> DetectionResult:
    pct = float(params["percentile"])
    min_dur = int(params["min_duration"])
    pr = df["precip"]
    base = pr[pr.index.year.isin(list(baseline))].dropna()
    wet = base[base >= WET_DAY_MM]
    if wet.empty:
        raise ValueError("No wet days in the baseline period; heavy-rain threshold is undefined for this region.")
    t = float(np.percentile(wet.to_numpy(), pct))

    values = pr.to_numpy()
    heavy = np.where(np.isnan(values), False, values > t)
    events = []
    for s, e in find_runs(heavy, min_dur):
        seg = slice(s, e + 1)
        start = pr.index[s]
        events.append(
            {
                "start": start.date().isoformat(),
                "end": pr.index[e].date().isoformat(),
                "year": int(start.year),
                "day_of_year": int(start.dayofyear),
                "duration": int(e - s + 1),
                "peak": r(np.nanmax(values[seg]), 1),
                "mean_excess": r(np.nanmean(values[seg] - t)),
                "cumulative_excess": r(np.nansum(values[seg]), 1),  # total mm in the event
            }
        )
    by_year: dict[int, list[dict]] = {}
    for ev in events:
        by_year.setdefault(ev["year"], []).append(ev)

    grouped = pr.groupby(pr.index.year)
    annual = []
    for y in years:
        if y not in valid:
            annual.append({"year": y, "valid": False, **{m.key: None for m in METRICS}})
            continue
        g = grouped.get_group(y)
        total = float(g.sum(skipna=True))
        heavy_mask = g > t
        heavy_total = float(g[heavy_mask].sum())
        evs = by_year.get(y, [])
        annual.append(
            {
                "year": y,
                "valid": True,
                "events": len(evs),
                "days": int(heavy_mask.sum()),
                "heavy_total": r(heavy_total, 1),
                "rx1day": r(g.max(), 1),
                "heavy_share": r(100 * heavy_total / total, 1) if total > 0 else None,
                "annual_total": r(total, 1),
            }
        )
    return DetectionResult(
        threshold={"method": "fixed", "percentile": pct, "value_mm": r(t, 1), "unit": "mm", "wet_day_mm": WET_DAY_MM},
        annual=annual,
        events=events,
        variable=VARIABLE,
    )
