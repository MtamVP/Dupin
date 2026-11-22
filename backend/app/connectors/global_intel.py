"""Global Structured Public OSINT Connectors (100% Free, Public APIs — Zero Auth Bypass).

Provides structured intelligence across worldwide public registries:
1. OpenAlex / ORCID Academic Author & Institution Lookup (250M+ scholars globally)
2. RDAP + crt.sh Certificate Transparency Infrastructure Lookup (custom domains/orgs)
3. GitHub Public User Search by Full Name + Organization (even without prior @handle)
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote

import httpx

from app.core.normalizer import normalize_text

FREE_EMAIL_DOMAINS: set[str] = {
    "gmail.com",
    "googlemail.com",
    "yahoo.com",
    "outlook.com",
    "hotmail.com",
    "live.com",
    "icloud.com",
    "me.com",
    "proton.me",
    "protonmail.com",
    "aol.com",
    "zoho.com",
    "mail.com",
    "yandex.com",
}


def is_custom_org_domain(domain: str) -> bool:
    """Return True if domain is an organizational/personal domain worth RDAP/crt.sh inspection."""
    d = domain.strip().lower().lstrip("www.")
    if not d or "." not in d or d in FREE_EMAIL_DOMAINS:
        return False
    return True


async def search_openalex_authors(
    full_name: str,
    organizations: Optional[list[str]] = None,
    timeout: float = 7.0,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """Query the free OpenAlex Authors API for global researchers, affiliations, ORCID, and works."""
    clean_name = full_name.strip()
    if len(clean_name) < 3:
        return []

    url = "https://api.openalex.org/authors"
    params = {"search": clean_name, "per-page": "5"}
    headers = {"User-Agent": "StalkerPlusPlus/1.0 (https://github.com/stalker-pp; public-osint)"}

    try:
        if client is not None:
            resp = await client.get(url, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                resp = await temp_client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            return []
        raw_results = resp.json().get("results", []) or []
    except Exception:
        return []

    norm_target = normalize_text(clean_name)
    norm_orgs = [normalize_text(o) for o in (organizations or []) if len(o.strip()) >= 2]

    matched: list[dict[str, Any]] = []
    for item in raw_results:
        disp_name = str(item.get("display_name") or "").strip()
        if not disp_name:
            continue
        norm_disp = normalize_text(disp_name)
        # Require strong name overlap (all tokens or substring)
        target_tokens = [t for t in norm_target.split() if len(t) >= 2]
        if not target_tokens:
            continue
        token_hits = sum(1 for t in target_tokens if t in norm_disp)
        if token_hits < max(2, len(target_tokens) - 1) and norm_target not in norm_disp:
            continue

        insts: list[str] = []
        years_active: list[int] = []
        for aff in item.get("affiliations") or []:
            inst = (aff.get("institution") or {}).get("display_name")
            if inst and inst not in insts:
                insts.append(str(inst))
            for y in aff.get("years") or []:
                if isinstance(y, int):
                    years_active.append(y)
        for lki in item.get("last_known_institutions") or []:
            inst = lki.get("display_name")
            if inst and inst not in insts:
                insts.append(str(inst))

        inst_blob = normalize_text(" ".join(insts))
        org_matched = any(o in inst_blob for o in norm_orgs) if norm_orgs else False

        # If user specified organizations, prefer authors whose affiliation matches OR who have high citation relevance
        works_count = int(item.get("works_count") or 0)
        cited_by = int(item.get("cited_by_count") or 0)
        if norm_orgs and not org_matched:
            continue

        orcid = str(item.get("orcid") or "").strip()
        oa_url = str(item.get("id") or "").strip()
        best_url = orcid or oa_url
        if not best_url:
            continue

        yr_span = f"{min(years_active)}–{max(years_active)}" if years_active else ""
        inst_str = ", ".join(insts[:3]) if insts else "Independent / Unlisted"
        snippet = (
            f"OpenAlex Scholar · Affiliations: {inst_str}"
            + (f" ({yr_span})" if yr_span else "")
            + f" · Works: {works_count}, Citations: {cited_by}"
            + (f" · ORCID: {orcid}" if orcid else "")
        )
        matched.append(
            {
                "title": f"{disp_name} — Academic Profile (OpenAlex / ORCID)",
                "url": best_url,
                "snippet": snippet,
                "orcid": orcid,
                "affiliations": insts[:5],
                "years": sorted(set(years_active))[-6:],
                "works_count": works_count,
                "cited_by_count": cited_by,
                "org_matched": org_matched,
            }
        )
    return matched[:3]


async def inspect_domain_infrastructure(
    domain: str,
    timeout: float = 6.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Query public RDAP registration metadata and crt.sh Certificate Transparency logs for a domain."""
    clean_dom = domain.strip().lower().lstrip("www.")
    if not is_custom_org_domain(clean_dom):
        return {"ok": False, "domain": clean_dom, "subdomains": [], "events": {}}

    headers = {"User-Agent": "StalkerPlusPlus/1.0 (+public-osint)"}
    rdap_events: dict[str, str] = {}
    registrar = ""
    subdomains: list[str] = []

    async def _run(c: httpx.AsyncClient) -> None:
        nonlocal registrar, subdomains
        # 1. RDAP public registry
        try:
            r_rdap = await c.get(f"https://rdap.org/domain/{quote(clean_dom)}", headers=headers, follow_redirects=True)
            if r_rdap.status_code == 200:
                data = r_rdap.json()
                for ev in data.get("events") or []:
                    action = str(ev.get("eventAction") or "")
                    dt = str(ev.get("eventDate") or "")[:10]
                    if action and dt:
                        rdap_events[action] = dt
                for ent in data.get("entities") or []:
                    roles = ent.get("roles") or []
                    if "registrar" in roles:
                        vcard = ent.get("vcardArray") or []
                        if len(vcard) >= 2 and isinstance(vcard[1], list):
                            for prop in vcard[1]:
                                if isinstance(prop, list) and len(prop) >= 4 and prop[0] == "fn":
                                    registrar = str(prop[3])
                                    break
        except Exception:
            pass

        # 2. crt.sh Certificate Transparency logs
        try:
            r_crt = await c.get(
                "https://crt.sh/",
                params={"q": f"%.{clean_dom}", "output": "json"},
                headers=headers,
            )
            if r_crt.status_code == 200:
                seen_subs: set[str] = set()
                for row in (r_crt.json() or [])[:120]:
                    nv = str(row.get("name_value") or "")
                    for line in nv.splitlines():
                        host = line.strip().lower().lstrip("*.")
                        if host.endswith(clean_dom) and host not in seen_subs:
                            seen_subs.add(host)
                            subdomains.append(host)
                            if len(subdomains) >= 15:
                                break
                    if len(subdomains) >= 15:
                        break
        except Exception:
            pass

    if client is not None:
        await _run(client)
    else:
        async with httpx.AsyncClient(timeout=timeout) as temp_client:
            await _run(temp_client)

    ok = bool(rdap_events or registrar or subdomains)
    parts: list[str] = []
    if registrar:
        parts.append(f"Registrar: {registrar}")
    if rdap_events.get("registration"):
        parts.append(f"Created: {rdap_events['registration']}")
    if subdomains:
        parts.append(f"CT Subdomains ({len(subdomains)}): {', '.join(subdomains[:6])}")

    return {
        "ok": ok,
        "domain": clean_dom,
        "registrar": registrar,
        "events": rdap_events,
        "subdomains": subdomains,
        "summary": " · ".join(parts) if parts else f"Public infrastructure record for {clean_dom}",
        "url": f"https://crt.sh/?q={quote(clean_dom)}",
    }


