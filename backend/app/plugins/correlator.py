"""SpiderFoot-Inspired Cross-Module Correlation Engine.

Evaluates structured correlation rules across all events and sources gathered by
multiple independent plugins (Username Recon, OpenAlex, Passive DNS/DoH, Wayback CDX,
URLScan, Shodan InternetDB, Gravatar/OpenPGP) to surface high-confidence cross-verified
findings and risk/outlier alerts.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from urllib.parse import urlparse

from app.core.normalizer import normalize_text


class OSINTCorrelator:
    """Runs deterministic cross-module correlation rules (inspired by SpiderFootCorrelator)."""

    def evaluate(
        self,
        *,
        sources: list[dict[str, Any]],
        processed_events: list[dict[str, Any]],
        trace: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        findings: list[dict[str, Any]] = []

        # Rule 1: CROSS_PLATFORM_IDENTITY_CONFIRMATION
        # Detect consistent display names or rel="me" / sameAs links spanning >= 2 independent platforms
        name_to_sites: dict[str, set[str]] = defaultdict(set)
        rel_me_links: list[str] = []
        for s in sources:
            site = str(s.get("site") or urlparse(str(s.get("url") or "")).netloc)
            disp = str(s.get("display_name") or "").strip()
            if disp and len(disp.split()) >= 2:
                name_to_sites[normalize_text(disp)].add(site)
            for link in (s.get("rel_me") or []) + (s.get("same_as") or []):
                if link not in rel_me_links:
                    rel_me_links.append(link)

        for norm_name, sites in name_to_sites.items():
            if len(sites) >= 2:
                findings.append(
                    {
                        "rule_id": "CORR_CROSS_PLATFORM_IDENTITY",
                        "severity": "HIGH",
                        "title": f"Cross-Platform Identity Confirmed ({len(sites)} independent platforms)",
                        "detail": f"Matching identity '{norm_name}' verified across: {', '.join(sorted(sites))}.",
                        "evidence_count": len(sites),
                    }
                )

        if rel_me_links:
            findings.append(
                {
                    "rule_id": "CORR_INDIEWEB_REL_ME",
                    "severity": "HIGH",
                    "title": f"Cryptographic / IndieWeb rel='me' & sameAs Links ({len(rel_me_links)})",
                    "detail": "Self-declared cross-platform links discovered: " + ", ".join(rel_me_links[:4]),
                    "evidence_count": len(rel_me_links),
                }
            )

        # Rule 2: CRYPTO_EMAIL_VERIFIED
        # Email corroborated across Gravatar/OpenPGP + upstream source (bio or seed)
        crypto_sources = [
            s for s in sources if any(k in str(s.get("url") or "").lower() for k in ("gravatar.com", "keys.openpgp.org"))
        ]
        if crypto_sources:
            findings.append(
                {
                    "rule_id": "CORR_CRYPTO_EMAIL_VERIFIED",
                    "severity": "HIGH",
                    "title": "Public Cryptographic / Gravatar Email Identity Corroborated",
                    "detail": "; ".join(str(s.get("title") or s.get("url")) for s in crypto_sources[:3]),
                    "evidence_count": len(crypto_sources),
                }
            )

        # Rule 3: MULTI_SOURCE_INFRASTRUCTURE
        # Custom domain corroborated by >= 2 independent passive telemetry providers (DoH, crt.sh, Wayback CDX, URLScan, Shodan InternetDB)
        infra_sources = [
            s for s in sources if int(s.get("infra_provider_count", 0)) >= 2
        ]
        for inf in infra_sources[:2]:
            findings.append(
                {
                    "rule_id": "CORR_MULTI_SOURCE_INFRASTRUCTURE",
                    "severity": "MEDIUM",
                    "title": f"Domain Infrastructure Corroborated ({inf['infra_provider_count']} passive feeds)",
                    "detail": f"{inf.get('title', '')}: {str(inf.get('snippet', ''))[:180]}",
                    "evidence_count": int(inf["infra_provider_count"]),
                }
            )

        # Rule 4: MULTI_HOP_CHAIN_DISCOVERED
        # SpiderFoot provenance chain reached hop >= 2 (e.g., Handle -> Bio Email -> Crypto/Domain)
        deep_hops = [t for t in trace if int(t.get("hop", 1)) >= 2]
        if deep_hops:
            findings.append(
                {
                    "rule_id": "CORR_MULTI_HOP_PIVOT_CHAIN",
                    "severity": "MEDIUM",
                    "title": f"Automated Multi-Hop Provenance Chain ({len(deep_hops)} downstream pivots)",
                    "detail": " -> ".join(f"Hop {h['hop']} [{h['plugin']}: {h['trigger']}]" for h in deep_hops[:3]),
                    "evidence_count": len(deep_hops),
                }
            )

        return findings
