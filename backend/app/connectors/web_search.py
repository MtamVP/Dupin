"""Smart Boolean Search Dork Generator and Multi-Engine Live Public Search Connector (ddgs)."""

from __future__ import annotations

import asyncio
import html
import json
import re
from typing import Any, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from pydantic import BaseModel, Field

from app.connectors.base import BaseConnector, CollectedDocument
from app.core.normalizer import strip_vietnamese_accents


class DorkRequest(BaseModel):
    """Multi-dimensional seed clues to synthesize targeted search dorks."""

    full_name: str = Field(..., min_length=1)
    aliases: list[str] = Field(default_factory=list)
    organizations: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    target_sites: list[str] = Field(
        default_factory=lambda: ["github.com", "linkedin.com", "facebook.com"]
    )


def unwrap_search_url(raw_href: str) -> str:
    """Unwrap DuckDuckGo redirect links (`//duckduckgo.com/l/?uddg=...`) into clean target URLs."""
    href = html.unescape(raw_href).strip()
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        qs = parse_qs(parsed.query)
        if "uddg" in qs and qs["uddg"]:
            return unquote(qs["uddg"][0])
    return href


def generate_smart_dorks(req: DorkRequest) -> list[dict[str, str]]:
    """Synthesize high-entropy Boolean search dorks with Vietnamese variant & negative filtering."""
    raw_name = req.full_name.strip()
    no_accent = strip_vietnamese_accents(raw_name)

    name_terms = [f'"{raw_name}"']
    if no_accent.lower() != raw_name.lower():
        name_terms.append(f'"{no_accent}"')
    for alias in req.aliases[:2]:
        if alias.strip():
            name_terms.append(f'"{alias.strip()}"')

    name_clause = f"({' OR '.join(name_terms)})" if len(name_terms) > 1 else name_terms[0]
    neg_clause = " ".join(f'-"{neg.strip()}"' for neg in req.negative_keywords if neg.strip())

    dorks: list[dict[str, str]] = []

    if req.organizations:
        org_terms = [f'"{o.strip()}"' for o in req.organizations if o.strip()]
        org_clause = f"({' OR '.join(org_terms)})" if len(org_terms) > 1 else org_terms[0]
        q = f"{name_clause} {org_clause} {neg_clause}".strip()
        dorks.append({"strategy": "identity_org_anchor", "query": q})

    context_items = [x.strip() for x in (req.locations + req.keywords) if x.strip()]
    if context_items:
        ctx_clause = " ".join(f'"{c}"' for c in context_items[:3])
        q = f"{name_clause} {ctx_clause} {neg_clause}".strip()
        dorks.append({"strategy": "spatiotemporal_keyword_pivot", "query": q})

    anchor_hint = f'"{req.organizations[0].strip()}"' if req.organizations else ""
    for site in req.target_sites:
        clean_site = site.strip()
        if not clean_site:
            continue
        q = f"site:{clean_site} {name_clause} {anchor_hint} {neg_clause}".strip()
        q = re.sub(r"\s+", " ", q)
        dorks.append({"strategy": f"site_pivot:{clean_site}", "query": q})

    if not dorks:
        q = f"{name_clause} {neg_clause}".strip()
        dorks.append({"strategy": "broad_identity", "query": q})

    return dorks


def _simplify_boolean_query(query: str) -> str:
    """Convert strict nested Boolean dork into a clean metasearch query for higher recall."""
    # Remove OR clauses inside parentheses, keep first variant + other terms
    simplified = re.sub(r'\("([^"]+)"\s+OR\s+"[^"]+"\)', r"\1", query)
    simplified = re.sub(r'[()"]', " ", simplified)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    return simplified


def _ddgs_single_backend_sync(
    query: str,
    backend: str,
    max_results: int = 10,
    timeout: int = 6,
    region: str = "wt-wt",
) -> list[dict[str, str]]:
    """Query a single valid ddgs backend synchronously with bounded timeout & region."""
    from ddgs import DDGS

    try:
        raw_items = DDGS(timeout=timeout).text(
            query, region=region, max_results=max_results, backend=backend
        ) or []
    except Exception:
        raw_items = []
    results: list[dict[str, str]] = []
    for item in raw_items:
        href = str(item.get("href") or item.get("url") or "").strip()
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or item.get("snippet") or "").strip()
        if href.startswith(("http://", "https://")):
            results.append({"url": href, "title": title, "snippet": body})
    return results


