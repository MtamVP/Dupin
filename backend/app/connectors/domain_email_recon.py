"""Multi-Source Zero-Key Passive Domain Infrastructure & Public Email Crypto Identity Recon.

Directly incorporates passive, API-key-free discovery sources from:
- laramies/theHarvester:
  1. Passive DNS over HTTPS (Cloudflare DoH: A, MX, TXT/SPF/Domain Verifications)
  2. Wayback Machine CDX API (`web.archive.org/cdx/search/cdx`: historical subdomains & deleted PDFs)
  3. URLScan.io Public Search (`urlscan.io/api/v1/search`: live/historical URLs, ASNs, IPs)
  4. Shodan InternetDB (`internetdb.shodan.io/{ip}`: open ports, hostnames, CPEs, tags — 0 API key)
  5. RDAP + crt.sh Certificate Transparency (via global_intel.py)
- Public Cryptographic Email Identity:
  6. Gravatar JSON public profile + linked accounts
  7. OpenPGP VKS keyserver (`keys.openpgp.org`)

Strictly Public OSINT Only — never uses forgot-password enumeration or credential dumps.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from typing import Any, Optional
from urllib.parse import quote, urlsplit

import httpx

from app.connectors.global_intel import inspect_domain_infrastructure, is_custom_org_domain
from app.core.normalizer import strip_vietnamese_accents

MAIL_PROVIDER_SIGNATURES: tuple[tuple[str, str], ...] = (
    ("google.com", "Google Workspace"),
    ("googlemail.com", "Google Workspace"),
    ("protection.outlook.com", "Microsoft 365"),
    ("zoho.com", "Zoho Mail"),
    ("protonmail.ch", "Proton Mail"),
    ("mimecast.com", "Mimecast"),
    ("yahoodns.net", "Yahoo Mail"),
    ("yandex.net", "Yandex Mail"),
)


async def query_passive_dns_doh(
    domain: str,
    timeout: float = 5.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Query Cloudflare DNS-over-HTTPS passively for A, MX, and TXT (SPF/verification) records."""
    clean_dom = domain.strip().lower().lstrip("www.")
    if not clean_dom or "." not in clean_dom:
        return {
            "ok": False,
            "domain": clean_dom,
            "ips": [],
            "mx": [],
            "txt": [],
            "mail_provider": "",
            "verifications": [],
        }

    headers = {"Accept": "application/dns-json", "User-Agent": "StalkerPlusPlus/1.0"}
    ip_records: list[str] = []
    mx_records: list[str] = []
    txt_records: list[str] = []
    verifications: list[str] = []

    async def _fetch(c: httpx.AsyncClient) -> None:
        for rtype, target_list in (("A", ip_records), ("MX", mx_records), ("TXT", txt_records)):
            try:
                resp = await c.get(
                    "https://cloudflare-dns.com/dns-query",
                    params={"name": clean_dom, "type": rtype},
                    headers=headers,
                )
                if resp.status_code == 200:
                    for ans in (resp.json().get("Answer") or [])[:15]:
                        val = str(ans.get("data") or "").strip().strip('"')
                        if val:
                            if rtype == "A" and not re.match(r"^\d+\.\d+\.\d+\.\d+$", val):
                                continue
                            target_list.append(val)
            except Exception:
                continue

    if client is not None:
        await _fetch(client)
    else:
        async with httpx.AsyncClient(timeout=timeout) as temp_client:
            await _fetch(temp_client)

    mail_provider = ""
    mx_blob = " ".join(mx_records).lower()
    for sig, label in MAIL_PROVIDER_SIGNATURES:
        if sig in mx_blob:
            mail_provider = label
            break

    for txt in txt_records:
        low = txt.lower()
        for tok in (
            "google-site-verification",
            "ms=",
            "atlassian-domain-verification",
            "facebook-domain-verification",
            "apple-domain-verification",
            "v=spf1",
        ):
            if tok in low:
                verifications.append(txt[:100])
                break

    ok = bool(ip_records or mx_records or txt_records)
    summary_parts: list[str] = []
    if mail_provider:
        summary_parts.append(f"Mail: {mail_provider}")
    elif mx_records:
        summary_parts.append(f"MX: {mx_records[0][:60]}")
    if ip_records:
        summary_parts.append(f"IP: {', '.join(ip_records[:3])}")
    if verifications:
        summary_parts.append(f"TXT ({len(verifications)}): {', '.join(verifications[:2])}")

    return {
        "ok": ok,
        "domain": clean_dom,
        "ips": ip_records[:6],
        "mx": mx_records,
        "txt": txt_records[:10],
        "mail_provider": mail_provider,
        "verifications": verifications[:6],
        "summary": " · ".join(summary_parts) if summary_parts else f"Passive DNS lookup for {clean_dom}",
    }


