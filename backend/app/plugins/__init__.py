"""Stalker++ extensible event-driven OSINT plugin SDK and built-in connector registry."""

from app.plugins.base import ConnectorPlugin, OSINTEvent, PluginExecutionResult, PluginManifest
from app.plugins.event_bus import EventDrivenPluginBus
from app.plugins.registry import PluginRegistry

__all__ = [
    "ConnectorPlugin",
    "EventDrivenPluginBus",
    "OSINTEvent",
    "PluginExecutionResult",
    "PluginManifest",
    "PluginRegistry",
]
