"""Public Web Page Fetcher, SpiderFoot-style Rule Extractor, and Manual Snippet Ingestor."""

from __future__ import annotations

import html
import re
from typing import Any, Optional

import httpx

from app.connectors.base import BaseConnector, CollectedDocument, detect_soft_404
from app.core.schemas import FeatureCategory, FeatureClaim

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
SOCIAL_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:github\.com|gitlab\.com|linkedin\.com/in|facebook\.com|x\.com|twitter\.com|t\.me)/[A-Za-z0-9_.-]+",
    re.IGNORECASE,
)
BIRTH_YEAR_RE = re.compile(r"\b(?:sinh năm|sn|born in|class of|khóa)\s*(19[7-9]\d|20[0-1]\d)\b", re.IGNORECASE)


def extract_rule_based_claims(text: str, source_url: str) -> tuple[list[FeatureClaim], list[str]]:
    """Fast SpiderFoot-style deterministic rule extraction before LLM processing."""
    claims: list[FeatureClaim] = []
    outbound: list[str] = []

    for email in sorted(set(EMAIL_RE.findall(text))):
        claims.append(
            FeatureClaim(
                category=FeatureCategory.TECHNICAL_ARTIFACT,
                key="email",
                value=email.lower(),
                confidence=0.9,
                source_url=source_url,
                evidence_quote=f"Extracted email: {email}",
            )
        )

    for s_url in sorted(set(SOCIAL_URL_RE.findall(text))):
        outbound.append(s_url)
        claims.append(
            FeatureClaim(
                category=FeatureCategory.IDENTITY,
                key="linked_profile_url",
                value=s_url,
                confidence=0.85,
                source_url=source_url,
                evidence_quote=f"Referenced social URL: {s_url}",
            )
        )

    for match in BIRTH_YEAR_RE.finditer(text):
        year = int(match.group(1))
        quote = match.group(0).strip()
        claims.append(
            FeatureClaim(
                category=FeatureCategory.SPATIOTEMPORAL,
                key="associated_year",
                value=year,
                confidence=0.75,
                source_url=source_url,
                evidence_quote=quote,
            )
        )

    return claims, outbound


def clean_html_to_text(raw_html: str) -> tuple[str, str, dict[str, str]]:
    """Strip scripts/styles, extract title & OpenGraph metadata, and return clean text."""
    title_match = re.search(r"<title[^>]*>(.*?)</title>", raw_html, re.IGNORECASE | re.DOTALL)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""

    meta: dict[str, str] = {}
    for prop, content in re.findall(
        r'<meta[^>]+(?:property|name)=["\']([^"\']+)["\'][^>]+content=["\']([^"\']+)["\']',
        raw_html,
        re.IGNORECASE,
    ):
        if prop.lower() in ("description", "og:title", "og:description", "og:site_name", "author"):
            meta[prop.lower()] = html.unescape(content).strip()

    cleaned = re.sub(
        r"<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>",
        " ",
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return title, cleaned, meta


class PublicWebFetcher(BaseConnector):
    """Fetches a public web URL, cleans HTML, detects soft-404, and extracts rule-based claims."""

    async def collect(
        self,
        target: str,
        client: Optional[httpx.AsyncClient] = None,
        **kwargs: Any,
    ) -> CollectedDocument:
        url = target.strip()
        raw_html, status, cached = await self.cached_get(url, client=client)
        title, clean_text, meta = clean_html_to_text(raw_html)
        soft_404 = detect_soft_404(title, clean_text, status_code=status)

        claims: list[FeatureClaim] = []
        outbound: list[str] = []
        if not soft_404:
            claims, outbound = extract_rule_based_claims(f"{raw_html}\n{clean_text}", url)

        return CollectedDocument(
            source_type="webpage",
            url=url,
            title=title or meta.get("og:title", url),
            content=clean_text[:8000],
            claims=claims,
            outbound_links=outbound,
            metadata=meta,
            is_soft_404=soft_404,
            cached=cached,
        )


def ingest_manual_snippet(
    text: str,
    source_url: str = "manual://human-analyst",
    title: str = "Human-Assisted Snippet",
) -> CollectedDocument:
    """Human-in-the-loop connector for analyst-pasted public snippets or bios."""
    claims, outbound = extract_rule_based_claims(text, source_url)
    return CollectedDocument(
        source_type="manual_snippet",
        url=source_url,
        title=title,
        content=text.strip(),
        claims=claims,
        outbound_links=outbound,
        metadata={"ingested_by": "human_in_the_loop"},
    )
