"""Entity Resolution Agent: 8-Dimensional Probabilistic Disambiguation & Negative Veto."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field

from app.core.fingerprints import handle_pattern_similarity
from app.core.normalizer import (
    generate_name_variants,
    normalize_org_or_location,
    string_similarity,
)
from app.core.schemas import FeatureCategory, Node


class ResolutionReport(BaseModel):
    """Explainable breakdown of why two nodes/profiles belong to the same entity or conflict."""

    node_a_id: str
    node_b_id: str
    overall_probability: float
    decision: str  # "SAME_ENTITY", "POSSIBLE_MATCH", "DIFFERENT_ENTITY"
    dimension_scores: dict[str, float] = Field(default_factory=dict)
    supporting_reasons: list[str] = Field(default_factory=list)
    conflicting_reasons: list[str] = Field(default_factory=list)


def _cosine(v1: list[float], v2: list[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    num = sum(a * b for a, b in zip(v1, v2))
    da = math.sqrt(sum(a * a for a in v1))
    db = math.sqrt(sum(b * b for b in v2))
    return (num / (da * db)) if (da and db) else 0.0


class EntityResolutionAgent:
    """Scores whether two nodes represent the same real-world person across all 8 dimensions."""

    def compare_nodes(self, node_a: Node, node_b: Node) -> ResolutionReport:
        reasons: list[str] = []
        conflicts: list[str] = []
        dim_scores: dict[str, float] = {}

        # 1. Identity & Phonetic Name / Variant / Handle Anatomy Similarity
        names_a = [node_a.label] + [
            str(c.value) for c in node_a.claims if c.key == "full_name" and c.polarity == "POSITIVE"
        ]
        names_b = [node_b.label] + [
            str(c.value) for c in node_b.claims if c.key == "full_name" and c.polarity == "POSITIVE"
        ]
        variants_a = [v for n in names_a for v in (generate_name_variants(n) or [n])]
        variants_b = [v for n in names_b for v in (generate_name_variants(n) or [n])]
        name_sim = max(
            string_similarity(va, vb) for va in variants_a for vb in variants_b
        )
        handle_sim = handle_pattern_similarity(node_a.label, node_b.label)
        identity_score = max(name_sim, handle_sim)
        dim_scores["identity"] = round(identity_score, 4)
        if identity_score >= 0.75:
            reasons.append(f"High identity/handle similarity ({identity_score:.2f}) between '{node_a.label}' and '{node_b.label}'")

        # Group claims by key and polarity
        pos_a = [c for c in node_a.claims if c.polarity == "POSITIVE"]
        pos_b = [c for c in node_b.claims if c.polarity == "POSITIVE"]
        neg_a = [c for c in node_a.claims if c.polarity == "NEGATIVE"]
        neg_b = [c for c in node_b.claims if c.polarity == "NEGATIVE"]

        # 2. Technical Artifact Exact Match (Email, Gravatar MD5, Linked Profile URL)
        tech_a = {
            (c.key, str(c.value).lower().strip())
            for c in pos_a
            if c.category == FeatureCategory.TECHNICAL_ARTIFACT or c.key in ("email", "gravatar_md5", "linked_profile_url")
        }
        tech_b = {
            (c.key, str(c.value).lower().strip())
            for c in pos_b
            if c.category == FeatureCategory.TECHNICAL_ARTIFACT or c.key in ("email", "gravatar_md5", "linked_profile_url")
        }
        shared_tech = tech_a & tech_b
        if shared_tech:
            dim_scores["technical_artifact"] = 1.0
            for k, v in shared_tech:
                reasons.append(f"Deterministic technical artifact match on {k}: {v}")
        else:
            dim_scores["technical_artifact"] = 0.0

        # 3. Education, Career & Location Context Overlap (with Vietnamese abbreviation expansion)
        ctx_a = {
            normalize_org_or_location(str(c.value))
            for c in pos_a
            if c.category in (FeatureCategory.EDUCATION_CAREER, FeatureCategory.SPATIOTEMPORAL)
            and isinstance(c.value, str)
        }
        ctx_b = {
            normalize_org_or_location(str(c.value))
            for c in pos_b
            if c.category in (FeatureCategory.EDUCATION_CAREER, FeatureCategory.SPATIOTEMPORAL)
            and isinstance(c.value, str)
        }
        shared_ctx = {x for x in (ctx_a & ctx_b) if x}
        if shared_ctx:
            dim_scores["context_overlap"] = min(1.0, 0.75 + 0.25 * (len(shared_ctx) - 1))
            reasons.append(f"Shared school/org/location context: {', '.join(sorted(shared_ctx))}")
        else:
            dim_scores["context_overlap"] = 0.0

        # 4. Birth / Associated Year Compatibility
        years_a = [int(c.value) for c in pos_a if c.key == "associated_year" and str(c.value).isdigit()]
        years_b = [int(c.value) for c in pos_b if c.key == "associated_year" and str(c.value).isdigit()]
        if years_a and years_b:
            min_diff = min(abs(ya - yb) for ya in years_a for yb in years_b)
            if min_diff == 0:
                dim_scores["temporal_compatibility"] = 1.0
                reasons.append(f"Exact associated year match ({years_a[0]})")
            elif min_diff <= 1:
                dim_scores["temporal_compatibility"] = 0.7
            else:
                dim_scores["temporal_compatibility"] = 0.0
                conflicts.append(f"Associated year mismatch ({years_a[0]} vs {years_b[0]})")

        # 5. Stylometry Vector Similarity
        vec_a = next((c.value for c in pos_a if c.key == "stylometry_vector" and isinstance(c.value, list)), None)
        vec_b = next((c.value for c in pos_b if c.key == "stylometry_vector" and isinstance(c.value, list)), None)
        if vec_a and vec_b:
            style_sim = _cosine(vec_a, vec_b)
            dim_scores["stylometry"] = round(style_sim, 4)
            if style_sim >= 0.85:
                reasons.append(f"Strong writing style (stylometry) similarity ({style_sim:.2f})")

        # 6. Negative Constraint Veto Check
        veto_penalty = 0.0
        neg_terms_a = {normalize_org_or_location(str(c.value)) for c in neg_a}
        neg_terms_b = {normalize_org_or_location(str(c.value)) for c in neg_b}
        violated_a = neg_terms_a & ctx_b
        violated_b = neg_terms_b & ctx_a
        if violated_a or violated_b:
            veto_penalty = 0.55
            violated = sorted(violated_a | violated_b)
            conflicts.append(f"Negative constraint violated on: {', '.join(violated)}")

        # Combine weighted evidence into posterior match probability
        raw_score = (
            0.35 * dim_scores.get("identity", 0.0)
            + 0.45 * dim_scores.get("technical_artifact", 0.0)
            + 0.30 * dim_scores.get("context_overlap", 0.0)
            + 0.15 * dim_scores.get("temporal_compatibility", 0.0)
            + 0.15 * dim_scores.get("stylometry", 0.0)
        )
        if conflicts and not shared_tech:
            raw_score -= 0.25
        final_prob = round(max(0.0, min(1.0, raw_score - veto_penalty)), 4)

        if final_prob >= 0.72:
            decision = "SAME_ENTITY"
        elif final_prob >= 0.42:
            decision = "POSSIBLE_MATCH"
        else:
            decision = "DIFFERENT_ENTITY"

        return ResolutionReport(
            node_a_id=node_a.id,
            node_b_id=node_b.id,
            overall_probability=final_prob,
            decision=decision,
            dimension_scores=dim_scores,
            supporting_reasons=reasons,
            conflicting_reasons=conflicts,
        )
