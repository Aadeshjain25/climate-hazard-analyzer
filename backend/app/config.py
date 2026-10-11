"""Application settings, read once from environment variables.

Kept dependency-free on purpose (no pydantic-settings) so the config surface is
obvious: every knob the app has is listed here with its default.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

try:  # load backend/.env for local development; real env vars always win
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # --- storage -----------------------------------------------------------
    # "memory://" uses an in-process mongomock database (local dev / tests only).
    mongodb_uri: str = field(default_factory=lambda: _env("MONGODB_URI", "memory://"))
    mongodb_db: str = field(default_factory=lambda: _env("MONGODB_DB", "climate_hazards"))
    analysis_cache_ttl_days: int = field(default_factory=lambda: _env_int("ANALYSIS_CACHE_TTL_DAYS", 7))
    geocode_cache_ttl_days: int = field(default_factory=lambda: _env_int("GEOCODE_CACHE_TTL_DAYS", 30))

    # --- data source ---------------------------------------------------------
    # "open-meteo" (real ERA5 reanalysis) or "synthetic" (offline demo, clearly labelled in the UI)
    data_source: str = field(default_factory=lambda: _env("DATA_SOURCE", "open-meteo"))
    open_meteo_archive_url: str = field(
        default_factory=lambda: _env("OPEN_METEO_ARCHIVE_URL", "https://archive-api.open-meteo.com/v1/archive")
    )
    open_meteo_geocode_url: str = field(
        default_factory=lambda: _env("OPEN_METEO_GEOCODE_URL", "https://geocoding-api.open-meteo.com/v1/search")
    )
    nominatim_url: str = field(
        default_factory=lambda: _env("NOMINATIM_URL", "https://nominatim.openstreetmap.org/search")
    )
    contact_email: str = field(default_factory=lambda: _env("CONTACT_EMAIL", "dev@example.com"))
    upstream_max_concurrency: int = field(default_factory=lambda: _env_int("UPSTREAM_MAX_CONCURRENCY", 2))
    upstream_max_retries: int = field(default_factory=lambda: _env_int("UPSTREAM_MAX_RETRIES", 3))
    upstream_timeout_s: int = field(default_factory=lambda: _env_int("UPSTREAM_TIMEOUT_S", 45))
    # Years per upstream request. Smaller chunks = smaller payloads + partial progress is cached.
    fetch_chunk_years: int = field(default_factory=lambda: _env_int("FETCH_CHUNK_YEARS", 20))

    # --- input limits ------------------------------------------------------
    min_year: int = 1940  # ERA5 starts 1940
    max_span_years: int = field(default_factory=lambda: _env_int("MAX_SPAN_YEARS", 86))
    min_span_years: int = 10  # fewer than 10 points makes a trend test meaningless
    max_bbox_deg: float = 10.0
    max_grid_per_axis: int = field(default_factory=lambda: _env_int("MAX_GRID_PER_AXIS", 3))

    # --- http / security ---------------------------------------------------
    cors_origins: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            o.strip()
            for o in _env("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
            if o.strip()
        )
    )
    # Number of reverse proxies in front of the app (Render/Railway/Cloud Run = 1).
    # 0 = use the socket peer address and ignore X-Forwarded-For entirely.
    trusted_proxy_hops: int = field(default_factory=lambda: _env_int("TRUSTED_PROXY_HOPS", 0))
    analysis_timeout_s: int = field(default_factory=lambda: _env_int("ANALYSIS_TIMEOUT_S", 120))
    debug: bool = field(default_factory=lambda: _env_bool("DEBUG", False))
    rate_limit_analyze: str = field(default_factory=lambda: _env("RATE_LIMIT_ANALYZE", "20/minute"))
    rate_limit_export: str = field(default_factory=lambda: _env("RATE_LIMIT_EXPORT", "10/minute"))
    rate_limit_geocode: str = field(default_factory=lambda: _env("RATE_LIMIT_GEOCODE", "30/minute"))
    rate_limit_default: str = field(default_factory=lambda: _env("RATE_LIMIT_DEFAULT", "120/minute"))

    @property
    def max_year(self) -> int:
        """Last *complete* calendar year. Partial years would bias annual counts low."""
        return date.today().year - 1


settings = Settings()

# Bump whenever detection / cleaning logic changes so cached analyses are invalidated.
ALGO_VERSION = "1.0.0"
