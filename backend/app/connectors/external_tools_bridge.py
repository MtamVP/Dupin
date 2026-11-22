"""Optional Local OSINT CLI Discovery Bridge (OpenOSINT / yogsec MCP Wrapper Pattern).

Safely detects whether the analyst already has classic open-source OSINT CLIs installed
in their local PATH (`maigret`, `sherlock`, `theHarvester`, `phoneinfoga`, `amass`)
without bundling invasive scrapers or requiring external installations.
"""

from __future__ import annotations

import shutil
from typing import Any

KNOWN_EXTERNAL_OSINT_CLIS: list[dict[str, str]] = [
    {
        "id": "sherlock",
        "binary": "sherlock",
        "repo": "https://github.com/sherlock-project/sherlock",
        "purpose": "400+ platform username sweep",
        "install_hint": "pipx install sherlock-project",
    },
    {
        "id": "maigret",
        "binary": "maigret",
        "repo": "https://github.com/soxoj/maigret",
        "purpose": "3,000+ site username + bio metadata recursive lookup",
        "install_hint": "pipx install maigret",
    },
    {
        "id": "theHarvester",
        "binary": "theHarvester",
        "repo": "https://github.com/laramies/theHarvester",
        "purpose": "Organizational domain & public email harvesting",
        "install_hint": "pipx install theHarvester",
    },
    {
        "id": "phoneinfoga",
        "binary": "phoneinfoga",
        "repo": "https://github.com/sundowndev/phoneinfoga",
        "purpose": "Phone number carrier & footprint scanner",
        "install_hint": "https://github.com/sundowndev/phoneinfoga/releases",
    },
    {
        "id": "amass",
        "binary": "amass",
        "repo": "https://github.com/owasp-amass/amass",
        "purpose": "OWASP passive subdomain & ASN infrastructure mapping",
        "install_hint": "go install github.com/owasp-amass/amass/v4/...@master",
    },
]


def detect_installed_osint_clis() -> list[dict[str, Any]]:
    """Probe local PATH for optional community OSINT binaries."""
    detected: list[dict[str, Any]] = []
    for item in KNOWN_EXTERNAL_OSINT_CLIS:
        resolved = shutil.which(item["binary"])
        detected.append(
            {
                **item,
                "installed": bool(resolved),
                "path": resolved or "",
            }
        )
    return detected
