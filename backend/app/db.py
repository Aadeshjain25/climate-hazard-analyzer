"""MongoDB connection + index setup.

Why MongoDB (the brief asks for NoSQL)?
  * Our two main records are naturally documents: a year of daily arrays for one grid
    cell, and a finished analysis (nested JSON returned as-is to the client).
  * TTL indexes give cache expiry for free (no cron job).
  * MongoDB Atlas has a free tier, so the deployed demo costs nothing.

MONGODB_URI=memory:// swaps in mongomock (in-process) so the app runs with zero
infrastructure for local development and tests.
"""
from __future__ import annotations

import logging

from .config import Settings

log = logging.getLogger(__name__)


def create_client(settings: Settings):
    if settings.mongodb_uri.startswith("memory://"):
        from mongomock_motor import AsyncMongoMockClient

        log.warning("Using in-memory MongoDB (mongomock). Data is lost on restart.")
        return AsyncMongoMockClient()
    from pymongo import AsyncMongoClient

    return AsyncMongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=8000, appname="climate-hazard-analyzer")


async def ensure_indexes(db, settings: Settings) -> None:
    # Expire finished analyses (results depend on algorithm version + parameters).
    await db["analyses"].create_index("created_at", expireAfterSeconds=settings.analysis_cache_ttl_days * 86400)
    await db["geocode_cache"].create_index("created_at", expireAfterSeconds=settings.geocode_cache_ttl_days * 86400)
    # weather_years is keyed by _id = source|cell|year (already unique + indexed).
    # Secondary index for ops queries like "what do we hold for this cell?"
    await db["weather_years"].create_index([("cell", 1), ("year", 1)])
