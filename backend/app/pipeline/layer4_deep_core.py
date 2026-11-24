"""Layer 4 (Innermost Deep Core): 8D Knowledge Graph, MCTS (UCB1), Critic Verification & Conflict Resolution.

This is the protected, highest-trust inner core of Stalker++.
It NEVER touches raw unverified web junk — it operates strictly on:
- Layer 1 validated seed anchors (`InvestigationContext`)
- Layer 2 gatekeeper-verified documents (`CollectionBundle`)

Core Algorithms executed here:
1. 8-Dimensional Entity Graph seeding & merging (SQLite + FTS5 + NetworkX).
2. Playbook selection + Blackboard initialization.
3. MCTS (UCB1) hypothesis selection -> ReaderAgent extraction -> CriticVerifierAgent anti-hallucination verification
   -> Bayesian log-odds multi-domain aggregation -> Reflexion backtracking.
4. Chronological Timeline construction & Age-Conflict audit.
5. Human-in-the-Loop Co-Steer disambiguation cards.
6. Graph Analytics: Adamic-Adar hidden link prediction & Information-Gain pivot ranking.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from app.agents.blackboard import InvestigationBlackboard
from app.agents.planner import PlannerAgent
from app.agents.playbooks import PlaybookRegistry
from app.core.graph_analytics import predict_hidden_links
from app.core.graph_store import GraphStore
from app.core.normalizer import normalize_text
from app.core.schemas import EdgeCreate, FeatureCategory, FeatureClaim, Node, NodeCreate
from app.pipeline.models import CollectionBundle, CoreReasoningResult, InvestigationContext


def build_timeline_events(
    parsed: dict[str, Any],
    ranked_sources: list[dict[str, Any]],
    anchors: dict[str, Any],
) -> list[dict[str, Any]]:
    """Build chronological timeline events from seed clues, decoded IDs, and discovered sources."""
    events: list[dict[str, Any]] = []
    seen_keys: set[tuple[int, str]] = set()
    byear = parsed.get("birth_year")

    if parsed.get("birth_date"):
        dob_parts = str(parsed["birth_date"]).split("/")
        if len(dob_parts) == 3 and dob_parts[-1].isdigit():
            y = int(dob_parts[-1])
            events.append(
                {
                    "year": y,
                    "date_label": parsed["birth_date"],
                    "event": f"Ngày sinh của {parsed['target_name']}",
                    "source_url": "user://prompt",
                    "status": "VERIFIED",
                }
            )
            seen_keys.add((y, "dob"))
    elif byear:
        events.append(
            {
                "year": int(byear),
                "date_label": str(byear),
                "event": f"Năm sinh của {parsed['target_name']}",
                "source_url": "user://prompt",
                "status": "VERIFIED",
            }
        )
        seen_keys.add((int(byear), "dob"))

    for sid in anchors.get("student_ids", []):
        if sid.get("entry_year"):
            ey = int(sid["entry_year"])
            key = (ey, f"entry:{sid['student_id']}")
            if key not in seen_keys:
                seen_keys.add(key)
                events.append(
                    {
                        "year": ey,
                        "date_label": str(ey),
                        "event": f"Nhập học {sid.get('institution', '')} {sid.get('cohort', '')} (MSSV {sid['student_id']})".strip(),
                        "source_url": "user://anchor-decoder",
                        "status": "VERIFIED",
                    }
                )

    year_re = re.compile(r"\b((?:19[89]\d|20[0-2]\d))\b")
    for src in ranked_sources[:8]:
        blob = f"{src.get('title', '')} {src.get('snippet', '')}"
        for ym in year_re.findall(blob):
            y = int(ym)
            if byear and y == int(byear):
                continue
            status = "VERIFIED" if src.get("match_score", 0) >= 3 else "CANDIDATE"
            if byear and y < int(byear) + 14:
                status = "CONFLICT"
            k = (y, src.get("url", ""))
            if k in seen_keys:
                continue
            seen_keys.add(k)
            events.append(
                {
                    "year": y,
                    "date_label": str(y),
                    "event": (src.get("title") or src.get("url") or "")[:110],
                    "source_url": src.get("url", ""),
                    "status": status,
                }
            )

    events.sort(key=lambda e: (int(e["year"]), 0 if e["status"] == "VERIFIED" else 1))
    return events[:16]


def build_disambiguation_cards(
    parsed: dict[str, Any],
    ranked_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Generate Human-in-the-Loop Co-Steer cards whenever a source shows potential homonym/org conflict."""
    cards: list[dict[str, Any]] = []
    known_orgs_norm = [normalize_text(o) for o in parsed.get("organizations", []) if o]

    for src in ranked_sources[:8]:
        title = src.get("title", "")
        snippet = src.get("snippet", "")
        url = src.get("url", "")
        blob_norm = normalize_text(f"{title} {snippet} {url}")

        matches_known_org = any(o and o in blob_norm for o in known_orgs_norm) if known_orgs_norm else True
        is_profile = any(dom in url.lower() for dom in ("linkedin.com", "facebook.com", "github.com"))
        is_conflict_candidate = (is_profile and not matches_known_org) or (
            known_orgs_norm and not matches_known_org and src.get("match_score", 0) <= 2
        )
        if not is_conflict_candidate:
            continue

        neg_hint = ""
        m_exp = re.search(r"(?:Kinh nghiệm|Experience|tại|at)[:\s]+([A-Za-zÀ-ỹ0-9&\-\s]{3,28})", snippet)
        if m_exp:
            neg_hint = m_exp.group(1).split("·")[0].strip(" .,;:-")
        elif "linkedin.com" in url.lower():
            neg_hint = title.split("-")[-1].strip()[:24] if "-" in title else "linkedin"
        else:
            clean_t = re.sub(r"^\[[^\]]+\]\s*", "", title).strip()
            neg_hint = clean_t.split()[-1] if " - " in clean_t else (clean_t.split()[0] if clean_t.split() else "")

        cards.append(
            {
                "title": title[:100] or url,
                "url": url,
                "reason": "Hồ sơ trùng tên nhưng tổ chức/ngữ cảnh khác với manh mối ban đầu — cần bạn xác nhận hoặc loại trừ.",
                "suggested_negative": neg_hint,
                "snippet": snippet[:180],
            }
        )
        if len(cards) >= 3:
            break
    return cards


