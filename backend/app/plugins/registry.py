"""Built-in Event-Driven Plugin Registry with automatic discovery of user-dropped community plugins."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from app.connectors.domain_email_recon import (
    inspect_public_email_crypto_identity,
    run_full_passive_domain_recon,
)
from app.connectors.external_tools_bridge import detect_installed_osint_clis
from app.connectors.global_intel import is_custom_org_domain
from app.connectors.phone_recon import analyze_phone_number
from app.connectors.username_recon import PUBLIC_SITE_MANIFEST, scan_username_profiles
from app.connectors.web_search import test_searxng_connection
from app.core.key_pool import IntegrationStore
from app.plugins.base import ConnectorPlugin, OSINTEvent, PluginExecutionResult, PluginManifest
from app.plugins.event_bus import EventDrivenPluginBus


class ParallelMetasearchPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="parallel_metasearch",
        name="Parallel SearXNG + ddgs Consensus Engine",
        version="1.0.0",
        category="search",
        description="Queries self-hosted SearXNG and ddgs concurrently with fair round-robin interleaving and consensus boosting.",
        local_only=True,
        capabilities=["web_search", "consensus_ranking", "boolean_dorks"],
        inspired_by=["searxng", "ddgs"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        db_path = context.get("db_path")
        if not db_path:
            return {"ready": True, "detail": "ddgs active"}
        cfg = IntegrationStore(db_path).get_local_config()
        if cfg.searxng_url.strip():
            probe = await test_searxng_connection(cfg.searxng_url.strip(), timeout=2.5)
            if probe.get("reachable") and probe.get("json_enabled"):
                return {
                    "ready": True,
                    "detail": f"SearXNG ({cfg.searxng_url}) + ddgs parallel",
                    "engines": probe.get("engines", []),
                }
            return {"ready": True, "detail": f"ddgs active (SearXNG offline: {cfg.searxng_url})"}
        return {"ready": True, "detail": "ddgs active (SearXNG optional)"}


class DeepDocumentReaderPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="deep_document_reader",
        name="Deep PDF & Excel Table Inspector",
        version="1.0.0",
        category="document",
        description="Downloads public PDF/XLSX admission, scholarship, and decision lists to extract exact matching target rows.",
        local_only=True,
        capabilities=["pdf_text_extraction", "xlsx_row_matching", "scanned_pdf_detection"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": "pypdf + openpyxl ready (12 MB safety cap)"}


class UsernameMultiPlatformPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="username_multi_platform",
        name="Multi-Platform Username & Recursive Bio Scanner",
        version="2.0.0",
        category="social",
        description="Maigret/Sherlock v2 declarative 55-platform & 5-engine (Discourse/Mastodon/WordPress/Gitea/Bluesky) sweep with rank priority, response_url Soft-404 redirect filtering, per-site circuit breaker, Social-Analyzer 0-100 scoring, JSON-LD/rel='me' extraction, and recursive depth-2 bio pivoting.",
        local_only=False,
        capabilities=[
            "maigret_json_manifest_v2",
            "five_reusable_engines",
            "response_url_soft_404_check",
            "circuit_breaker_health",
            "jsonld_rel_me_extraction",
            "confidence_0_100",
            "recursive_depth2_bio_pivot",
        ],
        consumes=["HANDLE_FOUND"],
        produces=["EMAIL_FOUND", "HANDLE_FOUND", "URL_FOUND"],
        inspired_by=["sherlock-project/sherlock", "soxoj/maigret", "qeeqbox/social-analyzer"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": f"{len(PUBLIC_SITE_MANIFEST)} Maigret/Sherlock v2 sites + 5 reusable engines ready"}

    async def handle_event(self, event: OSINTEvent, context: dict[str, Any]) -> PluginExecutionResult:
        if event.event_type != "HANDLE_FOUND":
            return PluginExecutionResult(plugin_id=self.manifest.id)
        scan = await scan_username_profiles(
            event.value,
            target_hints=context.get("target_hints") or [],
            tags=context.get("tags"),
            timeout=float(context.get("timeout", 4.5)),
            client=context.get("client"),
        )
        sources: list[dict[str, Any]] = []
        emitted: list[OSINTEvent] = []
        for prof in scan.get("found_profiles", [])[:8]:
            sources.append(
                {
                    "title": f"{prof['display_name']} (@{prof['username']}) — {prof['site']} [{prof['confidence_score']}/100]",
                    "url": prof["url"],
                    "snippet": prof["bio"] or f"Public {prof['site']} profile for @{prof['username']}",
                    "confidence_score": prof["confidence_score"],
                    "site": prof["site"],
                    "display_name": prof["display_name"],
                    "rel_me": prof.get("rel_me") or [],
                    "same_as": prof.get("same_as") or [],
                }
            )
        pivots = scan.get("discovered_pivots") or {}
        for em in pivots.get("emails", [])[:3]:
            emitted.append(OSINTEvent(event_type="EMAIL_FOUND", value=em, source_plugin=self.manifest.id))
        for h in pivots.get("handles", [])[:2]:
            emitted.append(OSINTEvent(event_type="HANDLE_FOUND", value=h, source_plugin=self.manifest.id))
        return PluginExecutionResult(
            plugin_id=self.manifest.id,
            sources=sources,
            emitted_events=emitted,
            notes=[f"Scanned {scan['checked_sites']} platforms for @{scan['username']} -> {len(sources)} public hits"],
        )


class PhoneFootprintPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="phone_footprint_analyzer",
        name="Phone Number Carrier & Footprint Dorker",
        version="1.0.0",
        category="enrichment",
        description="Parses E.164 & Vietnamese mobile prefixes, identifies carriers, normalizes formats, and generates targeted public footprint dorks.",
        local_only=True,
        capabilities=["e164_parse", "vn_carrier_lookup", "multi_format_phone_dorks"],
        consumes=["PHONE_FOUND"],
        produces=[],
        inspired_by=["sundowndev/phoneinfoga"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": "Offline E.164 + VN carrier database ready"}

    async def handle_event(self, event: OSINTEvent, context: dict[str, Any]) -> PluginExecutionResult:
        if event.event_type != "PHONE_FOUND":
            return PluginExecutionResult(plugin_id=self.manifest.id)
        info = analyze_phone_number(event.value, name_hint=str(context.get("target_name") or ""))
        if not info.get("valid"):
            return PluginExecutionResult(plugin_id=self.manifest.id)
        note = (
            f"SĐT {info['e164']} ({info['country_name']} · Nhà mạng: {info['carrier']} · "
            f"Loại: {info['line_type']})"
        )
        return PluginExecutionResult(
            plugin_id=self.manifest.id,
            dorks=info.get("dorks", []),
            notes=[note],
        )


class PassiveDnsEmailCryptoPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="passive_dns_email_crypto",
        name="Passive DNS (DoH) & Public Crypto Email Recon",
        version="1.0.0",
        category="enrichment",
        description="Combines passive Cloudflare DoH (MX/TXT/SPF), RDAP/crt.sh subdomains, public Gravatar JSON profiles, and OpenPGP keyserver lookups.",
        local_only=False,
        capabilities=["passive_doh_mx_txt", "gravatar_json_profile", "openpgp_vks_lookup", "rdap_crtsh"],
        consumes=["EMAIL_FOUND", "DOMAIN_FOUND"],
        produces=["DOMAIN_FOUND", "URL_FOUND"],
        inspired_by=["laramies/theHarvester", "owasp-amass/amass"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": "Cloudflare DoH + Gravatar + keys.openpgp.org ready"}

    async def handle_event(self, event: OSINTEvent, context: dict[str, Any]) -> PluginExecutionResult:
        client = context.get("client")
        sources: list[dict[str, Any]] = []
        emitted: list[OSINTEvent] = []
        notes: list[str] = []

        if event.event_type == "EMAIL_FOUND":
            res = await inspect_public_email_crypto_identity(event.value, client=client)
            if res.get("ok"):
                grav = res.get("gravatar")
                if grav:
                    sources.append(
                        {
                            "title": f"Gravatar Public Profile: {grav.get('display_name') or res['email']}",
                            "url": grav["profile_url"],
                            "snippet": res["summary"],
                        }
                    )
                    for acc in grav.get("linked_accounts", [])[:4]:
                        if acc.get("url"):
                            emitted.append(
                                OSINTEvent(event_type="URL_FOUND", value=acc["url"], source_plugin=self.manifest.id)
                            )
                if res.get("openpgp_found"):
                    sources.append(
                        {
                            "title": f"OpenPGP Public Key ({res['email']})",
                            "url": res["openpgp_url"],
                            "snippet": "Verified public PGP key published on keys.openpgp.org.",
                        }
                    )
                notes.append(res["summary"])
            dom = event.value.split("@")[-1].strip().lower()
            if is_custom_org_domain(dom):
                emitted.append(OSINTEvent(event_type="DOMAIN_FOUND", value=dom, source_plugin=self.manifest.id))

        elif event.event_type == "DOMAIN_FOUND" and is_custom_org_domain(event.value):
            full_dom = await run_full_passive_domain_recon(event.value, client=client)
            if full_dom.get("ok"):
                sources.append(
                    {
                        "title": f"Multi-Source Passive Recon ({full_dom['provider_count']} feeds): {event.value}",
                        "url": full_dom["url"],
                        "snippet": full_dom["summary"][:280],
                        "infra_provider_count": full_dom["provider_count"],
                        "providers": full_dom["providers"],
                    }
                )
                for apdf in (full_dom.get("archived_pdfs") or [])[:2]:
                    sources.append(
                        {
                            "title": f"Wayback Archived PDF ({apdf['timestamp']}): {apdf['original_url'].split('/')[-1]}",
                            "url": apdf["wayback_url"],
                            "snippet": f"Historical PDF discovered via Wayback CDX API for {event.value}",
                        }
                    )
                notes.append(f"{event.value} ({', '.join(full_dom['providers'])}): {full_dom['summary']}")

        return PluginExecutionResult(
            plugin_id=self.manifest.id,
            sources=sources,
            emitted_events=emitted,
            notes=notes,
        )


class GitHubFootprintPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="github_public_footprint",
        name="GitHub Public Profile & UTC Timezone Analyzer",
        version="1.0.0",
        category="social",
        description="Collects public GitHub profiles, repositories, email commits, and infers UTC activity signatures.",
        local_only=False,
        capabilities=["profile_lookup", "repo_scan", "utc_timezone_inference"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": "Public REST API ready"}


class WaybackRecoveryPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="wayback_archive_recovery",
        name="Wayback Machine & Mirror Pivot Engine",
        version="1.0.0",
        category="archive",
        description="Recovers de-indexed or offline institutional pages via Internet Archive snapshots and public document mirrors.",
        local_only=False,
        capabilities=["wayback_lookup", "network_diagnosis", "mirror_pivoting"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": "archive.org availability API ready"}


class BrowserCompanionPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="browser_companion_clipper",
        name="Human-in-the-Loop Browser Companion Bridge",
        version="1.0.0",
        category="enrichment",
        description="Receives user-selected public snippets from the Chrome/Edge Companion Extension via /api/workspaces/{id}/clip.",
        local_only=True,
        capabilities=["browser_clip_ingest", "human_in_the_loop_social"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": "POST /api/workspaces/{id}/clip active"}


class OpenAlexGlobalPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="openalex_global_research",
        name="OpenAlex & ORCID Global Scholar Registry",
        version="1.0.0",
        category="enrichment",
        description="Queries 250M+ global academic profiles, institutional affiliations, publication timelines, and ORCID identifiers.",
        local_only=False,
        capabilities=["scholar_lookup", "affiliation_timeline", "orcid_resolution"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": "api.openalex.org public REST API ready"}


class DomainInfraPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="domain_rdap_crtsh",
        name="Global Domain RDAP & crt.sh CT Inspector",
        version="1.0.0",
        category="enrichment",
        description="Inspects public RDAP registration dates and Certificate Transparency subdomains for custom organizational domains.",
        local_only=False,
        capabilities=["rdap_lookup", "certificate_transparency", "subdomain_discovery"],
        inspired_by=["laramies/theHarvester", "owasp-amass/amass"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        return {"ready": True, "detail": "rdap.org + crt.sh public endpoints ready"}


class ExternalOsintCliBridgePlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="external_osint_cli_bridge",
        name="Optional Local OSINT CLI Discovery Bridge",
        version="1.0.0",
        category="enrichment",
        description="Detects locally installed community CLIs (sherlock, maigret, theHarvester, phoneinfoga, amass) for hybrid MCP workflows.",
        local_only=True,
        capabilities=["cli_auto_discovery", "mcp_bridge"],
        inspired_by=["OpenOSINT/OpenOSINT", "yogsec/OSINT-Tools"],
    )

    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        clis = detect_installed_osint_clis()
        installed = [c["id"] for c in clis if c["installed"]]
        detail = (
            f"Detected local CLIs: {', '.join(installed)}"
            if installed
            else "0 optional external CLIs installed (built-in native engines active)"
        )
        return {"ready": True, "detail": detail, "clis": clis}


class PluginRegistry:
    """Discovers built-in and community plugins dropped into `plugins/*.py`."""

    def __init__(self, extra_plugin_dir: Path | None = None) -> None:
        self._plugins: dict[str, ConnectorPlugin] = {}
        for p in (
            ParallelMetasearchPlugin(),
            DeepDocumentReaderPlugin(),
            UsernameMultiPlatformPlugin(),
            PhoneFootprintPlugin(),
            PassiveDnsEmailCryptoPlugin(),
            GitHubFootprintPlugin(),
            WaybackRecoveryPlugin(),
            BrowserCompanionPlugin(),
            OpenAlexGlobalPlugin(),
            DomainInfraPlugin(),
            ExternalOsintCliBridgePlugin(),
        ):
            self.register(p)
        if extra_plugin_dir and extra_plugin_dir.exists():
            self._load_external_plugins(extra_plugin_dir)

    def register(self, plugin: ConnectorPlugin) -> None:
        self._plugins[plugin.manifest.id] = plugin

    def all_plugins(self) -> list[ConnectorPlugin]:
        return list(self._plugins.values())

    def create_event_bus(self) -> EventDrivenPluginBus:
        return EventDrivenPluginBus(self.all_plugins())

    def _load_external_plugins(self, plugin_dir: Path) -> None:
        for py_file in sorted(plugin_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"stalker_ext_{py_file.stem}", py_file)
                if not spec or not spec.loader:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                factory = getattr(mod, "register_plugin", None)
                if callable(factory):
                    plugin = factory()
                    if isinstance(plugin, ConnectorPlugin):
                        self.register(plugin)
            except Exception:
                continue

    def list_manifests(self) -> list[dict[str, Any]]:
        return [p.manifest.model_dump() for p in self._plugins.values()]

    async def list_with_health(self, context: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for p in self._plugins.values():
            try:
                status = await p.health(context)
            except Exception as exc:
                status = {"ready": False, "detail": str(exc)}
            out.append({**p.manifest.model_dump(), "health": status})
        return out
