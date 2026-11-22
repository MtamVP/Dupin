"""Tests for Deep ReAct Engine: High-Entropy Anchor Decoder, ID Bracketing, Mirror Pivots, Wayback Recovery, and Vision OCR."""

import json
from pathlib import Path

import httpx
import pytest

from app.connectors.mirror_pivots import (
    build_mirror_pivot_queries,
    check_wayback_snapshot,
    diagnose_url_health,
    extract_root_org_domain,
    is_junk_category_url,
)
from app.core.anchor_decoder import bracket_numeric_ids, decode_high_entropy_anchors
from app.core.llm_provider import GeminiProvider


def test_high_entropy_anchor_decoder_ueh_case_study() -> None:
    text = (
        "Email sinh viên: minhanh.31251029999@st.ueh.edu.vn, "
        "Quyết định 2623/QĐ-ĐHKT-ĐT, mã lớp DH51HRP001, mã LHP 26C1ECO50102103."
    )
    anchors = decode_high_entropy_anchors(text)
    assert anchors["emails"][0]["email"] == "minhanh.31251029999@st.ueh.edu.vn"
    assert "UEH (Đại học Kinh tế TP.HCM)" in anchors["inferred_orgs"]
    assert anchors["student_ids"][0]["student_id"] == "31251029999"
    assert anchors["student_ids"][0]["cohort"] == "K51"
    assert anchors["student_ids"][0]["intake_year"] == 2025
    assert "2623/QĐ-ĐHKT-ĐT" in anchors["doc_numbers"]
    assert "DH51HRP001" in anchors["class_codes"]
    assert "26C1ECO50102103" in anchors["lhp_codes"]


def test_id_bracketing_prevents_confirmation_bias() -> None:
    observed = [
        (31251029990, "Quản lý công (7340403)"),
        (31251029998, "Luật kinh doanh quốc tế (7380101)"),
    ]
    res = bracket_numeric_ids(31251029995, observed)
    assert res["lower_bound"] == (31251029990, "Quản lý công (7340403)")
    assert res["upper_bound"] == (31251029998, "Luật kinh doanh quốc tế (7380101)")
    # Must NEVER claim 100% certainty when sandwiched between two different categories!
    assert all(c["probability"] <= 0.80 for c in res["candidates"])
    assert len(res["candidates"]) >= 2


def test_mirror_pivot_query_generation() -> None:
    parsed = {
        "target_name": "Nguyễn Minh Anh",
        "organizations": ["UEH"],
        "keywords": ["IELTS 7.0"],
        "raw_prompt": "UEH IELTS 7.0 danh sách",
        "negative_keywords": ["Trưng Vương"],
    }
    anchors = decode_high_entropy_anchors(
        "minhanh.31251029999@st.ueh.edu.vn 2623/QĐ-ĐHKT-ĐT DH51HRP001"
    )
    queries = build_mirror_pivot_queries(parsed, anchors)
    strategies = {q["strategy"] for q in queries}
    assert "mirror:org_domain_portal" in strategies
    assert "mirror:student_id_exact" in strategies
    assert "mirror:studocu_cohort_list" in strategies
    assert "mirror:scribd_cohort_list" in strategies
    assert "mirror:doc_number_pivot" in strategies
    # Must target specific /document/ paths, NEVER generic /course/ or /institution/ pages
    assert any("studocu.com/vn/document" in q["query"] and "K51" in q["query"] for q in queries)
    assert is_junk_category_url("https://www.studocu.com/vn/course/ueh-isb/ngon-ngu-anh/123")
    assert is_junk_category_url("https://help.studocu.com/hc/de")
    assert not is_junk_category_url("https://www.studocu.com/vn/document/ueh/ielts/142779871")
    assert extract_root_org_domain("st.ueh.edu.vn") == "ueh.edu.vn"


