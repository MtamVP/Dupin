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
    assert len(seen_queries) == 2
    assert "serper" in doc.metadata["engines_used"]
    assert len(doc.metadata["results"]) == 1
    # Key error_count must remain 0 because HTTP 400 retry succeeded cleanly
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
