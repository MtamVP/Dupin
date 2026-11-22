"""Maigret + Sherlock + Social-Analyzer Compatible Multi-Platform Username Recon Engine.

Directly implements proven engineering architectures from:
- soxoj/maigret: External JSON site & engine registry (`DiscourseJson`, `MastodonApi`,
  `WordpressAuthor`), `regex_check` pre-filtering, dual `presence_strs` + `absence_strs`
  Soft-404 verification, tag-based filtering, and recursive bio/link pivoting.
- qeeqbox/social-analyzer: OpenGraph / Twitter Card / JSON-LD `@type: Person` / IndieWeb
  `rel="me"` metadata extraction + transparent 0-100 multi-factor confidence scoring.

Strictly Public OSINT Only (no auth-wall bypass, no CAPTCHA evasion).
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

import httpx

from app.connectors.metadata_extractor import extract_structured_html_metadata
from app.core.normalizer import normalize_text

DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "data" / "sites_manifest.json"
CUSTOM_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "data" / "custom_sites.json"

HANDLE_MENTION_RE = re.compile(r"(?:^|[\s(,;])@([A-Za-z0-9_.-]{3,30})\b")
EMAIL_IN_BIO_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_IN_BIO_RE = re.compile(r"https?://[^\s<>\"')]+", re.IGNORECASE)

# Sherlock-style `response_url` Soft-404 redirect markers:
# sites that return HTTP 200 after redirecting an invalid username to login/404/error/home
DEFAULT_ERROR_URL_MARKERS: tuple[str, ...] = (
    "/404",
    "/not-found",
    "/notfound",
    "/error",
    "/login",
    "/signin",
    "/sign-in",
    "/auth/login",
    "/accounts/login",
    "/suspended",
)

SUPPORTED_MODES: frozenset[str] = frozenset(
    {
        "github_json",
        "gitlab_json",
        "devto_json",
        "reddit_json",
        "hn_json",
        "hf_json",
        "keybase_json",
        "codeforces_json",
        "docker_json",
        "discourse_json",
        "mastodon_json",
        "wordpress_json",
        "chess_json",
        "lichess_json",
        "bluesky_json",
        "gitea_json",
        "crates_json",
        "rubygems_json",
        "lobsters_json",
        "html_check",
        "html_title",
    }
)


class SiteHealthTracker:
    """Maigret/Sherlock-style per-site Circuit Breaker to skip dead or rate-limiting sites cleanly."""

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: float = 180.0) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

    def is_open(self, site_name: str) -> bool:
        until = self._open_until.get(site_name)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._open_until.pop(site_name, None)
            self._failures.pop(site_name, None)
            return False
        return True

    def record_success(self, site_name: str) -> None:
        self._failures.pop(site_name, None)
        self._open_until.pop(site_name, None)

    def record_failure(self, site_name: str, hard_rate_limit: bool = False) -> None:
        if hard_rate_limit:
            self._open_until[site_name] = time.monotonic() + self.cooldown_seconds
            self._failures[site_name] = self.failure_threshold
            return
        cnt = self._failures.get(site_name, 0) + 1
        self._failures[site_name] = cnt
        if cnt >= self.failure_threshold:
            self._open_until[site_name] = time.monotonic() + self.cooldown_seconds

    def status_snapshot(self) -> dict[str, Any]:
        now = time.monotonic()
        open_sites = [s for s, t in self._open_until.items() if t > now]
        return {
            "open_circuits": sorted(open_sites),
            "open_count": len(open_sites),
            "tracked_failures": dict(self._failures),
        }


SITE_HEALTH = SiteHealthTracker()


def _is_soft_404_redirect(
    probe_url: str,
    final_url: str,
    extra_markers: Optional[list[str]] = None,
) -> bool:
    """Sherlock `errorType: response_url` detector: catch HTTP 200 redirects to login/404/root."""
    if not final_url:
        return False
    p_in = urlparse(probe_url)
    p_out = urlparse(final_url)
    out_path = p_out.path.lower().rstrip("/")
    in_path = p_in.path.lower().rstrip("/")
    markers = tuple(DEFAULT_ERROR_URL_MARKERS) + tuple(m.lower() for m in (extra_markers or []) if m)
    if any(mk in out_path for mk in markers):
        return True
    # Profile URL had a specific user path (e.g. /u/alice) but redirected to homepage root `/`
    if in_path and in_path != "/" and (not out_path or out_path == "") and not p_out.query:
        return True
    return False


def validate_sites_manifest(specs: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    """Sherlock/Maigret CI-grade self-check validator for site manifest integrity."""
    items = specs if specs is not None else PUBLIC_SITE_MANIFEST
    errors: list[str] = []
    seen_names: set[str] = set()
    by_mode: dict[str, int] = {}
    for idx, sp in enumerate(items):
        name = str(sp.get("site") or "").strip()
        if not name:
            errors.append(f"entry[{idx}]: missing 'site' name")
            continue
        low_name = name.lower()
        if low_name in seen_names:
            errors.append(f"duplicate site: {name}")
        seen_names.add(low_name)
        url_tpl = str(sp.get("url") or "")
        if "{u}" not in url_tpl:
            errors.append(f"{name}: url missing '{{u}}' placeholder")
        mode = str(sp.get("mode") or "html_check")
        by_mode[mode] = by_mode.get(mode, 0) + 1
        if mode not in SUPPORTED_MODES:
            errors.append(f"{name}: unsupported mode '{mode}'")
        rx = sp.get("regex_check")
        if rx:
            try:
                re.compile(rx)
            except re.error as exc:
                errors.append(f"{name}: invalid regex_check ({exc})")
    return {
        "valid": len(errors) == 0,
        "total_sites": len(items),
        "verified_json_api_sites": sum(v for k, v in by_mode.items() if k.endswith("_json")),
        "html_check_sites": by_mode.get("html_check", 0) + by_mode.get("html_title", 0),
        "modes_breakdown": by_mode,
        "errors": errors,
    }


def _expand_engine_site(site: dict[str, Any], engines: dict[str, Any]) -> dict[str, Any]:
    """Expand a Maigret-style engine-inherited site definition into concrete probe/profile URLs."""
    eng_name = site.get("engine")
    if not eng_name or eng_name not in engines:
        return site
    eng = engines[eng_name]
    base = str(site.get("base_url") or "").rstrip("/")
    expanded = dict(site)
    expanded["mode"] = eng.get("mode", "html_check")
    expanded["url"] = f"{base}{eng['profile_suffix']}".replace("{username}", "{u}")
    expanded["api_url"] = f"{base}{eng['probe_suffix']}".replace("{username}", "{u}")
    return expanded


def _convert_external_maigret_or_sherlock_json(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt an external Maigret `data.json` or Sherlock `data.json` into Stalker++ site specs."""
    converted: list[dict[str, Any]] = []
    sites_dict = raw.get("sites") if isinstance(raw.get("sites"), dict) else raw
    if not isinstance(sites_dict, dict):
        return []
    for name, info in list(sites_dict.items())[:250]:
        if not isinstance(info, dict) or not info.get("url"):
            continue
        url_tpl = str(info["url"]).replace("{username}", "{u}").replace("{}", "{u}")
        if "{u}" not in url_tpl:
            continue
        pres = [str(s).lower() for s in (info.get("presenseStrs") or info.get("presence_strs") or []) if s]
        absc = [str(s).lower() for s in (info.get("absenceStrs") or info.get("absence_strs") or []) if s]
        err_msg = info.get("errorMsg")
        if isinstance(err_msg, str) and err_msg:
            absc.append(err_msg.lower())
        elif isinstance(err_msg, list):
            absc.extend(str(x).lower() for x in err_msg if x)
        converted.append(
            {
                "site": str(name),
                "category": "community_imported",
                "tags": list(info.get("tags") or ["imported"]),
                "url": url_tpl,
                "mode": "html_check",
                "presence_strs": pres,
                "absence_strs": absc or ["page not found", "404"],
                "regex_check": str(info.get("regexCheck") or info.get("regex_check") or ""),
            }
        )
    return converted


