"""Read-through cache of raw daily weather in MongoDB.

Layout: one document per (source, grid cell, calendar year)
    _id     = "open-meteo:era5|12.75:77.50|1995"
    tmax/tmin/precip = arrays (raw values, None for missing), units = as reported

Why per-year documents?
  * Overlapping requests share work: 1990-2020 then 1980-2010 only fetches 1980-1989.
  * Documents stay small (~365*3 numbers, a few KB) - well under Mongo's 16 MB cap.
  * Past years of reanalysis are effectively immutable, so they never expire.
    (We only serve complete years, so no "still-changing" year is ever cached.)

We store RAW values (with their units) and clean on read. That keeps the
original data auditable and lets us change QC rules without re-downloading.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import date, datetime, timezone

import pandas as pd

from ..regions import Cell
from .sources import WeatherSource

log = logging.getLogger(__name__)


def _contiguous_spans(years: list[int], max_len: int) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    for y in sorted(years):
        if spans and y == spans[-1][1] + 1 and (y - spans[-1][0]) < max_len:
            spans[-1] = (spans[-1][0], y)
        else:
            spans.append((y, y))
    return spans


class WeatherStore:
    def __init__(self, db, source: WeatherSource, chunk_years: int = 20):
        self._col = db["weather_years"]
        self._source = source
        self._chunk_years = chunk_years
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.last_fetch_stats = {"years_from_cache": 0, "years_fetched": 0, "upstream_requests": 0}

    def _id(self, cell: Cell, year: int) -> str:
        return f"{self._source.name}|{cell.key}|{year}"

    async def _cached_years(self, cell: Cell, years: range) -> set[int]:
        ids = [self._id(cell, y) for y in years]
        found = set()
        async for doc in self._col.find({"_id": {"$in": ids}}, {"year": 1}):
            found.add(doc["year"])
        return found

    async def get(self, cells: list[Cell], start_year: int, end_year: int) -> tuple[dict[str, pd.DataFrame], dict]:
        """Return {cell_key: DataFrame(date index; tmax, tmin, precip)} plus cache stats."""
        years = range(start_year, end_year + 1)
        stats = {"years_from_cache": 0, "years_fetched": 0, "upstream_requests": 0}

        # Per-cell locks (acquired in sorted order -> no deadlocks) mean two concurrent
        # requests for the same place trigger ONE upstream download, not two.
        ordered = sorted(cells, key=lambda c: c.key)
        for c in ordered:
            await self._locks[c.key].acquire()
        try:
            missing_by_cell: dict[str, list[int]] = {}
            for c in ordered:
                have = await self._cached_years(c, years)
                stats["years_from_cache"] += len(have)
                missing = [y for y in years if y not in have]
                if missing:
                    missing_by_cell[c.key] = missing

            # Group cells that miss the same years so they share one multi-location request.
            groups: dict[tuple[int, ...], list[Cell]] = defaultdict(list)
            for c in ordered:
                if c.key in missing_by_cell:
                    groups[tuple(missing_by_cell[c.key])].append(c)

            for missing_years, group_cells in groups.items():
                for y0, y1 in _contiguous_spans(list(missing_years), self._chunk_years):
                    raw = await self._source.fetch(group_cells, date(y0, 1, 1), date(y1, 12, 31))
                    stats["upstream_requests"] += 1
                    await self._store(group_cells, raw)
                    stats["years_fetched"] += (y1 - y0 + 1) * len(group_cells)
        finally:
            for c in ordered:
                self._locks[c.key].release()

        frames = {c.key: await self._load(c, years) for c in cells}
        self.last_fetch_stats = stats
        return frames, stats

    async def _store(self, cells: list[Cell], raw: dict[str, dict]) -> None:
        now = datetime.now(timezone.utc)
        for c in cells:
            rec = raw[c.key]
            by_year: dict[int, dict[str, list]] = defaultdict(lambda: {"dates": [], "tmax": [], "tmin": [], "precip": []})
            for i, d in enumerate(rec["dates"]):
                y = int(d[:4])
                b = by_year[y]
                b["dates"].append(d)
                b["tmax"].append(rec["tmax"][i])
                b["tmin"].append(rec["tmin"][i])
                b["precip"].append(rec["precip"][i])
            for y, b in by_year.items():
                doc = {
                    "_id": self._id(c, y),
                    "source": self._source.name,
                    "cell": c.key,
                    "lat": c.lat,
                    "lon": c.lon,
                    "year": y,
                    "start": b["dates"][0],
                    "tmax": b["tmax"],
                    "tmin": b["tmin"],
                    "precip": b["precip"],
                    "units": rec.get("units", {}),
                    "fetched_at": now,
                }
                await self._col.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    async def _load(self, cell: Cell, years: range) -> pd.DataFrame:
        parts = []
        units: dict = {}
        cursor = self._col.find({"_id": {"$in": [self._id(cell, y) for y in years]}})
        async for doc in cursor:
            idx = pd.date_range(doc["start"], periods=len(doc["tmax"]), freq="D")
            parts.append(
                pd.DataFrame(
                    {"tmax": doc["tmax"], "tmin": doc["tmin"], "precip": doc["precip"]}, index=idx, dtype="float64"
                )
            )
            units = doc.get("units") or units
        if not parts:
            return pd.DataFrame(columns=["tmax", "tmin", "precip"], dtype="float64")
        df = pd.concat(parts).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df.attrs["units"] = units
        return df
