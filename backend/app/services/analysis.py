"""Orchestrates one analysis: cache lookup -> data -> clean -> detect -> trends -> insights -> store.

Two cache layers:
  1. weather_years (raw daily data, permanent)  - see weather_store.py
  2. analyses      (finished JSON result, TTL)   - this module

The API reads finished analyses from MongoDB. A repeat request for the same
normalised parameters is a single indexed `find_one` by _id (a SHA-256 of the
parameters + algorithm version + data source).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import numpy as np

from .. import hazards
from ..config import ALGO_VERSION
from ..regions import Region
from . import cleaning, insights, trends
from .weather_store import WeatherStore

log = logging.getLogger(__name__)


class AnalysisError(ValueError):
    """Bad-but-valid request (e.g. no wet days in a desert). Mapped to HTTP 422."""


@dataclass(frozen=True)
class AnalysisParams:
    hazard: str
    region: Region
    start_year: int
    end_year: int
    percentile: float
    min_duration: int
    threshold_method: str
    baseline_start: int | None = None
    baseline_end: int | None = None

    @property
    def baseline(self) -> tuple[int, int]:
        return (self.baseline_start or self.start_year, self.baseline_end or self.end_year)

    def cache_key(self, source: str, max_per_axis: int) -> str:
        payload = {
            "v": ALGO_VERSION,
            "src": source,
            "hz": self.hazard,
            "rg": self.region.cache_key(),
            "grid": max_per_axis,
            "y": [self.start_year, self.end_year],
            "b": list(self.baseline),
            "p": round(self.percentile, 2),
            "d": self.min_duration,
            "m": self.threshold_method,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class AnalysisService:
    def __init__(self, db, store: WeatherStore, source_name: str, ttl_days: int, max_per_axis: int):
        self._col = db["analyses"]
        self._store = store
        self._source_name = source_name
        self._ttl_days = ttl_days
        self._max_per_axis = max_per_axis
        self._inflight: dict[str, asyncio.Future] = {}

    async def run(self, p: AnalysisParams) -> dict:
        key = p.cache_key(self._source_name, self._max_per_axis)
        doc = await self._col.find_one({"_id": key})
        if doc:
            result = doc["result"]
            result["meta"]["cached"] = True
            return result

        # Coalesce identical concurrent requests: the 2nd caller awaits the 1st's work.
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await self._compute(p)
            await self._col.replace_one(
                {"_id": key},
                {"_id": key, "params": _params_doc(p), "result": result, "created_at": datetime.now(timezone.utc)},
                upsert=True,
            )
            fut.set_result(result)
            return result
        except Exception as exc:
            fut.set_exception(exc)
            fut.exception()  # mark retrieved -> no "never retrieved" warning if nobody else awaited
            raise
        finally:
            self._inflight.pop(key, None)

    async def _compute(self, p: AnalysisParams) -> dict:
        hz = hazards.get(p.hazard)
        b0, b1 = p.baseline
        y0, y1 = min(p.start_year, b0), max(p.end_year, b1)
        cells = p.region.cells(self._max_per_axis)

        frames, fetch_stats = await self._store.get(cells, y0, y1)

        cleaned, report = [], None
        for c in cells:
            df_c, rep_c = cleaning.clean(frames[c.key], y0, y1)
            cleaned.append(df_c)
            if report is None:
                report = rep_c
            else:
                report.merge(rep_c)
        assert report is not None
        report.cells_used = len(cells)
        df = cleaning.aggregate_cells(cleaned)

        valid_all = cleaning.valid_years(df[hz.VARIABLE], report)
        years = list(range(p.start_year, p.end_year + 1))
        valid = {y for y in valid_all if p.start_year <= y <= p.end_year}
        baseline = {y for y in valid_all if b0 <= y <= b1}
        # list (not dict) because BSON documents require string keys
        report.year_coverage = [
            {"year": y, "coverage": v} for y, v in sorted(report.year_coverage.items()) if p.start_year <= y <= p.end_year
        ]
        report.excluded_years = [y for y in report.excluded_years if p.start_year <= y <= p.end_year]
        if len(valid) < 10:
            raise AnalysisError("Fewer than 10 years with adequate data coverage; cannot analyse trends.")
        if len(baseline) < 10:
            raise AnalysisError("Fewer than 10 valid baseline years; choose a longer baseline.")

        params = {"percentile": p.percentile, "min_duration": p.min_duration, "threshold_method": p.threshold_method}
        try:
            det = hz.detect(df, years, valid, baseline, params)
        except ValueError as exc:
            raise AnalysisError(str(exc)) from exc

        events = [e for e in det.events if p.start_year <= e["year"] <= p.end_year]
        trend_results = {
            m.key: trends.analyse(years, [row[m.key] if row["valid"] else None for row in det.annual]) for m in hz.METRICS
        }

        # "Warming stripes": annual mean Tmax anomaly vs the analysed period's mean.
        tmax_year = df["tmax"].groupby(df.index.year).mean()
        tmax_year = tmax_year[(tmax_year.index >= p.start_year) & (tmax_year.index <= p.end_year)]
        ref = float(np.nanmean([tmax_year.get(y) for y in valid if y in tmax_year.index]))
        stripes = [
            {"year": int(y), "anomaly": round(float(v - ref), 3) if y in valid and not np.isnan(v) else None}
            for y, v in tmax_year.items()
        ]

        region_dict = p.region.to_dict(self._max_per_axis)
        quality = report.to_dict()
        quality["fetch"] = fetch_stats
        baseline_label = f"{b0}–{b1}"
        summary = insights.build(
            hz, det.annual, trend_results, events, region_dict, params, quality, self._source_name, baseline_label
        )

        return {
            "meta": {
                "hazard": hz.NAME,
                "hazard_label": hz.LABEL,
                "region": region_dict,
                "start_year": p.start_year,
                "end_year": p.end_year,
                "baseline": {"start": b0, "end": b1},
                "params": params,
                "source": self._source_name,
                "source_detail": "ERA5 reanalysis via Open-Meteo Historical Weather API"
                if self._source_name.startswith("open-meteo")
                else "Synthetic demo data (NOT real)",
                "algo_version": ALGO_VERSION,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "cached": False,
            },
            "metrics": [vars(m) for m in hz.METRICS],
            "primary_metric": hz.PRIMARY_METRIC,
            "threshold": det.threshold,
            "annual": det.annual,
            "events": events,
            "trends": trend_results,
            "insights": summary,
            "quality": quality,
            "stripes": stripes,
        }


def _params_doc(p: AnalysisParams) -> dict:
    d = asdict(p)
    d["region"] = asdict(p.region)
    return d
