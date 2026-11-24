"""Layer 5 (Synthesis & Delivery): Executive Report, Smart Dorks, Pipeline Telemetry & Persistence."""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from app.config import settings
from app.connectors.web_search import DorkRequest, generate_smart_dorks
from app.core.graph_store import GraphStore
from app.core.key_pool import IntegrationStore
from app.core.llm_provider import GeminiProvider
from app.pipeline.models import CollectionBundle, CoreReasoningResult, InvestigationContext


async def run_layer5_synthesis(
    *,
    store: GraphStore,
    ctx: InvestigationContext,
    bundle: CollectionBundle,
    core_result: CoreReasoningResult,
    live_search: bool = True,
    model_override: Optional[str] = None,
    layer_timings_ms: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """Synthesize final executive report, deduplicate dorks, attach 5-layer telemetry, and persist turn."""
    parsed = ctx.parsed
    anchors = ctx.anchors
    target_name = ctx.target_name
    region = ctx.region
    bb = core_result.blackboard
    ranked_sources = bundle.ranked_sources

    # Deduplicated Smart Dorks (Plugin Bus + Mirror Pivots + Intersection + Platform Dorks)
    dorks = (
        bundle.bus_dorks[:3]
        + bundle.mirror_queries[:3]
        + bundle.intersection_queries
        + generate_smart_dorks(
            DorkRequest(
                full_name=target_name,
                aliases=parsed["aliases"],
                organizations=parsed["organizations"],
                locations=parsed["locations"],
                keywords=parsed["keywords"] + ([parsed["birth_date"]] if parsed["birth_date"] else []),
                negative_keywords=bb.negative_keywords,
            )
        )
    )
    seen_dq: set[str] = set()
    unique_dorks: list[dict[str, str]] = []
    for d in dorks:
        if d["query"] not in seen_dq:
            seen_dq.add(d["query"])
            unique_dorks.append(d)

    # Optional Gemini text synthesis when Google Search Grounding was not used/available
    google_ai_summary = bundle.google_ai_summary
    google_ai_error = bundle.google_ai_error
    int_store = IntegrationStore(store.db_path)
    local_cfg = int_store.get_local_config()

    if live_search and not google_ai_summary and ranked_sources and local_cfg.active_mode in ("auto", "gemini_pool"):
        src_digest = "\n".join(f"- {s['title']} ({s['url']}): {s['snippet']}" for s in ranked_sources[:8])
        rel_desc = ", ".join(
            f"{rp.get('relation', 'RELATED_TO')} -> {rp.get('name', '')}"
            for rp in parsed.get("related_people", [])
            if rp.get("name")
        )
        tree_info = bundle.investigation_tree or {}
        tree_summary = ""
        if tree_info.get("activated"):
            tree_lines = [
                f"  - [{n['branch_id']} | d={n['depth']} | {n['status']} | score={n['score']}] {n['label']}"
                + (f" (reason: {n['conflict_reason']})" if n.get("conflict_reason") else "")
                for n in (tree_info.get("nodes") or [])[:10]
            ]
            tree_summary = "\nDivide-and-Conquer Decision Tree:\n" + "\n".join(tree_lines) + "\n"
        dossier_section = (
            f"\nDỮ LIỆU ĐÃ XÁC NHẬN TRONG HỒ SƠ (Ground Truth — ƯU TIÊN TUYỆT ĐỐI):\n{ctx.dossier_blob[:1600]}\n"
            if ctx.dossier_blob
            else ""
        )
        if region == "global":
            synth_prompt = (
                f"Analyze public OSINT findings for primary target '{target_name}'.\n"
                f"Known clues: DOB={parsed['birth_date'] or parsed['birth_year']}, "
                f"organizations={parsed['organizations']}, locations={parsed['locations']}, "
                f"related_people=[{rel_desc or 'none'}], "
                f"IDs={[s['student_id'] for s in anchors.get('student_ids', [])]}.{tree_summary}{dossier_section}\n"
                f"Collected public sources:\n{src_digest}\n\n"
                "CRITICAL RULE: Never confuse biographical attributes (birth year, title, employer) of a related person "
                "(parent/spouse/sibling) with those of the primary target. Always respect Ground Truth in Verified Dossier.\n"
                "Summarize concisely in English with clean Markdown headings: "
                "(1) Most authoritative sources and verified facts, "
                "(2) Current entity resolution & uncertainty assessment (no fabrication), "
                "(3) Recommended next public OSINT pivots."
            )
        else:
            synth_prompt = (
                f"Phân tích kết quả OSINT công khai cho mục tiêu chính '{target_name}'.\n"
                f"Manh mối đã biết: ngày/năm sinh={parsed['birth_date'] or parsed['birth_year']}, "
                f"tổ chức={parsed['organizations']}, địa điểm={parsed['locations']}, "
                f"người liên quan=[{rel_desc or 'không có'}], "
                f"MSSV={[s['student_id'] for s in anchors.get('student_ids', [])]}.{tree_summary}{dossier_section}\n"
                f"Các nguồn vừa thu thập được:\n{src_digest}\n\n"
                "QUY TẮC BẮT BUỘC: Luôn tôn trọng các sự kiện đã xác nhận trong Hồ sơ (Ground Truth) và không bịa đặt hay gán nhầm thông tin của người trùng tên / người liên quan sang mục tiêu chính.\n"
                "Hãy tổng hợp ngắn gọn bằng tiếng Việt: (1) Nguồn nào đáng giá nhất và chứa thông tin gì, "
                "(2) Nhận định khoanh vùng hiện tại (nêu rõ độ bất định, nhánh nào xác nhận/nhánh nào đã quay lui, không bịa đặt), (3) Gợi ý bước tra cứu tiếp theo."
            )

        # Rotate across ALL configured Gemini keys on 401/403/429/connection failure (up to 8 keys)
        active_synth_keys = [k for k in int_store.list_keys("gemini") if k.get("enabled")]
        max_synth_attempts = max(1, min(len(active_synth_keys), 8))
        tried_synth_ids: set[str] = set()
        for k_attempt in range(max_synth_attempts):
            synth_key_obj = int_store.acquire_key("gemini")
            if synth_key_obj and synth_key_obj["id"] in tried_synth_ids:
                break
            if synth_key_obj:
                tried_synth_ids.add(synth_key_obj["id"])
            synth_key = synth_key_obj["api_key"] if synth_key_obj else (settings.gemini_api_key if k_attempt == 0 else "")
            synth_key_label = synth_key_obj["name"] if synth_key_obj else "env:STALKER_GEMINI_API_KEY"
            synth_model = model_override or (
                synth_key_obj["model"] if (synth_key_obj and synth_key_obj.get("model")) else settings.gemini_model
            )
            if not synth_key:
                break

            rotate_synth_key = False
            for sm in [
                synth_model,
                "gemini-4-hydrogen",
                "gemini-3.8-flash",
                "gemini-3.6-flash",
                "gemini-3.5-flash-lite",
                "gemini-3.1-flash-lite",
            ]:
                try:
                    google_ai_summary = await GeminiProvider(synth_key, sm).generate(synth_prompt)
                    if google_ai_summary:
                        bb.log(
                            "ReaderAgent",
                            "GEMINI_SYNTHESIS",
                            f"Tổng hợp kết quả bằng Key [{synth_key_label}] ({sm}) (không tốn quota Google Search)",
                        )
                        google_ai_error = ""
                        break
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    if code in (400, 404, 503):
                        continue
                    if synth_key_obj:
                        int_store.report_key_error(synth_key_obj["id"], is_rate_limit=(code == 429))
                    bb.log(
                        "ReaderAgent",
                        "SYNTHESIS_KEY_ROTATION",
                        f"Key [{synth_key_label}] lỗi HTTP {code} -> Xoay sang key Gemini kế tiếp.",
                    )
                    rotate_synth_key = True
                    break
                except Exception:
                    if synth_key_obj:
                        int_store.report_key_error(synth_key_obj["id"], is_rate_limit=False)
                    rotate_synth_key = True
                    break
            if google_ai_summary or not rotate_synth_key:
                break

    # Build clean human-readable executive report
    readable_claims = [
        c
        for c in core_result.target_node.claims
        if c.polarity == "POSITIVE" and c.key not in ("stylometry_vector", "temporal_activity_signature")
    ]
    filtered_out_count = bundle.gatekeeper_stats.rejected_count

    lines: list[str] = []
    if ctx.vision_extracted_text:
        lines.append(f"**Phân tích từ ảnh chụp bạn gửi (Vision OCR):**\n{ctx.vision_extracted_text}")
    if google_ai_summary:
        lines.append(google_ai_summary)
    else:
        if google_ai_error:
            lines.append(f"**Cảnh báo Gemini API:** {google_ai_error} (hệ thống đã tự chuyển sang chế độ tìm kiếm cục bộ).")
        clue_summary_parts = [f"**{target_name}**"]
        if parsed["birth_date"]:
            clue_summary_parts.append(f"sinh ngày **{parsed['birth_date']}**")
        elif parsed["birth_year"]:
            clue_summary_parts.append(f"sinh năm **{parsed['birth_year']}**")
        if parsed["organizations"]:
            clue_summary_parts.append(f"liên quan tới **{', '.join(parsed['organizations'])}**")
        if parsed["locations"]:
            clue_summary_parts.append(f"tại **{', '.join(parsed['locations'])}**")
        lines.append(
            f"Đã chạy vòng lặp **5-Layer Concentric OSINT Pipeline (Lọc ngoài -> Thu thập đa kênh -> Lõi 8D MCTS)** cho: {', '.join(clue_summary_parts)}."
        )
    if anchors.get("student_ids"):
        sid_desc = ", ".join(
            f"`{s['student_id']}`" + (f" ({s.get('institution', '')} {s.get('cohort', '')})" if s.get("cohort") else "")
            for s in anchors["student_ids"]
        )
        lines.append(f"**Giải mã Khóa chính (MSSV):** {sid_desc}.")
    if bundle.network_diagnostics:
        down = [d for d in bundle.network_diagnostics if not d["reachable"]]
        if down:
            lines.append(
                "**Chẩn đoán Tầng Mạng:** "
                + "; ".join(f"`{d['url']}` ({d['diagnosis']})" for d in down)
            )
    if bundle.bus_notes:
        lines.append("**Phân tích Chuyên môn (Plugin Bus):** " + " · ".join(bundle.bus_notes[:4]))

    if ranked_sources:
        lines.append(
            f"Tìm thấy **{len(ranked_sources)} nguồn công khai có nhắc trực tiếp tới mục tiêu** "
            f"(Tầng 2 Gatekeeper đã lọc bỏ **{filtered_out_count}** trang nhiễu trước khi đưa vào Lõi)."
        )
    else:
        lines.append(
            f"Chưa thấy trang công khai nào trên chỉ mục mở khớp đồng thời tên **{target_name}** cùng các trường/ngày sinh trên "
            f"(Tầng 2 Gatekeeper đã lọc bỏ **{filtered_out_count}** kết quả nhiễu). "
            "Bạn có thể bấm trực tiếp nút **Google AI** bên dưới để tra sâu trên Google, hoặc bật **Google AI Mode** bằng Gemini API Key ở góc trên phải."
        )

    if readable_claims:
        seen_kv: set[str] = set()
        clean_items: list[str] = []
        for c in readable_claims:
            val_str = str(c.value or "").strip()
            if not val_str or any(ch in val_str for ch in ("#", "[", "]", "*")) or len(val_str) > 65:
                continue
            if c.key == "school_or_org" and re.match(
                r"^(?:đang\s+học|từng\s+học|học\s+sinh|sinh\s+viên|cựu\s+học\s+sinh)\b",
                val_str,
                flags=re.IGNORECASE,
            ):
                continue
            item_str = f"{c.key}: {val_str}"
            if item_str not in seen_kv:
                seen_kv.add(item_str)
                clean_items.append(item_str)
        if clean_items:
            lines.append(f"**Hồ sơ đặc trưng đã khóa ({len(clean_items)}):** " + " · ".join(clean_items[:8]))

    pipeline_telemetry = {
        "architecture": "5-layer-concentric-osint",
        "gatekeeper": bundle.gatekeeper_stats.to_dict(),
        "layer_timings_ms": layer_timings_ms or {},
        "investigation_tree": bundle.investigation_tree or {},
    }

    response_payload = {
        "blackboard_id": bb.id,
        "assistant_reply": "\n\n".join(lines),
        "parsed_clues": parsed,
        "discovered_sources": ranked_sources[:8],
        "suggested_dorks": unique_dorks[:6],
        "reasoning_steps": [t.model_dump(mode="json") for t in bb.trace[-12:]],
        "learned_negative_keywords": bb.negative_keywords,
        "recommended_pivots": core_result.recommended_pivots,
        "hidden_links": core_result.hidden_links,
        "timeline_events": core_result.timeline_events,
        "disambiguation_cards": core_result.disambiguation_cards,
        "plugin_bus_trace": bundle.bus_trace,
        "correlations": bundle.bus_correlations,
        "graph_stats": core_result.graph_stats,
        "step_reward": core_result.step_result.get("reward", 0.0),
        "pipeline_telemetry": pipeline_telemetry,
    }
    store.add_chat_message(
        ctx.workspace_id,
        role="assistant",
        content=response_payload["assistant_reply"],
        payload=response_payload,
    )
    return response_payload