def load_sites_manifest(extra_manifest_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Load built-in Maigret-compatible manifest plus optional custom Maigret/Sherlock JSON."""
    specs: list[dict[str, Any]] = []
    if DEFAULT_MANIFEST_PATH.is_file():
        data = json.loads(DEFAULT_MANIFEST_PATH.read_text(encoding="utf-8"))
        engines = data.get("engines") or {}
        for s in data.get("sites") or []:
            specs.append(_expand_engine_site(s, engines))

    ext_path = extra_manifest_path or CUSTOM_MANIFEST_PATH
    if ext_path and ext_path.is_file():
        try:
            ext_raw = json.loads(ext_path.read_text(encoding="utf-8"))
            existing_names = {s["site"].lower() for s in specs}
            for imp in _convert_external_maigret_or_sherlock_json(ext_raw):
                if imp["site"].lower() not in existing_names:
                    specs.append(imp)
                    existing_names.add(imp["site"].lower())
        except Exception:
            pass
    return specs


PUBLIC_SITE_MANIFEST: list[dict[str, Any]] = load_sites_manifest()


def extract_recursive_pivots(text: str, seed_username: str) -> dict[str, list[str]]:
    """Maigret-style recursive pivot extraction: mine secondary handles, emails, and URLs from bios."""
    seed_low = seed_username.strip().lower().lstrip("@")
    emails = sorted({e.lower() for e in EMAIL_IN_BIO_RE.findall(text or "")})
    urls = sorted({u.rstrip(".,;)") for u in URL_IN_BIO_RE.findall(text or "")})
    handles: list[str] = []
    seen_h: set[str] = {seed_low}
    for m in HANDLE_MENTION_RE.findall(text or ""):
        h = m.strip("._-").lower()
        if len(h) >= 3 and h not in seen_h and not any(h in em for em in emails):
            seen_h.add(h)
            handles.append(m.strip("._-"))
    return {"handles": handles[:5], "emails": emails[:5], "urls": urls[:8]}


def compute_social_analyzer_score(
    *,
    verified_api: bool,
    display_name: str,
    bio: str,
    avatar_url: str,
    has_structured_ld: bool,
    rel_me_count: int,
    target_hints: list[str],
) -> int:
    """Social-Analyzer-inspired transparent 0-100 multi-layer confidence score."""
    score = 55 if verified_api else 35
    if display_name:
        score += 10
    if bio and len(bio.strip()) >= 8:
        score += 10
    if avatar_url:
        score += 5
    if has_structured_ld:
        score += 5
    if rel_me_count > 0:
        score += 5
    if target_hints:
        blob = normalize_text(f"{display_name} {bio}")
        hits = sum(1 for h in target_hints if len(normalize_text(h)) >= 3 and normalize_text(h) in blob)
        score += min(20, hits * 10)
    return min(100, score)


async def _check_single_site(
    client: httpx.AsyncClient,
    spec: dict[str, Any],
    username: str,
    target_hints: list[str],
    use_circuit_breaker: bool = False,
) -> Optional[dict[str, Any]]:
    # Maigret-style regex_check pre-filter: skip requests when username fails site syntax rules
    rx = spec.get("regex_check")
    if rx:
        try:
            if not re.match(rx, username):
                return None
        except re.error:
            pass

    # Circuit breaker skip (disabled during deterministic mock-client unit tests)
    site_name = str(spec.get("site") or "")
    if use_circuit_breaker and SITE_HEALTH.is_open(site_name):
        return None

    enc_u = quote(username)
    profile_url = spec["url"].format(u=enc_u)
    probe_url = spec.get("api_url", spec["url"]).format(u=enc_u)
    mode = spec.get("mode", "html_check")

    try:
        resp = await client.get(probe_url, follow_redirects=True)
    except Exception:
        if use_circuit_breaker:
            SITE_HEALTH.record_failure(site_name)
        return None

    if resp.status_code == 429:
        if use_circuit_breaker:
            SITE_HEALTH.record_failure(site_name, hard_rate_limit=True)
        return None
    if resp.status_code >= 500:
        if use_circuit_breaker:
            SITE_HEALTH.record_failure(site_name)
        return None
    if use_circuit_breaker:
        SITE_HEALTH.record_success(site_name)

    if resp.status_code != 200:
        return None

    # Sherlock `response_url` redirect Soft-404 check (catches HTTP 200 -> /login or /404 or root)
    final_url = str(getattr(resp, "url", "") or "")
    if _is_soft_404_redirect(probe_url, final_url, spec.get("error_url_markers")):
        return None

    display_name = ""
    bio = ""
    avatar_url = ""
    location = ""
    extra_links: list[str] = []
    rel_me: list[str] = []
    same_as: list[str] = []
    has_ld = False
    verified_api = mode.endswith("_json")

    try:
        if mode == "github_json":
            d = resp.json()
            if not d.get("login"):
                return None
            display_name = str(d.get("name") or d["login"])
            bio = " · ".join(x for x in [d.get("bio"), d.get("company"), d.get("location")] if x)
            avatar_url = str(d.get("avatar_url") or "")
            location = str(d.get("location") or "")
            if d.get("blog"):
                extra_links.append(str(d["blog"]))
                rel_me.append(str(d["blog"]))
            if d.get("email"):
                bio = f"{bio} · {d['email']}".strip(" ·")
        elif mode == "gitlab_json":
            arr = resp.json()
            if not isinstance(arr, list) or not arr:
                return None
            d = arr[0]
            display_name = str(d.get("name") or d.get("username") or "")
            avatar_url = str(d.get("avatar_url") or "")
            bio = f"GitLab user @{d.get('username', username)} (state: {d.get('state', 'active')})"
        elif mode == "devto_json":
            d = resp.json()
            if not d.get("username"):
                return None
            display_name = str(d.get("name") or d["username"])
            bio = str(d.get("summary") or "")
            avatar_url = str(d.get("profile_image") or "")
            location = str(d.get("location") or "")
            if d.get("website_url"):
                extra_links.append(str(d["website_url"]))
        elif mode == "reddit_json":
            d = (resp.json() or {}).get("data") or {}
            if not d.get("name") or d.get("is_suspended"):
                return None
            sub = d.get("subreddit") or {}
            display_name = str(sub.get("title") or d["name"])
            bio = str(sub.get("public_description") or f"Reddit karma: {d.get('total_karma', 0)}")
            avatar_url = str(d.get("icon_img") or "")
        elif mode == "hn_json":
            d = resp.json()
            if not isinstance(d, dict) or not d.get("id"):
                return None
            display_name = str(d["id"])
            raw_about = html.unescape(re.sub(r"<[^>]+>", " ", str(d.get("about") or ""))).strip()
            bio = raw_about or f"HackerNews karma: {d.get('karma', 0)}"
        elif mode == "hf_json":
            d = resp.json()
            if not d.get("user"):
                return None
            display_name = str(d.get("fullname") or d["user"])
            bio = str(d.get("details") or f"HuggingFace models: {d.get('numModels', 0)}")
            avatar_url = str(d.get("avatarUrl") or "")
        elif mode == "keybase_json":
            them = (resp.json() or {}).get("them") or []
            if not them or not them[0]:
                return None
            prof = them[0].get("profile") or {}
            display_name = str(prof.get("full_name") or username)
            bio = str(prof.get("bio") or "Verified Keybase cryptographic identity")
            location = str(prof.get("location") or "")
        elif mode == "codeforces_json":
            body = resp.json()
            if body.get("status") != "OK" or not body.get("result"):
                return None
            u = body["result"][0]
            display_name = " ".join(x for x in [u.get("firstName"), u.get("lastName")] if x) or u.get("handle", username)
            bio = " · ".join(
                x
                for x in [
                    u.get("organization"),
                    u.get("city"),
                    u.get("country"),
                    f"Rank: {u['rank']} ({u.get('rating', 0)})" if u.get("rank") else "",
                ]
                if x
            )
            avatar_url = str(u.get("avatar") or "")
        elif mode == "docker_json":
            d = resp.json()
            if not d.get("username"):
                return None
            display_name = str(d.get("full_name") or d["username"])
            bio = str(d.get("company") or d.get("location") or f"DockerHub @{d['username']}")
        elif mode == "discourse_json":
            # Maigret DiscourseJson engine (e.g. university Discourse forums like forum.uit.edu.vn)
            u = (resp.json() or {}).get("user") or {}
            if not u.get("username"):
                return None
            display_name = str(u.get("name") or u["username"])
            bio = " · ".join(
                x
                for x in [
                    u.get("bio_raw"),
                    u.get("title"),
                    f"Joined: {str(u.get('created_at', ''))[:10]}" if u.get("created_at") else "",
                    f"Trust level: {u.get('trust_level')}" if u.get("trust_level") is not None else "",
                ]
                if x
            )
        elif mode == "mastodon_json":
            # Maigret MastodonApi engine (Fediverse accounts with verified rel="me" fields)
            u = resp.json()
            if not isinstance(u, dict) or not u.get("acct"):
                return None
            display_name = str(u.get("display_name") or u["acct"])
            note_clean = html.unescape(re.sub(r"<[^>]+>", " ", str(u.get("note") or ""))).strip()
            bio = note_clean or f"Mastodon @{u['acct']}"
            avatar_url = str(u.get("avatar") or "")
            for fld in u.get("fields") or []:
                val_html = str(fld.get("value") or "")
                for lnk in URL_IN_BIO_RE.findall(val_html):
                    extra_links.append(lnk)
                    if fld.get("verified_at"):
                        rel_me.append(lnk)
        elif mode == "wordpress_json":
            arr = resp.json()
            if not isinstance(arr, list) or not arr:
                return None
            u = arr[0]
            display_name = str(u.get("name") or u.get("slug") or username)
            bio = str(u.get("description") or f"WordPress author {display_name}")
        elif mode == "chess_json":
            u = resp.json()
            if not u.get("username"):
                return None
            display_name = str(u.get("name") or u["username"])
            bio = " · ".join(x for x in [u.get("title"), u.get("location"), f"Status: {u.get('status')}"] if x)
            avatar_url = str(u.get("avatar") or "")
        elif mode == "lichess_json":
            u = resp.json()
            if not u.get("id"):
                return None
            prof = u.get("profile") or {}
            display_name = " ".join(x for x in [prof.get("firstName"), prof.get("lastName")] if x) or u["id"]
            bio = str(prof.get("bio") or prof.get("location") or f"Lichess @{u['id']}")
        elif mode == "bluesky_json":
            u = resp.json()
            if not isinstance(u, dict) or not u.get("handle"):
                return None
            display_name = str(u.get("displayName") or u["handle"])
            bio = str(u.get("description") or f"Bluesky @{u['handle']} · {u.get('followersCount', 0)} followers")
            avatar_url = str(u.get("avatar") or "")
        elif mode == "gitea_json":
            u = resp.json()
            if not isinstance(u, dict) or not u.get("login"):
                return None
            display_name = str(u.get("full_name") or u["login"])
            bio = " · ".join(x for x in [u.get("description"), u.get("location"), u.get("website")] if x)
            avatar_url = str(u.get("avatar_url") or "")
            if u.get("website"):
                extra_links.append(str(u["website"]))
                rel_me.append(str(u["website"]))
        elif mode == "crates_json":
            u = (resp.json() or {}).get("user") or {}
            if not u.get("login"):
                return None
            display_name = str(u.get("name") or u["login"])
            bio = f"Crates.io Rust author @{u['login']}"
            avatar_url = str(u.get("avatar") or "")
        elif mode == "rubygems_json":
            u = resp.json()
            if not isinstance(u, dict) or not u.get("handle"):
                return None
            display_name = str(u["handle"])
            bio = f"RubyGems author @{u['handle']}"
        elif mode == "lobsters_json":
            u = resp.json()
            if not isinstance(u, dict) or not u.get("username"):
                return None
            display_name = str(u["username"])
            bio = str(u.get("about") or f"Lobsters user @{u['username']} (karma: {u.get('karma', 0)})")
            avatar_url = str(u.get("avatar_url") or "")
            if u.get("github_username"):
                extra_links.append(f"https://github.com/{u['github_username']}")
                rel_me.append(f"https://github.com/{u['github_username']}")
        elif mode in ("html_check", "html_title"):
            body = resp.text[:90_000]
            low = body.lower()
            absence = spec.get("absence_strs") or spec.get("error_markers") or []
            presence = spec.get("presence_strs") or []
            if any(err.lower() in low for err in absence):
                return None
            if presence and not any(p.lower() in low for p in presence):
                return None
            if username.lower() not in low:
                return None
            meta = extract_structured_html_metadata(body)
            title_clean = meta.get("title") or ""
            if not title_clean or any(err.lower() in title_clean.lower() for err in absence):
                return None
            display_name = title_clean[:100]
            ld = meta.get("jsonld_person") or {}
            has_ld = bool(ld)
            bio_parts = [meta.get("description") or ""]
            if ld.get("job_title"):
                bio_parts.append(ld["job_title"])
            if ld.get("works_for"):
                bio_parts.append(f"@ {ld['works_for']}")
            if ld.get("alumni_of"):
                bio_parts.append(f"Alumni: {ld['alumni_of']}")
            bio = " · ".join(p for p in bio_parts if p)[:280]
            avatar_url = meta.get("image") or ""
            rel_me = meta.get("rel_me") or []
            same_as = meta.get("same_as") or []
            extra_links.extend(rel_me + same_as)
        else:
            return None
    except Exception:
        return None

    pivots = extract_recursive_pivots(f"{display_name} {bio} {' '.join(extra_links)}", username)
    confidence_0_100 = compute_social_analyzer_score(
        verified_api=verified_api,
        display_name=display_name,
        bio=bio,
        avatar_url=avatar_url,
        has_structured_ld=has_ld,
        rel_me_count=len(rel_me),
        target_hints=target_hints,
    )
    return {
        "site": spec["site"],
        "category": spec.get("category", "general"),
        "tags": spec.get("tags", []),
        "username": username,
        "url": profile_url,
        "display_name": display_name,
        "bio": bio[:280],
        "location": location,
        "avatar_url": avatar_url,
        "rel_me": list(dict.fromkeys(rel_me))[:6],
        "same_as": list(dict.fromkeys(same_as))[:6],
        "confidence_score": confidence_0_100,
        "recursive_pivots": pivots,
    }


async def scan_username_profiles(
    username: str,
    target_hints: Optional[list[str]] = None,
    sites: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
    max_sites: int = 30,
    timeout: float = 5.0,
    recursive_depth: int = 1,
    max_recursive_handles: int = 2,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Run concurrent Sherlock/Maigret/Social-Analyzer-compatible public username scan.

    Upgrades over naive username scanners:
    - Maigret `rank` & verified-JSON-API priority sorting
    - Sherlock `response_url` redirect Soft-404 rejection + dual presence/absence HTML checks
    - Per-site circuit breaker (`SiteHealthTracker`) to skip rate-limiting/dead hosts in 0ms
    - Controlled Maigret recursive multi-hop pivot scanning (`recursive_depth=2`) with cycle guard
    """
    clean_u = username.strip().lstrip("@")
    if not clean_u or not re.match(r"^[A-Za-z0-9_.-]{2,45}$", clean_u):
        return {
            "username": clean_u,
            "checked_sites": 0,
            "manifest_total": len(PUBLIC_SITE_MANIFEST),
            "found_profiles": [],
            "discovered_pivots": {"handles": [], "emails": [], "urls": []},
            "recursion_tree": [],
        }

    hints = target_hints or []
    wanted_sites = {s.lower() for s in sites} if sites else None
    wanted_tags = {t.lower() for t in tags} if tags else None

    specs: list[dict[str, Any]] = []
    for idx, sp in enumerate(PUBLIC_SITE_MANIFEST):
        if wanted_sites is not None and sp["site"].lower() not in wanted_sites:
            continue
        if wanted_tags is not None and not (wanted_tags & {t.lower() for t in sp.get("tags", [])}):
            continue
        specs.append((int(sp.get("rank", 100 + idx)), idx, sp))
    # Sort by Maigret popularity rank (verified high-signal platforms scanned first!)
    specs.sort(key=lambda item: (item[0], item[1]))
    selected_specs = [item[2] for item in specs[:max_sites]]

    headers = {"User-Agent": "StalkerPlusPlus-OSINT/2.0 (+public-profile-lookup)"}
    use_cb = client is None

    async def _scan_one_handle(c: httpx.AsyncClient, handle: str, handle_specs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sem = asyncio.Semaphore(12)

        async def _guarded(sp: dict[str, Any]) -> Optional[dict[str, Any]]:
            async with sem:
                return await _check_single_site(c, sp, handle, hints, use_circuit_breaker=use_cb)

        raw = await asyncio.gather(*(_guarded(sp) for sp in handle_specs), return_exceptions=True)
        return [r for r in raw if isinstance(r, dict)]

    recursion_tree: list[dict[str, Any]] = []
    visited_handles: set[str] = {clean_u.lower()}
    all_found: list[dict[str, Any]] = []
    total_checked = 0

    async def _execute_with_client(c: httpx.AsyncClient) -> None:
        nonlocal total_checked
        hop1 = await _scan_one_handle(c, clean_u, selected_specs)
        total_checked += len(selected_specs)
        for p in hop1:
            p["hop"] = 1
        all_found.extend(hop1)
        recursion_tree.append({"hop": 1, "handle": clean_u, "hits": len(hop1), "parent": None})

        # Maigret-style recursive pivot: scan newly discovered secondary handles from bios/rel=me
        if recursive_depth >= 2 and hop1:
            next_handles: list[tuple[str, str]] = []
            for p in hop1:
                for nh in (p.get("recursive_pivots") or {}).get("handles", []):
                    nh_clean = nh.strip().lstrip("@")
                    if (
                        nh_clean
                        and nh_clean.lower() not in visited_handles
                        and re.match(r"^[A-Za-z0-9_.-]{3,35}$", nh_clean)
                        and not nh_clean.isdigit()
                    ):
                        visited_handles.add(nh_clean.lower())
                        next_handles.append((nh_clean, f"{p['site']}:{clean_u}"))
                        if len(next_handles) >= max_recursive_handles:
                            break
                if len(next_handles) >= max_recursive_handles:
                    break

            hop2_specs = selected_specs[: min(15, len(selected_specs))]
            for nh_clean, parent_ref in next_handles:
                hop2 = await _scan_one_handle(c, nh_clean, hop2_specs)
                total_checked += len(hop2_specs)
                for p in hop2:
                    p["hop"] = 2
                    p["discovered_from"] = parent_ref
                all_found.extend(hop2)
                recursion_tree.append(
                    {"hop": 2, "handle": nh_clean, "hits": len(hop2), "parent": parent_ref}
                )

    if client is not None:
        await _execute_with_client(client)
    else:
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as temp_client:
            await _execute_with_client(temp_client)

    # Deduplicate by profile URL, keeping highest confidence score
    dedup_by_url: dict[str, dict[str, Any]] = {}
    for p in all_found:
        u_key = p["url"].lower()
        if u_key not in dedup_by_url or int(p["confidence_score"]) > int(dedup_by_url[u_key]["confidence_score"]):
            dedup_by_url[u_key] = p
    found = sorted(dedup_by_url.values(), key=lambda r: int(r.get("confidence_score", 0)), reverse=True)

    agg_handles: list[str] = []
    agg_emails: list[str] = []
    agg_urls: list[str] = []
    for p in found:
        pv = p.get("recursive_pivots") or {}
        for h in pv.get("handles", []):
            if h not in agg_handles:
                agg_handles.append(h)
        for em in pv.get("emails", []):
            if em not in agg_emails:
                agg_emails.append(em)
        for u in pv.get("urls", []) + (p.get("rel_me") or []) + (p.get("same_as") or []):
            if u not in agg_urls:
                agg_urls.append(u)

    return {
        "username": clean_u,
        "checked_sites": total_checked,
        "manifest_total": len(PUBLIC_SITE_MANIFEST),
        "found_profiles": found,
        "discovered_pivots": {
            "handles": agg_handles[:8],
            "emails": agg_emails[:8],
            "urls": agg_urls[:12],
        },
        "recursion_tree": recursion_tree,
    }
