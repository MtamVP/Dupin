"""Base connector with SQLite HTTP caching, per-domain rate limiting, and soft-404 detection."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.core.schemas import FeatureClaim, utc_now

SOFT_404_PATTERNS: tuple[str, ...] = (
    "page not found",
    "user not found",
    "profile not found",
    "account suspended",
    "this account doesn't exist",
    "404 not found",
    "không tìm thấy trang",
    "tài khoản không tồn tại",
)


class CollectedDocument(BaseModel):
    """Normalized output returned by any public data connector."""

    source_type: str
    url: str
    title: str = ""
    content: str = ""
    claims: list[FeatureClaim] = Field(default_factory=list)
    outbound_links: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_soft_404: bool = False
    cached: bool = False


def detect_soft_404(title: str, content: str, status_code: int = 200) -> bool:
    """Detect false-positive 200 OK pages that actually report missing profiles (Maigret-style)."""
    if status_code >= 400:
        return True
    combined = f"{title} {content[:1500]}".lower()
    if len(content.strip()) < 1200:
        for pat in SOFT_404_PATTERNS:
            if pat in combined:
                return True
    return False


class BaseConnector(ABC):
    """Abstract public OSINT connector with persistent SQLite cache and polite rate-limiting."""

    _domain_last_call: dict[str, float] = {}
    _min_interval_sec: float = 0.5

    def __init__(self, db_path: str | Path, timeout: float = 15.0) -> None:
        self.db_path = Path(db_path)
        self.timeout = timeout

    @staticmethod
    def _url_hash(url: str) -> str:
        return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()

    def _get_cached(self, url: str, ttl_seconds: int = 300) -> Optional[tuple[str, int]]:
        if not self.db_path.exists():
            return None
        from datetime import datetime

        h = self._url_hash(url)
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        try:
            conn.execute("PRAGMA busy_timeout = 10000;")
            row = conn.execute(
                "SELECT content, status_code, fetched_at FROM http_cache WHERE url_hash = ?", (h,)
            ).fetchone()
        finally:
            conn.close()
        if not row:
            return None
        try:
            fetched_dt = datetime.fromisoformat(row[2])
            if (utc_now() - fetched_dt).total_seconds() > ttl_seconds:
                return None
        except Exception:
            pass
        return (row[0], int(row[1]))

    def _set_cached(self, url: str, content: str, status_code: int) -> None:
        if not self.db_path.exists():
            return
        h = self._url_hash(url)
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        try:
            conn.execute("PRAGMA busy_timeout = 10000;")
            with conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO http_cache (url_hash, url, content, status_code, fetched_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (h, url, content, status_code, utc_now().isoformat()),
                )
        finally:
            conn.close()

    async def _respect_rate_limit(self, url: str) -> None:
        domain = urlparse(url).netloc.lower() or "default"
        now = time.monotonic()
        last = self._domain_last_call.get(domain, 0.0)
        wait = self._min_interval_sec - (now - last)
        if wait > 0:
            await asyncio.sleep(wait)
        self._domain_last_call[domain] = time.monotonic()

    async def cached_get(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        use_cache: bool = True,
        client: Optional[httpx.AsyncClient] = None,
    ) -> tuple[str, int, bool]:
        """Perform an HTTP GET with SQLite caching and per-domain rate limiting."""
        if use_cache:
            cached = self._get_cached(url)
            if cached is not None:
                return cached[0], cached[1], True

        await self._respect_rate_limit(url)
        req_headers = {"User-Agent": "StalkerPP-Academic-OSINT/0.2 (+local-first)"}
        if headers:
            req_headers.update(headers)

        if client is not None:
            resp = await client.get(url, headers=req_headers, follow_redirects=True)
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as temp_client:
                resp = await temp_client.get(url, headers=req_headers, follow_redirects=True)

        text = resp.text
        if use_cache and resp.status_code == 200:
            self._set_cached(url, text, resp.status_code)
        return text, resp.status_code, False

    @abstractmethod
    async def collect(self, target: str, **kwargs: Any) -> CollectedDocument:
        """Collect public OSINT data for the given target identifier or URL."""
