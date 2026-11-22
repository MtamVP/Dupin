"""Structured HTML Metadata, JSON-LD (@type: Person), and IndieWeb rel='me' Extractor.

Directly inspired by qeeqbox/social-analyzer/modules/extraction.js and soxoj/socid-extractor:
- Filters noisy visual/layout meta tags (`viewport`, `charset`, `width`, `height`, `color`, `rgba`)
- Extracts OpenGraph (`og:*`, `profile:*`) and Twitter Cards (`twitter:*`)
- Parses Schema.org JSON-LD (`Person` / `ProfilePage`: name, jobTitle, worksFor, alumniOf, sameAs)
- Extracts IndieWeb `rel="me"` bidirectional cross-platform identity verification links
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

NOISY_META_RE = re.compile(
    r"regionsallowed|width|height|color|rgba\(|charset|viewport|refresh|equiv|theme-color|msapplication",
    re.IGNORECASE,
)
META_TAG_RE = re.compile(r"<meta\s+([^>]+?)/?>", re.IGNORECASE | re.DOTALL)
ATTR_RE = re.compile(r'([a-zA-Z0-9_:-]+)\s*=\s*(?:"([^"]*)"|\'([^\']*)\')')
JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
REL_ME_RE = re.compile(
    r'<a[^>]+rel=["\'][^"\']*\bme\b[^"\']*["\'][^>]+href=["\'](https?://[^"\']+)["\']'
    r'|<a[^>]+href=["\'](https?://[^"\']+)["\'][^>]+rel=["\'][^"\']*\bme\b[^"\']*["\']'
    r'|<link[^>]+rel=["\'][^"\']*\bme\b[^"\']*["\'][^>]+href=["\'](https?://[^"\']+)["\']',
    re.IGNORECASE,
)
TITLE_TAG_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def _walk_jsonld_objects(obj: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(obj, dict):
        found.append(obj)
        for k in ("@graph", "mainEntity", "author", "creator"):
            if k in obj:
                found.extend(_walk_jsonld_objects(obj[k]))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_walk_jsonld_objects(item))
    return found


def extract_structured_html_metadata(raw_html: str) -> dict[str, Any]:
    """Extract clean OpenGraph, Twitter Card, JSON-LD Person, and rel='me' links from HTML."""
    snippet_html = (raw_html or "")[:120_000]
    meta_map: dict[str, str] = {}

    for m in META_TAG_RE.finditer(snippet_html):
        attr_str = m.group(1)
        if NOISY_META_RE.search(attr_str):
            continue
        attrs = {k.lower(): html.unescape(v1 or v2).strip() for k, v1, v2 in ATTR_RE.findall(attr_str)}
        key = attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or ""
        val = attrs.get("content") or ""
        if key and val:
            if key in meta_map and val not in meta_map[key]:
                meta_map[key] = f"{meta_map[key]}, {val}"[:300]
            else:
                meta_map[key] = val[:300]

    title_m = TITLE_TAG_RE.search(snippet_html)
    page_title = html.unescape(re.sub(r"\s+", " ", title_m.group(1))).strip() if title_m else ""

    # Parse JSON-LD Person / ProfilePage fields
    person_ld: dict[str, Any] = {}
    same_as_links: list[str] = []
    for jm in JSON_LD_RE.finditer(snippet_html):
        raw_json = jm.group(1).strip()
        try:
            parsed = json.loads(raw_json)
        except Exception:
            continue
        for node in _walk_jsonld_objects(parsed):
            ntype = str(node.get("@type") or "").lower()
            if "person" in ntype:
                if node.get("name") and not person_ld.get("name"):
                    person_ld["name"] = str(node["name"]).strip()
                if node.get("jobTitle") and not person_ld.get("job_title"):
                    person_ld["job_title"] = str(node["jobTitle"]).strip()
                if node.get("description") and not person_ld.get("description"):
                    person_ld["description"] = str(node["description"]).strip()[:280]
                for field, out_key in (("worksFor", "works_for"), ("alumniOf", "alumni_of")):
                    v = node.get(field)
                    if isinstance(v, dict) and v.get("name"):
                        person_ld[out_key] = str(v["name"]).strip()
                    elif isinstance(v, str) and v.strip():
                        person_ld[out_key] = v.strip()
                    elif isinstance(v, list) and v:
                        first = v[0]
                        if isinstance(first, dict) and first.get("name"):
                            person_ld[out_key] = str(first["name"]).strip()
                        elif isinstance(first, str):
                            person_ld[out_key] = first.strip()
                sa = node.get("sameAs")
                if isinstance(sa, str) and sa.startswith(("http://", "https://")):
                    same_as_links.append(sa.strip())
                elif isinstance(sa, list):
                    for link in sa:
                        if isinstance(link, str) and link.startswith(("http://", "https://")):
                            same_as_links.append(link.strip())

    # Extract IndieWeb rel="me" cross-platform identity proof links
    rel_me_links: list[str] = []
    for rm in REL_ME_RE.finditer(snippet_html):
        href = (rm.group(1) or rm.group(2) or rm.group(3) or "").strip()
        if href and href not in rel_me_links:
            rel_me_links.append(href)

    og_title = meta_map.get("og:title") or meta_map.get("twitter:title") or ""
    og_desc = meta_map.get("og:description") or meta_map.get("description") or meta_map.get("twitter:description") or ""
    og_image = meta_map.get("og:image") or meta_map.get("twitter:image") or ""

    return {
        "title": person_ld.get("name") or og_title or page_title,
        "description": person_ld.get("description") or og_desc,
        "image": og_image,
        "meta": meta_map,
        "jsonld_person": person_ld,
        "same_as": list(dict.fromkeys(same_as_links))[:10],
        "rel_me": rel_me_links[:10],
    }
