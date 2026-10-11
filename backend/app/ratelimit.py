"""Per-client rate limiting (slowapi = limits library + FastAPI integration).

Client identity = IP address. Behind a reverse proxy the socket peer is the proxy,
so we read X-Forwarded-For - but ONLY the entry our own proxy appended. The left
side of that header is attacker-controlled (anyone can send "X-Forwarded-For: 1.2.3.4"),
so trusting the first entry would let a client dodge the limiter by rotating fake IPs.
"""
from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request

from .config import settings


def client_ip(request: Request) -> str:
    hops = settings.trusted_proxy_hops
    if hops > 0:
        xff = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return request.client.host if request.client else "unknown"


# In-memory storage is per-process. For several instances, point storage_uri at Redis
# (e.g. "redis://...") so all instances share one counter.
limiter = Limiter(key_func=client_ip, default_limits=[settings.rate_limit_default], headers_enabled=True)
