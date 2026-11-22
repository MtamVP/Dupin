"""Unit & integration tests for Stalker++ OSINT Ecosystem Plugins (100% synthetic data & offline mocks):
- Sherlock / Maigret / Social-Analyzer username scanner + recursive bio pivot extraction
- PhoneInfoga E.164 & Vietnamese carrier analyzer + multi-format dorks
- theHarvester / Amass passive DNS (DoH) + Gravatar & OpenPGP public email crypto identity
- SpiderFoot-style multi-hop EventDrivenPluginBus (Handle -> Bio Email -> PGP + Passive DNS)
- OpenOSINT / yogsec CLI bridge discovery + 11 MCP tools
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.connectors.domain_email_recon import (
    infer_corporate_email_patterns,
    inspect_public_email_crypto_identity,
    query_passive_dns_doh,
)
from app.connectors.external_tools_bridge import detect_installed_osint_clis
from app.connectors.phone_recon import analyze_phone_number, extract_phone_candidates
from app.connectors.username_recon import (
    extract_recursive_pivots,
    scan_username_profiles,
)
from app.core.graph_store import GraphStore
from app.plugins.base import OSINTEvent
from app.plugins.registry import PluginRegistry


@pytest.mark.asyncio
async def test_username_scanner_soft404_scoring_and_recursive_bio_pivots() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "api.github.com/users/alexdemo99" in url:
            return httpx.Response(
                200,
                json={
                    "login": "alexdemo99",
                    "name": "Alex Demo",
                    "bio": "ML researcher at ExampleLab. Contact: alex@examplelab.org · alt @alex_ml",
                    "company": "ExampleLab",
                    "location": "Singapore",
                    "avatar_url": "https://avatars.example.com/1",
                },
            )
        if "hacker-news.firebaseio.com/v0/user/alexdemo99.json" in url:
            return httpx.Response(
                200,
                json={"id": "alexdemo99", "karma": 420, "about": "Working on ExampleLab OSS"},
            )
        if "pypi.org/user/alexdemo99" in url:
            # Simulated Soft-404 page returning HTTP 200 with "Page Not Found"
            return httpx.Response(200, text="<html><title>Page Not Found · PyPI</title></html>")
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        res = await scan_username_profiles(
            "@alexdemo99",
            target_hints=["Alex Demo", "ExampleLab"],
            sites=["GitHub", "HackerNews", "PyPI", "GitLab"],
            client=client,
        )

    assert res["checked_sites"] == 4
    found_sites = {p["site"] for p in res["found_profiles"]}
    assert found_sites == {"GitHub", "HackerNews"}  # PyPI Soft-404 rejected, GitLab 404 rejected
    gh_prof = next(p for p in res["found_profiles"] if p["site"] == "GitHub")
    assert gh_prof["confidence_score"] >= 90
    assert "alex@examplelab.org" in res["discovered_pivots"]["emails"]
    assert "alex_ml" in res["discovered_pivots"]["handles"]

    # Direct recursive pivot extractor check
    pv = extract_recursive_pivots("Reach me at demo@acme.org or @alt_dev", "seed_user")
    assert pv["emails"] == ["demo@acme.org"]
    assert pv["handles"] == ["alt_dev"]


def test_phone_infoga_vn_and_international_dorks() -> None:
    vn = analyze_phone_number("0987.654.321", name_hint="Nguyễn Minh Anh")
    assert vn["valid"] is True
    assert vn["country_iso"] == "VN"
    assert vn["carrier"] == "Viettel"
    assert vn["e164"] == "+84987654321"
    assert "0987.654.321" in vn["formatted_variants"]
    assert any(d["strategy"] == "phone:name_intersection" for d in vn["dorks"])
    assert any("chotot.com" in d["query"] for d in vn["dorks"])

    us = analyze_phone_number("+1 415 555 0199")
    assert us["valid"] is True
    assert us["country_iso"] == "US/CA"
    assert us["e164"] == "+14155550199"

    extracted = extract_phone_candidates("Liên hệ 0909 123 456 hoặc +65 8123 4567, MSSV 31251029999")
    assert len(extracted) == 2


@pytest.mark.asyncio
async def test_passive_dns_doh_gravatar_openpgp_and_spiderfoot_event_bus() -> None:
    target_email = "alex@examplelab.org"
    md5_hex = hashlib.md5(target_email.encode("utf-8")).hexdigest()

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        if "api.github.com/users/alexdemo99" in url:
            return httpx.Response(
                200,
                json={
                    "login": "alexdemo99",
                    "name": "Alex Demo",
                    "bio": f"Email: {target_email}",
                    "avatar_url": "https://avatars.example.com/1",
                },
            )
        if f"gravatar.com/{md5_hex}.json" in url:
            return httpx.Response(
                200,
                json={
                    "entry": [
                        {
                            "displayName": "Alex Demo",
                            "profileUrl": f"https://gravatar.com/{md5_hex}",
                            "accounts": [{"shortname": "mastodon", "url": "https://mastodon.social/@alexdemo"}],
                        }
                    ]
                },
            )
        if "keys.openpgp.org/vks/v1/by-email/" in url:
            return httpx.Response(200, text="-----BEGIN PGP PUBLIC KEY BLOCK-----\nMOCK\n-----END PGP PUBLIC KEY BLOCK-----")
        if "cloudflare-dns.com/dns-query" in url:
            if "type=MX" in url:
                return httpx.Response(200, json={"Answer": [{"data": "10 aspmx.l.google.com."}]})
            if "type=TXT" in url:
                return httpx.Response(200, json={"Answer": [{"data": '"v=spf1 include:_spf.google.com ~all"'}]})
        if "rdap.org/domain/examplelab.org" in url:
            return httpx.Response(200, json={"events": [{"eventAction": "registration", "eventDate": "2020-05-01T00:00:00Z"}]})
        if "crt.sh" in url:
            return httpx.Response(200, json=[{"name_value": "portal.examplelab.org"}])
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        # Direct unit checks
        dns = await query_passive_dns_doh("examplelab.org", client=client)
        assert dns["ok"] is True
        assert dns["mail_provider"] == "Google Workspace"

        em_id = await inspect_public_email_crypto_identity(target_email, client=client)
        assert em_id["ok"] is True
        assert em_id["openpgp_found"] is True
        assert em_id["gravatar"]["display_name"] == "Alex Demo"

        patterns = infer_corporate_email_patterns("Nguyễn Minh Anh", "examplelab.org")
        assert "nguyen.anh@examplelab.org" in patterns

        # Full SpiderFoot-style 2-hop EventDrivenPluginBus cascade:
        # Hop 1: HANDLE_FOUND:alexdemo99 -> GitHub bio reveals EMAIL_FOUND:alex@examplelab.org
        # Hop 2: EMAIL_FOUND:alex@examplelab.org -> Gravatar + OpenPGP + emits DOMAIN_FOUND:examplelab.org
        bus = PluginRegistry().create_event_bus()
        bus_res = await bus.run(
            seed_events=[OSINTEvent(event_type="HANDLE_FOUND", value="alexdemo99")],
            context={"client": client, "target_hints": ["Alex Demo"]},
            max_hops=2,
        )

    urls = [s["url"] for s in bus_res["sources"]]
    assert any("github.com/alexdemo99" in u for u in urls)
    assert any("gravatar.com" in u for u in urls)
    assert any("keys.openpgp.org" in u for u in urls)
    assert len(bus_res["trace"]) >= 2


def test_mcp_11_tools_rest_endpoints_and_cli_bridge(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "eco_api.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    # 1. MCP Server exposes all 11 tools including the 3 new ecosystem tools
    mcp_resp = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert mcp_resp.status_code == 200
    tool_names = {t["name"] for t in mcp_resp.json()["result"]["tools"]}
    assert len(tool_names) >= 11
    assert {"stalker_scan_username", "stalker_analyze_phone", "stalker_recon_domain_email"}.issubset(tool_names)

    # 2. Call stalker_analyze_phone via MCP & REST
    mcp_phone = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "stalker_analyze_phone", "arguments": {"phone": "0901234567"}},
        },
    )
    assert mcp_phone.status_code == 200
    assert "MobiFone" in mcp_phone.json()["result"]["content"][0]["text"]

    rest_phone = client.post("/api/tools/analyze-phone", json={"phone": "0912345678", "name_hint": "Demo User"})
    assert rest_phone.status_code == 200
    assert rest_phone.json()["carrier"] == "VinaPhone"

    # 3. Plugins API now exposes all 11 built-in plugins including CLI bridge
    p_resp = client.get("/api/plugins")
    pids = {p["id"] for p in p_resp.json()["plugins"]}
    assert {
        "username_multi_platform",
        "phone_footprint_analyzer",
        "passive_dns_email_crypto",
        "external_osint_cli_bridge",
    }.issubset(pids)

    # 4. External CLI detector runs safely
    clis = detect_installed_osint_clis()
    assert {c["id"] for c in clis} == {"sherlock", "maigret", "theHarvester", "phoneinfoga", "amass"}


@pytest.mark.asyncio
async def test_deep_source_inspired_engines_metadata_5source_recon_and_correlator(tmp_path: Path) -> None:
    import json
    from app.connectors.domain_email_recon import run_full_passive_domain_recon
    from app.connectors.metadata_extractor import extract_structured_html_metadata
    from app.connectors.username_recon import PUBLIC_SITE_MANIFEST, load_sites_manifest
    from app.plugins.correlator import OSINTCorrelator

    # 1. Verify Maigret-compatible 45-site manifest + DiscourseJson/MastodonApi expansion + custom JSON import
    assert len(PUBLIC_SITE_MANIFEST) >= 40
    site_names = {s["site"] for s in PUBLIC_SITE_MANIFEST}
    assert "UIT Forum (Discourse)" in site_names
    assert "Mastodon.social" in site_names
    assert "Viblo" in site_names

    custom_file = tmp_path / "custom_maigret.json"
    custom_file.write_text(
        json.dumps(
            {
                "sites": {
                    "CustomOSS": {
                        "url": "https://custom-oss.example.org/u/{username}",
                        "presenseStrs": ["profile"],
                        "absenceStrs": ["not found"],
                        "tags": ["coding"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    extended = load_sites_manifest(extra_manifest_path=custom_file)
    assert any(s["site"] == "CustomOSS" for s in extended)

    # 2. Social-Analyzer metadata extractor: filters viewport/charset, extracts JSON-LD Person + rel="me"
    sample_html = """
    <html>
      <head>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <meta property="og:title" content="Alex Demo Profile" />
        <meta property="og:image" content="https://cdn.example.org/avatar.png" />
        <script type="application/ld+json">
          {"@type": "Person", "name": "Alex Demo", "jobTitle": "Security Researcher",
           "worksFor": {"name": "ExampleLab"}, "alumniOf": {"name": "Demo University"},
           "sameAs": ["https://github.com/alexdemo99"]}
        </script>
      </head>
      <body>
        <a rel="me" href="https://mastodon.social/@alexdemo99">Mastodon</a>
      </body>
    </html>
    """
    meta = extract_structured_html_metadata(sample_html)
    assert "viewport" not in meta["meta"]
    assert meta["jsonld_person"]["works_for"] == "ExampleLab"
    assert meta["jsonld_person"]["alumni_of"] == "Demo University"
    assert "https://mastodon.social/@alexdemo99" in meta["rel_me"]
    assert "https://github.com/alexdemo99" in meta["same_as"]

    # 3. PhoneInfoga 5-category dorks + RFC3966 check
    ph = analyze_phone_number("0987.654.321")
    assert set(ph["dork_categories"].keys()) == {
        "general",
        "social_media",
        "disposable_providers",
        "reputation",
        "individuals",
    }
    assert ph["rfc3966"] == "+84-98-765-4321"

    # 4. theHarvester 5-source zero-key passive domain recon (DoH + RDAP/crt.sh + Wayback CDX + URLScan + Shodan InternetDB)
    def recon_handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if "cloudflare-dns.com" in u:
            if "type=A" in u:
                return httpx.Response(200, json={"Answer": [{"data": "93.184.216.34"}]})
            if "type=MX" in u:
                return httpx.Response(200, json={"Answer": [{"data": "10 mail.protection.outlook.com."}]})
            return httpx.Response(200, json={"Answer": [{"data": '"v=spf1 include:spf.protection.outlook.com"'}]})
        if "rdap.org/domain/examplelab.org" in u:
            return httpx.Response(200, json={"events": [{"eventAction": "registration", "eventDate": "2019-01-01T00:00:00Z"}]})
        if "crt.sh" in u:
            return httpx.Response(200, json=[{"name_value": "api.examplelab.org"}])
        if "web.archive.org/cdx" in u:
            return httpx.Response(
                200,
                json=[
                    ["original", "timestamp", "mimetype"],
                    ["https://docs.examplelab.org/2024/report.pdf", "20240501120000", "application/pdf"],
                ],
            )
        if "urlscan.io/api/v1/search" in u:
            return httpx.Response(
                200,
                json={"results": [{"page": {"domain": "portal.examplelab.org", "asnname": "CLOUDFLARENET", "ip": "93.184.216.34"}}]},
            )
        if "internetdb.shodan.io/93.184.216.34" in u:
            return httpx.Response(
                200,
                json={"ports": [80, 443], "hostnames": ["edge.examplelab.org"], "tags": ["cloud"], "cpes": []},
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(recon_handler)) as client:
        full_dom = await run_full_passive_domain_recon("examplelab.org", client=client)

    assert full_dom["ok"] is True
    assert full_dom["provider_count"] == 5
    assert "Wayback CDX" in full_dom["providers"]
    assert "URLScan.io" in full_dom["providers"]
    assert "Shodan InternetDB" in full_dom["providers"]
    assert len(full_dom["archived_pdfs"]) == 1
    assert {"api.examplelab.org", "docs.examplelab.org", "portal.examplelab.org", "edge.examplelab.org"}.issubset(
        set(full_dom["subdomains"])
    )

    # 5. SpiderFoot Cross-Module Correlator verifies multi-platform + rel="me" + multi-feed infra + multi-hop
    corrs = OSINTCorrelator().evaluate(
        sources=[
            {
                "site": "GitHub",
                "url": "https://github.com/alexdemo99",
                "display_name": "Alex Demo",
                "rel_me": ["https://mastodon.social/@alexdemo99"],
            },
            {
                "site": "Mastodon.social",
                "url": "https://mastodon.social/@alexdemo99",
                "display_name": "Alex Demo",
            },
            {
                "title": "Multi-Source Passive Recon (5 feeds): examplelab.org",
                "url": "https://crt.sh/?q=examplelab.org",
                "snippet": full_dom["summary"],
                "infra_provider_count": 5,
            },
        ],
        processed_events=[],
        trace=[{"hop": 2, "plugin": "passive_dns_email_crypto", "trigger": "EMAIL_FOUND:alex@examplelab.org"}],
    )
    rule_ids = {c["rule_id"] for c in corrs}
    assert "CORR_CROSS_PLATFORM_IDENTITY" in rule_ids
    assert "CORR_INDIEWEB_REL_ME" in rule_ids
    assert "CORR_MULTI_SOURCE_INFRASTRUCTURE" in rule_ids
    assert "CORR_MULTI_HOP_PIVOT_CHAIN" in rule_ids
