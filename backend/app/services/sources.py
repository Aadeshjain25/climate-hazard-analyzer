"""Weather data sources.

OpenMeteoSource  - real data: Open-Meteo Historical Weather API, ERA5 reanalysis.
SyntheticSource  - offline demo data (deterministic, with a built-in warming trend,
                   gaps and spikes so the cleaning pipeline has something to do).
                   Never used unless DATA_SOURCE=synthetic, and the UI shows a banner.

Both return the same raw shape per cell:
  {"dates": [...ISO dates...], "tmax": [...], "tmin": [...], "precip": [...],
   "units": {"tmax": "°C", "tmin": "°C", "precip": "mm"}}
"""
from __future__ import annotations

import hashlib
import math
from datetime import date, timedelta
from typing import Protocol

import numpy as np

from ..regions import Cell
from .upstream import UpstreamClient, UpstreamError

DAILY_VARS = ("temperature_2m_max", "temperature_2m_min", "precipitation_sum")
VAR_MAP = {"temperature_2m_max": "tmax", "temperature_2m_min": "tmin", "precipitation_sum": "precip"}


class WeatherSource(Protocol):
    name: str

    async def fetch(self, cells: list[Cell], start: date, end: date) -> dict[str, dict]: ...


class OpenMeteoSource:
    """ERA5 via Open-Meteo. Free, no API key, global, 1940-present, ~5 day lag.

    We request `models=era5` explicitly instead of the default `best_match`:
    best_match blends datasets with different resolutions, and a dataset switch
    partway through a time series can create an artificial step change that a
    trend test would happily report as "climate change".
    """

    name = "open-meteo:era5"

    def __init__(self, client: UpstreamClient, url: str):
        self._client = client
        self._url = url

    async def fetch(self, cells: list[Cell], start: date, end: date) -> dict[str, dict]:
        params = {
            # Multiple locations in ONE request (comma-separated) -> fewer round trips.
            "latitude": ",".join(f"{c.lat:.4f}" for c in cells),
            "longitude": ",".join(f"{c.lon:.4f}" for c in cells),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": ",".join(DAILY_VARS),
            "models": "era5",
            "timezone": "GMT",  # one fixed day boundary for every cell -> comparable days
            "temperature_unit": "celsius",
            "precipitation_unit": "mm",
        }
        payload = await self._client.get_json(self._url, params)
        items = payload if isinstance(payload, list) else [payload]
        if len(items) != len(cells):
            raise UpstreamError(f"Expected {len(cells)} locations, got {len(items)}")

        out: dict[str, dict] = {}
        for cell, item in zip(cells, items):
            if not isinstance(item, dict) or item.get("error"):
                raise UpstreamError(f"Upstream error payload: {str(item.get('reason', 'unknown'))[:120]}")
            daily = item.get("daily") or {}
            units = item.get("daily_units") or {}
            dates = daily.get("time")
            if not isinstance(dates, list) or not dates:
                raise UpstreamError("Upstream response missing daily.time")
            rec = {"dates": dates, "units": {}}
            for var, short in VAR_MAP.items():
                values = daily.get(var)
                if not isinstance(values, list) or len(values) != len(dates):
                    raise UpstreamError(f"Upstream response has malformed {var}")
                rec[short] = values
                rec["units"][short] = units.get(var, "")
            out[cell.key] = rec
        return out


class SyntheticSource:
    """Deterministic fake climate for offline demos and tests."""

    name = "synthetic"

    async def fetch(self, cells: list[Cell], start: date, end: date) -> dict[str, dict]:
        return self.generate(cells, start, end)

    @staticmethod
    def generate(cells: list[Cell], start: date, end: date) -> dict[str, dict]:
        n = (end - start).days + 1
        dates = [(start + timedelta(days=i)).isoformat() for i in range(n)]
        out = {}
        for cell in cells:
            seed = int(hashlib.sha256(f"{cell.key}:{start}:{end}".encode()).hexdigest()[:8], 16)
            rng = np.random.default_rng(seed)
            doy = np.array([(start + timedelta(days=i)).timetuple().tm_yday for i in range(n)])
            years = np.array([(start + timedelta(days=i)).year for i in range(n)])
            base = 30 - abs(cell.lat) * 0.35
            amp = 4 + abs(cell.lat) * 0.12
            phase = 120 if cell.lat >= 0 else 300
            seasonal = base + amp * np.cos(2 * math.pi * (doy - phase) / 365.25)
            warming = (years - 1980) * 0.025  # +0.25 °C / decade
            # AR(1) weather noise -> realistic multi-day persistence (heatwaves need runs)
            noise = np.zeros(n)
            eps = rng.normal(0, 1.6, n)
            for i in range(1, n):
                noise[i] = 0.7 * noise[i - 1] + eps[i]
            tmax = seasonal + warming + noise
            tmin = tmax - 9 - rng.gamma(2, 0.8, n)
            precip = np.where(rng.random(n) < 0.3, rng.gamma(0.8, 8 + (years - 1980) * 0.03, n), 0.0)
            tmax_l = [round(float(v), 1) for v in tmax]
            tmin_l = [round(float(v), 1) for v in tmin]
            pr_l = [round(float(v), 1) for v in precip]
            # Inject realistic dirt: a gap, a spike, a negative-precip glitch.
            if n > 400:
                for k in range(200, 203):
                    tmax_l[k] = None  # type: ignore[call-overload]
                    tmin_l[k] = None  # type: ignore[call-overload]
                tmax_l[300] = 71.3  # physically impossible
                pr_l[310] = -0.2
                tmax_l[320] = round(tmax_l[320] + 18.0, 1)  # isolated spike (within physical bounds)
            out[cell.key] = {
                "dates": dates,
                "tmax": tmax_l,
                "tmin": tmin_l,
                "precip": pr_l,
                "units": {"tmax": "°C", "tmin": "°C", "precip": "mm"},
            }
        return out
