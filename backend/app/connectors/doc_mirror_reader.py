"""Public Deep-Reader for Scribd & Studocu Document Mirrors (Strictly Public OSINT).

Extracts publicly visible structured metadata (URL university/course/doc slugs,
JSON-LD, OpenGraph/meta tags, and publicly rendered preview text) from Scribd
and Studocu document pages using Python stdlib HTML parsing (zero extra dependencies)
without bypassing authentication, paywalls, or CAPTCHAs.
"""

from __future__ import annotations

import html as html_lib
import json
import re
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import unquote, urlparse

import httpx

from app.connectors.mirror_pivots import check_wayback_snapshot
from app.core.anchor_decoder import decode_high_entropy_anchors
from app.core.normalizer import normalize_text


def _assert_safe_public_url(url: str) -> None:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Unsupported scheme")
    host = (parsed.hostname or "").lower()
    if (
        not host
        or host in ("localhost", "127.0.0.1", "0.0.0.0", "::1")
        or host.startswith(("10.", "192.168.", "169.254.", "127."))
    ):
        raise ValueError("Blocked local/private host")

MAX_MIRROR_HTML_BYTES = 3 * 1024 * 1024  # 3 MB safety ceiling

_SCRIBD_DOC_RE = re.compile(
    r"^/(?:document|doc|presentation|read)/(\d+)(?:/([^/?#]+))?",
    re.IGNORECASE,
)
_STUDOCU_DOC_RE = re.compile(
    r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?document/([^/]+)/([^/]+)/([^/]+)/(\d+)",
    re.IGNORECASE,
)

_SKIP_TAGS = frozenset({"script", "style", "noscript", "nav", "footer", "header", "aside", "svg"})
_BLOCK_TAGS = frozenset({"p", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "div", "article", "section", "br"})


