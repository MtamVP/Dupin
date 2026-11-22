"""Typed Layer Contracts & Blueprint for Stalker++ 5-Layer Concentric OSINT Pipeline.

Architecture Philosophy (Outer Filtering -> Mid Collection -> Innermost Deep Core):
- Layer 1 (Perimeter / Intake): Parse raw clues, Vision OCR, decode high-entropy anchors, merge multi-turn context.
- Layer 2 (Outer Sanitization / Gatekeeper): Fast-reject junk URLs, off-domain noise, homonyms, and temporal conflicts
  BEFORE any candidate is allowed into the reasoning core.
- Layer 3 (Multi-Channel Collectors): Parallel public search, Maigret/Sherlock username recon, SpiderFoot plugin bus,
  OpenAlex/GitHub/RDAP registries, Google AI Grounding, and deep PDF/XLSX inspection — all guarded by Layer 2.
- Layer 4 (Deep Core — Innermost): 8D Knowledge Graph (SQLite+FTS5+NetworkX), MCTS (UCB1) Planner, CriticVerifierAgent
  anti-hallucination verification, Bayesian log-odds fusion, Timeline conflict audit, Adamic-Adar link prediction.
- Layer 5 (Synthesis & Delivery): LLM/deterministic executive synthesis, smart dorks, and full layer telemetry.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.agents.blackboard import InvestigationBlackboard
from app.core.schemas import Node

PIPELINE_ARCHITECTURE_SPEC: list[dict[str, Any]] = [
    {
        "layer": 1,
        "code": "L1_INTAKE_PERIMETER",
        "ring": "outermost",
        "name": "Perimeter Intake & Anchor Decoding",
        "module": "app.pipeline.layer1_intake",
        "responsibilities": [
            "Structured clue parsing (name, DOB, orgs, locations, negatives, numeric ID isolation)",
            "Multimodal Vision OCR & verified Dossier / Geo / Multi-turn context hydration",
            "High-entropy anchor decoding (MSSV/student IDs, institutional emails, doc numbers, class codes, phones)",
            "Automatic VN vs Global region classification",
        ],
    },
    {
        "layer": 2,
        "code": "L2_OUTER_GATEKEEPER",
        "ring": "outer_filter",
        "name": "Outer Sanitization, Noise Shield & Temporal Veto",
        "module": "app.pipeline.layer2_gatekeeper",
        "responsibilities": [
            "Zero-cost fast rejection of junk URLs, malformed redirects, duplicates, and off-domain site: fallbacks",
            "Negative-constraint instant veto (Reflexion memory)",
            "Temporal Seniority & High-School/University Grade-Age impossibility veto",
            "Target-relevance cross-clue scoring, exact-ID academic context verification, and itemized rejection telemetry",
        ],
    },
    {
        "layer": 3,
        "code": "L3_MULTI_CHANNEL_COLLECTORS",
        "ring": "collection_enrichment",
        "name": "Multi-Channel Collectors & Maigret/Sherlock/SpiderFoot Bus",
        "module": "app.pipeline.layer3_collectors",
        "responsibilities": [
            "Direct URL health diagnostics + Wayback Machine archive recovery",
            "Autonomous 2-round Google AI Search Grounding with key-pool rotation & model fallback",
            "SpiderFoot Event-Driven Plugin Bus (Maigret/Sherlock 55-site scanner with response_url Soft-404 & recursive depth-2 pivoting, PhoneInfoga, 5-feed Passive DNS/Email, Correlator)",
            "Global public registries (OpenAlex/ORCID, GitHub Name Search, RDAP/crt.sh)",
            "Concurrent Cross-Clue Search (SearXNG + ddgs Yahoo/Brave/DDG/Yandex) -> Mirror Pivots -> Deep PDF/XLSX reader (all funneled through L2 Gatekeeper)",
        ],
    },
    {
        "layer": 4,
        "code": "L4_DEEP_CORE_REASONING",
        "ring": "innermost_core",
        "name": "Deep Core: 8D Entity Graph, MCTS (UCB1) & Critic Verification",
        "module": "app.pipeline.layer4_deep_core",
        "responsibilities": [
            "8-Dimensional Knowledge Graph persistence (SQLite + FTS5 + NetworkX)",
            "MCTS (UCB1) hypothesis selection, ReaderAgent extraction, and CriticVerifierAgent anti-hallucination grounding",
            "Bayesian log-odds multi-domain confidence aggregation & Reflexion backtracking",
            "Chronological Timeline & Age-Conflict audit + Co-Steer disambiguation cards",
            "Adamic-Adar hidden link prediction & Information-Gain pivot ranking",
        ],
    },
    {
        "layer": 5,
        "code": "L5_SYNTHESIS_DELIVERY",
        "ring": "presentation",
        "name": "Executive Synthesis, Smart Dorks & Pipeline Telemetry",
        "module": "app.pipeline.layer5_synthesis",
        "responsibilities": [
            "Context-aware Gemini/Ollama executive synthesis or deterministic fallback report",
            "Deduplicated multi-strategy Boolean & Google AI Mode dork generation",
            "Full 5-layer observability metrics (timings, accepted/rejected funnel, rejection reasons)",
        ],
    },
]


@dataclass
class InvestigationContext:
    """Immutable Layer 1 output passed inward to Layers 2, 3, 4, and 5."""

    workspace_id: str
    raw_prompt: str
    parsed: dict[str, Any]
    anchors: dict[str, Any]
    region: str
    target_name: str
    vision_extracted_text: str = ""
    dossier_blob: str = ""
    geo_blob: str = ""
    phone_candidates: list[str] = field(default_factory=list)


@dataclass
class GateDecision:
    """Layer 2 verdict for a single candidate source before entering the deep core."""

    accepted: bool
    score: int = 0
    matched_clues: list[str] = field(default_factory=list)
    reject_reason: str = ""


@dataclass
class GatekeeperTelemetry:
    """Transparent outer-filter funnel statistics produced by Layer 2."""

    total_inspected: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    rejected_by_reason: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_inspected": self.total_inspected,
            "accepted": self.accepted_count,
            "rejected": self.rejected_count,
            "rejected_by_reason": dict(self.rejected_by_reason),
        }


@dataclass
class CollectionBundle:
    """Layer 3 output containing ONLY Layer-2-verified candidates plus collector traces."""

    ranked_sources: list[dict[str, Any]] = field(default_factory=list)
    relevant_docs: list[dict[str, str]] = field(default_factory=list)
    intersection_queries: list[dict[str, str]] = field(default_factory=list)
    mirror_queries: list[dict[str, str]] = field(default_factory=list)
    bus_dorks: list[dict[str, str]] = field(default_factory=list)
    bus_notes: list[str] = field(default_factory=list)
    bus_trace: list[dict[str, Any]] = field(default_factory=list)
    bus_correlations: list[dict[str, Any]] = field(default_factory=list)
    network_diagnostics: list[dict[str, Any]] = field(default_factory=list)
    google_ai_summary: str = ""
    google_ai_error: str = ""
    gatekeeper_stats: GatekeeperTelemetry = field(default_factory=GatekeeperTelemetry)


@dataclass
class CoreReasoningResult:
    """Layer 4 innermost core output: verified graph state, MCTS evaluation, timelines, pivots."""

    target_node: Node
    blackboard: InvestigationBlackboard
    step_result: dict[str, Any] = field(default_factory=dict)
    timeline_events: list[dict[str, Any]] = field(default_factory=list)
    disambiguation_cards: list[dict[str, Any]] = field(default_factory=list)
    hidden_links: list[dict[str, Any]] = field(default_factory=list)
    recommended_pivots: list[dict[str, Any]] = field(default_factory=list)
    graph_stats: dict[str, int] = field(default_factory=lambda: {"nodes": 0, "edges": 0})
