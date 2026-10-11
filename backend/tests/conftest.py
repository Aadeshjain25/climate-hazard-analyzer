from __future__ import annotations

import dataclasses
from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app
from app.ratelimit import limiter
from app.regions import Cell
from app.services.sources import SyntheticSource
from app.services.upstream import UpstreamClient


class FakeOpenMeteo:
    """httpx transport that mimics the Open-Meteo archive API using synthetic data."""

    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.fail_next = 0  # number of upcoming calls to answer with HTTP 500

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.fail_next > 0:
            self.fail_next -= 1
            return httpx.Response(500, text="boom")
        q = request.url.params
        lats = [float(x) for x in q["latitude"].split(",")]
        lons = [float(x) for x in q["longitude"].split(",")]
        start, end = date.fromisoformat(q["start_date"]), date.fromisoformat(q["end_date"])
        cells = [Cell(la, lo) for la, lo in zip(lats, lons)]
        data = SyntheticSource.generate(cells, start, end)
        items = []
        for c in cells:
            d = data[c.key]
            items.append({
                "latitude": c.lat, "longitude": c.lon,
                "daily_units": {"time": "iso8601", "temperature_2m_max": "°C", "temperature_2m_min": "°C", "precipitation_sum": "mm"},
                "daily": {"time": d["dates"], "temperature_2m_max": d["tmax"], "temperature_2m_min": d["tmin"], "precipitation_sum": d["precip"]},
            })
        return httpx.Response(200, json=items if len(items) > 1 else items[0])

    def archive_calls(self) -> int:
        return sum(1 for r in self.calls if "archive" in str(r.url))


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    async def instant(*a, **k):
        return None
    monkeypatch.setattr(UpstreamClient, "_sleep", staticmethod(instant))
    limiter.reset()
    yield


@pytest.fixture
def fake_api():
    return FakeOpenMeteo()


@pytest.fixture
def client(fake_api):
    cfg = dataclasses.replace(settings, mongodb_uri="memory://", data_source="open-meteo")
    app = create_app(cfg, upstream_transport=httpx.MockTransport(fake_api))
    with TestClient(app) as c:
        yield c
