"""SpiderFoot-Inspired Multi-Hop Event-Driven OSINT Plugin Bus.

Takes seed events (HANDLE_FOUND, EMAIL_FOUND, DOMAIN_FOUND, PHONE_FOUND) and cascades them
through subscribed plugins up to `max_hops`, automatically deduplicating seen events and
aggregating discovered sources, dorks, and trace logs.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.plugins.base import ConnectorPlugin, OSINTEvent, PluginExecutionResult
from app.plugins.correlator import OSINTCorrelator


class EventDrivenPluginBus:
    """Asynchronous multi-hop event router across registered Stalker++ plugins."""

    def __init__(self, plugins: list[ConnectorPlugin]) -> None:
        self._plugins = plugins

    def subscribers_for(self, event_type: str) -> list[ConnectorPlugin]:
        return [p for p in self._plugins if event_type in (p.manifest.consumes or [])]

    async def run(
        self,
        seed_events: list[OSINTEvent],
        context: dict[str, Any],
        max_hops: int = 2,
        max_events_per_hop: int = 6,
    ) -> dict[str, Any]:
        seen: set[tuple[str, str]] = set()
        queue: list[OSINTEvent] = []
        for ev in seed_events:
            key = (ev.event_type, ev.value.strip().lower())
            if ev.value.strip() and key not in seen:
                seen.add(key)
                queue.append(ev)

        all_sources: list[dict[str, Any]] = []
        all_dorks: list[dict[str, str]] = []
        all_notes: list[str] = []
        trace: list[dict[str, Any]] = []
        processed_events: list[dict[str, Any]] = []

        for hop in range(1, max_hops + 1):
            if not queue:
                break
            batch = queue[:max_events_per_hop]
            next_queue: list[OSINTEvent] = []

            tasks: list[tuple[OSINTEvent, ConnectorPlugin, Any]] = []
            for ev in batch:
                processed_events.append(ev.model_dump())
                for plugin in self.subscribers_for(ev.event_type):
                    tasks.append((ev, plugin, plugin.handle_event(ev, context)))

            if not tasks:
                break

            results = await asyncio.gather(*(t[2] for t in tasks), return_exceptions=True)
            for (ev, plugin, _), res in zip(tasks, results):
                if not isinstance(res, PluginExecutionResult):
                    continue
                if res.sources or res.emitted_events or res.dorks or res.notes:
                    trace.append(
                        {
                            "hop": hop,
                            "plugin": plugin.manifest.id,
                            "trigger": f"{ev.event_type}:{ev.value}",
                            "sources_found": len(res.sources),
                            "emitted": [f"{e.event_type}:{e.value}" for e in res.emitted_events],
                        }
                    )
                all_sources.extend(res.sources)
                all_dorks.extend(res.dorks)
                all_notes.extend(res.notes)
                for child_ev in res.emitted_events:
                    if not child_ev.parent_event_id:
                        child_ev.parent_event_id = ev.id
                    ckey = (child_ev.event_type, child_ev.value.strip().lower())
                    if child_ev.value.strip() and ckey not in seen:
                        seen.add(ckey)
                        next_queue.append(child_ev)

            queue = next_queue

        # Deduplicate sources by URL and dorks by query
        seen_urls: set[str] = set()
        unique_sources: list[dict[str, Any]] = []
        for s in all_sources:
            u = str(s.get("url") or "").strip().lower().rstrip("/")
            if u and u not in seen_urls:
                seen_urls.add(u)
                unique_sources.append(s)

        seen_dorks: set[str] = set()
        unique_dorks: list[dict[str, str]] = []
        for d in all_dorks:
            q = d.get("query", "").strip()
            if q and q not in seen_dorks:
                seen_dorks.add(q)
                unique_dorks.append(d)

        correlations = OSINTCorrelator().evaluate(
            sources=unique_sources,
            processed_events=processed_events,
            trace=trace,
        )

        return {
            "processed_events": processed_events,
            "sources": unique_sources,
            "dorks": unique_dorks,
            "notes": all_notes,
            "trace": trace,
            "correlations": correlations,
        }