async def query_wayback_cdx(
    domain: str,
    limit: int = 25,
    timeout: float = 6.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Query Internet Archive Wayback CDX API (theHarvester pattern) for historical subdomains & archived PDFs."""
    clean_dom = domain.strip().lower().lstrip("www.")
    if not clean_dom or "." not in clean_dom:
        return {"ok": False, "domain": clean_dom, "subdomains": [], "archived_pdfs": []}

    url = "https://web.archive.org/cdx/search/cdx"
    params = {
        "url": f"*.{clean_dom}/*",
        "output": "json",
        "fl": "original,timestamp,mimetype",
        "collapse": "urlkey",
        "limit": str(limit),
    }
    headers = {"User-Agent": "StalkerPlusPlus/1.0 (+public-osint)"}

    try:
        if client is not None:
            resp = await client.get(url, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                resp = await temp_client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            return {"ok": False, "domain": clean_dom, "subdomains": [], "archived_pdfs": []}
        rows = resp.json()
        if not isinstance(rows, list) or len(rows) <= 1:
            return {"ok": False, "domain": clean_dom, "subdomains": [], "archived_pdfs": []}
    except Exception:
        return {"ok": False, "domain": clean_dom, "subdomains": [], "archived_pdfs": []}

    subdomains: list[str] = []
    seen_subs: set[str] = set()
    archived_pdfs: list[dict[str, str]] = []

    for row in rows[1:]:
        if not isinstance(row, list) or len(row) < 3:
            continue
        orig_url, ts, mime = str(row[0]), str(row[1]), str(row[2]).lower()
        host = (urlsplit(orig_url).hostname or "").lower().rstrip(".")
        if host and host.endswith(clean_dom) and host not in seen_subs:
            seen_subs.add(host)
            subdomains.append(host)
        if "pdf" in mime or orig_url.lower().endswith(".pdf"):
            archived_pdfs.append(
                {
                    "original_url": orig_url,
                    "wayback_url": f"https://web.archive.org/web/{ts}/{orig_url}",
                    "timestamp": ts[:8],
                }
            )

    return {
        "ok": bool(subdomains or archived_pdfs),
        "domain": clean_dom,
        "subdomains": subdomains[:15],
        "archived_pdfs": archived_pdfs[:8],
    }


async def query_urlscan_domain(
    domain: str,
    timeout: float = 6.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Query public URLScan.io Search API (theHarvester pattern) for subdomains, ASNs, and IPs."""
    clean_dom = domain.strip().lower().lstrip("www.")
    if not clean_dom or "." not in clean_dom:
        return {"ok": False, "domain": clean_dom, "subdomains": [], "asns": [], "ips": []}

    url = "https://urlscan.io/api/v1/search/"
    params = {"q": f"domain:{clean_dom}", "size": "10"}
    headers = {"User-Agent": "StalkerPlusPlus/1.0 (+public-osint)"}

    try:
        if client is not None:
            resp = await client.get(url, params=params, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                resp = await temp_client.get(url, params=params, headers=headers)
        if resp.status_code != 200:
            return {"ok": False, "domain": clean_dom, "subdomains": [], "asns": [], "ips": []}
        results = (resp.json() or {}).get("results") or []
    except Exception:
        return {"ok": False, "domain": clean_dom, "subdomains": [], "asns": [], "ips": []}

    subdomains: list[str] = []
    asns: list[str] = []
    ips: list[str] = []
    for item in results:
        page = item.get("page") or {}
        dom = str(page.get("domain") or "").lower().strip()
        if dom and dom.endswith(clean_dom) and dom not in subdomains:
            subdomains.append(dom)
        asn = str(page.get("asnname") or page.get("asn") or "").strip()
        if asn and asn not in asns:
            asns.append(asn)
        ip = str(page.get("ip") or "").strip()
        if ip and ip not in ips:
            ips.append(ip)

    return {
        "ok": bool(subdomains or asns or ips),
        "domain": clean_dom,
        "subdomains": subdomains[:12],
        "asns": asns[:5],
        "ips": ips[:6],
    }


async def query_shodan_internetdb(
    ip_address: str,
    timeout: float = 5.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Query free, zero-API-key Shodan InternetDB (`internetdb.shodan.io/{ip}`, theHarvester pattern)."""
    clean_ip = ip_address.strip()
    if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", clean_ip):
        return {"ok": False, "ip": clean_ip, "ports": [], "hostnames": [], "tags": []}

    url = f"https://internetdb.shodan.io/{quote(clean_ip)}"
    headers = {"User-Agent": "StalkerPlusPlus/1.0 (+public-osint)"}
    try:
        if client is not None:
            resp = await client.get(url, headers=headers)
        else:
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                resp = await temp_client.get(url, headers=headers)
        if resp.status_code != 200:
            return {"ok": False, "ip": clean_ip, "ports": [], "hostnames": [], "tags": []}
        data = resp.json()
        return {
            "ok": True,
            "ip": clean_ip,
            "ports": list(data.get("ports") or [])[:15],
            "hostnames": list(data.get("hostnames") or [])[:10],
            "tags": list(data.get("tags") or [])[:10],
            "cpes": list(data.get("cpes") or [])[:8],
        }
    except Exception:
        return {"ok": False, "ip": clean_ip, "ports": [], "hostnames": [], "tags": []}


async def run_full_passive_domain_recon(
    domain: str,
    timeout: float = 6.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Run 5 zero-key passive domain telemetry sources concurrently (theHarvester + Amass pattern)."""
    clean_dom = domain.strip().lower().lstrip("www.")
    if not is_custom_org_domain(clean_dom):
        return {"ok": False, "domain": clean_dom, "provider_count": 0, "summary": ""}

    dns_res, infra_res, cdx_res, urlscan_res = await asyncio.gather(
        query_passive_dns_doh(clean_dom, timeout=timeout, client=client),
        inspect_domain_infrastructure(clean_dom, timeout=timeout, client=client),
        query_wayback_cdx(clean_dom, timeout=timeout, client=client),
        query_urlscan_domain(clean_dom, timeout=timeout, client=client),
        return_exceptions=True,
    )
    dns_d = dns_res if isinstance(dns_res, dict) else {"ok": False}
    infra_d = infra_res if isinstance(infra_res, dict) else {"ok": False}
    cdx_d = cdx_res if isinstance(cdx_res, dict) else {"ok": False}
    urlscan_d = urlscan_res if isinstance(urlscan_res, dict) else {"ok": False}

    # Optional Hop: Shodan InternetDB lookup on primary resolved IP (0 API key)
    shodan_d: dict[str, Any] = {"ok": False}
    ips = (dns_d.get("ips") or []) + (urlscan_d.get("ips") or [])
    if ips:
        shodan_d = await query_shodan_internetdb(ips[0], timeout=timeout, client=client)

    all_subs = list(
        dict.fromkeys(
            (infra_d.get("subdomains") or [])
            + (cdx_d.get("subdomains") or [])
            + (urlscan_d.get("subdomains") or [])
            + (shodan_d.get("hostnames") or [])
        )
    )
    providers = [
        name
        for name, res in (
            ("Cloudflare DoH", dns_d),
            ("RDAP/crt.sh", infra_d),
            ("Wayback CDX", cdx_d),
            ("URLScan.io", urlscan_d),
            ("Shodan InternetDB", shodan_d),
        )
        if res.get("ok")
    ]

    summary_parts: list[str] = []
    if dns_d.get("mail_provider"):
        summary_parts.append(f"Mail: {dns_d['mail_provider']}")
    if urlscan_d.get("asns"):
        summary_parts.append(f"ASN: {urlscan_d['asns'][0]}")
    if shodan_d.get("ports"):
        summary_parts.append(f"Ports: {','.join(str(p) for p in shodan_d['ports'][:6])}")
    if all_subs:
        summary_parts.append(f"Subdomains ({len(all_subs)}): {', '.join(all_subs[:6])}")
    if cdx_d.get("archived_pdfs"):
        summary_parts.append(f"Wayback PDFs: {len(cdx_d['archived_pdfs'])}")

    return {
        "ok": bool(providers),
        "domain": clean_dom,
        "providers": providers,
        "provider_count": len(providers),
        "subdomains": all_subs[:25],
        "archived_pdfs": cdx_d.get("archived_pdfs") or [],
        "passive_dns": dns_d,
        "domain_infra": infra_d,
        "wayback_cdx": cdx_d,
        "urlscan": urlscan_d,
        "shodan_internetdb": shodan_d,
        "url": infra_d.get("url") or f"https://crt.sh/?q={quote(clean_dom)}",
        "summary": " · ".join(summary_parts) if summary_parts else f"Passive recon for {clean_dom}",
    }


async def inspect_public_email_crypto_identity(
    email: str,
    timeout: float = 5.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Check public Gravatar profile JSON and keys.openpgp.org public key existence for an email."""
    clean_em = email.strip().lower()
    if "@" not in clean_em:
        return {"ok": False, "email": clean_em, "gravatar": None, "openpgp_found": False}

    md5_hash = hashlib.md5(clean_em.encode("utf-8")).hexdigest()
    headers = {"User-Agent": "StalkerPlusPlus/1.0 (+public-osint)"}
    gravatar_data: Optional[dict[str, Any]] = None
    openpgp_found = False
    openpgp_url = f"https://keys.openpgp.org/vks/v1/by-email/{quote(clean_em)}"

    async def _run(c: httpx.AsyncClient) -> None:
        nonlocal gravatar_data, openpgp_found
        try:
            r_grav = await c.get(f"https://www.gravatar.com/{md5_hash}.json", headers=headers)
            if r_grav.status_code == 200:
                entries = (r_grav.json() or {}).get("entry") or []
                if entries:
                    e0 = entries[0]
                    accounts = [
                        {"shortname": str(a.get("shortname") or ""), "url": str(a.get("url") or "")}
                        for a in (e0.get("accounts") or [])
                        if a.get("url")
                    ]
                    gravatar_data = {
                        "profile_url": str(e0.get("profileUrl") or f"https://gravatar.com/{md5_hash}"),
                        "display_name": str(e0.get("displayName") or ""),
                        "about": str(e0.get("aboutMe") or ""),
                        "location": str(e0.get("currentLocation") or ""),
                        "linked_accounts": accounts[:8],
                    }
        except Exception:
            pass

        try:
            r_pgp = await c.get(openpgp_url, headers=headers)
            if r_pgp.status_code == 200 and "BEGIN PGP PUBLIC KEY BLOCK" in r_pgp.text:
                openpgp_found = True
        except Exception:
            pass

    if client is not None:
        await _run(client)
    else:
        async with httpx.AsyncClient(timeout=timeout) as temp_client:
            await _run(temp_client)

    ok = bool(gravatar_data or openpgp_found)
    parts: list[str] = []
    if gravatar_data:
        parts.append(
            f"Gravatar public profile: {gravatar_data.get('display_name') or md5_hash}"
            + (f" · Linked accounts: {len(gravatar_data['linked_accounts'])}" if gravatar_data["linked_accounts"] else "")
        )
    if openpgp_found:
        parts.append("Public OpenPGP key published on keys.openpgp.org")

    return {
        "ok": ok,
        "email": clean_em,
        "gravatar_md5": md5_hash,
        "gravatar": gravatar_data,
        "openpgp_found": openpgp_found,
        "openpgp_url": openpgp_url if openpgp_found else "",
        "summary": " · ".join(parts) if parts else "",
    }


def infer_corporate_email_patterns(full_name: str, domain: str) -> list[str]:
    """Generate likely public corporate/academic email patterns (theHarvester pattern)."""
    clean_dom = domain.strip().lower().lstrip("www.")
    tokens = [t for t in re.split(r"\s+", strip_vietnamese_accents(full_name).lower()) if t.isalpha()]
    if not tokens or "." not in clean_dom:
        return []
    first = tokens[0]
    last = tokens[-1]
    if len(tokens) == 1:
        return [f"{first}@{clean_dom}"]
    return list(
        dict.fromkeys(
            [
                f"{first}.{last}@{clean_dom}",
                f"{last}.{first}@{clean_dom}",
                f"{first[0]}{last}@{clean_dom}",
                f"{last}{first[0]}@{clean_dom}",
                f"{''.join(tokens)}@{clean_dom}",
            ]
        )
    )