def _ddgs_live_search_sync(query: str, max_results: int = 10, region: str = "wt-wt") -> list[dict[str, str]]:
    """Race fast valid ddgs backends (`yahoo`, `brave`, `duckduckgo`) IN PARALLEL with region hint.

    Uses ThreadPoolExecutor so slow/rate-limited engines never block Yahoo (1s) or Brave (0.4s),
    preserving deep-rank gold hits (#3-#8) for Layer 2 OuterGatekeeper inspection.
    """
    from concurrent.futures import ThreadPoolExecutor, wait

    def _race(
        q_str: str,
        backends: tuple[str, ...],
        per_backend_timeout: int,
        wall_timeout: float,
    ) -> list[dict[str, str]]:
        merged: list[dict[str, str]] = []
        seen: set[str] = set()
        pool = ThreadPoolExecutor(max_workers=len(backends))
        try:
            futs = [
                pool.submit(_ddgs_single_backend_sync, q_str, b, max_results, per_backend_timeout, region)
                for b in backends
            ]
            done, _ = wait(futs, timeout=wall_timeout)
            for fut in futs:
                if fut not in done:
                    continue
                try:
                    batch = fut.result()
                except Exception:
                    continue
                for item in batch:
                    norm = _normalize_result_url(item["url"])
                    if norm not in seen:
                        seen.add(norm)
                        merged.append(item)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return merged

    hits = _race(query, ("yahoo", "brave", "duckduckgo"), per_backend_timeout=6, wall_timeout=7.0)
    if not hits:
        simple_q = _simplify_boolean_query(query)
        if simple_q and simple_q != query:
            hits = _race(simple_q, ("yahoo", "duckduckgo"), per_backend_timeout=5, wall_timeout=6.0)
    return hits[: max_results * 2]


def _invoke_ddgs_compat(query: str, max_results: int, region: str) -> list[dict[str, str]]:
    """Invoke `_ddgs_live_search_sync` with region, staying compatible with 2-arg test mocks."""
    try:
        return _ddgs_live_search_sync(query, max_results, region=region)
    except TypeError:
        return _ddgs_live_search_sync(query, max_results)


