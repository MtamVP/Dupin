"""Backwards-Compatible Orchestrator Facade delegating to the 5-Layer Concentric OSINT Pipeline.

All heavy logic has been strictly separated into concentric architectural layers under `app.pipeline`:
- Layer 1 (`app.pipeline.layer1_intake`): Perimeter Intake, Vision OCR, Clue Parsing & Anchor Decoding.
- Layer 2 (`app.pipeline.layer2_gatekeeper`): Outer Sanitization, Noise Shield, Temporal Veto & Relevance Gate.
- Layer 3 (`app.pipeline.layer3_collectors`): Multi-Channel Collectors & Maigret/Sherlock/SpiderFoot Plugin Bus.
- Layer 4 (`app.pipeline.layer4_deep_core`): Innermost Deep Core (8D Graph, MCTS UCB1, Critic, Bayesian, Adamic-Adar).
- Layer 5 (`app.pipeline.layer5_synthesis`): Executive Synthesis, Smart Dorks & Full 5-Layer Telemetry.

This module preserves 100% backwards compatibility for all existing callers, API endpoints, MCP tools, and tests.
"""

from __future__ import annotations

from app.pipeline import (
    PIPELINE_ARCHITECTURE_SPEC,
    OuterGatekeeper,
    build_disambiguation_cards,
    build_intersection_queries,
    build_timeline_events,
    execute_concentric_pipeline,
    parse_user_prompt,
    score_source_relevance,
)

# Public entrypoint alias preserved for API, MCP server, and tests
handle_chat_turn = execute_concentric_pipeline

__all__ = [
    "PIPELINE_ARCHITECTURE_SPEC",
    "OuterGatekeeper",
    "build_disambiguation_cards",
    "build_intersection_queries",
    "build_timeline_events",
    "execute_concentric_pipeline",
    "handle_chat_turn",
    "parse_user_prompt",
    "score_source_relevance",
]
