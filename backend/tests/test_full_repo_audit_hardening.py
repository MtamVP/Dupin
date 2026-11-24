"""Full-Repo Hardening & Edge-Case Chaos Tests (DOB crashes, SSE errors, dynamic PDFs, SQLite WAL, catalog)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.connectors.document_reader import is_inspectable_document_url
from app.core.graph_store import GraphStore
from app.core.schemas import WorkspaceCreate
from app.pipeline import (
    build_timeline_events,
    execute_concentric_pipeline,
    parse_user_prompt,
    score_source_relevance,
)


def test_malformed_and_non_slash_dob_never_crashes_pipeline(tmp_path: Path) -> None:
    """Invalid DOB (99/99/2007) or hyphenated Dossier DOB (2007-05-15) must never throw ValueError."""
    p_bad = parse_user_prompt("Tran Minh Anh, 99/99/2007, UEH")
    assert p_bad["birth_date"] == ""

    p_iso = parse_user_prompt("Tran Minh Anh, 2007-05-15, UEH")
    assert p_iso["birth_date"] == "15/05/2007"
    assert p_iso["birth_year"] == 2007

    # Simulate legacy/corrupted birth_date string directly in Layer 2 & Layer 4
    corrupted = dict(p_iso, birth_date="thang 5 nam 2007")
    ok, score, _ = score_source_relevance("Tran Minh Anh UEH 2025", "https://ueh.edu.vn/list", corrupted)
    assert ok is True and score >= 2
    ev = build_timeline_events(corrupted, [], {"student_ids": []})
    assert isinstance(ev, list)

    # Dossier item with ISO DOB must normalize cleanly without crashing
    store = GraphStore(tmp_path / "dob_chaos.db")
    ws = store.create_workspace(WorkspaceCreate(name="DOB Chaos"))
    store.add_dossier_item(ws.id, field_key="Ngày sinh", field_value="2007-05-15")
    store.add_dossier_item(ws.id, field_key="Ngày sinh phụ", field_value="không rõ")

    import asyncio

    res = asyncio.run(
        execute_concentric_pipeline(
            store=store,
            workspace_id=ws.id,
            prompt="Tran Minh Anh, UEH",
            live_search=False,
            deep_mode=False,
        )
    )
    assert res["parsed_clues"]["birth_date"] == "15/05/2007"


def test_dynamic_click_to_download_pdf_url_detection() -> None:
    """Dynamic click-to-download endpoints (Vietstock, CafeF, HOSE, .edu.vn) must be recognized."""
    assert is_inspectable_document_url("https://hcmussh.edu.vn/api/storage/download?id=123") is True
    assert is_inspectable_document_url("https://static2.vietstock.vn/data/HOSE/2025/BCQT/file") is True
    assert is_inspectable_document_url("https://cafef1.mediacdn.vn/download/123456") is True
    assert is_inspectable_document_url("https://www.hsx.vn/Modules/Listed/Web/DownloadFile?id=99") is True
    assert is_inspectable_document_url("https://example.com/about-us") is False


def test_blank_prompt_rejected_and_sse_error_handled_cleanly(tmp_path: Path, monkeypatch) -> None:
    """Blank-only prompt returns 422, and internal SSE error emits clean `event: error` instead of hanging."""
    test_store = GraphStore(tmp_path / "sse_hardening.db")
    ws = test_store.create_workspace(WorkspaceCreate(name="SSE Chaos"))
    monkeypatch.setattr(main, "store", test_store)

    with TestClient(main.app) as client:
        r_blank = client.post(f"/api/workspaces/{ws.id}/chat", json={"prompt": "   ", "live_search": False})
        assert r_blank.status_code == 422

        r_blank_stream = client.post(f"/api/workspaces/{ws.id}/chat/stream", json={"prompt": "\t\n ", "live_search": False})
        assert r_blank_stream.status_code == 422

        async def boom(**kwargs):
            raise RuntimeError("Simulated pipeline failure")

        monkeypatch.setattr(main, "handle_chat_turn", boom)
        r_err = client.post(f"/api/workspaces/{ws.id}/chat/stream", json={"prompt": "Test User", "live_search": False})
        assert r_err.status_code == 200
        assert "event: error" in r_err.text
        assert "Simulated pipeline failure" in r_err.text


def test_catalog_and_extension_hygiene() -> None:
    """Verify catalog.json v2.0 lists all 11 MCP tools & extension/popup.js uses safe DOM APIs (no innerHTML)."""
    repo_root = Path(__file__).resolve().parents[2]
    cat = json.loads((repo_root / "catalog.json").read_text(encoding="utf-8"))
    assert cat["architecture"] == "5-layer-concentric-osint"
    assert len(cat["mcp_tools"]) == 11
    assert len(cat["pipeline_layers"]) == 5

    popup_js = (repo_root / "extension" / "popup.js").read_text(encoding="utf-8")
    assert "innerHTML" not in popup_js


def test_lowercase_vn_org_province_and_prose_paste_parsing() -> None:
    """Ensure lowercase Vietnamese org acronyms, provinces, and pasted AI paragraphs parse cleanly."""
    p1 = parse_user_prompt("Trần Kiều Oanh, Phú Yên, 1991, ussh")
    assert p1["target_name"] == "Trần Kiều Oanh"
    assert "ussh" in [o.lower() for o in p1["organizations"]]
    assert any("phú yên" in loc.lower() for loc in p1["locations"])
    assert p1["birth_year"] == 1991

    prose = (
        "Dựa trên thông tin công khai (Họ tên Trần Kiều Oanh, giới tính Nữ, "
        "ngày sinh 20/02/1990, nơi sinh/quê quán tỉnh Phú Yên) xuất hiện tại các nguồn sau:\n"
        "• Hồ sơ học thuật tại Trường ĐH KHXH&NV (mã số: 241922909999)."
    )
    p2 = parse_user_prompt(prose)
    assert p2["target_name"] == "Trần Kiều Oanh"
    assert p2["target_name"].lower() != "giới tính nữ"
    assert p2["birth_date"] == "20/02/1990"
    assert p2["birth_year"] == 1990
    assert all(len(loc) <= 35 and ")" not in loc and ":" not in loc for loc in p2["locations"])
    assert any("phú yên" in loc.lower() for loc in p2["locations"])


def test_serper_free_query_sanitizer_and_400_retry(tmp_path: Path, monkeypatch) -> None:
    """Verify Serper Free HTTP 400 ('Query pattern not allowed') auto-retries with clean query without error penalty."""
    import asyncio
    import httpx
    from app.connectors.web_search import WebSearchConnector, _sanitize_query_for_serper_free
    from app.core.key_pool import APIKeyCreate, IntegrationStore

    clean = _sanitize_query_for_serper_free('site:edu.vn "Trần Kiều Oanh" "20/02/1990" filetype:pdf')
    assert clean.count('"') == 2  # Preserves first exact quoted phrase for precision
    assert '"Trần Kiều Oanh"' in clean
    assert "site:" not in clean
    assert "filetype:" not in clean
    assert "edu.vn" in clean and "pdf" in clean and "20/02/1990" in clean

    db = tmp_path / "serper_retry.db"
    GraphStore(db)
    istore = IntegrationStore(db)
    added = istore.add_key(APIKeyCreate(name="SerperFree", provider="serper", api_key="serper-test-key-1234"))

    ws = WebSearchConnector(db)
    seen_queries: list[str] = []

    async def fake_search_serper(query: str, api_key: str, max_results: int = 8, region: str = "global"):
        seen_queries.append(query)
        if query.count('"') > 2 or "site:" in query:
            req = httpx.Request("POST", "https://google.serper.dev/search")
            resp = httpx.Response(400, request=req, json={"message": "Query pattern not allowed for free accounts."})
            raise httpx.HTTPStatusError("400 Bad Request", request=req, response=resp)
        return [
            {
                "url": "https://example.edu.vn/doc/123.pdf",
                "title": "Sample Official PDF",
                "snippet": "Trần Kiều Oanh 20/02/1990",
                "sources": ["serper"],
                "consensus_score": 2,
            }
        ]

    monkeypatch.setattr(ws, "_search_serper", fake_search_serper)
    doc = asyncio.run(ws.collect('site:edu.vn "Trần Kiều Oanh" "20/02/1990"', max_results=8, region="vn"))
    assert len(seen_queries) == 1
    assert "serper" in doc.metadata["engines_used"]
    assert len(doc.metadata["results"]) == 1
    # Key error_count must remain 0 because proactive sanitization succeeded in 1 request
    masked = istore.get_masked_key(added["id"])
    assert masked is not None and masked["error_count"] == 0


def test_7digit_hcmut_and_alphanumeric_student_id_anchor_decoding() -> None:
    """Ensure 7-digit MSSV (HCMUT K25) & labeled alphanumeric MSSV are decoded and URL digits are ignored."""
    from app.connectors.mirror_pivots import build_mirror_pivot_queries
    from app.core.anchor_decoder import decode_high_entropy_anchors

    anc = decode_high_entropy_anchors("Nguyễn Văn Mẫu, 2550999, HCMUT, https://example.com/posts/987654321")
    sids = {s["student_id"]: s for s in anc["student_ids"]}
    assert "2550999" in sids
    assert sids["2550999"]["institution"] == "HCMUT"
    assert sids["2550999"]["cohort"] == "K25"
    assert sids["2550999"]["intake_year"] == 2025
    assert "987654321" not in sids  # URL path numbers must never be treated as MSSV

    anc2 = decode_high_entropy_anchors("Trần Minh Mẫu, MSSV: SE180999, FPT")
    assert any(s["student_id"] == "SE180999" for s in anc2["student_ids"])

    parsed = parse_user_prompt("Nguyễn Văn Mẫu, 2550999, HCMUT")
    pivots = build_mirror_pivot_queries(parsed, anc, region="vn")
    assert any(p["strategy"] == "mirror:student_id_exact" and "2550999" in p["query"] for p in pivots)
    assert any(p["strategy"] == "mirror:edu_vn_student_id" and "2550999" in p["query"] for p in pivots)


def test_natural_key_value_form_bio_without_commas() -> None:
    """Ensure pasted Key:Value profile forms (multi-line or single-line, no commas) parse cleanly."""
    kv_multiline = (
        "Họ và tên:Trần Ngọc Mai\n"
        "Năm sinh:1978\n"
        "Dân tộc:Kinh\n"
        "Nghề nghiệp:Kế toán\n"
        "Điện thoại:0901234567\n"
        "Đơn vị công tác của Mẹ:Công ty TNHH Ánh Dương (số 10, đường Lê Lợi, Sài Gòn, TP.HCM)\n"
        "Cựu sinh viên UEH:Trúng tuyển 1996, Khóa 1996-2000, Hệ Chính quy"
    )
    p = parse_user_prompt(kv_multiline)
    assert p["target_name"] == "Trần Ngọc Mai"
    assert "\n" not in p["target_name"]
    assert p["birth_year"] == 1978
    assert any("Công ty TNHH Ánh Dương" in o for o in p["organizations"])
    assert any("UEH" in o for o in p["organizations"])
    assert any("Kế toán" in k for k in p["keywords"])

    # Also verify single-line space-separated Key:Value form
    kv_singleline = kv_multiline.replace("\n", " ")
    p2 = parse_user_prompt(kv_singleline)
    assert p2["target_name"] == "Trần Ngọc Mai"
    assert p2["birth_year"] == 1978
    assert any("Công ty TNHH Ánh Dương" in o for o in p2["organizations"])
    assert any("UEH" in o for o in p2["organizations"])


def test_extended_high_entropy_anchors_cccd_mst_sbd_orcid_plate_wallet() -> None:
    """Verify decoding & pivoting for CCCD (63-province schema), MST, SBD, ORCID, License Plate, Social UID, Wallet."""
    from app.connectors.mirror_pivots import build_mirror_pivot_queries
    from app.core.anchor_decoder import decode_high_entropy_anchors
    from app.pipeline.layer2_gatekeeper import _evaluate_relevance_detailed

    sample = (
        "Họ và tên:Nguyễn Minh Mẫu "
        "CCCD:079207000123 "
        "MST:0312345678 "
        "SBD:02099999 "
        "ORCID:0000-0002-1825-0097 "
        "Biển số:51G-999.99 "
        "t.me/minhmau_dev "
        "0x1111111111111111111111111111111111111111"
    )
    anc = decode_high_entropy_anchors(sample)

    # 1. CCCD decoded mathematically (079=TP.HCM, 2=Nam 20xx, 07=2007) and NOT duplicated into student_ids
    assert len(anc["cccds"]) == 1
    assert anc["cccds"][0]["birth_province"] == "TP.HCM"
    assert anc["cccds"][0]["gender"] == "Nam"
    assert anc["cccds"][0]["birth_year"] == 2007
    assert not any(s["student_id"] == "079207000123" for s in anc["student_ids"])

    # 2. MST, SBD, ORCID, License Plate, Telegram handle, EVM Wallet
    assert anc["tax_ids"] == ["0312345678"]
    assert anc["exam_ids"] == ["02099999"]
    assert anc["orcid_ids"] == ["0000-0002-1825-0097"]
    assert anc["license_plates"][0]["plate"] == "51G-999.99"
    assert anc["license_plates"][0]["province"] == "TP.HCM"
    assert any(s["platform"] == "telegram" and s["id"] == "minhmau_dev" for s in anc["social_ids"])
    assert anc["crypto_wallets"] == ["0x1111111111111111111111111111111111111111"]

    # 3. Pivot queries & L2 Gatekeeper acceptance
    parsed = parse_user_prompt(sample)
    parsed["anchors"] = anc
    pivots = build_mirror_pivot_queries(parsed, anc, region="vn")
    strategies = {p["strategy"] for p in pivots}
    assert {"mirror:tax_id_exact", "mirror:masothue_pivot", "mirror:exam_id_exact", "mirror:orcid_exact", "mirror:public_id_exact", "mirror:license_plate_exact", "mirror:crypto_wallet_exact"}.issubset(strategies)

    dec = _evaluate_relevance_detailed(
        "Công ty TNHH Mẫu - MST 0312345678",
        "https://masothue.com/0312345678-cong-ty-mau",
        parsed,
    )
    assert dec.accepted is True


def test_org_with_city_name_dai_hoc_intact_and_master_lecturer_seniority_veto() -> None:
    """Verify stress-test bugfixes: University of Toronto -> org, Dai hoc Kinh te intact, Master/Lecturer vetoed for 2007."""
    from app.pipeline.layer2_gatekeeper import _evaluate_relevance_detailed

    p1 = parse_user_prompt("Alex Sample, University of Toronto, ORCID: 0000-0001-6873-6425")
    assert "University of Toronto" in p1["organizations"]
    assert "University of Toronto" not in p1["locations"]

    p2 = parse_user_prompt("Trần Văn Mẫu, Đại học Kinh tế, VEPR")
    assert "Đại học Kinh tế" in p2["organizations"]
    assert "VEPR" in p2["organizations"]

    p3 = parse_user_prompt("Nguyễn Minh Mẫu, 2007, HCMUT")
    d_master = _evaluate_relevance_detailed(
        "Nguyễn Minh Mẫu | Master of Engineering | HCMUT",
        "https://researchgate.net/profile/Nguyen-Minh-Mau",
        p3,
    )
    assert d_master.accepted is False and d_master.reject_reason == "temporal_seniority_veto"

    d_teacher = _evaluate_relevance_detailed(
        "HCMUT - Các bạn cho mình hỏi thầy Nguyễn Minh Mẫu dạy môn này",
        "https://facebook.com/groups/hcmut/posts/123",
        p3,
    )
    assert d_teacher.accepted is False and d_teacher.reject_reason == "temporal_seniority_veto"


def test_name_and_phone_intersection_priority_and_gatekeeper_boost() -> None:
    """Verify Name + Phone generates Round-1 phone intersection queries and boosts phone hits above name-only homonyms."""
    from app.pipeline.layer2_gatekeeper import _evaluate_relevance_detailed
    from app.pipeline.layer3_collectors import build_intersection_queries

    parsed = parse_user_prompt("Trần Minh Mẫu, 0901234567")
    parsed["phone_candidates"] = ["0901234567"]
    qs = build_intersection_queries(parsed, phone_candidates=["0901234567"])
    assert qs[0]["strategy"] == "intersect_name_phone"
    assert '"Trần Minh Mẫu" 0901234567' in qs[0]["query"]
    assert qs[1]["strategy"] == "exact_phone_digits"
    assert '"0901234567"' in qs[1]["query"]

    d_phone = _evaluate_relevance_detailed(
        "3285 TRẦN MINH MẪU 0901.234.567 TP Hồ Chí Minh",
        "https://scribd.com/document/123/sample",
        parsed,
    )
    d_homonym = _evaluate_relevance_detailed(
        "GS.TS Trần Minh Mẫu làm Hiệu trưởng Đại học XYZ",
        "https://news.example.vn/gs-ts-tran-minh-mau",
        parsed,
    )
    assert d_phone.accepted is True and d_homonym.accepted is True
    assert d_phone.score > d_homonym.score + 3
    assert "Khớp SĐT" in d_phone.matched_clues


def test_reverse_temporal_veto_prefix_surname_and_kv_keywords_cleanup() -> None:
    """Verify reverse-direction temporal veto (older cohort <=1990), prefix-surname penalty, and clean KV keywords."""
    from app.pipeline.layer2_gatekeeper import _evaluate_relevance_detailed

    kv_prompt = (
        "Họ và tên:Trần Minh Mẫu Năm sinh:1975 Nghề nghiệp:Kế toán "
        "Điện thoại:0901234567 Đơn vị công tác:Công ty TNHH Alpha (TP.HCM) "
        "Cựu sinh viên UEH:Khóa 1993-1997, Kế toán kiểm toán"
    )
    parsed = parse_user_prompt(kv_prompt)
    parsed["phone_candidates"] = ["0901234567"]
    assert parsed["target_name"] == "Trần Minh Mẫu"
    assert parsed["birth_year"] == 1975
    assert all(":" not in kw for kw in parsed["keywords"])

    # 1. Child worksheet & 2024 freshman MSSV are vetoed for 1975 cohort
    d_child = _evaluate_relevance_detailed(
        "Starter 4-Tran Minh Mau Báo cáo tình hình học tập tháng 8 của học sinh Trần Minh Mẫu",
        "https://www.scribd.com/document/999/Starter-4-Tran-Minh-Mau",
        parsed,
    )
    assert d_child.accepted is False and d_child.reject_reason == "temporal_younger_cohort_veto"

    d_freshman = _evaluate_relevance_detailed(
        "Tên: Trần Minh Mẫu MSSV: 31241023984 CTKT 4.2 bài tập nguyên lý kế toán",
        "https://www.scribd.com/document/888/Tran-Minh-Mau-BT",
        parsed,
    )
    assert d_freshman.accepted is False and d_freshman.reject_reason == "temporal_younger_cohort_veto"

    # 2. Adult teacher/parent role or exact phone match is NEVER falsely vetoed
    d_phone_safe = _evaluate_relevance_detailed(
        "Starter 4 danh sách phụ huynh 0901234567 Trần Minh Mẫu",
        "https://example.vn/list",
        parsed,
    )
    assert d_phone_safe.accepted is True and "Khớp SĐT" in d_phone_safe.matched_clues

    # 3. Prefix-surname mismatch ("Nguyễn Trần Minh Mẫu" vs "Trần Minh Mẫu") is penalized below exact match
    d_prefixed = _evaluate_relevance_detailed(
        "Nguyễn Trần Minh Mẫu - International Business Graduate @UEH",
        "https://vn.linkedin.com/in/nguyen-tran-minh-mau",
        parsed,
    )
    d_exact = _evaluate_relevance_detailed(
        "Trần Minh Mẫu - Cựu sinh viên UEH",
        "https://example.vn/tran-minh-mau-ueh",
        parsed,
    )
    assert "Nghi khác họ đệm" in d_prefixed.matched_clues
    assert d_prefixed.score < d_exact.score


def test_clean_org_verbs_markdown_and_suffix_diacritic_history_filters() -> None:
    """Verify org cleaner strips 'đang học'/'Từng học cấp 2'/Markdown headers and L2 filters suffix/diacritic/history homonyms."""
    from app.pipeline.layer2_gatekeeper import _evaluate_relevance_detailed

    p = parse_user_prompt(
        "Nguyễn Minh Như, đang học UEH ngành kinh doanh quốc tế, 2007, "
        "Từng học cấp 2 THPT Chuyên Trần Đại Nghĩa, chuyên văn"
    )
    assert p["target_name"] == "Nguyễn Minh Như"
    assert "UEH" in p["organizations"]
    assert "THPT Chuyên Trần Đại Nghĩa" in p["organizations"]
    assert all(not o.lower().startswith(("đang học", "từng học", "#")) for o in p["organizations"])
    assert any("kinh doanh quốc tế" in kw.lower() for kw in p["keywords"])

    # Vision markdown output must never inject "### 4. [Tóm tắt Trường Chuẩn Hóa]" into organizations
    v_parsed = parse_user_prompt(
        "### 4. [Tóm tắt Trường Chuẩn Hóa]\n"
        "Họ và tên: Nguyễn Minh Như\n"
        "Năm sinh: 2007\n"
        "Đơn vị công tác: Đại học Kinh tế TP. Hồ Chí Minh (UEH) - Ngành Kinh doanh Quốc tế (Cựu học sinh THPT chuyên Trần Đại Nghĩa, chuyên Văn)\n"
        "Địa điểm: Thành phố Hồ Chí Minh"
    )
    assert all("#" not in o and "Tóm tắt" not in o and "Ngành" not in o for o in v_parsed["organizations"])
    assert "Đại học Kinh tế TP. Hồ Chí Minh" in v_parsed["organizations"]
    assert "UEH" in v_parsed["organizations"]

    # L2 suffix given name ("Nguyễn Minh Như Huỳnh", "Nguyễn Văn A Heo") must be hard-rejected
    # while valid metadata followers ("Nam", "Nữ", "12A10") remain accepted.
    d_suffix = _evaluate_relevance_detailed(
        "Nguyễn Minh Như Huỳnh (@huynh1505) · GitHub BA Intern",
        "https://github.com/huynh1505",
        p,
    )
    assert d_suffix.accepted is False and d_suffix.reject_reason == "suffix_name_mismatch"

    d_nickname = _evaluate_relevance_detailed(
        "Nguyễn Văn A Heo - bài viết công khai",
        "https://facebook.com/nguyenvanaheo",
        parse_user_prompt("Nguyễn Văn A"),
    )
    assert d_nickname.accepted is False and d_nickname.reject_reason == "suffix_name_mismatch"

    d_valid_gender = _evaluate_relevance_detailed(
        "643 Huỳnh Nguyễn Thuận Nam 12A10 THPT Nguyễn Thượng Hiền",
        "https://thptnguyenthuonghien.hcm.edu.vn/danh-sach-12a10",
        parse_user_prompt("Huỳnh Nguyễn Thuận, 04/10/2007, THPT Nguyễn Thượng Hiền"),
    )
    assert d_valid_gender.accepted is True

    # Strong input-corroborating hits (score >= 4) must NOT be rotated out even if unpinned,
    # whereas weak unpinned hits ARE rotated out on subsequent turns.
    from app.pipeline.models import InvestigationContext
    from app.pipeline.layer2_gatekeeper import OuterGatekeeper

    strong_url = "https://thptnguyenthuonghien.hcm.edu.vn/danh-sach-12a10"
    weak_url = "https://example.com/random-mention"
    ctx_keep = InvestigationContext(
        workspace_id="ws-test",
        raw_prompt="Huỳnh Nguyễn Thuận, 04/10/2007, THPT Nguyễn Thượng Hiền",
        parsed=parse_user_prompt("Huỳnh Nguyễn Thuận, 04/10/2007, THPT Nguyễn Thượng Hiền"),
        anchors={},
        region="vn",
        target_name="Huỳnh Nguyễn Thuận",
        previously_shown_unverified_urls={strong_url, weak_url},
        confirmed_urls=set(),
    )
    gk = OuterGatekeeper(ctx_keep)
    assert gk.evaluate_candidate(
        title="Danh sách học sinh 12A10 THPT Nguyễn Thượng Hiền",
        url=strong_url,
        snippet="32 Huỳnh Nguyễn Thuận 04/10/2007 12A10 THPT Nguyễn Thượng Hiền",
    ) is True
    assert gk.evaluate_candidate(
        title="Bài viết ngẫu nhiên",
        url=weak_url,
        snippet="Huỳnh Nguyễn Thuận bình luận trên diễn đàn",
    ) is False
    assert gk.telemetry.rejected_by_reason.get("unverified_rotated_out") == 1

    # MOET 7-digit major code (7340404) must NOT be decoded as a personal student_id
    from app.core.anchor_decoder import decode_high_entropy_anchors
    anc_major = decode_high_entropy_anchors(
        "656 NGUYỄN VIỆT KHUÊ 23/03/2007 Nữ 31251021275 IELTS 7 08/08/2024 7340404 Quản trị nhân lực"
    )
    sid_list = [s["student_id"] for s in anc_major["student_ids"]]
    assert "31251021275" in sid_list
    assert "7340404" not in sid_list

    # Neighbor DOB conflict veto: 01/04/2005 right after target name when target is 23/03/2007
    d_dob_conflict = _evaluate_relevance_detailed(
        "174 NGUYỄN VIỆT KHUÊ 01/04/2005 Kinh THPT Chợ Gạo YDS",
        "https://www.scribd.com/document/869476458/Danh-sach-trung-tuyen-NV-1",
        parse_user_prompt("Nguyễn Việt Khuê, 23/03/2007, THCS Nguyễn Gia Thiều"),
    )
    assert d_dob_conflict.accepted is False and d_dob_conflict.reject_reason == "dob_mismatch_veto"

    d_history = _evaluate_relevance_detailed(
        "Sử liệu Pháp về cuộc kháng chiến Tây Sơn và Nguyễn Ánh như các tài liệu xưa",
        "https://example.vn/tay-son",
        parse_user_prompt("Nguyễn Anh Như, UEH, 2007"),
    )
    assert d_history.accepted is False and d_history.reject_reason == "no_target_match"


def test_verified_only_multiformat_exports_docx_pdf_xlsx_html_and_noise_exclusion(tmp_path: Path, monkeypatch) -> None:
    """Verify verified_only=true excludes unverified claims and exports valid DOCX, PDF, XLSX, HTML, CSV, JSON."""
    import io
    import zipfile
    from openpyxl import load_workbook
    from pypdf import PdfReader
    from app.core.graph_store import GraphStore
    from app.core.schemas import FeatureCategory, FeatureClaim, NodeCreate, WorkspaceCreate

    test_store = GraphStore(tmp_path / "export_verified.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    ws = test_store.create_workspace(WorkspaceCreate(name="Hồ sơ Đã Xác nhận"))
    # Add 1 VERIFIED claim (matching a pinned dossier URL) and 1 UNVERIFIED claim (random unpinned URL)
    test_store.upsert_node(
        ws.id,
        NodeCreate(
            type="Person",
            label="Trần Minh Mẫu",
            claims=[
                FeatureClaim(
                    category=FeatureCategory.TECHNICAL_ARTIFACT,
                    key="school_or_org",
                    value="UEH_CONFIRMED_ORG",
                    confidence=0.95,
                    source_url="https://confirmed.example.edu.vn/profile",
                    evidence_quote="Sinh viên UEH đã xác nhận",
                ),
                FeatureClaim(
                    category=FeatureCategory.TECHNICAL_ARTIFACT,
                    key="school_or_org",
                    value="UNVERIFIED_NOISE_ORG_999",
                    confidence=0.60,
                    source_url="https://unverified-random-blog.example.com/post",
                    evidence_quote="Nhiễu chưa kiểm chứng",
                ),
            ],
        ),
    )
    test_store.add_dossier_item(
        workspace_id=ws.id,
        field_key="Trường đại học đã xác nhận",
        field_value="Đại học Kinh tế TP.HCM (UEH)",
        source_url="https://confirmed.example.edu.vn/profile",
    )

    # 1. Obsidian with verified_only=true includes confirmed item & excludes UNVERIFIED_NOISE_ORG_999
    obs = client.get(f"/api/workspaces/{ws.id}/export/obsidian?verified_only=true").text
    assert "Đại học Kinh tế TP.HCM (UEH)" in obs
    assert "UEH_CONFIRMED_ORG" in obs
    assert "UNVERIFIED_NOISE_ORG_999" not in obs

    # 2. CSV with verified_only=true includes verified_dossier row & excludes unverified claim
    csv_txt = client.get(f"/api/workspaces/{ws.id}/export/csv?verified_only=true").text
    assert "verified_dossier" in csv_txt
    assert "Đại học Kinh tế TP.HCM (UEH)" in csv_txt
    assert "UNVERIFIED_NOISE_ORG_999" not in csv_txt

    # 3. DOCX export is a valid OpenXML ZIP containing word/document.xml with confirmed items only
    r_docx = client.get(f"/api/workspaces/{ws.id}/export/docx?verified_only=true")
    assert r_docx.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r_docx.content)) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        assert "Đại học Kinh tế TP.HCM (UEH)" in doc_xml
        assert "UNVERIFIED_NOISE_ORG_999" not in doc_xml

    # 4. PDF export is a valid %PDF-1.4 readable by pypdf.PdfReader
    r_pdf = client.get(f"/api/workspaces/{ws.id}/export/pdf?verified_only=true")
    assert r_pdf.status_code == 200 and r_pdf.content.startswith(b"%PDF-1.4")
    pdf_reader = PdfReader(io.BytesIO(r_pdf.content))
    assert len(pdf_reader.pages) >= 1
    pdf_text = pdf_reader.pages[0].extract_text() or ""
    assert "UEH_CONFIRMED_ORG" in pdf_text
    assert "UNVERIFIED_NOISE_ORG_999" not in pdf_text

    # 5. XLSX export is a valid 3-sheet Excel workbook
    r_xlsx = client.get(f"/api/workspaces/{ws.id}/export/xlsx?verified_only=true")
    assert r_xlsx.status_code == 200
    wb = load_workbook(io.BytesIO(r_xlsx.content))
    assert "HoSoDaXacNhan" in wb.sheetnames
    assert "DocSauTaiLieuPDF" in wb.sheetnames

    # 6. HTML & JSON exports
    r_html = client.get(f"/api/workspaces/{ws.id}/export/html?verified_only=true")
    assert r_html.status_code == 200 and "Đại học Kinh tế TP.HCM (UEH)" in r_html.text
    assert "UNVERIFIED_NOISE_ORG_999" not in r_html.text

    r_json = client.get(f"/api/workspaces/{ws.id}/export/json?verified_only=true")
    assert r_json.status_code == 200 and len(r_json.json()["verified_dossier_items"]) == 1


def test_workspace_pinning_and_deep_search_summary() -> None:
    """Verify workspace pinning (`PATCH /api/workspaces/{id}/pin`), pinned-first sorting, and search_summary indexing."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    ws_a = client.post("/api/workspaces", json={"name": "Phiên A"}).json()
    ws_b = client.post("/api/workspaces", json={"name": "Phiên B"}).json()

    # Add dossier clue inside Phiên B so deep search summary includes it
    client.post(
        f"/api/workspaces/{ws_b['id']}/dossier",
        json={"field_key": "MSSV", "field_value": "31251020209", "source_url": ""},
    )

    # Pin Phiên A
    r_pin = client.patch(f"/api/workspaces/{ws_a['id']}/pin", json={"pinned": True})
    assert r_pin.status_code == 200 and r_pin.json()["pinned"] is True

    listed = client.get("/api/workspaces").json()
    ids = [w["id"] for w in listed]
    assert ids.index(ws_a["id"]) < ids.index(ws_b["id"])  # Pinned workspace sorts first
    ws_b_full = next(w for w in listed if w["id"] == ws_b["id"])
    assert "31251020209" in (ws_b_full.get("search_summary") or "")

    client.delete(f"/api/workspaces/{ws_a['id']}")
    client.delete(f"/api/workspaces/{ws_b['id']}")


