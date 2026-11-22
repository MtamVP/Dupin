"""International OSINT Export Formats: Obsidian Markdown Vault (with PII Redaction) & STIX 2.1 Bundle."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.schemas import GraphSnapshot

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+84|0)(?:3|5|7|8|9)\d{8}\b")
DOB_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(?:19\d{2}|20\d{2})\b")
LONG_ID_RE = re.compile(r"\b\d{8,12}\b")


def redact_pii(text: str) -> str:
    """Mask sensitive personal identifiers (emails, phone numbers, exact DOBs, 8-12 digit IDs)."""
    s = EMAIL_RE.sub("[REDACTED_EMAIL]", str(text or ""))
    s = PHONE_RE.sub("[REDACTED_PHONE]", s)
    s = DOB_RE.sub("[REDACTED_DOB]", s)
    s = LONG_ID_RE.sub(lambda m: m.group(0)[:2] + "****" + m.group(0)[-2:], s)
    return s


def export_obsidian_markdown(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    redact: bool = False,
) -> str:
    """Generate an Obsidian-ready Markdown dossier note with YAML frontmatter and [[wikilinks]]."""
    clean = redact_pii if redact else (lambda x: str(x or ""))
    ws_name = clean(snapshot.workspace.name)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = [
        "---",
        f'title: "OSINT Dossier — {ws_name}"',
        f"workspace_id: {snapshot.workspace.id}",
        f"exported_at: {now_iso}",
        f"redacted: {'true' if redact else 'false'}",
        "tags: [stalker-pp, osint, entity-resolution]",
        "---",
        "",
        f"# {ws_name}",
        "",
        "## Verified Dossier Items",
        "",
    ]
    if dossier_items:
        lines.append("| Field | Verified Value | Source |")
        lines.append("|---|---|---|")
        for it in dossier_items:
            fk = clean(it.get("field_key", "")).replace("|", "\\|")
            fv = clean(it.get("field_value", "")).replace("|", "\\|")
            src = clean(it.get("source_url", ""))
            src_md = f"[Source]({src})" if src.startswith(("http://", "https://")) else src
            lines.append(f"| **{fk}** | {fv} | {src_md} |")
    else:
        lines.append("_No verified dossier items pinned yet._")

    lines.extend(["", "## Knowledge Graph Entities (8D)", ""])
    node_map = {n.id: n for n in snapshot.nodes}
    for n in snapshot.nodes:
        lines.append(f"### [[{clean(n.label)}]] (`{n.type}` · confidence `{n.confidence:.2f}`)")
        for c in n.claims:
            if c.key in ("stylometry_vector", "temporal_activity_signature"):
                continue
            pol = "POSITIVE" if c.polarity == "POSITIVE" else "NEGATIVE"
            lines.append(
                f"- **[{pol}]** `{c.category.value}:{c.key}` = {clean(str(c.value))} "
                f"(conf `{c.confidence:.2f}`, src: {clean(c.source_url)})"
            )
        lines.append("")

    if snapshot.edges:
        lines.extend(["## Verified & Hypothesis Relationships", ""])
        for e in snapshot.edges:
            src_lbl = clean(node_map[e.source_id].label) if e.source_id in node_map else e.source_id
            dst_lbl = clean(node_map[e.target_id].label) if e.target_id in node_map else e.target_id
            lines.append(
                f"- [[{src_lbl}]] — **{e.relation}** (`{e.status}`, `{e.confidence:.2f}`) → [[{dst_lbl}]]"
            )

    return "\n".join(lines).strip() + "\n"


def export_stix_bundle(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    redact: bool = False,
) -> dict[str, Any]:
    """Generate a STIX 2.1 compliant JSON bundle for interoperability with MISP / OpenCTI / Maltego."""
    clean = redact_pii if redact else (lambda x: str(x or ""))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    objects: list[dict[str, Any]] = []
    stix_id_map: dict[str, str] = {}

    for n in snapshot.nodes:
        stix_type = "identity" if n.type in ("Person", "Org") else "note"
        sid = f"{stix_type}--{uuid4()}"
        stix_id_map[n.id] = sid
        if stix_type == "identity":
            objects.append(
                {
                    "type": "identity",
                    "spec_version": "2.1",
                    "id": sid,
                    "created": now_iso,
                    "modified": now_iso,
                    "name": clean(n.label),
                    "identity_class": "individual" if n.type == "Person" else "organization",
                    "confidence": int(round(n.confidence * 100)),
                    "x_stalker_claims": [
                        {
                            "category": c.category.value,
                            "key": c.key,
                            "value": clean(str(c.value)),
                            "polarity": c.polarity,
                            "source_url": clean(c.source_url),
                        }
                        for c in n.claims
                        if c.key not in ("stylometry_vector", "temporal_activity_signature")
                    ],
                }
            )
        else:
            objects.append(
                {
                    "type": "note",
                    "spec_version": "2.1",
                    "id": sid,
                    "created": now_iso,
                    "modified": now_iso,
                    "abstract": f"{n.type}: {clean(n.label)}",
                    "content": clean(n.label),
                    "object_refs": [],
                }
            )

    for e in snapshot.edges:
        src_sid = stix_id_map.get(e.source_id)
        dst_sid = stix_id_map.get(e.target_id)
        if src_sid and dst_sid:
            objects.append(
                {
                    "type": "relationship",
                    "spec_version": "2.1",
                    "id": f"relationship--{uuid4()}",
                    "created": now_iso,
                    "modified": now_iso,
                    "relationship_type": e.relation.lower().replace("_", "-"),
                    "source_ref": src_sid,
                    "target_ref": dst_sid,
                    "confidence": int(round(e.confidence * 100)),
                    "description": clean(e.evidence_quote),
                }
            )

    if dossier_items:
        target_refs = [sid for sid in stix_id_map.values() if sid.startswith("identity--")][:5]
        dossier_summary = "\n".join(
            f"- {clean(it.get('field_key', ''))}: {clean(it.get('field_value', ''))} ({clean(it.get('source_url', ''))})"
            for it in dossier_items
        )
        objects.append(
            {
                "type": "note",
                "spec_version": "2.1",
                "id": f"note--{uuid4()}",
                "created": now_iso,
                "modified": now_iso,
                "abstract": f"Verified Dossier ({len(dossier_items)} items)",
                "content": dossier_summary,
                "object_refs": target_refs,
            }
        )

    return {
        "type": "bundle",
        "id": f"bundle--{uuid4()}",
        "spec_version": "2.1",
        "x_generator": "Stalker++ v1.0",
        "x_redacted": redact,
        "objects": objects,
    }
