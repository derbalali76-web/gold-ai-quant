"""Polite HTTP client: timeouts, retries with exponential backoff, per-host rate limiting, attribution.

The transport is injectable so every adapter can be contract-tested offline with recorded payloads.
Secrets (API keys) are redacted from anything that is logged or stored.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx

USER_AGENT = "GoldAIQuant/0.3 (personal research; contact: local user)"


@dataclass
class Response:
    status: int
    text: str
    url: str
    elapsed_ms: float
    content: bytes = b""


Transport = Callable[[str, dict, float], Response]


def _httpx_transport(url: str, params: dict, timeout: float) -> Response:
    t0 = time.monotonic()
    r = httpx.get(url, params=params, timeout=timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True)
    return Response(r.status_code, r.text, str(r.url), (time.monotonic() - t0) * 1000, r.content)


def redact(s: str) -> str:
    return re.sub(r"(apikey|api_key|token|key)=([^&\s]+)", r"\1=***", s, flags=re.I)


class HttpError(Exception):
    def __init__(self, msg: str, status: Optional[int] = None):
        super().__init__(redact(msg))
        self.status = status


@dataclass
class RateLimiter:
    """Simple sliding-window limiter: at most `calls` per `period` seconds."""
    calls: int
    period: float
    _stamps: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def acquire(self) -> None:
        with self._lock:
            now = self.clock()
            self._stamps = [s for s in self._stamps if now - s < self.period]
            if len(self._stamps) >= self.calls:
                wait = self.period - (now - self._stamps[0])
                if wait > 0:
                    self.sleep(wait)
                now = self.clock()
                self._stamps = [s for s in self._stamps if now - s < self.period]
            self._stamps.append(now)


class HttpClient:
    def __init__(self, transport: Transport | None = None, retries: int = 3, backoff: float = 1.0,
                 timeout: float = 15.0, limiter: RateLimiter | None = None, sleep=time.sleep):
        self.transport = transport or _httpx_transport
        self.retries, self.backoff, self.timeout = retries, backoff, timeout
        self.limiter = limiter
        self.sleep = sleep
        self.last_error: Optional[str] = None
        self.last_latency_ms: Optional[float] = None

    def get(self, url: str, params: dict | None = None) -> Response:
        params = params or {}
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            if self.limiter:
                self.limiter.acquire()
            try:
                r = self.transport(url, params, self.timeout)
            except Exception as exc:  # network failure
                last = HttpError(f"network error: {exc}")
            else:
                self.last_latency_ms = r.elapsed_ms
                if r.status == 200:
                    self.last_error = None
                    return r
                if r.status in (429, 500, 502, 503, 504):
                    last = HttpError(f"HTTP {r.status} from {r.url}", r.status)
                else:  # 4xx other than 429: do not retry
                    self.last_error = redact(f"HTTP {r.status} from {r.url}")
                    raise HttpError(self.last_error, r.status)
            if attempt < self.retries:
                self.sleep(self.backoff * (2 ** attempt))
        self.last_error = str(last)
        raise last  # type: ignore[misc]
