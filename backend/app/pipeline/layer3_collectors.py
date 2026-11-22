"""Layer 3 (Multi-Channel Collection & Enrichment): Collectors Funneled Through Layer 2 Gatekeeper.

Organized into 5 crisp sub-stages:
- Stage 3A: Direct URL health diagnostics + Wayback Machine archive recovery + Explicit GitHub aliases.
- Stage 3B: Autonomous 2-round Google AI Search Grounding (with Key Pool rotation & model fallback).
- Stage 3C: SpiderFoot Event-Driven Plugin Bus (Maigret/Sherlock username recon, PhoneInfoga, 5-feed Passive DNS/Email, Correlator).
- Stage 3D: Global Structured Public Registries (OpenAlex/ORCID, GitHub Name Search, RDAP/crt.sh).
- Stage 3E: Concurrent Cross-Clue Search (Round 1 Intersection -> Round 2 Mirror Pivots -> Adaptive GitHub Pivot -> Deep PDF/XLSX Reader).

Strict Invariant: Every single discovered source MUST pass through `gatekeeper.evaluate_candidate()` (Layer 2)
before it is permitted to enter Layer 4 (the Deep Core).
"""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.agents.blackboard import InvestigationBlackboard
from app.config import settings
from app.connectors.document_reader import fetch_and_inspect_document, is_inspectable_document_url
from app.connectors.github_api import GitHubPublicConnector
from app.connectors.global_intel import (
    inspect_domain_infrastructure,
    is_custom_org_domain,
    search_github_by_name,
    search_openalex_authors,
)
from app.connectors.mirror_pivots import (
    build_mirror_pivot_queries,
    check_wayback_snapshot,
    diagnose_url_health,
)
from app.connectors.web_fetcher import PublicWebFetcher
from app.connectors.web_search import WebSearchConnector
from app.core.anchor_decoder import decode_high_entropy_anchors
from app.core.graph_store import GraphStore
from app.core.llm_provider import GeminiProvider
from app.core.normalizer import normalize_text, strip_vietnamese_accents
from app.pipeline.layer2_gatekeeper import OuterGatekeeper
from app.pipeline.models import CollectionBundle, InvestigationContext
from app.plugins.base import OSINTEvent
from app.plugins.registry import PluginRegistry


def build_intersection_queries(parsed: dict[str, Any]) -> list[dict[str, str]]:
    """Build exact-name + clue intersection queries prioritizing highest-entropy anchors (exact DOB, orgs)."""
    name = parsed["target_name"]
    no_accent = strip_vietnamese_accents(name)
    neg_str = " ".join(f'-"{n}"' for n in parsed.get("negative_keywords", []))

    queries: list[dict[str, str]] = []
    orgs = parsed.get("organizations", [])
    locs = parsed.get("locations", [])
    kws = parsed.get("keywords", [])
    related = parsed.get("related_people", [])
    dob = parsed.get("birth_date", "")
    byear = parsed.get("birth_year")

    # 0. Relational Intersection Queries (e.g. "Nguyễn Minh An" + "Nguyễn Văn Bình")
    for rp in related[:2]:
        rp_name = str(rp.get("name") or "").strip()
        if not rp_name:
            continue
        queries.append(
            {
                "strategy": f"intersect_relation:{rp.get('relation', 'RELATED')}",
                "query": f'"{name}" "{rp_name}" {neg_str}'.strip(),
            }
        )
        queries.append(
            {
                "strategy": "natural_relation",
                "query": f"{name} {rp_name} {neg_str}".strip(),
            }
        )
        queries.append(
            {
                "strategy": "exact_target_from_relation",
                "query": f'"{name}" {neg_str}'.strip(),
            }
        )
        queries.append(
            {
                "strategy": "related_person_context",
                "query": f'"{rp_name}" {neg_str}'.strip(),
            }
        )

    # Prefer short uppercase org acronym (e.g., UEH, USSH, UIT, HUST)
    short_org_hint = next(
        (o for o in orgs if re.match(r"^[A-Za-z]{2,8}$", o.strip())),
        next(
            (k for k in kws if re.match(r"^[A-Za-z]{2,6}$", k.strip())),
            orgs[0] if orgs else "",
        ),
    )

    # 1. Highest-Entropy Priority: Exact Name + Exact Full DOB (DD/MM/YYYY) (+ Org)
    if dob:
        if short_org_hint:
            q_dob_org = f'"{name}" "{dob}" {short_org_hint} {neg_str}'.strip()
            queries.append({"strategy": "intersect_dob_org", "query": q_dob_org})
        q_dob = f'"{name}" "{dob}" {neg_str}'.strip()
        queries.append({"strategy": "intersect_exact_dob", "query": q_dob})

    # 2. Exact Name + EACH Organization/School separately + natural unquoted query
    for org in orgs[:3]:
        org_clean = org.strip()
        org_clause = org_clean if (" " not in org_clean and len(org_clean) <= 10) else f'"{org_clean}"'
        q = f'"{name}" {org_clause} {neg_str}'.strip()
        queries.append({"strategy": f"intersect_org:{org_clean}", "query": q})
    if orgs:
        primary_org_clean = orgs[0].strip()
        q_nat = f"{name} {primary_org_clean} {neg_str}".strip()
        queries.append({"strategy": f"natural_name_org:{primary_org_clean}", "query": q_nat})

    # 3. Exact Name + All Organizations together if >= 2
    if len(orgs) >= 2:
        q = f'"{name}" "{orgs[0]}" "{orgs[1]}" {neg_str}'.strip()
        queries.append({"strategy": "intersect_multi_org", "query": q})

    # 4. Exact Name + Birth Year (only when full DOB wasn't provided)
    if not dob and byear:
        q = f'"{name}" "{byear}" {neg_str}'.strip()
        queries.append({"strategy": "intersect_year", "query": q})

    # 5. Exact Name + Location
    for loc in locs[:1]:
        q = f'"{name}" "{loc}" {neg_str}'.strip()
        queries.append({"strategy": f"intersect_loc:{loc}", "query": q})

    # 6. Unaccented exact name + primary org
    if no_accent.lower() != name.lower() and orgs:
        q = f'"{no_accent}" "{orgs[0]}" {neg_str}'.strip()
        queries.append({"strategy": "intersect_unaccented", "query": q})

    if not queries:
        queries.append({"strategy": "exact_name", "query": f'"{name}" {neg_str}'.strip()})

    return queries


