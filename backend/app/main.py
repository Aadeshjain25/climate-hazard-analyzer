"""FastAPI application factory."""
from __future__ import annotations

import inspect
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from .config import Settings, settings
from .db import create_client, ensure_indexes
from .ratelimit import limiter
from .routers.api import router
from .services.analysis import AnalysisError, AnalysisService
from .services.geocode import Geocoder, OfflineGeocoder
from .services.sources import OpenMeteoSource, SyntheticSource
from .services.upstream import UpstreamClient, UpstreamError
from .services.weather_store import WeatherStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def create_app(cfg: Settings = settings, upstream_transport=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        client = create_client(cfg)
        db = client[cfg.mongodb_db]
        await ensure_indexes(db, cfg)
        upstream = UpstreamClient(
            user_agent=f"ClimateHazardTrendAnalyzer/1.0 (+{cfg.contact_email})",
            max_concurrency=cfg.upstream_max_concurrency,
            max_retries=cfg.upstream_max_retries,
            timeout_s=cfg.upstream_timeout_s,
            transport=upstream_transport,
        )
        if cfg.data_source == "synthetic":
            source = SyntheticSource()
            geocoder = OfflineGeocoder()
        else:
            source = OpenMeteoSource(upstream, cfg.open_meteo_archive_url)
            geocoder = Geocoder(db, upstream, cfg.nominatim_url, cfg.open_meteo_geocode_url, cfg.max_bbox_deg)
        store = WeatherStore(db, source, cfg.fetch_chunk_years)
        app.state.db = db
        app.state.source_name = source.name
        app.state.geocoder = geocoder
        app.state.analysis = AnalysisService(db, store, source.name, cfg.analysis_cache_ttl_days, cfg.max_grid_per_axis)
        log.info("Started with data source=%s", source.name)
        try:
            yield
        finally:
            await upstream.aclose()
            closed = client.close()  # coroutine for pymongo's AsyncMongoClient, plain call for mongomock
            if inspect.isawaitable(closed):
                await closed

    app = FastAPI(
        title="Climate Hazard Trend Analyzer API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cfg.cors_origins),
        allow_methods=["GET"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition", "X-RateLimit-Remaining", "Retry-After"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
        return response

    @app.exception_handler(RateLimitExceeded)
    async def rate_limited(request: Request, exc: RateLimitExceeded):
        resp = JSONResponse({"detail": f"Too many requests ({exc.detail}). Please slow down."}, status_code=429)
        resp.headers["Retry-After"] = "60"
        return resp

    @app.exception_handler(UpstreamError)
    async def upstream_failed(request: Request, exc: UpstreamError):
        log.warning("Upstream error: %s", exc)
        status = 503 if exc.retryable or exc.status in (429, None) else 502
        return JSONResponse(
            {"detail": "The weather data provider is unavailable or rate-limited right now. Please retry in a minute."},
            status_code=status,
            headers={"Retry-After": "60"},
        )

    @app.exception_handler(AnalysisError)
    async def analysis_failed(request: Request, exc: AnalysisError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Short, user-readable messages; never echo the raw input back.
        msgs = []
        for e in exc.errors():
            loc = ".".join(str(x) for x in e.get("loc", []) if x not in ("query",))
            msgs.append(f"{loc}: {e.get('msg')}")
        return JSONResponse({"detail": "; ".join(msgs)}, status_code=422)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("Unhandled error on %s", request.url.path)
        return JSONResponse({"detail": "Internal server error."}, status_code=500)

    app.include_router(router)
    return app


app = create_app()
