"""Safe access to third-party HTTP APIs.

Every outbound call goes through `UpstreamClient.get_json`, which gives us:
  * a bounded concurrency semaphore  -> we never hammer a free public API
  * hard timeouts                    -> a slow upstream cannot pin our workers
  * retries with exponential backoff + jitter, honouring Retry-After on 429
  * only idempotent GETs with params passed as a dict (httpx encodes them, so user
    input can never be spliced into the URL/path)
  * a small, typed error surface (UpstreamError) that the API maps to 502/503
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class UpstreamError(Exception):
    def __init__(self, message: str, status: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class UpstreamClient:
    def __init__(
        self,
        user_agent: str,
        max_concurrency: int = 2,
        max_retries: int = 3,
        timeout_s: float = 45.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._sem = asyncio.Semaphore(max_concurrency)
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_s, connect=10.0),
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            follow_redirects=False,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_json(self, url: str, params: dict[str, Any]) -> Any:
        attempt = 0
        while True:
            attempt += 1
            try:
                async with self._sem:
                    resp = await self._client.get(url, params=params)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt > self._max_retries:
                    raise UpstreamError(f"Upstream unreachable: {type(exc).__name__}", retryable=True) from exc
                await self._sleep(attempt)
                continue

            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError as exc:
                    raise UpstreamError("Upstream returned invalid JSON", status=200) from exc

            if resp.status_code in RETRYABLE_STATUS and attempt <= self._max_retries:
                await self._sleep(attempt, retry_after=resp.headers.get("Retry-After"))
                continue

            # Non-retryable (4xx) or retries exhausted. Do not echo the upstream body to clients.
            log.warning("Upstream %s returned %s: %s", url, resp.status_code, resp.text[:300])
            raise UpstreamError(
                f"Upstream returned HTTP {resp.status_code}",
                status=resp.status_code,
                retryable=resp.status_code in RETRYABLE_STATUS,
            )

    @staticmethod
    async def _sleep(attempt: int, retry_after: str | None = None) -> None:
        delay = min(2 ** (attempt - 1), 16) + random.uniform(0, 0.5)
        if retry_after:
            try:
                delay = max(delay, min(float(retry_after), 60.0))
            except ValueError:
                pass
        await asyncio.sleep(delay)
