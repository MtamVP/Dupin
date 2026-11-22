"""Extensible Event-Driven Plugin SDK for Stalker++ Community & Built-in OSINT Connectors.

Adopts the SpiderFoot event-driven pub/sub architecture: plugins declare which typed
OSINT events they `consumes` (e.g. HANDLE_FOUND, EMAIL_FOUND, DOMAIN_FOUND, PHONE_FOUND)
and which downstream events they `produces` for automatic multi-hop chaining.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

EventType = Literal[
    "HANDLE_FOUND",
    "EMAIL_FOUND",
    "DOMAIN_FOUND",
    "PHONE_FOUND",
    "NAME_FOUND",
    "URL_FOUND",
]


class OSINTEvent(BaseModel):
    """Typed intelligence event with SpiderFoot-style parent provenance tracking."""

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    parent_event_id: str = ""
    event_type: EventType
    value: str
    source_plugin: str = "seed"
    confidence: float = 0.85
    metadata: dict[str, Any] = Field(default_factory=dict)


class PluginExecutionResult(BaseModel):
    """Standardized output emitted by any ConnectorPlugin when handling an event."""

    plugin_id: str
    sources: list[dict[str, Any]] = Field(default_factory=list)
    emitted_events: list[OSINTEvent] = Field(default_factory=list)
    dorks: list[dict[str, str]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PluginManifest(BaseModel):
    """Machine-readable metadata describing a Stalker++ connector or analyzer plugin."""

    id: str = Field(..., min_length=2, max_length=64)
    name: str
    version: str = "1.0.0"
    category: Literal["search", "document", "social", "archive", "enrichment", "export"]
    description: str
    local_only: bool = True
    requires_api_key: bool = False
    ethical_scope: str = "public_osint_only"
    capabilities: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    inspired_by: list[str] = Field(default_factory=list)


class ConnectorPlugin(ABC):
    """Base interface for pluggable OSINT collectors and analyzers."""

    manifest: PluginManifest

    @abstractmethod
    async def health(self, context: dict[str, Any]) -> dict[str, Any]:
        """Return live readiness status (`{"ready": bool, "detail": str}`)."""

    async def handle_event(
        self, event: OSINTEvent, context: dict[str, Any]
    ) -> PluginExecutionResult:
        """Process a typed OSINTEvent and return discovered sources + downstream events."""
        return PluginExecutionResult(plugin_id=self.manifest.id)

    async def execute(self, query: str, context: dict[str, Any]) -> dict[str, Any]:
        """Optional direct execution entrypoint for tool-calling agents."""
        return {"plugin": self.manifest.id, "query": query, "status": "not_implemented"}