def seed_core_graph_and_blackboard(
    *,
    store: GraphStore,
    ctx: InvestigationContext,
    playbook_registry: Optional[PlaybookRegistry] = None,
    use_llm: bool = False,
) -> tuple[Node, PlannerAgent, InvestigationBlackboard]:
    """Layer 4A: Seed verified 8D entities/edges into SQLite Knowledge Graph and initialize MCTS Blackboard."""
    parsed = ctx.parsed
    anchors = ctx.anchors
    target_name = ctx.target_name
    workspace_id = ctx.workspace_id

    planner = PlannerAgent(store=store, playbook_registry=playbook_registry, use_llm=use_llm)

    seed_claims: list[FeatureClaim] = []
    if parsed["birth_date"]:
        seed_claims.append(
            FeatureClaim(
                category=FeatureCategory.SPATIOTEMPORAL,
                key="birth_date",
                value=parsed["birth_date"],
                confidence=0.95,
                source_url="user://prompt",
                evidence_quote=f"Ngày sinh: {parsed['birth_date']}",
            )
        )
    if parsed["birth_year"]:
        seed_claims.append(
            FeatureClaim(
                category=FeatureCategory.SPATIOTEMPORAL,
                key="associated_year",
                value=parsed["birth_year"],
                confidence=0.95,
                source_url="user://prompt",
                evidence_quote=f"Năm sinh: {parsed['birth_year']}",
            )
        )
    for neg in parsed["negative_keywords"]:
        seed_claims.append(
            FeatureClaim(
                category=FeatureCategory.NEGATIVE_CONSTRAINT,
                key="user_negative_filter",
                value=neg,
                polarity="NEGATIVE",
                confidence=0.95,
                source_url="user://prompt",
                evidence_quote=f"Loại trừ: {neg}",
            )
        )
    for org in parsed["organizations"]:
        seed_claims.append(
            FeatureClaim(
                category=FeatureCategory.EDUCATION_CAREER,
                key="school_or_org",
                value=org,
                confidence=0.90,
                source_url="user://prompt",
                evidence_quote=f"Trường/Tổ chức: {org}",
            )
        )
    for loc in parsed["locations"]:
        seed_claims.append(
            FeatureClaim(
                category=FeatureCategory.SPATIOTEMPORAL,
                key="location",
                value=loc,
                confidence=0.85,
                source_url="user://prompt",
                evidence_quote=f"Địa điểm: {loc}",
            )
        )
    for sid_info in anchors.get("student_ids", []):
        seed_claims.append(
            FeatureClaim(
                category=FeatureCategory.IDENTITY,
                key="student_id",
                value=sid_info["student_id"],
                confidence=0.98,
                source_url="user://prompt",
                evidence_quote=f"MSSV: {sid_info['student_id']}"
                + (f" ({sid_info.get('institution', '')} {sid_info.get('cohort', '')})" if sid_info.get("cohort") else ""),
            )
        )
    for em in anchors.get("emails", []):
        seed_claims.append(
            FeatureClaim(
                category=FeatureCategory.TECHNICAL_ARTIFACT,
                key="email",
                value=em["email"],
                confidence=0.98,
                source_url="user://prompt",
                evidence_quote=f"Email: {em['email']}",
            )
        )
    for cls_c in anchors.get("class_codes", []):
        seed_claims.append(
            FeatureClaim(
                category=FeatureCategory.EDUCATION_CAREER,
                key="class_code",
                value=cls_c,
                confidence=0.92,
                source_url="user://prompt",
                evidence_quote=f"Mã lớp: {cls_c}",
            )
        )

    target_node = store.upsert_node(
        workspace_id,
        NodeCreate(type="Person", label=target_name, claims=seed_claims, confidence=0.80),
    )

    for org in parsed["organizations"]:
        org_node = store.upsert_node(workspace_id, NodeCreate(type="Org", label=org, confidence=0.90))
        store.add_edge(
            workspace_id,
            EdgeCreate(
                source_id=target_node.id,
                target_id=org_node.id,
                relation="STUDIED_OR_WORKED_AT",
                confidence=0.90,
                status="VERIFIED",
                evidence_quote=f"Manh mối liên kết: {org}",
                source_url="user://prompt",
            ),
        )
    for loc in parsed["locations"]:
        loc_node = store.upsert_node(workspace_id, NodeCreate(type="Location", label=loc, confidence=0.85))
        store.add_edge(
            workspace_id,
            EdgeCreate(
                source_id=target_node.id,
                target_id=loc_node.id,
                relation="LOCATED_IN",
                confidence=0.85,
                status="VERIFIED",
                evidence_quote=f"Manh mối địa điểm: {loc}",
                source_url="user://prompt",
            ),
        )
    for alias in parsed.get("aliases", []):
        al_val = str(alias or "").strip()
        if al_val and not al_val.isdigit():
            al_node = store.upsert_node(workspace_id, NodeCreate(type="Alias", label=al_val, confidence=0.90))
            store.add_edge(
                workspace_id,
                EdgeCreate(
                    source_id=target_node.id,
                    target_id=al_node.id,
                    relation="OWNS_ACCOUNT",
                    confidence=0.90,
                    status="VERIFIED",
                    evidence_quote=f"Tài khoản / Biệt danh: {al_val}",
                    source_url="user://prompt",
                ),
            )
    for rp in parsed.get("related_people", []):
        rp_name = str(rp.get("name") or "").strip()
        rp_rel = str(rp.get("relation") or "RELATED_TO")
        if rp_name:
            rp_node = store.upsert_node(workspace_id, NodeCreate(type="Person", label=rp_name, confidence=0.90))
            store.add_edge(
                workspace_id,
                EdgeCreate(
                    source_id=target_node.id,
                    target_id=rp_node.id,
                    relation=rp_rel,
                    confidence=0.90,
                    status="VERIFIED",
                    evidence_quote=f"Manh mối quan hệ ({rp_rel}): {rp_name}",
                    source_url="user://prompt",
                ),
            )
            store.add_dossier_item(
                workspace_id=workspace_id,
                field_key=f"Người liên quan ({rp_rel})",
                field_value=f"{target_name} — {rp_name}",
                category="social_relation",
                source_url="user://prompt",
                note="Tự động lưu từ thông tin đầu vào",
            )

    # Auto-seed structured confirmed clues from user input directly into Verified Dossier.
    # CRITICAL: If this turn pivoted to a secondary/related person (e.g., sibling "Đặng Như Phong" inside
    # the workspace for "Đặng Kiều Diễm"), NEVER overwrite the primary subject's "Họ và tên" / "Ngày sinh" /
    # "MSSV" with the secondary person's fields — tag them under the secondary person's name instead!
    ws_obj = store.get_workspace(workspace_id)
    ws_name_norm = normalize_text(ws_obj.name) if ws_obj else ""
    existing_dossier = store.list_dossier_items(workspace_id)
    primary_dossier_name = next(
        (
            str(it.get("field_value") or "").strip()
            for it in existing_dossier
            if str(it.get("field_key") or "").strip().lower() in ("họ và tên", "họ tên", "full name")
        ),
        "",
    )
    is_secondary_person_pivot = bool(
        target_name
        and target_name != "Đối tượng chưa rõ tên"
        and (
            (primary_dossier_name and normalize_text(target_name) != normalize_text(primary_dossier_name))
            or (
                not primary_dossier_name
                and ws_name_norm
                and not ws_name_norm.startswith(("dieu tra", "investigation"))
                and normalize_text(target_name) != ws_name_norm
                and ws_name_norm not in normalize_text(target_name)
                and normalize_text(target_name) not in ws_name_norm
            )
        )
    )
    key_suffix = f" ({target_name})" if is_secondary_person_pivot else ""

    if target_name and target_name != "Đối tượng chưa rõ tên" and len(target_name) <= 60:
        if is_secondary_person_pivot:
            store.add_dossier_item(
                workspace_id=workspace_id,
                field_key="Người liên quan đang tra cứu",
                field_value=target_name,
                category="social_relation",
                source_url="user://prompt",
                note="Tự động lưu từ thông tin đầu vào (không ghi đè mục tiêu chính)",
            )
        else:
            store.add_dossier_item(
                workspace_id=workspace_id,
                field_key="Họ và tên",
                field_value=target_name,
                category="identity",
                source_url="user://prompt",
                note="Tự động lưu từ thông tin đầu vào",
            )
    if parsed.get("birth_date"):
        store.add_dossier_item(
            workspace_id=workspace_id,
            field_key=f"Ngày sinh{key_suffix}",
            field_value=str(parsed["birth_date"]),
            category="spatiotemporal",
            source_url="user://prompt",
            note="Tự động lưu từ thông tin đầu vào",
        )
    elif parsed.get("birth_year"):
        store.add_dossier_item(
            workspace_id=workspace_id,
            field_key=f"Năm sinh{key_suffix}",
            field_value=str(parsed["birth_year"]),
            category="spatiotemporal",
            source_url="user://prompt",
            note="Tự động lưu từ thông tin đầu vào",
        )
    for org in parsed.get("organizations", []):
        if org and len(org) <= 80:
            store.add_dossier_item(
                workspace_id=workspace_id,
                field_key=f"Trường / Tổ chức{key_suffix}",
                field_value=org,
                category="education_career",
                source_url="user://prompt",
                note="Tự động lưu từ thông tin đầu vào",
            )
    for loc in parsed.get("locations", []):
        if loc and len(loc) <= 60:
            store.add_dossier_item(
                workspace_id=workspace_id,
                field_key=f"Địa điểm / Quê quán{key_suffix}",
                field_value=loc,
                category="spatiotemporal",
                source_url="user://prompt",
                note="Tự động lưu từ thông tin đầu vào",
            )
    for sid_info in anchors.get("student_ids", []):
        sid_val = str(sid_info.get("student_id") or "").strip()
        if sid_val:
            store.add_dossier_item(
                workspace_id=workspace_id,
                field_key=f"MSSV / Mã định danh{key_suffix}",
                field_value=sid_val,
                category="identity",
                source_url="user://prompt",
                note="Tự động lưu từ thông tin đầu vào",
            )
    for em in anchors.get("emails", []):
        em_val = str(em.get("email") or "").strip()
        if em_val:
            store.add_dossier_item(
                workspace_id=workspace_id,
                field_key=f"Email{key_suffix}",
                field_value=em_val,
                category="technical_artifact",
                source_url="user://prompt",
                note="Tự động lưu từ thông tin đầu vào",
            )
    for cls_c in anchors.get("class_codes", []):
        if cls_c:
            store.add_dossier_item(
                workspace_id=workspace_id,
                field_key=f"Mã lớp{key_suffix}",
                field_value=str(cls_c),
                category="education_career",
                source_url="user://prompt",
                note="Tự động lưu từ thông tin đầu vào",
            )

    playbook_id = (
        "developer_digital_footprint"
        if parsed["aliases"] and not parsed["organizations"]
        else "vietnam_student_alumni"
    )
    bb = planner.initialize_blackboard(
        workspace_id=workspace_id,
        target_name=target_name,
        playbook_id=playbook_id,
        aliases=parsed["aliases"],
        organizations=parsed["organizations"],
        locations=parsed["locations"],
        keywords=parsed["keywords"],
        negative_keywords=parsed["negative_keywords"],
    )
    return target_node, planner, bb


