"""Critic & Verifier Agent: Anti-Hallucination Quote Verification & Timeline Anomaly Detection."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from app.agents.reader import ExtractedTriple, ExtractionResult
from app.core.normalizer import normalize_text
from app.core.schemas import FeatureClaim, Node


class TimelineEvent(BaseModel):
    """A single chronological milestone reconstructed for an entity."""

    year: int
    event_type: str
    description: str
    source_url: str
    evidence_quote: str


class TimelineAuditReport(BaseModel):
    """Chronological timeline with detected temporal anomalies and unexplored gaps."""

    node_id: str
    label: str
    events: list[TimelineEvent] = Field(default_factory=list)
    anomalies: list[str] = Field(default_factory=list)
    unexplored_gaps: list[dict[str, Any]] = Field(default_factory=list)


def verify_quote_grounding(evidence_quote: str, source_text: str) -> float:
    """Compute grounding score [0.0, 1.0] verifying that evidence_quote exists in source_text.

    Prevents LLM hallucinated triples that cannot be traced back to the document.
    """
    norm_quote = normalize_text(evidence_quote)
    norm_source = normalize_text(source_text)
    if not norm_quote or not norm_source:
        return 0.0
    if norm_quote in norm_source:
        return 1.0

    q_tokens = set(norm_quote.split())
    s_tokens = set(norm_source.split())
    if not q_tokens:
        return 0.0
    overlap = len(q_tokens & s_tokens) / len(q_tokens)
    return round(overlap, 4)


class CriticVerifierAgent:
    """Audits extracted claims/triples against source text and checks temporal consistency."""

    def audit_extraction(
        self, extraction: ExtractionResult, source_text: str
    ) -> tuple[list[FeatureClaim], list[tuple[ExtractedTriple, str]]]:
        """Filter claims and classify triples into ('VERIFIED'|'HYPOTHESIS'|'REJECTED')."""
        verified_claims: list[FeatureClaim] = []
        for claim in extraction.claims:
            # Technical artifacts (like gravatar_md5) derived deterministically from grounded quotes pass
            if claim.key in ("gravatar_md5", "stylometry_vector"):
                verified_claims.append(claim)
                continue
            grounding = verify_quote_grounding(claim.evidence_quote, source_text)
            if grounding >= 0.65:
                claim.confidence = round(claim.confidence * (0.7 + 0.3 * grounding), 4)
                verified_claims.append(claim)

        audited_triples: list[tuple[ExtractedTriple, str]] = []
        for triple in extraction.triples:
            grounding = verify_quote_grounding(triple.evidence_quote, source_text)
            if grounding >= 0.85 and triple.confidence >= 0.75:
                status = "VERIFIED"
            elif grounding >= 0.55:
                status = "HYPOTHESIS"
                triple.confidence = round(triple.confidence * grounding, 4)
            else:
                status = "REJECTED"
                triple.confidence = 0.1
            audited_triples.append((triple, status))

        return verified_claims, audited_triples

    def reconstruct_and_audit_timeline(self, node: Node) -> TimelineAuditReport:
        """Build a chronological timeline from node claims, flagging anomalies & multi-year gaps."""
        events: list[TimelineEvent] = []
        birth_years: list[int] = []

        for claim in node.claims:
            if claim.polarity == "NEGATIVE":
                continue

            if claim.key == "associated_year" and str(claim.value).isdigit():
                yr = int(claim.value)
                q_lower = claim.evidence_quote.lower()
                if any(k in q_lower for k in ("sinh năm", "sn", "born in")):
                    birth_years.append(yr)
                    ev_type = "BIRTH"
                else:
                    ev_type = "MILESTONE"
                events.append(
                    TimelineEvent(
                        year=yr,
                        event_type=ev_type,
                        description=f"{claim.key}: {claim.value}",
                        source_url=claim.source_url,
                        evidence_quote=claim.evidence_quote,
                    )
                )
            else:
                # Extract any 4-digit year mentioned inside the evidence_quote of school/work/location claims
                for ym in re.findall(r"\b(19[7-9]\d|20[0-2]\d)\b", claim.evidence_quote):
                    yr = int(ym)
                    events.append(
                        TimelineEvent(
                            year=yr,
                            event_type=claim.key.upper(),
                            description=f"{claim.key}: {claim.value}",
                            source_url=claim.source_url,
                            evidence_quote=claim.evidence_quote,
                        )
                    )

        events.sort(key=lambda e: e.year)
        anomalies: list[str] = []

        if len(set(birth_years)) > 1:
            anomalies.append(f"Conflicting birth years detected: {sorted(set(birth_years))}")

        primary_birth = min(birth_years) if birth_years else None
        for ev in events:
            if primary_birth is not None:
                age_at_event = ev.year - primary_birth
                if ev.event_type in ("WORKPLACE", "WORKS_AT") and age_at_event < 15:
                    anomalies.append(
                        f"Temporal anomaly: Workplace event in {ev.year} occurs at age {age_at_event} (born {primary_birth})"
                    )
                if age_at_event < 0:
                    anomalies.append(
                        f"Impossible timeline: Event in {ev.year} precedes birth year {primary_birth}"
                    )

        # Detect unexplored timeline gaps (> 3 years between known non-birth milestones)
        non_birth_years = sorted({e.year for e in events if e.event_type != "BIRTH"})
        gaps: list[dict[str, Any]] = []
        for i in range(len(non_birth_years) - 1):
            y1, y2 = non_birth_years[i], non_birth_years[i + 1]
            if y2 - y1 > 3:
                gaps.append(
                    {
                        "from_year": y1,
                        "to_year": y2,
                        "gap_years": y2 - y1,
                        "suggested_query": f'"{node.label}" "{y1 + 1}".."{y2 - 1}"',
                    }
                )

        return TimelineAuditReport(
            node_id=node.id,
            label=node.label,
            events=events,
            anomalies=anomalies,
            unexplored_gaps=gaps,
        )