async def search_github_by_name(
    full_name: str,
    organizations: Optional[list[str]] = None,
    timeout: float = 6.0,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """Search public GitHub users by full name (for targets without a known @handle)."""
    clean_name = full_name.strip()
    if len(clean_name) < 3:
        return []

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "StalkerPlusPlus/1.0 (+public-osint)",
    }
    q = f'"{clean_name}" in:name'
    try:
        if client is not None:
            resp = await client.get("https://api.github.com/search/users", params={"q": q, "per_page": "3"}, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                resp = await temp_client.get(
                    "https://api.github.com/search/users",
                    params={"q": q, "per_page": "3"},
                    headers=headers,
                )
        if resp.status_code != 200:
            return []
        items = resp.json().get("items", []) or []
    except Exception:
        return []

    norm_orgs = [normalize_text(o) for o in (organizations or []) if len(o.strip()) >= 2]
    results: list[dict[str, Any]] = []

    async def _enrich(c: httpx.AsyncClient, login: str) -> Optional[dict[str, Any]]:
        try:
            pr = await c.get(f"https://api.github.com/users/{quote(login)}", headers=headers)
            if pr.status_code != 200:
                return None
            u = pr.json()
            bio = str(u.get("bio") or "")
            comp = str(u.get("company") or "")
            loc = str(u.get("location") or "")
            name = str(u.get("name") or login)
            blob = normalize_text(f"{name} {bio} {comp} {loc}")
            org_match = any(o in blob for o in norm_orgs) if norm_orgs else True
            # If orgs were provided and user has >1 candidates, prefer org-matching profiles
            if norm_orgs and not org_match and len(items) > 1:
                return None
            # Reject empty impersonator accounts (0 public repos AND 0 followers) when searching by name
            repos_cnt = int(u.get("public_repos") or 0)
            foll_cnt = int(u.get("followers") or 0)
            if repos_cnt == 0 and foll_cnt == 0:
                return None
            snippet = (
                f"{name} (@{login})"
                + (f" · Bio: {bio}" if bio else "")
                + (f" · Org: {comp}" if comp else "")
                + (f" · Location: {loc}" if loc else "")
                + f" · Repos: {u.get('public_repos', 0)}"
            )
            return {
                "username": login,
                "title": f"{name} (@{login}) · GitHub",
                "url": str(u.get("html_url") or f"https://github.com/{login}"),
                "snippet": snippet[:280],
                "org_matched": org_match,
            }
        except Exception:
            return None

    if client is not None:
        for it in items[:2]:
            login = str(it.get("login") or "").strip()
            if login:
                prof = await _enrich(client, login)
                if prof:
                    results.append(prof)
    else:
        async with httpx.AsyncClient(timeout=timeout) as temp_client:
            for it in items[:2]:
                login = str(it.get("login") or "").strip()
                if login:
                    prof = await _enrich(temp_client, login)
                    if prof:
                        results.append(prof)
    return results