@pytest.mark.asyncio
async def test_network_diagnostics_wayback_and_vision_ocr() -> None:
    def timeout_handler(req: httpx.Request) -> httpx.Response:
        if "archive.org" in str(req.url):
            return httpx.Response(
                200,
                json={
                    "archived_snapshots": {
                        "closest": {
                            "available": True,
                            "url": "https://web.archive.org/web/20250910/https://daotao.ueh.edu.vn/file.pdf",
                            "timestamp": "20250910",
                        }
                    }
                },
            )
        raise httpx.ReadTimeout("Simulated institutional server timeout")

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout_handler)) as client:
        diag = await diagnose_url_health("https://daotao.ueh.edu.vn/file.pdf", client=client)
        assert diag["reachable"] is False
        assert "CONNECTION_TIMEOUT" in diag["diagnosis"]

        wb = await check_wayback_snapshot("https://daotao.ueh.edu.vn/file.pdf", client=client)
        assert wb is not None
        assert "web.archive.org" in wb["archived_url"]

    # Test Gemini Vision multimodal image analysis
    def vision_handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content.decode("utf-8"))
        assert body["contents"][0]["parts"][1]["inline_data"]["mime_type"] == "image/png"
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "Mã lớp: DH51HRP001, Đợt 2"}]}}]},
        )

    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
    async with httpx.AsyncClient(transport=httpx.MockTransport(vision_handler)) as client:
        v_text = await provider.analyze_image_and_text("Đọc bảng TKB", "aGVsbG8=", client=client)
    assert "DH51HRP001" in v_text


def test_numeric_student_id_not_classified_as_social_alias() -> None:
    """Pure numeric MSSV tokens must never be sent to social username scanners as aliases."""
    from app.agents.chat_orchestrator import parse_user_prompt

    parsed = parse_user_prompt("Tran Minh Anh, THPT Chu Van An, 15/05/2007, UEH, 31251029999, minhanh.31251029999@st.ueh.edu.vn")
    assert "31251029999" not in parsed["aliases"]
    assert parsed["target_name"] == "Tran Minh Anh"
    assert "UEH" in parsed["organizations"]


def test_highschool_grade_year_temporal_veto() -> None:
    """A 2018 article citing a Grade 11 student must be vetoed for a target born in 2007."""
    from app.agents.chat_orchestrator import parse_user_prompt, score_source_relevance

    parsed = parse_user_prompt("Tran Minh Anh, THPT Chu Van An, 15/05/2007, UEH")
    is_rel_old, _, _ = score_source_relevance(
        "Danh sach tinh nguyen vien 2018: 20. Tran Minh Anh, Lop 11, Hanoi Academy. 21. Le B, THPT Chu Van An",
        "https://example.vn/tinh-nguyen-vien-2018-12345.htm",
        parsed,
    )
    assert is_rel_old is False

    is_rel_valid, score_valid, _ = score_source_relevance(
        "Danh sach sinh vien UEH 2025: Tran Minh Anh, THPT Chu Van An",
        "https://ueh.edu.vn/danh-sach-2025.pdf",
        parsed,
    )
    assert is_rel_valid is True
    assert score_valid >= 2


def test_site_constraint_and_empty_host_filter() -> None:
    """Off-domain Bing fallback junk and empty-host Brave redirects must be stripped."""
    from app.connectors.web_search import _enforce_site_constraint, _is_malformed_result

    assert _is_malformed_result({"url": "http:///go/v1/broken-redirect", "title": "Broken"}) is True

    items = [
        {"url": "https://wasmarcade.com/gta-5", "title": "Play GTA 5"},
        {"url": "https://li.ueh.edu.vn/courses/ielts/", "title": "UEH IELTS"},
        {"url": "https://www.scribd.com/document/999999/UEH-K51", "title": "UEH K51"},
    ]
    kept_ueh = _enforce_site_constraint('site:ueh.edu.vn "31251029999"', items)
    assert [i["url"] for i in kept_ueh] == ["https://li.ueh.edu.vn/courses/ielts/"]

    kept_scribd = _enforce_site_constraint('site:scribd.com/document "31251029999"', items)
    assert [i["url"] for i in kept_scribd] == ["https://www.scribd.com/document/999999/UEH-K51"]
