"""A small, polite HTTP client shared by the network-facing agents.

Responsibilities:
  * client-side rate limiting (NCBI bans clients that hammer the API),
  * automatic retries with backoff on transient failures,
  * a hard *dry-run* switch so the whole pipeline can run offline.

Keeping all network access behind this single object means there is exactly
one place that talks to the outside world -- easy to mock in tests and easy to
reason about for reproducibility.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import requests

from .config import NCBIConfig

log = logging.getLogger(__name__)


class DryRunError(RuntimeError):
    """Raised when a network call is attempted while dry-run is enabled."""


class RateLimiter:
    """Simple monotonic-clock rate limiter (no external deps)."""

    def __init__(self, requests_per_second: float) -> None:
        self._min_interval = 1.0 / requests_per_second
        self._last = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last = time.monotonic()


class HTTPClient:
    """Thin wrapper over :mod:`requests` with rate limiting + retries."""

    def __init__(self, ncbi: NCBIConfig, *, dry_run: bool = False) -> None:
        self.ncbi = ncbi
        self.dry_run = dry_run
        self._limiter = RateLimiter(ncbi.requests_per_second)
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": f"{ncbi.tool} (+{ncbi.email})"})

    def _identity_params(self) -> dict[str, str]:
        params = {"tool": self.ncbi.tool, "email": self.ncbi.email}
        if self.ncbi.api_key:
            params["api_key"] = self.ncbi.api_key
        return params

    def get(
        self,
        url: str,
        params: Optional[dict] = None,
        *,
        add_identity: bool = True,
    ) -> requests.Response:
        """Perform a rate-limited GET with retries.

        Raises :class:`DryRunError` if dry-run is on, so callers must provide a
        cached/offline path instead of hitting the network.
        """
        if self.dry_run:
            raise DryRunError(f"dry-run: refusing network GET {url}")

        merged = dict(params or {})
        if add_identity:
            merged.update(self._identity_params())

        last_exc: Optional[Exception] = None
        for attempt in range(1, self.ncbi.max_retries + 1):
            self._limiter.wait()
            try:
                resp = self._session.get(
                    url, params=merged, timeout=self.ncbi.timeout_seconds
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc  # network-level: transient, retry
            else:
                # Only 429 and 5xx are worth retrying; other 4xx (e.g. 404)
                # are permanent -- fail fast instead of hammering the server.
                if resp.status_code != 429 and not 500 <= resp.status_code < 600:
                    resp.raise_for_status()
                    return resp
                last_exc = requests.HTTPError(f"transient {resp.status_code}")

            backoff = min(2 ** attempt, 30)
            log.warning(
                "GET %s failed (attempt %d/%d): %s; retrying in %ds",
                url, attempt, self.ncbi.max_retries, last_exc, backoff,
            )
            time.sleep(backoff if attempt < self.ncbi.max_retries else 0)
        raise RuntimeError(f"GET {url} failed after {self.ncbi.max_retries} attempts") \
            from last_exc

    def download(self, url: str, dest, *, add_identity: bool = False) -> None:
        """Stream a binary asset to ``dest`` (a path-like)."""
        if self.dry_run:
            raise DryRunError(f"dry-run: refusing download {url}")
        resp = self.get(url, add_identity=add_identity)
        from pathlib import Path

        Path(dest).write_bytes(resp.content)