async def run_layer3_collectors(
    *,
    ctx: InvestigationContext,
    gatekeeper: OuterGatekeeper,
    store: GraphStore,
    bb: InvestigationBlackboard,
    live_search: bool = True,
    deep_mode: bool = True,
    model_override: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> CollectionBundle:
    """Execute all Layer 3 collection channels and filter every candidate through Layer 2 Gatekeeper."""
    parsed = ctx.parsed
    anchors = ctx.anchors
    target_name = ctx.target_name
    region = ctx.region

    bundle = CollectionBundle(
        intersection_queries=build_intersection_queries(parsed),
        mirror_queries=build_mirror_pivot_queries(parsed, anchors, region=region),
    )

    if ctx.vision_extracted_text:
        bb.log("ReaderAgent", "VISION_OCR", f"Extracted {len(ctx.vision_extracted_text)} chars from attached screenshot.")
        gatekeeper.relevant_docs.append({"text": ctx.vision_extracted_text, "source_url": "user://uploaded-screenshot"})

    # ------------------------------------------------------------------
    # Stage 3A: Direct URLs (Health Diagnostics + Wayback) & Explicit GitHub Aliases
    # ------------------------------------------------------------------
    if live_search and parsed["urls"]:
        fetcher = PublicWebFetcher(store.db_path)
        for url in parsed["urls"][:3]:
            diag = await diagnose_url_health(url, client=client)
            bundle.network_diagnostics.append(diag)
            if not diag["reachable"]:
                bb.log("CollectorAgent", "NETWORK_DIAGNOSIS", f"{url} -> {diag['diagnosis']}")
                wb = await check_wayback_snapshot(url, client=client)
                if wb:
                    bb.log("CollectorAgent", "WAYBACK_RECOVERY", f"Found archived snapshot: {wb['archived_url']}")
                    gatekeeper.evaluate_candidate(
                        f"Wayback Archive ({wb['timestamp']})",
                        wb["archived_url"],
                        f"Bản lưu dự phòng của {url} do server gốc không phản hồi.",
                        force_keep=True,
                    )
                continue
            try:
                page = await fetcher.collect(url, client=client)
                if not page.is_soft_404 and page.content:
                    gatekeeper.evaluate_candidate(page.title, page.url, page.content[:1500], force_keep=True)
            except Exception:
                continue

    if live_search and parsed["aliases"]:
        gh = GitHubPublicConnector(store.db_path)
        for alias in parsed["aliases"][:2]:
            try:
                gh_doc = await gh.collect(alias, client=client)
                if not gh_doc.is_soft_404:
                    summary = f"{gh_doc.title}. {gh_doc.content}. " + " ".join(
                        c.evidence_quote for c in gh_doc.claims
                    )
                    gatekeeper.evaluate_candidate(gh_doc.title, gh_doc.url, summary, force_keep=True)
            except Exception:
                continue

    # ------------------------------------------------------------------
    # Stage 3B: Autonomous 2-Round Google AI Grounding (Key Pool Rotation + Fallback)
    # ------------------------------------------------------------------
    from app.core.key_pool import IntegrationStore

    int_store = IntegrationStore(store.db_path)
    local_cfg = int_store.get_local_config()

    if live_search and local_cfg.active_mode in ("auto", "gemini_pool"):
        dossier_ctx = f"\nThông tin ĐÃ XÁC NHẬN trong Hồ sơ tổng hợp:\n{ctx.dossier_blob}" if ctx.dossier_blob else ""
        geo_ctx = f"\nTọa độ bản đồ đính kèm: {ctx.geo_blob}" if ctx.geo_blob else ""
        system_osint = (
            "Bạn là chuyên gia điều tra thông tin mở (OSINT) chuyên nghiệp. "
            "Quy tắc bắt buộc:\n"
            "1. Chỉ trích dẫn các tài liệu/trang CỤ THỂ (như /document/ trên Studocu/Scribd, file PDF, cổng thông tin chính thức, hồ sơ cá nhân khớp dữ kiện). TUYỆT ĐỐI bỏ qua trang chủ đề/chuyên mục chung chung.\n"
            "2. Luôn truy tìm các mỏ neo bất biến: Số hiệu quyết định/văn bản, Mã ID tài liệu Studocu/Scribd, link rút gọn chính thức, mã lớp, và các MSSV liền kề để kẹp khoảng.\n"
            "3. Giữ tính khách quan: phân biệt rõ đâu là DỮ KIỆN ĐÃ XÁC THỰC và đâu là GIẢ THUYẾT KHOANH VÙNG (kèm xác suất ước lượng, không bịa đặt)."
        )
        g_prompt_r1 = (
            f"Hãy dùng Google Search tìm kiếm chuyên sâu thông tin công khai về đúng 1 đối tượng:\n"
            f"- Tên: {target_name}\n"
            f"- Ngày/năm sinh: {parsed['birth_date'] or parsed['birth_year'] or 'Chưa rõ'}\n"
            f"- Trường/Tổ chức: {parsed['organizations']}\n"
            f"- Địa điểm: {parsed['locations']}\n"
            f"- MSSV / Mã định danh: {[s['student_id'] for s in anchors.get('student_ids', [])]}\n"
            f"- Email: {[e['email'] for e in anchors.get('emails', [])]}\n"
            f"- Từ khóa bổ sung: {parsed['keywords']}\n"
            f"- Loại trừ: {parsed['negative_keywords']}"
            f"{dossier_ctx}{geo_ctx}\n\n"
            f"Yêu cầu gốc của người dùng: {ctx.raw_prompt}\n"
            "Hãy tìm mọi nguồn công khai liên quan trực tiếp (kể cả bản lưu trên Studocu/Scribd nếu web gốc lỗi), "
            "liệt kê chính xác Tên tài liệu, Mã ID tài liệu, Số hiệu văn bản (nếu có) và gợi ý bước tra cứu tiếp theo."
        )
        fallback_models = [
            "gemini-3.5-flash-lite",
            "gemini-4-hydrogen",
            "gemini-3.6-flash",
            "gemini-3.1-flash-lite",
            "gemini-3.8-flash",
        ]
        for attempt in range(3):
            pool_key = int_store.acquire_key("gemini")
            api_key_to_use = pool_key["api_key"] if pool_key else (settings.gemini_api_key if attempt == 0 else "")
            requested_model = (
                model_override
                or (pool_key["model"] if (pool_key and pool_key.get("model")) else settings.gemini_model)
            )
            key_label = pool_key["name"] if pool_key else "env:STALKER_GEMINI_API_KEY"
            if not api_key_to_use:
                break

            models_to_try = [requested_model] + [m for m in fallback_models if m != requested_model]
            succeeded = False
            rotate_next_key = False

            for mdl in models_to_try:
                try:
                    g_provider = GeminiProvider(api_key_to_use, mdl)
                    bb.log("CollectorAgent", "GOOGLE_AI_ROUND1", f"Key [{key_label}] ({mdl}) -> Google Search Grounding Round 1")
                    g_res = await g_provider.generate_with_google_search(g_prompt_r1, system=system_osint, client=client)
                    bundle.google_ai_summary = g_res.get("text", "")
                    for src in g_res.get("sources", []):
                        gatekeeper.evaluate_candidate(
                            src["title"], src["url"], "Nguồn xác thực từ Google Search Grounding", force_keep=True
                        )

                    if deep_mode and bundle.google_ai_summary:
                        r1_anchors = decode_high_entropy_anchors(bundle.google_ai_summary)
                        for dno in r1_anchors.get("doc_numbers", []):
                            if dno not in anchors["doc_numbers"]:
                                anchors["doc_numbers"].append(dno)
                        g_prompt_r2 = (
                            f"Dựa trên kết quả Vòng 1 dưới đây về {target_name}:\n"
                            f"---\n{bundle.google_ai_summary[:2500]}\n---\n"
                            "Hãy chạy thêm 1 lượt Google Search đào sâu vào các tài liệu/cổng thông tin/mã văn bản vừa phát hiện "
                            "(ưu tiên tìm bản PDF/Studocu/Scribd cụ thể, kẹp khoảng mã số nếu có, hoặc cổng tra cứu công khai liên quan) "
                            "rồi tổng hợp thành báo cáo cuối cùng ngắn gọn, rõ ràng, chia thành: "
                            "(1) Thông tin & Tài liệu cụ thể tìm được kèm Mã ID/Link, (2) Phân tích & Khoanh vùng, (3) Bước tiếp theo cho người dùng."
                        )
                        bb.log("CollectorAgent", "GOOGLE_AI_ROUND2", f"Key [{key_label}] ({mdl}) -> Deep Follow-up Round 2")
                        g_res2 = await g_provider.generate_with_google_search(g_prompt_r2, system=system_osint, client=client)
                        if g_res2.get("text"):
                            bundle.google_ai_summary = g_res2["text"]
                        for src in g_res2.get("sources", []):
                            gatekeeper.evaluate_candidate(
                                src["title"], src["url"], "Nguồn đào sâu Vòng 2 (Google AI)", force_keep=True
                            )

                    succeeded = True
                    break
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    err_snippet = exc.response.text[:160].replace("\n", " ")
                    if code in (400, 404, 503):
                        bundle.google_ai_error = f"Model '{mdl}' trả về HTTP {code}: {err_snippet}"
                        bb.log("CollectorAgent", "MODEL_FALLBACK", f"{bundle.google_ai_error} -> Tự động thử model kế tiếp.")
                        continue
                    if code == 429:
                        bundle.google_ai_error = (
                            f"Key [{key_label}] hết quota tool google_search (HTTP 429) -> "
                            "Chuyển sang tìm kiếm mở + Gemini đọc tổng hợp."
                        )
                        bb.log("CollectorAgent", "GOOGLE_SEARCH_QUOTA_FALLBACK", bundle.google_ai_error)
                        rotate_next_key = True
                        break
                    if pool_key:
                        int_store.report_key_error(pool_key["id"], is_rate_limit=False)
                    bundle.google_ai_error = f"Key [{key_label}] lỗi HTTP {code}: {err_snippet}"
                    bb.log("CollectorAgent", "KEY_ROTATION_FAILOVER", f"{bundle.google_ai_error} -> Xoay sang key kế tiếp.")
                    rotate_next_key = True
                    break
                except Exception as exc:
                    if pool_key:
                        int_store.report_key_error(pool_key["id"], is_rate_limit=False)
                    bundle.google_ai_error = f"Key [{key_label}] lỗi kết nối: {type(exc).__name__}"
                    bb.log("CollectorAgent", "GOOGLE_AI_WARNING", bundle.google_ai_error)
                    rotate_next_key = True
                    break

            if succeeded or (not rotate_next_key and not pool_key):
                break

    # ------------------------------------------------------------------
    # Stage 3C: SpiderFoot Event-Driven Plugin Bus (Maigret/Sherlock + PhoneInfoga + Passive DNS + Correlator)
    # ------------------------------------------------------------------
    seed_events: list[OSINTEvent] = []
    for ph in ctx.phone_candidates[:2]:
        seed_events.append(OSINTEvent(event_type="PHONE_FOUND", value=ph, source_plugin="layer1_intake"))
    if live_search and client is None:
        for al in parsed.get("aliases", [])[:2]:
            seed_events.append(OSINTEvent(event_type="HANDLE_FOUND", value=al, source_plugin="layer1_intake"))
        for em in anchors.get("emails", [])[:2]:
            seed_events.append(OSINTEvent(event_type="EMAIL_FOUND", value=em["email"], source_plugin="anchor_decoder"))

    if seed_events:
        bus = PluginRegistry().create_event_bus()
        bus_res = await bus.run(
            seed_events=seed_events,
            context={
                "target_name": target_name,
                "target_hints": [target_name] + parsed.get("organizations", []) + parsed.get("locations", []),
                "timeout": 4.5,
            },
            max_hops=2,
        )
        bundle.bus_dorks = bus_res.get("dorks", [])
        bundle.bus_notes = bus_res.get("notes", [])
        bundle.bus_trace = bus_res.get("trace", [])
        bundle.bus_correlations = bus_res.get("correlations", [])
        for corr in bundle.bus_correlations:
            bb.log("Correlator", corr["rule_id"], f"[{corr['severity']}] {corr['title']}: {corr['detail'][:160]}")
        for step in bundle.bus_trace:
            bb.log(
                "PluginBus",
                f"HOP{step['hop']}_{step['plugin'].upper()}",
                f"{step['trigger']} -> {step['sources_found']} nguồn, emitted={step['emitted']}",
            )
        for bsrc in bus_res.get("sources", [])[:8]:
            gatekeeper.evaluate_candidate(
                bsrc.get("title", ""),
                bsrc.get("url", ""),
                bsrc.get("snippet", ""),
                force_keep=True,
                consensus_score=3 if int(bsrc.get("confidence_score", 0)) >= 70 else 2,
            )

    if live_search:
        # ------------------------------------------------------------------
        # Stage 3D: Global Structured Public Registries (OpenAlex/ORCID + GitHub Name Search + RDAP/crt.sh)
        # ------------------------------------------------------------------
        if client is None:
            custom_domains: list[str] = []
            for em in anchors.get("emails", []):
                dom = str(em.get("domain") or "").lower()
                if is_custom_org_domain(dom) and ".edu." not in dom and dom not in custom_domains:
                    custom_domains.append(dom)
            for u in parsed.get("urls", []):
                host = urlparse(u).netloc.lower().lstrip("www.")
                if is_custom_org_domain(host) and host not in custom_domains:
                    custom_domains.append(host)

            struct_tasks: list[Any] = [
                search_openalex_authors(target_name, parsed.get("organizations"), timeout=6.0),
            ]
            run_gh_name = not parsed["aliases"] and len(target_name.split()) >= 2
            if run_gh_name:
                struct_tasks.append(search_github_by_name(target_name, parsed.get("organizations"), timeout=6.0))
            if custom_domains:
                struct_tasks.append(inspect_domain_infrastructure(custom_domains[0], timeout=6.0))

            struct_results = await asyncio.gather(*struct_tasks, return_exceptions=True)

            oa_list = struct_results[0] if isinstance(struct_results[0], list) else []
            if oa_list:
                bb.log(
                    "CollectorAgent",
                    "GLOBAL_OPENALEX_ORCID",
                    f"Tìm thấy {len(oa_list)} hồ sơ học thuật toàn cầu (OpenAlex/ORCID) khớp '{target_name}'",
                )
                for oa in oa_list:
                    gatekeeper.evaluate_candidate(
                        oa["title"],
                        oa["url"],
                        oa["snippet"],
                        force_keep=True,
                        consensus_score=3 if oa.get("org_matched") else 1,
                    )

            idx_ptr = 1
            if run_gh_name:
                gh_list = struct_results[idx_ptr] if isinstance(struct_results[idx_ptr], list) else []
                idx_ptr += 1
                if gh_list:
                    bb.log(
                        "CollectorAgent",
                        "GLOBAL_GITHUB_SEARCH",
                        f"Phát hiện {len(gh_list)} hồ sơ GitHub công khai cho '{target_name}'",
                    )
                    for g_item in gh_list:
                        gatekeeper.evaluate_candidate(
                            g_item["title"],
                            g_item["url"],
                            g_item["snippet"],
                            force_keep=bool(g_item.get("org_matched")),
                            consensus_score=3 if g_item.get("org_matched") else 1,
                        )

            if custom_domains and idx_ptr < len(struct_results):
                dom_res = struct_results[idx_ptr]
                if isinstance(dom_res, dict) and dom_res.get("ok"):
                    bb.log(
                        "CollectorAgent",
                        "GLOBAL_RDAP_CRTSH",
                        f"Domain {dom_res['domain']}: {dom_res['summary'][:140]}",
                    )
                    gatekeeper.evaluate_candidate(
                        f"Infrastructure & CT Logs: {dom_res['domain']}",
                        dom_res["url"],
                        dom_res["summary"],
                        force_keep=True,
                        consensus_score=2,
                    )

        # ------------------------------------------------------------------
        # Stage 3E: Concurrent Cross-Clue Search -> Mirror Pivots -> Adaptive Pivot -> Deep Document Reader
        # ------------------------------------------------------------------
        ws_conn = WebSearchConnector(store.db_path)
        search_sem = asyncio.Semaphore(2)

        async def _bounded_collect(q_str: str, max_res: int) -> Any:
            async with search_sem:
                return await ws_conn.collect(q_str, client=client, max_results=max_res, region=region)

        # Round 1 (Entropy-First): Execute highest-entropy anchors (exact Student ID / Scribd ID) FIRST
        # while search engines are 100% fresh & unthrottled, alongside top intersection queries!
        priority_id_queries = [
            mq
            for mq in bundle.mirror_queries
            if mq["strategy"]
            in (
                "mirror:student_id_name",
                "mirror:student_id_exact",
                "mirror:scribd_student_id",
                "mirror:org_domain_portal",
            )
        ][:3]
        seen_q_strings: set[str] = set()
        r1_queries: list[dict[str, str]] = []
        for q_obj in priority_id_queries + bundle.intersection_queries:
            if q_obj["query"] not in seen_q_strings:
                seen_q_strings.add(q_obj["query"])
                r1_queries.append(q_obj)
            if len(r1_queries) >= 5:
                break

        target_sid_tokens = [s["student_id"].lower() for s in anchors.get("student_ids", [])]
        target_cohort_tokens = [
            c.lower()
            for s in anchors.get("student_ids", [])
            for c in (
                s.get("cohort", ""),
                f"khoa {s.get('cohort', '')[1:]}" if s.get("cohort", "").lower().startswith("k") else "",
                f"khoa-{s.get('cohort', '')[1:]}" if s.get("cohort", "").lower().startswith("k") else "",
                s.get("institution", ""),
            )
            if c
        ]

        r1_docs = await asyncio.gather(
            *(_bounded_collect(q_obj["query"], 14) for q_obj in r1_queries),
            return_exceptions=True,
        )
        for q_obj, ws_doc in zip(r1_queries, r1_docs):
            if isinstance(ws_doc, Exception):
                continue
            eng_tag = "+".join(ws_doc.metadata.get("engines_used") or ["ddgs"])
            bb.log("CollectorAgent", "REACT_ROUND1_INTERSECT", f"[{q_obj['strategy']}|{eng_tag}|{region}] {q_obj['query']}")
            is_r1_exact_id = q_obj["strategy"] in (
                "mirror:student_id_name",
                "mirror:student_id_exact",
                "mirror:scribd_student_id",
                "mirror:org_domain_portal",
            )
            for r in ws_doc.metadata.get("results", []):
                r_url = str(r.get("url", ""))
                r_url_low = r_url.lower()
                r_low = f"{r.get('title', '')} {r.get('snippet', '')} {r_url}".lower()
                r_norm = normalize_text(f"{r.get('title', '')} {r.get('snippet', '')} {r_url}")
                is_doc_like = any(
                    seg in r_url_low for seg in ("/document/", ".pdf", ".xlsx", "/uploads/", "/storage/", "/download")
                )
                matches_id_or_cohort = (
                    any(sid in r_low for sid in target_sid_tokens)
                    or any(tok in r_norm or tok in r_url_low for tok in target_cohort_tokens if len(tok) >= 3)
                )
                boost_hit = is_r1_exact_id and is_doc_like and matches_id_or_cohort
                gatekeeper.evaluate_candidate(
                    r.get("title", ""),
                    r_url,
                    r.get("snippet", ""),
                    force_keep=boost_hit and bool(r_url),
                    consensus_score=int(r.get("consensus_score", 0)),
                    mirror_boost_label="Khớp chỉ mục MSSV trong tài liệu" if boost_hit else "",
                )

        # Round 2 (Deep ReAct): Discover new immutable anchors + remaining Secondary Mirrors (deduped from Round 1)
        if deep_mode:
            r1_blob = " ".join(d["text"] for d in gatekeeper.relevant_docs)
            discovered_anchors = decode_high_entropy_anchors(r1_blob)
            for doc_no in discovered_anchors.get("doc_numbers", []):
                if doc_no not in anchors["doc_numbers"]:
                    anchors["doc_numbers"].append(doc_no)
                    bb.log("PlannerAgent", "REACT_ANCHOR_FOUND", f"Phát hiện số hiệu văn bản mới: {doc_no} -> Pivot sang kho lưu trữ")
            bundle.mirror_queries = build_mirror_pivot_queries(parsed, anchors, region=region)

            r2_queries = [mq for mq in bundle.mirror_queries if mq["query"] not in seen_q_strings][:5]
            r2_docs = await asyncio.gather(
                *(_bounded_collect(mq["query"], 12) for mq in r2_queries),
                return_exceptions=True,
            )

            for mq, m_doc in zip(r2_queries, r2_docs):
                if isinstance(m_doc, Exception):
                    continue
                eng_tag = "+".join(m_doc.metadata.get("engines_used") or ["ddgs"])
                bb.log("CollectorAgent", "REACT_ROUND2_MIRROR", f"[{mq['strategy']}|{eng_tag}|{region}] {mq['query']}")
                for r in m_doc.metadata.get("results", []):
                    r_url = str(r.get("url", ""))
                    r_url_low = r_url.lower()
                    r_low = f"{r.get('title', '')} {r.get('snippet', '')} {r_url}".lower()
                    if any(bad in r_low for bad in ("help.studocu.com", "haiti", "studocu.com/pl/", "studocu.com/de/")):
                        gatekeeper._record_reject("junk_url")
                        continue

                    is_doc_like_url = (
                        "/document/" in r_url_low
                        or ".pdf" in r_url_low
                        or ".xlsx" in r_url_low
                        or "/uploads/" in r_url_low
                        or "/storage/" in r_url_low
                        or "/download" in r_url_low
                    )
                    r_norm = normalize_text(f"{r.get('title', '')} {r.get('snippet', '')} {r_url}")
                    matches_id_or_cohort = (
                        any(sid in r_low for sid in target_sid_tokens)
                        or any(tok in r_norm or tok in r_url_low for tok in target_cohort_tokens if len(tok) >= 3)
                    )
                    is_exact_id_mirror = (
                        mq["strategy"]
                        in (
                            "mirror:student_id_exact",
                            "mirror:scribd_student_id",
                            "mirror:studocu_student_id",
                            "mirror:edu_vn_student_id",
                            "mirror:org_domain_portal",
                        )
                        and is_doc_like_url
                        and matches_id_or_cohort
                    )
                    is_mirror_hit = is_exact_id_mirror or (
                        mq["strategy"]
                        in (
                            "mirror:studocu_cohort_list",
                            "mirror:scribd_cohort_list",
                            "mirror:scribd_cohort_prefix",
                            "mirror:studocu_cohort_prefix",
                            "mirror:doc_number_pivot",
                        )
                        and is_doc_like_url
                        and matches_id_or_cohort
                    )
                    gatekeeper.evaluate_candidate(
                        r.get("title", ""),
                        r_url,
                        r.get("snippet", ""),
                        force_keep=is_mirror_hit and bool(r_url),
                        consensus_score=int(r.get("consensus_score", 0)),
                        mirror_boost_label="Khớp chỉ mục MSSV trong tài liệu" if is_exact_id_mirror else "",
                    )

            # Adaptive Pivot Chaining: auto-enrich discovered GitHub handles
            if client is None:
                known_aliases_low = {a.lower() for a in parsed.get("aliases", [])}
                for src in list(gatekeeper.ranked_sources):
                    m_gh = re.match(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_-]{2,39})/?$", src["url"])
                    if m_gh:
                        new_handle = m_gh.group(1)
                        if new_handle.lower() not in known_aliases_low and new_handle.lower() not in (
                            "topics", "explore", "orgs", "features", "marketplace", "login", "signup"
                        ):
                            known_aliases_low.add(new_handle.lower())
                            try:
                                gh_conn = GitHubPublicConnector(store.db_path)
                                gh_doc = await gh_conn.collect(new_handle)
                                if not gh_doc.is_soft_404:
                                    extra_summary = f"{gh_doc.title}. {gh_doc.content}. " + " ".join(
                                        c.evidence_quote for c in gh_doc.claims
                                    )
                                    gatekeeper.relevant_docs.append({"text": extra_summary[:2000], "source_url": gh_doc.url})
                                    src["snippet"] = extra_summary[:280]
                                    src["match_score"] = int(src.get("match_score", 0)) + 2
                                    bb.log(
                                        "PlannerAgent",
                                        "ADAPTIVE_PIVOT_CHAIN",
                                        f"Tự động mở rộng từ GitHub @{new_handle} -> trích xuất hồ sơ, repos & múi giờ hoạt động",
                                    )
                            except Exception:
                                pass
                            break

            # Deep-fetch top 2 highest-scoring discovered PDFs/XLSX or institutional documents
            fetcher = PublicWebFetcher(store.db_path)
            fetched_deep = 0
            pdf_terms = [target_name] + [s["student_id"] for s in anchors.get("student_ids", [])]
            if parsed.get("birth_date"):
                pdf_terms.append(parsed["birth_date"])
            for src in sorted(gatekeeper.ranked_sources, key=lambda s: s.get("match_score", 0), reverse=True):
                if fetched_deep >= 2:
                    break
                if src.get("match_score", 0) < 1:
                    continue
                s_url = src["url"]
                if is_inspectable_document_url(s_url):
                    try:
                        doc_res = await fetch_and_inspect_document(
                            s_url, target_terms=pdf_terms, timeout=8.0, client=client
                        )
                        if doc_res.get("ok"):
                            fetched_deep += 1
                            excerpts = doc_res.get("excerpts") or []
                            src["deep_inspected"] = True
                            src["doc_type"] = doc_res.get("doc_type", "pdf")
                            src["scanned_pdf"] = bool(doc_res.get("scanned_pages_detected"))
                            src["pdf_excerpts"] = excerpts
                            if excerpts:
                                merged_ex = " | ".join(ex["line"] for ex in excerpts[:3])
                                src["snippet"] = (
                                    merged_ex[:280] if len(merged_ex) > len(src.get("snippet", "")) else src["snippet"]
                                )
                                src["match_score"] = int(src.get("match_score", 0)) + 3
                                if "PDF Đọc sâu" not in src.get("matched_clues", []):
                                    src.setdefault("matched_clues", []).append("PDF Đọc sâu")
                                gatekeeper.relevant_docs.append({"text": merged_ex[:2500], "source_url": s_url})
                                bb.log("ReaderAgent", "DEEP_PDF_EXTRACT", f"Đọc sâu {s_url} -> trích được {len(excerpts)} dòng khớp mục tiêu")
                                deep_anchors = decode_high_entropy_anchors(merged_ex[:4000])
                                for dno in deep_anchors.get("doc_numbers", []):
                                    if dno not in anchors["doc_numbers"]:
                                        anchors["doc_numbers"].append(dno)
                            elif doc_res.get("scanned_pages_detected"):
                                bb.log("ReaderAgent", "DEEP_PDF_SCANNED", f"PDF {s_url} là bản scan ảnh (không có lớp text) -> dùng snippet chỉ mục.")
                    except Exception:
                        continue
                elif any(k in s_url.lower() for k in ("/document/", ".edu.vn", "github.com")):
                    try:
                        p_doc = await fetcher.collect(s_url, client=client)
                        if not p_doc.is_soft_404 and p_doc.content:
                            fetched_deep += 1
                            src["deep_inspected"] = True
                            gatekeeper.relevant_docs.append({"text": p_doc.content[:2500], "source_url": s_url})
                            deep_anchors = decode_high_entropy_anchors(p_doc.content[:4000])
                            for dno in deep_anchors.get("doc_numbers", []):
                                if dno not in anchors["doc_numbers"]:
                                    anchors["doc_numbers"].append(dno)
                                    bb.log("ReaderAgent", "DEEP_FETCH_ANCHOR", f"Đọc trang {s_url} -> phát hiện văn bản {dno}")
                    except Exception:
                        continue

    # Finalize Layer 2 Gatekeeper ranking & pruning before handing off to Layer 4 Deep Core!
    ranked_sources, relevant_docs = gatekeeper.finalize_and_prune()
    if gatekeeper.telemetry.rejected_count > 0:
        reason_summary = ", ".join(f"{k}={v}" for k, v in sorted(gatekeeper.telemetry.rejected_by_reason.items()))
        bb.log(
            "OuterGatekeeper",
            "LAYER2_NOISE_SHIELD",
            f"Đã lọc bỏ {gatekeeper.telemetry.rejected_count} ứng viên nhiễu trước khi vào Lõi ({reason_summary}).",
        )

    bundle.ranked_sources = ranked_sources
    bundle.relevant_docs = relevant_docs
    bundle.gatekeeper_stats = gatekeeper.telemetry
    return bundle