def _enforce_site_constraint(query: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop off-domain fallback garbage when a query explicitly contains `site:<domain_or_path>`.

    Some search engines (especially Bing via SearXNG) ignore `site:` on 0-hit queries and return
    completely unrelated pages (e.g., gaming/dictionary sites). Enforcing the requested site filter
    prevents junk from polluting both results and `http_cache`.
    """
    site_matches = re.findall(r"(?:^|\s)site:([^\s)\"]+)", query, flags=re.IGNORECASE)
    if not site_matches:
        return items

    # Only enforce when the query is NOT an OR-union of multiple sites + filetype
    allowed_constraints = [s.lower().strip().rstrip("/") for s in site_matches if s.strip()]
    if not allowed_constraints:
        return items

    kept: list[dict[str, Any]] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        parsed = urlparse(url)
        host = parsed.netloc.lower().lstrip("www.")
        host_and_path = f"{host}{parsed.path.lower()}"
        matched = False
        for c in allowed_constraints:
            c_clean = c.lstrip("www.")
            if "/" in c_clean:
                c_host, c_path = c_clean.split("/", 1)
                if (host == c_host or host.endswith(f".{c_host}")) and f"/{c_path}" in parsed.path.lower():
                    matched = True
                    break
            else:
                if host == c_clean or host.endswith(f".{c_clean}") or c_clean in host_and_path:
                    matched = True
                    break
        if matched:
            kept.append(item)
    return kept


def _normalize_result_url(url: str) -> str:
    """Normalize a URL for cross-engine deduplication (lowercase host, strip fragment & trailing slash)."""
    parsed = urlparse(url.strip())
    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{scheme}://{netloc}{path}{query}"


def _is_malformed_result(item: dict[str, Any]) -> bool:
    """Reject broken/concatenated metasearch results (e.g., empty-host redirects or title mashups)."""
    url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    if not url.startswith(("http://", "https://")):
        return True
    parsed_u = urlparse(url)
    if not parsed_u.netloc or "." not in parsed_u.netloc:
        return True
    if len(title) > 180:
        return True
    # Detect ddgs title-mashup where another result's domain is glued directly after '...'
    m_glued = re.search(r"\.\.\.([a-z0-9.-]+\.[a-z]{2,6})$", title.lower())
    if m_glued:
        glued_host = m_glued.group(1)
        actual_host = parsed_u.netloc.lower()
        if glued_host not in actual_host:
            return True
    return False


def merge_parallel_search_results(
    searxng_items: list[dict[str, Any]],
    ddgs_items: list[dict[str, Any]],
    max_results: int = 8,
) -> list[dict[str, Any]]:
    """Fuse SearXNG + ddgs results with URL deduplication and Consensus Ranking.

    URLs returned by BOTH SearXNG and ddgs receive the highest consensus score (3)
    and prefer SearXNG's structured title/snippet over ddgs's scraped text.
    """
    merged: dict[str, dict[str, Any]] = {}
    rank_counter = 0

    for item in searxng_items:
        if _is_malformed_result(item):
            continue
        norm_url = _normalize_result_url(item["url"])
        if norm_url in merged:
            continue
        sx_engines = item.get("engines") or []
        base_score = 2 if isinstance(sx_engines, list) and len(sx_engines) >= 2 else 1
        merged[norm_url] = {
            "url": item["url"],
            "title": str(item.get("title") or "").strip(),
            "snippet": str(item.get("snippet") or "").strip(),
            "sources": ["searxng"],
            "searxng_engines": list(sx_engines) if isinstance(sx_engines, list) else [],
            "consensus_score": base_score,
            "_source_priority": 0,  # Prefer SearXNG on tie
            "_rank": rank_counter,
        }
        rank_counter += 1

    for item in ddgs_items:
        if _is_malformed_result(item):
            continue
        norm_url = _normalize_result_url(item["url"])
        if norm_url in merged:
            existing = merged[norm_url]
            if "ddgs" not in existing["sources"]:
                existing["sources"].append("ddgs")
                existing["consensus_score"] = 3  # Confirmed by BOTH SearXNG & ddgs
            if not existing["snippet"] and item.get("snippet"):
                existing["snippet"] = str(item["snippet"]).strip()
            if not existing["title"] and item.get("title"):
                existing["title"] = str(item["title"]).strip()
        else:
            merged[norm_url] = {
                "url": item["url"],
                "title": str(item.get("title") or "").strip(),
                "snippet": str(item.get("snippet") or "").strip(),
                "sources": ["ddgs"],
                "searxng_engines": [],
                "consensus_score": 1,
                "_source_priority": 1,
                "_rank": rank_counter,
            }
            rank_counter += 1

    # Fair Consensus-First + Round-Robin Interleave so neither SearXNG nor ddgs
    # can crowd out unique hits from the other engine when slicing to max_results.
    both_hits = sorted(
        [r for r in merged.values() if int(r["consensus_score"]) >= 3],
        key=lambda r: int(r["_rank"]),
    )
    sx_only = sorted(
        [r for r in merged.values() if int(r["consensus_score"]) < 3 and r["_source_priority"] == 0],
        key=lambda r: (-int(r["consensus_score"]), int(r["_rank"])),
    )
    ddgs_only = sorted(
        [r for r in merged.values() if int(r["consensus_score"]) < 3 and r["_source_priority"] == 1],
        key=lambda r: int(r["_rank"]),
    )

    interleaved: list[dict[str, Any]] = list(both_hits)
    i = 0
    while i < len(sx_only) or i < len(ddgs_only):
        if i < len(sx_only):
            interleaved.append(sx_only[i])
        if i < len(ddgs_only):
            interleaved.append(ddgs_only[i])
        i += 1

    cleaned: list[dict[str, Any]] = []
    for r in interleaved[:max_results]:
        cleaned.append(
            {
                "url": r["url"],
                "title": r["title"],
                "snippet": r["snippet"],
                "sources": r["sources"],
                "searxng_engines": r["searxng_engines"],
                "consensus_score": r["consensus_score"],
            }
        )
    return cleaned


async def test_searxng_connection(
    base_url: str,
    timeout: float = 5.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Probe a local/self-hosted SearXNG instance and verify JSON API availability."""
    clean_base = base_url.strip().rstrip("/")
    if not clean_base:
        return {
            "reachable": False,
            "json_enabled": False,
            "base_url": "",
            "sample_count": 0,
            "engines": [],
            "error": "Chưa nhập URL SearXNG.",
        }

    async def _probe(c: httpx.AsyncClient) -> dict[str, Any]:
        resp = await c.get(
            f"{clean_base}/search",
            params={"q": "wikipedia", "format": "json"},
        )
        if resp.status_code == 403:
            return {
                "reachable": True,
                "json_enabled": False,
                "base_url": clean_base,
                "sample_count": 0,
                "engines": [],
                "error": "SearXNG đang chạy nhưng chưa bật format=json (HTTP 403). Hãy thêm 'json' vào search.formats trong searxng/settings.yml.",
            }
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "").lower()
        if "json" not in content_type:
            try:
                data = resp.json()
            except Exception:
                return {
                    "reachable": True,
                    "json_enabled": False,
                    "base_url": clean_base,
                    "sample_count": 0,
                    "engines": [],
                    "error": "SearXNG trả về HTML thay vì JSON. Hãy bật 'json' trong search.formats của settings.yml.",
                }
        else:
            data = resp.json()

        items = data.get("results", []) or []
        engines = sorted(
            {str(e) for it in items for e in (it.get("engines") or []) if e}
        )
        return {
            "reachable": True,
            "json_enabled": True,
            "base_url": clean_base,
            "sample_count": len(items),
            "engines": engines[:10],
            "error": "",
        }

    try:
        if client is not None:
            return await _probe(client)
        async with httpx.AsyncClient(timeout=timeout) as c:
            return await _probe(c)
    except Exception as exc:
        return {
            "reachable": False,
            "json_enabled": False,
            "base_url": clean_base,
            "sample_count": 0,
            "engines": [],
            "error": str(exc),
        }