def test_source_feedback_permanent_veto_and_progressive_unverified_rotation(tmp_path: Path) -> None:
    """Verify user-rejected sources are permanently vetoed and previously shown unverified sources rotate out on next turn."""
    import asyncio
    from app.core.graph_store import GraphStore
    from app.core.schemas import WorkspaceCreate
    from app.pipeline.layer1_intake import run_layer1_intake
    from app.pipeline.layer2_gatekeeper import OuterGatekeeper

    store = GraphStore(tmp_path / "feedback_rotation.db")
    ws = store.create_workspace(WorkspaceCreate(name="Rotation Test"))

    # 1. User marks url_bad as REJECTED ("Không đúng")
    store.add_source_feedback(ws.id, "https://www.scribd.com/document/111/bad-homonym", verdict="REJECTED", title="Bad")

    # 2. User pins url_confirmed to Verified Dossier ("Lưu Hồ sơ")
    store.add_dossier_item(
        workspace_id=ws.id,
        field_key="Nguồn đã xác nhận",
        field_value="Confirmed UEH List",
        source_url="https://www.studocu.vn/vn/document/ueh/confirmed/222",
    )

    # 3. Prior assistant turn showed url_confirmed (pinned) AND url_unverified (not pinned by user)
    store.add_chat_message(
        ws.id,
        role="assistant",
        content="Turn 1 report",
        payload={
            "parsed_clues": {"target_name": "Lê Hoàng Luân", "organizations": ["UEH"]},
            "discovered_sources": [
                {"title": "Confirmed UEH", "url": "https://www.studocu.vn/vn/document/ueh/confirmed/222", "snippet": "Lê Hoàng Luân UEH"},
                {"title": "Unverified Old", "url": "https://www.scribd.com/document/333/unverified-old", "snippet": "Lê Hoàng Luân UEH"},
            ],
        },
    )

    # 4. Run Layer 1 Intake for Turn 2 on the same target
    ctx = asyncio.run(run_layer1_intake(store=store, workspace_id=ws.id, prompt="Lê Hoàng Luân, UEH"))
    assert "https://www.scribd.com/document/111/bad-homonym" in ctx.rejected_urls
    assert "https://www.studocu.vn/vn/document/ueh/confirmed/222" in ctx.confirmed_urls
    assert "https://www.scribd.com/document/333/unverified-old" in ctx.previously_shown_unverified_urls

    # 5. Layer 2 OuterGatekeeper must:
    #    - block url_bad with `user_rejected_source`
    #    - block url_unverified with `unverified_rotated_out` (so deeper results behind it move up!)
    #    - allow url_confirmed and brand-new url_fresh_rank9
    gk = OuterGatekeeper(ctx)
    assert gk.evaluate_candidate("Bad Doc", "https://www.scribd.com/document/111/bad-homonym", "Lê Hoàng Luân UEH") is False
    assert gk.evaluate_candidate("Old Unverified", "https://www.scribd.com/document/333/unverified-old", "Lê Hoàng Luân UEH") is False
    assert gk.evaluate_candidate("Confirmed Doc", "https://www.studocu.vn/vn/document/ueh/confirmed/222", "Lê Hoàng Luân UEH") is True
    assert gk.evaluate_candidate("Fresh Deeper Hit #9", "https://www.studocu.vn/vn/document/ueh/fresh-hit/444", "Lê Hoàng Luân UEH") is True

    assert gk.telemetry.rejected_by_reason.get("user_rejected_source") == 1
    assert gk.telemetry.rejected_by_reason.get("unverified_rotated_out") == 1
    kept_urls = [s["url"] for s in gk.ranked_sources]
    assert "https://www.studocu.vn/vn/document/ueh/fresh-hit/444" in kept_urls