async def run_layer4_deep_core(
    *,
    store: GraphStore,
    ctx: InvestigationContext,
    bundle: CollectionBundle,
    target_node: Node,
    planner: PlannerAgent,
    bb: InvestigationBlackboard,
) -> CoreReasoningResult:
    """Layer 4B (Innermost Deep Core): Execute MCTS + Critic Verification + Graph Analytics on clean verified docs."""
    selected = planner.select_next_hypothesis(bb)
    step_result: dict[str, Any] = {}
    if selected and bundle.relevant_docs:
        step_result = await planner.evaluate_and_expand(
            bb=bb,
            hypothesis_id=selected.id,
            collected_texts=bundle.relevant_docs[:6],
            max_depth=3,
        )

    store.save_blackboard(bb)

    snapshot = store.get_graph(ctx.workspace_id)
    g = store.to_networkx(ctx.workspace_id)
    hidden_links = predict_hidden_links(g, top_k=3)
    pivots = store.suggest_pivots(ctx.workspace_id, top_k=3)
    refreshed_target = store.get_node(target_node.id) or target_node

    timeline_events = build_timeline_events(ctx.parsed, bundle.ranked_sources, ctx.anchors)
    disambiguation_cards = build_disambiguation_cards(ctx.parsed, bundle.ranked_sources)

    return CoreReasoningResult(
        target_node=refreshed_target,
        blackboard=bb,
        step_result=step_result,
        timeline_events=timeline_events,
        disambiguation_cards=disambiguation_cards,
        hidden_links=hidden_links,
        recommended_pivots=pivots,
        graph_stats={
            "nodes": len(snapshot.nodes) if snapshot else 0,
            "edges": len(snapshot.edges) if snapshot else 0,
        },
    )
