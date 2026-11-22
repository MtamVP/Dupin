"""Stalker++ 5-Layer Concentric OSINT Pipeline Orchestrator.

Explicit Layer Flow (Outer Filtering -> Multi-Channel Collection -> Innermost Deep Core):
  Layer 1 (Intake Perimeter)     -> Parse clues, Vision OCR, decode anchors, hydrate context.
  Layer 4A (Core Seed)           -> Persist validated seed entities/edges & initialize Blackboard.
  Layer 3 (Collectors) + Layer 2 -> Gather external sources, guarded strictly by OuterGatekeeper (L2).
  Layer 4B (Deep Core Reasoning) -> MCTS (UCB1), Critic verification, Bayesian fusion, Timeline, Adamic-Adar.
  Layer 5 (Synthesis & Delivery) -> Executive summary, Smart Dorks, 5-layer telemetry, persistence.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from app.agents.playbooks import PlaybookRegistry
from app.core.graph_store import GraphStore
from app.pipeline.layer1_intake import parse_user_prompt, run_layer1_intake
from app.pipeline.layer2_gatekeeper import OuterGatekeeper, score_source_relevance
from app.pipeline.layer3_collectors import build_intersection_queries, run_layer3_collectors
from app.pipeline.layer4_deep_core import (
    build_disambiguation_cards,
    build_timeline_events,
    run_layer4_deep_core,
    seed_core_graph_and_blackboard,
)
from app.pipeline.layer5_synthesis import run_layer5_synthesis
from app.pipeline.models import PIPELINE_ARCHITECTURE_SPEC


async def execute_concentric_pipeline(
    store: GraphStore,
    workspace_id: str,
    prompt: str,
    live_search: bool = True,
    deep_mode: bool = True,
    use_llm: bool = False,
    model_override: Optional[str] = None,
    image_b64: Optional[str] = None,
    image_mime: str = "image/png",
    geo_point: Optional[dict[str, Any]] = None,
    attached_file_text: Optional[str] = None,
    playbook_registry: Optional[PlaybookRegistry] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Run the full 5-Layer Concentric OSINT Pipeline with per-layer latency & gatekeeper telemetry."""
    timings: dict[str, float] = {}

    # Layer 1 (Outermost Perimeter): Intake, Vision OCR, Anchor Decoding, Context Hydration
    t0 = time.perf_counter()
    ctx = await run_layer1_intake(
        store=store,
        workspace_id=workspace_id,
        prompt=prompt,
        model_override=model_override,
        image_b64=image_b64,
        image_mime=image_mime,
        geo_point=geo_point,
        attached_file_text=attached_file_text,
        client=client,
    )
    timings["L1_intake_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    # Layer 4A (Core Seed): Seed verified 8D entities & initialize MCTS Blackboard
    t1 = time.perf_counter()
    target_node, planner, bb = seed_core_graph_and_blackboard(
        store=store,
        ctx=ctx,
        playbook_registry=playbook_registry,
        use_llm=use_llm,
    )
    timings["L4a_core_seed_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    # Layer 2 (Outer Gatekeeper) instantiated to shield Layer 4 from all Layer 3 external noise
    gatekeeper = OuterGatekeeper(ctx)

    # Layer 3 (Multi-Channel Collectors) strictly funneled through Layer 2 (Outer Gatekeeper)
    t2 = time.perf_counter()
    bundle = await run_layer3_collectors(
        ctx=ctx,
        gatekeeper=gatekeeper,
        store=store,
        bb=bb,
        live_search=live_search,
        deep_mode=deep_mode,
        model_override=model_override,
        client=client,
    )
    timings["L2_L3_collect_and_gate_ms"] = round((time.perf_counter() - t2) * 1000, 1)

    # Layer 4B (Innermost Deep Core): MCTS, CriticVerifier, Bayesian Fusion, Timeline, Adamic-Adar
    t3 = time.perf_counter()
    core_result = await run_layer4_deep_core(
        store=store,
        ctx=ctx,
        bundle=bundle,
        target_node=target_node,
        planner=planner,
        bb=bb,
    )
    timings["L4b_deep_core_ms"] = round((time.perf_counter() - t3) * 1000, 1)

    # Layer 5 (Synthesis & Delivery): Executive Summary, Smart Dorks, Telemetry & Persistence
    t4 = time.perf_counter()
    response = await run_layer5_synthesis(
        store=store,
        ctx=ctx,
        bundle=bundle,
        core_result=core_result,
        live_search=live_search,
        model_override=model_override,
        layer_timings_ms=timings,
    )
    timings["L5_synthesis_ms"] = round((time.perf_counter() - t4) * 1000, 1)
    timings["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    response["pipeline_telemetry"]["layer_timings_ms"] = timings
    return response


__all__ = [
    "PIPELINE_ARCHITECTURE_SPEC",
    "OuterGatekeeper",
    "build_disambiguation_cards",
    "build_intersection_queries",
    "build_timeline_events",
    "execute_concentric_pipeline",
    "parse_user_prompt",
    "score_source_relevance",
]
