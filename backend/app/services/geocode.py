"""Place search -> coordinates (+ bounding box for states/regions).

Primary: OpenStreetMap Nominatim (returns bounding boxes, so a *state* can become
a lat/lon box). Its usage policy requires <= 1 request/second, an identifying
User-Agent, and caching - all enforced here.
Fallback: Open-Meteo geocoding (points only), used if Nominatim fails.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone

from .upstream import UpstreamClient, UpstreamError

log = logging.getLogger(__name__)

AREA_TYPES = {"state", "province", "region", "state_district", "county", "district", "administrative", "country"}
_ws = re.compile(r"\s+")


def normalise_query(q: str) -> str:
    return _ws.sub(" ", q).strip().lower()


class Geocoder:
    def __init__(self, db, client: UpstreamClient, nominatim_url: str, open_meteo_url: str, max_bbox_deg: float):
        self._col = db["geocode_cache"]
        self._client = client
        self._nominatim = nominatim_url
        self._om = open_meteo_url
        self._max_bbox = max_bbox_deg
        self._lock = asyncio.Lock()
        self._last_call = 0.0

    async def search(self, query: str) -> list[dict]:
        key = normalise_query(query)
        cached = await self._col.find_one({"_id": key})
        if cached:
            return cached["results"]
        try:
            results = await self._nominatim_search(key)
        except UpstreamError as exc:
            log.warning("Nominatim failed (%s); falling back to Open-Meteo geocoding", exc)
            results = []
        if not results:
            try:
                results = await self._open_meteo_search(key)
            except UpstreamError as exc:
                log.warning("Open-Meteo geocoding failed: %s", exc)
                raise
        await self._col.replace_one(
            {"_id": key}, {"_id": key, "results": results, "created_at": datetime.now(timezone.utc)}, upsert=True
        )
        return results

    async def _nominatim_search(self, q: str) -> list[dict]:
        async with self._lock:  # global 1 req/s throttle (Nominatim policy)
            wait = 1.05 - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            data = await self._client.get_json(self._nominatim, {"q": q, "format": "jsonv2", "limit": 6})
            self._last_call = time.monotonic()
        out = []
        for item in data if isinstance(data, list) else []:
            try:
                lat, lon = float(item["lat"]), float(item["lon"])
                bb = [float(v) for v in item.get("boundingbox", [])]  # [south, north, west, east]
            except (KeyError, TypeError, ValueError):
                continue
            atype = item.get("addresstype") or item.get("type") or ""
            kind = "area" if atype in AREA_TYPES else "place"
            bbox = None
            if kind == "area" and len(bb) == 4:
                s, n, w, e = bb
                bbox = {"south": s, "west": w, "north": n, "east": e}
            out.append(
                {
                    "label": item.get("display_name", q)[:160],
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    "kind": kind,
                    "type": atype,
                    "bbox": bbox,
                    "bbox_too_large": bool(bbox and (bbox["north"] - bbox["south"] > self._max_bbox or bbox["east"] - bbox["west"] > self._max_bbox)),
                }
            )
        return out

    async def _open_meteo_search(self, q: str) -> list[dict]:
        data = await self._client.get_json(self._om, {"name": q, "count": 6, "language": "en", "format": "json"})
        out = []
        for item in (data or {}).get("results", []) or []:
            try:
                lat, lon = float(item["latitude"]), float(item["longitude"])
            except (KeyError, TypeError, ValueError):
                continue
            parts = [item.get("name"), item.get("admin1"), item.get("country")]
            out.append(
                {
                    "label": ", ".join(p for p in parts if p)[:160],
                    "lat": round(lat, 4),
                    "lon": round(lon, 4),
                    "kind": "place",
                    "type": item.get("feature_code", ""),
                    "bbox": None,
                    "bbox_too_large": False,
                }
            )
        return out


class OfflineGeocoder:
    """Used with DATA_SOURCE=synthetic so the demo works with no internet at all."""

    PLACES = [
        ("Bengaluru, Karnataka, India", 12.9716, 77.5946, None),
        ("Delhi, India", 28.6139, 77.209, None),
        ("Mumbai, Maharashtra, India", 19.076, 72.8777, None),
        ("Chennai, Tamil Nadu, India", 13.0827, 80.2707, None),
        ("Karnataka, India", 15.0, 76.0, {"south": 11.5, "west": 74.0, "north": 18.5, "east": 78.6}),
        ("Rajasthan, India", 26.6, 73.8, {"south": 23.0, "west": 69.5, "north": 30.2, "east": 78.3}),
        ("Phoenix, Arizona, USA", 33.4484, -112.074, None),
        ("London, UK", 51.5074, -0.1278, None),
    ]

    async def search(self, query: str) -> list[dict]:
        q = normalise_query(query)
        return [
            {"label": n, "lat": la, "lon": lo, "kind": "area" if bb else "place", "type": "", "bbox": bb, "bbox_too_large": False}
            for n, la, lo, bb in self.PLACES
            if q in n.lower()
        ]
