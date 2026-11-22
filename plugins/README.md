# Stalker++ Community Plugins Directory

Drop any Python file (`*.py`) implementing `ConnectorPlugin` and exposing a `register_plugin()` factory into this folder. Stalker++ automatically discovers it on startup and surfaces its status in `GET /api/plugins` and the **Kết nối & Plugins** UI tab.

## Example (`plugins/example_whois.py`)
```python
from app.plugins.base import ConnectorPlugin, PluginManifest


class PublicWhoisPlugin(ConnectorPlugin):
    manifest = PluginManifest(
        id="public_whois",
        name="Public Domain WHOIS Lookup",
        version="1.0.0",
        category="enrichment",
        description="Queries public RDAP/WHOIS metadata for domains discovered in OSINT clues.",
        local_only=False,
        capabilities=["rdap_lookup"],
    )

    async def health(self, context):
        return {"ready": True, "detail": "RDAP public endpoint ready"}


def register_plugin():
    return PublicWhoisPlugin()
```

> **Ethical Guardrail**: All community plugins must strictly operate on **publicly accessible data only** (no login bypassing, no CAPTCHA evasion, no private data scraping).