_VN_DIACRITIC_RE = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
    re.IGNORECASE,
)


def infer_query_region(query: str, explicit_region: str = "auto") -> str:
    """Resolve search region ('vn' vs 'global') automatically from query text when set to 'auto'."""
    if explicit_region in ("vn", "global"):
        return explicit_region
    low = (query or "").lower()
    if _VN_DIACRITIC_RE.search(low) or ".vn" in low or any(
        tok in low for tok in ("tphcm", "hcmut", "ueh", "hust", "ptit", "thpt", "mssv", "danh sach")
    ):
        return "vn"
    return "global"


def _sanitize_query_for_serper_free(query: str) -> str:
    """Rewrite Google Dork operators into a clean query accepted by Serper.dev Free accounts.

    Serper Free rejects `site:`, `filetype:`, `inurl:`, `OR`, and 2+ quoted phrases with HTTP 400
    ('Query pattern not allowed for free accounts.'), while allowing a single exact quoted phrase
    (e.g., `"Full Name" scribd` or `"2550999" Bách Khoa`).
    """
    q = (query or "").strip()
    if not q:
        return ""
    # Preserve the first quoted phrase (typically exact target name or exact ID) so Google doesn't fuzzy-drift
    quoted_phrases = re.findall(r'"([^"]+)"', q)
    first_quoted = quoted_phrases[0].strip() if quoted_phrases else ""
    if first_quoted:
        q = q.replace(f'"{first_quoted}"', " __KEEP_Q0__ ", 1)

    # site:studocu.com/vn/document -> studocu.com ; site:edu.vn -> edu.vn
    q = re.sub(
        r"\bsite:([a-zA-Z0-9.-]+)(?:/[^\s)]*)?",
        lambda m: m.group(1),
        q,
        flags=re.IGNORECASE,
    )
    # filetype:pdf -> pdf
    q = re.sub(r"\b(?:filetype|ext):([a-zA-Z0-9]+)\b", r"\1", q, flags=re.IGNORECASE)
    # Strip inurl:/intitle:/intext: prefixes while keeping their value
    q = re.sub(r"\b(?:inurl|intitle|intext|allintitle|allinurl):", "", q, flags=re.IGNORECASE)
    # Remove remaining quotes, parentheses, and standalone boolean OR/AND
    q = q.replace('"', " ").replace("(", " ").replace(")", " ")
    q = re.sub(r"\b(?:OR|AND)\b", " ", q)
    # Deduplicate tokens while preserving order
    seen: set[str] = set()
    tokens: list[str] = []
    for tok in q.split():
        if tok == "__KEEP_Q0__":
            tokens.append(f'"{first_quoted}"')
            seen.add(first_quoted.lower())
            continue
        low = tok.lower()
        if low not in seen:
            seen.add(low)
            tokens.append(tok)
    return " ".join(tokens).strip()