class _PublicMirrorHTMLParser(HTMLParser):
    """Lightweight stdlib HTML parser extracting meta tags, title, JSON-LD, and clean visible text lines."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta_tags: dict[str, str] = {}
        self.title_parts: list[str] = []
        self.json_ld_raw: list[str] = []
        self.lines: list[str] = []

        self._in_title = False
        self._in_json_ld = False
        self._json_ld_buf: list[str] = []
        self._skip_depth = 0
        self._cur_line: list[str] = []

    def _flush_line(self) -> None:
        if not self._cur_line:
            return
        joined = re.sub(r"\s+", " ", " ".join(self._cur_line)).strip()
        self._cur_line.clear()
        if joined:
            self.lines.append(joined)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        t = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}

        if t == "meta":
            key = (attr_map.get("property") or attr_map.get("name") or "").strip().lower()
            content = attr_map.get("content", "").strip()
            if key and content and key not in self.meta_tags:
                self.meta_tags[key] = content
            return

        if t == "title":
            self._in_title = True
            return

        if t == "script" and "ld+json" in attr_map.get("type", "").lower():
            self._in_json_ld = True
            self._json_ld_buf = []
            self._skip_depth += 1
            return

        if t in _SKIP_TAGS:
            self._skip_depth += 1
            return

        if t in _BLOCK_TAGS and self._skip_depth == 0:
            self._flush_line()

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "title":
            self._in_title = False
            return
        if t == "script" and self._in_json_ld:
            self._in_json_ld = False
            raw = "".join(self._json_ld_buf).strip()
            if raw:
                self.json_ld_raw.append(raw)
            self._json_ld_buf = []
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if t in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if t in _BLOCK_TAGS and self._skip_depth == 0:
            self._flush_line()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
            return
        if self._in_json_ld:
            self._json_ld_buf.append(data)
            return
        if self._skip_depth == 0 and data and data.strip():
            self._cur_line.append(data.strip())

    def close(self) -> None:
        super().close()
        self._flush_line()


def is_doc_mirror_url(url: str) -> bool:
    """Return True if URL points to a public Scribd or Studocu document page."""
    if not url:
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""
    if host.endswith("scribd.com") and _SCRIBD_DOC_RE.match(path):
        return True
    if (host.endswith("studocu.com") or host.endswith("studocu.vn")) and "/document/" in path.lower():
        return True
    return False


def _humanize_slug(slug: str) -> str:
    """Turn a URL slug like 'truong-dai-hoc-kinh-te-tp-hcm' into readable text."""
    clean = unquote(slug or "").strip("/ ")
    clean = re.sub(r"[-_]+", " ", clean)
    return re.sub(r"\s+", " ", clean).strip()


def parse_doc_mirror_url_metadata(url: str) -> dict[str, Any]:
    """Zero-network structural parser extracting platform, doc_id, university, course & title slug."""
    meta: dict[str, Any] = {
        "platform": "",
        "doc_id": "",
        "title_slug": "",
        "university_slug": "",
        "course_slug": "",
        "url": url,
    }
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return meta
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host.endswith("scribd.com"):
        meta["platform"] = "scribd"
        m = _SCRIBD_DOC_RE.match(path)
        if m:
            meta["doc_id"] = m.group(1)
            meta["title_slug"] = _humanize_slug(m.group(2) or "")
    elif host.endswith("studocu.com") or host.endswith("studocu.vn"):
        meta["platform"] = "studocu"
        m = _STUDOCU_DOC_RE.match(path)
        if m:
            meta["university_slug"] = _humanize_slug(m.group(1))
            meta["course_slug"] = _humanize_slug(m.group(2))
            meta["title_slug"] = _humanize_slug(m.group(3))
            meta["doc_id"] = m.group(4)
        else:
            parts = [p for p in path.split("/") if p]
            if parts and parts[-1].isdigit():
                meta["doc_id"] = parts[-1]
            if len(parts) >= 2:
                meta["title_slug"] = _humanize_slug(parts[-2])
    return meta


def _parse_json_ld_list(raw_blocks: list[str]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for raw in raw_blocks:
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict):
            if isinstance(data.get("@graph"), list):
                blocks.extend(item for item in data["@graph"] if isinstance(item, dict))
            else:
                blocks.append(data)
        elif isinstance(data, list):
            blocks.extend(item for item in data if isinstance(item, dict))
    return blocks


def _extract_author_name(author_obj: Any) -> str:
    if isinstance(author_obj, str):
        return author_obj.strip()
    if isinstance(author_obj, dict):
        return str(author_obj.get("name") or "").strip()
    if isinstance(author_obj, list):
        names = [_extract_author_name(a) for a in author_obj]
        return ", ".join(n for n in names if n)
    return ""


def _build_match_tokens(target_terms: list[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """Build (original, normalized) text tokens + digit-only phone/ID tokens."""
    text_tokens: list[tuple[str, str]] = []
    digit_tokens: list[str] = []
    seen_t: set[str] = set()
    seen_d: set[str] = set()
    for term in target_terms:
        clean = str(term or "").strip()
        if len(clean) < 3:
            continue
        digits = re.sub(r"\D+", "", clean)
        if len(digits) >= 8 and digits.isdigit() and len(digits) >= len(clean) - 4:
            if digits.startswith("84") and len(digits) == 11:
                digits = "0" + digits[2:]
            core = digits.lstrip("0")
            for d in (digits, core):
                if len(d) >= 8 and d not in seen_d:
                    seen_d.add(d)
                    digit_tokens.append(d)
        norm = normalize_text(clean)
        key = norm or clean.lower()
        if key not in seen_t:
            seen_t.add(key)
            text_tokens.append((clean, key))
    text_tokens.sort(key=lambda pair: len(pair[1]), reverse=True)
    return text_tokens, digit_tokens


def extract_doc_mirror_public_html(
    html: str,
    url: str,
    target_terms: list[str],
    max_excerpts: int = 8,
) -> dict[str, Any]:
    """Parse public HTML of a Scribd or Studocu document page into structured metadata & target excerpts."""
    url_meta = parse_doc_mirror_url_metadata(url)
    platform = url_meta.get("platform") or ("scribd" if "scribd" in url.lower() else "studocu")

    parser = _PublicMirrorHTMLParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:
        pass

    meta_tags = parser.meta_tags
    title = (
        meta_tags.get("og:title")
        or re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
        or url_meta.get("title_slug", "")
    )
    description = meta_tags.get("og:description") or meta_tags.get("description", "")
    author = meta_tags.get("author", "")
    published = meta_tags.get("article:published_time") or meta_tags.get("date", "")
    page_count = ""
    course_name = url_meta.get("course_slug", "")
    university_name = url_meta.get("university_slug", "")

    for block in _parse_json_ld_list(parser.json_ld_raw):
        if not title and block.get("name"):
            title = str(block["name"]).strip()
        if not description and block.get("description"):
            description = str(block["description"]).strip()
        if not author and block.get("author"):
            author = _extract_author_name(block["author"])
        if not published and (block.get("datePublished") or block.get("uploadDate")):
            published = str(block.get("datePublished") or block.get("uploadDate")).strip()
        if not page_count and block.get("numberOfPages"):
            page_count = str(block["numberOfPages"]).strip()
        is_part = block.get("isPartOf")
        if isinstance(is_part, dict):
            if not course_name and is_part.get("name"):
                course_name = str(is_part["name"]).strip()
            provider = is_part.get("provider") or block.get("provider")
            if isinstance(provider, dict) and provider.get("name"):
                university_name = str(provider["name"]).strip()

    preview_lines: list[str] = []
    seen_lines: set[str] = set()

    def _add_line(raw_ln: str) -> None:
        cleaned = re.sub(r"\s+", " ", html_lib.unescape(raw_ln or "")).strip()
        if len(cleaned) < 10:
            return
        low_c = cleaned.lower()
        if any(
            bp in low_c
            for bp in (
                "cookie",
                "sign in",
                "log in",
                "start your free trial",
                "upgrade to premium",
                "tải xuống ngay",
                "đăng nhập để xem",
                "why is this page out of focus",
            )
        ):
            return
        if cleaned not in seen_lines:
            seen_lines.add(cleaned)
            preview_lines.append(cleaned)

    if title:
        _add_line(title)
    if description:
        for seg in re.split(r"[\n\r]+", description):
            _add_line(seg)
    for ln in parser.lines:
        if 10 <= len(ln) <= 800:
            _add_line(ln)
        if len(preview_lines) >= 250:
            break

    text_tokens, digit_tokens = _build_match_tokens(target_terms)
    excerpts: list[dict[str, Any]] = []
    for idx, line in enumerate(preview_lines):
        norm_ln = normalize_text(line)
        low_ln = line.lower()
        digits_ln = re.sub(r"\D+", "", line)
        matched_terms = [
            orig
            for orig, norm_t in text_tokens
            if (norm_t and norm_t in norm_ln) or (orig.lower() in low_ln)
        ]
        for dt in digit_tokens:
            if dt in digits_ln and dt not in matched_terms:
                matched_terms.append(dt)
        if not matched_terms:
            continue
        start_i = max(0, idx - 1)
        end_i = min(len(preview_lines), idx + 2)
        context_block = " \n ".join(preview_lines[start_i:end_i])
        excerpts.append(
            {
                "page": 1,
                "matched_terms": matched_terms,
                "line": line[:400],
                "context": context_block[:700],
            }
        )
        if len(excerpts) >= max_excerpts:
            break

    combined_public_text = " ".join(
        [title, description, university_name, course_name, url_meta.get("title_slug", "")] + preview_lines[:80]
    )
    discovered_anchors = decode_high_entropy_anchors(combined_public_text[:8000])

    metadata = {
        "platform": platform,
        "doc_id": url_meta.get("doc_id", ""),
        "title": title[:240],
        "author": author[:120],
        "university": university_name[:160],
        "course": course_name[:160],
        "published": published[:40],
        "page_count": page_count[:20],
        "description": description[:400],
        "preview_lines_count": len(preview_lines),
    }

    return {
        "ok": True,
        "doc_type": f"{platform}_mirror",
        "url": url,
        "metadata": metadata,
        "excerpts": excerpts,
        "discovered_anchors": discovered_anchors,
        "public_text_summary": combined_public_text[:2500],
    }


async def fetch_and_inspect_doc_mirror(
    url: str,
    target_terms: list[str],
    timeout: float = 8.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Fetch a public Scribd or Studocu document page (SSRF-guarded, no auth/paywall bypass)
    and extract structured public metadata, preview excerpts, and anchors.
    Falls back to URL slug metadata (and Wayback public archive if live fetch is blocked).
    """
    if not is_doc_mirror_url(url):
        return {"ok": False, "error": "not_a_doc_mirror_url"}

    url_meta = parse_doc_mirror_url_metadata(url)
    try:
        _assert_safe_public_url(url)
    except Exception as exc:
        return {"ok": False, "error": f"ssrf_blocked: {exc}"}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    html_text = ""
    fetch_source = "live_public_html"
    try:
        if client is not None:
            resp = await client.get(url, headers=headers, follow_redirects=True, timeout=timeout)
        else:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as temp_client:
                resp = await temp_client.get(url, headers=headers)
        if resp.status_code == 200 and resp.content and len(resp.content) <= MAX_MIRROR_HTML_BYTES:
            html_text = resp.text or ""
    except Exception:
        html_text = ""

    if not html_text:
        try:
            wb = await check_wayback_snapshot(url, timeout=4.0, client=client)
            if wb and wb.get("archived_url"):
                arch_url = wb["archived_url"]
                _assert_safe_public_url(arch_url)
                if client is not None:
                    wb_resp = await client.get(arch_url, headers=headers, follow_redirects=True, timeout=timeout)
                else:
                    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as temp_client:
                        wb_resp = await temp_client.get(arch_url, headers=headers)
                if wb_resp.status_code == 200 and wb_resp.content and len(wb_resp.content) <= MAX_MIRROR_HTML_BYTES:
                    html_text = wb_resp.text or ""
                    fetch_source = "wayback_public_archive"
        except Exception:
            pass

    if html_text:
        parsed_res = extract_doc_mirror_public_html(html_text, url, target_terms=target_terms)
        parsed_res["fetch_source"] = fetch_source
        return parsed_res

    slug_blob = " ".join(
        v
        for v in (
            url_meta.get("university_slug", ""),
            url_meta.get("course_slug", ""),
            url_meta.get("title_slug", ""),
        )
        if v
    )
    return {
        "ok": bool(slug_blob),
        "doc_type": f"{url_meta.get('platform', 'mirror')}_mirror",
        "url": url,
        "fetch_source": "url_slug_only",
        "metadata": {
            "platform": url_meta.get("platform", ""),
            "doc_id": url_meta.get("doc_id", ""),
            "title": url_meta.get("title_slug", ""),
            "author": "",
            "university": url_meta.get("university_slug", ""),
            "course": url_meta.get("course_slug", ""),
            "published": "",
            "page_count": "",
            "description": "",
            "preview_lines_count": 0,
        },
        "excerpts": [],
        "discovered_anchors": decode_high_entropy_anchors(slug_blob),
        "public_text_summary": slug_blob,
    }