class WebSearchConnector(BaseConnector):
    """Live multi-engine public web search: Serper (Google) or Parallel (SearXNG Local + ddgs) with Consensus Fusion."""

    DDG_HTML_URL = "https://html.duckduckgo.com/html/"

    async def _search_serper(
        self, query: str, api_key: str, max_results: int = 8, region: str = "global"
    ) -> list[dict[str, Any]]:
        """Query Google Search via Serper.dev JSON API using rotated key."""
        body: dict[str, Any] = {"q": query, "num": max_results}
        if region == "vn":
            body["gl"] = "vn"
            body["hl"] = "vi"
        else:
            body["hl"] = "en"
        async with httpx.AsyncClient(timeout=self.timeout) as c:
            resp = await c.post(
                "https://google.serper.dev/search",
                headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            organic = resp.json().get("organic", [])
            return [
                {
                    "url": str(item.get("link", "")),
                    "title": str(item.get("title", "")),
                    "snippet": str(item.get("snippet", "")),
                    "sources": ["serper"],
                    "consensus_score": 2,
                }
                for item in organic
                if item.get("link")
            ]

    async def _search_searxng(
        self, query: str, base_url: str, max_results: int = 8, region: str = "global"
    ) -> list[dict[str, Any]]:
        """Query self-hosted local SearXNG JSON API (aggregates Google, Bing, Brave, DDG locally)."""
        clean_base = base_url.rstrip("/")
        # Tight timeout so offline local SearXNG never stalls parallel ddgs results
        sx_timeout = min(float(self.timeout), 6.0)
        sx_lang = "vi-VN" if region == "vn" else "all"
        async with httpx.AsyncClient(timeout=sx_timeout) as c:
            resp = await c.get(
                f"{clean_base}/search",
                params={"q": query, "format": "json", "language": sx_lang},
            )
            resp.raise_for_status()
            items = resp.json().get("results", [])[: max_results * 2]
            return [
                {
                    "url": str(item.get("url", "")),
                    "title": str(item.get("title", "")),
                    "snippet": str(item.get("content", "")),
                    "engines": item.get("engines") or [],
                }
                for item in items
                if item.get("url")
            ]

    def _parse_ddg_html(self, body: str) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        link_matches = re.findall(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        snippet_matches = re.findall(
            r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            body,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for idx, (href, raw_title) in enumerate(link_matches[:10]):
            clean_url = unwrap_search_url(href)
            clean_title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            raw_snip = snippet_matches[idx] if idx < len(snippet_matches) else ""
            clean_snip = html.unescape(re.sub(r"<[^>]+>", "", raw_snip)).strip()
            if clean_url.startswith(("http://", "https://")):
                results.append({"url": clean_url, "title": clean_title, "snippet": clean_snip})
        return results

    async def collect(
        self,
        target: str,
        client: Optional[httpx.AsyncClient] = None,
        max_results: int = 8,
        region: str = "auto",
        **kwargs: Any,
    ) -> CollectedDocument:
        query = target.strip()
        resolved_region = infer_query_region(query, region)
        engines_used: list[str] = []
        searxng_active = False

        # Mock HTTP client path (used by deterministic unit tests)
        if client is not None:
            cache_key_url = f"ddgs://search?q={quote_plus(query)}"
            url = f"{self.DDG_HTML_URL}?q={quote_plus(query)}"
            body, status, cached = await self.cached_get(url, client=client)
            results: list[dict[str, Any]] = self._parse_ddg_html(body)
            engines_used = ["mock_ddg"]
        else:
            from app.core.key_pool import IntegrationStore

            int_store = IntegrationStore(self.db_path)
            local_cfg = int_store.get_local_config()
            sx_url = local_cfg.searxng_url.strip()
            cache_key_url = f"search://multi?q={quote_plus(query)}&sx={1 if sx_url else 0}&reg={resolved_region}"

            cached_row = self._get_cached(cache_key_url)
            if cached_row is not None and cached_row[1] == 200:
                results = json.loads(cached_row[0])
                status, cached = 200, True
                engines_used = ["cache"]
            else:
                results = []

                # Priority 1: Rotated Serper.dev Google Search key if configured
                serper_key = int_store.acquire_key("serper")
                if serper_key:
                    try:
                        results = await self._search_serper(
                            query, serper_key["api_key"], max_results, region=resolved_region
                        )
                        if results:
                            engines_used.append("serper")
                    except httpx.HTTPStatusError as exc:
                        # Serper.dev Free accounts reject dork operators (site:, filetype:, multiple quotes)
                        # with HTTP 400. Automatically rewrite into a clean natural Google query and retry once
                        # without penalizing the key's error_count!
                        if exc.response.status_code == 400:
                            clean_serper_q = _sanitize_query_for_serper_free(query)
                            if clean_serper_q and clean_serper_q != query:
                                try:
                                    results = await self._search_serper(
                                        clean_serper_q,
                                        serper_key["api_key"],
                                        max_results,
                                        region=resolved_region,
                                    )
                                    if results:
                                        engines_used.append("serper")
                                except httpx.HTTPStatusError as exc2:
                                    int_store.report_key_error(
                                        serper_key["id"],
                                        is_rate_limit=(exc2.response.status_code == 429),
                                    )
                                except Exception:
                                    int_store.report_key_error(serper_key["id"], is_rate_limit=False)
                            else:
                                int_store.report_key_error(serper_key["id"], is_rate_limit=False)
                        else:
                            int_store.report_key_error(
                                serper_key["id"], is_rate_limit=(exc.response.status_code == 429)
                            )
                    except Exception:
                        int_store.report_key_error(serper_key["id"], is_rate_limit=False)

                # Priority 2: Parallel Local SearXNG + Parallel-Race ddgs (yahoo || brave || ddg)
                ddgs_timed_out = False
                ddgs_reg = "vn-vi" if resolved_region == "vn" else "wt-wt"
                if not results:
                    if sx_url:
                        sx_raw, ddgs_raw = await asyncio.gather(
                            asyncio.wait_for(
                                self._search_searxng(query, sx_url, max_results, region=resolved_region),
                                timeout=6.5,
                            ),
                            asyncio.wait_for(
                                asyncio.to_thread(_invoke_ddgs_compat, query, max_results, ddgs_reg),
                                timeout=14.0,
                            ),
                            return_exceptions=True,
                        )
                        if isinstance(ddgs_raw, (asyncio.TimeoutError, TimeoutError)):
                            ddgs_timed_out = True
                        sx_items: list[dict[str, Any]] = (
                            _enforce_site_constraint(query, sx_raw) if isinstance(sx_raw, list) else []
                        )
                        ddgs_items: list[dict[str, Any]] = (
                            _enforce_site_constraint(query, ddgs_raw) if isinstance(ddgs_raw, list) else []
                        )
                        if sx_items:
                            searxng_active = True
                            engines_used.append("searxng")
                        if ddgs_items:
                            engines_used.append("ddgs")
                        results = merge_parallel_search_results(
                            sx_items, ddgs_items, max_results=max_results
                        )
                    else:
                        try:
                            ddgs_items = _enforce_site_constraint(
                                query,
                                await asyncio.wait_for(
                                    asyncio.to_thread(_invoke_ddgs_compat, query, max_results, ddgs_reg),
                                    timeout=14.0,
                                ),
                            )
                        except (asyncio.TimeoutError, TimeoutError):
                            ddgs_timed_out = True
                            ddgs_items = []
                        except Exception:
                            ddgs_items = []
                        if ddgs_items:
                            engines_used.append("ddgs")
                        results = merge_parallel_search_results([], ddgs_items, max_results=max_results)

                status, cached = (200 if results else 204), False
                # Do not poison 24h http_cache with degraded partial results when ddgs timed out
                if results and not ddgs_timed_out:
                    self._set_cached(cache_key_url, json.dumps(results, ensure_ascii=False), 200)

        consensus_hits = sum(1 for r in results if int(r.get("consensus_score", 0)) >= 3)
        links = [r["url"] for r in results]
        summary_text = "\n".join(
            f"- [{r['title']}]({r['url']}): {r['snippet']}" for r in results
        )
        return CollectedDocument(
            source_type="web_search",
            url=cache_key_url,
            title=f"Search Results: {query}",
            content=summary_text,
            outbound_links=links,
            metadata={
                "query": query,
                "results": results,
                "status_code": status,
                "engines_used": engines_used,
                "searxng_active": searxng_active,
                "consensus_hits": consensus_hits,
            },
            cached=cached,
        )
