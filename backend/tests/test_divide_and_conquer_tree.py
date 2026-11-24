"""Unit & integration tests for the Adaptive Divide-and-Conquer & Branch-and-Bound Investigation Tree.

100% synthetic data & offline mocks (zero real PII, zero live network calls).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx

from app.agents.blackboard import InvestigationBlackboard
from app.connectors.document_reader import (
    extract_embedded_document_links,
    extract_roster_candidates_from_excerpts,
)
from app.connectors.web_search import WebSearchConnector
from app.core.graph_store import GraphStore
from app.pipeline.investigation_tree import (
    InvestigationTree,
    should_activate_divide_and_conquer,
    verify_same_person_consistency,
)
from app.pipeline.layer1_intake import parse_user_prompt
from app.pipeline.layer2_gatekeeper import OuterGatekeeper
from app.pipeline.models import InvestigationContext


def test_embedded_attachment_extractor_and_ssrf_guard() -> None:
    """Verify portal HTML attachment crawler finds relative PDFs, iframes, and Drive links while blocking localhost."""
    html = """
    <html><body>
      <a href="/uploads/danh-sach-khoi-12.pdf">Tải danh sách PDF</a>
      <iframe src="https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz/preview"></iframe>
      <a href="http://127.0.0.1:8000/secret.pdf">SSRF attempt</a>
      <a href="https://school.edu.vn/files/bang-diem.xlsx">Excel</a>
    </body></html>
    """
    links = extract_embedded_document_links("https://school.edu.vn/bai-viet/123", html)
    assert "https://school.edu.vn/uploads/danh-sach-khoi-12.pdf" in links
    assert "https://drive.google.com/uc?export=download&id=1AbCdEfGhIjKlMnOpQrStUvWxYz" in links
    assert "https://school.edu.vn/files/bang-diem.xlsx" in links
    assert not any("127.0.0.1" in u for u in links)


def test_roster_row_expansion_and_same_person_consistency_pruning() -> None:
    """Verify table rows expand partial names into structured candidates and prune conflicting birth years."""
    excerpts = [
        {"page": 1, "line": "12A13 13 Trần Thị Minh Khuê 18/12/2007"},
        {"page": 1, "line": "12A02 04 Lê Minh Khuê 10/01/1999"},
    ]
    cands = extract_roster_candidates_from_excerpts(excerpts, "Minh Khuê")
    assert len(cands) == 2
    by_name = {c["full_name"]: c for c in cands}
    assert by_name["Trần Thị Minh Khuê"]["birth_date"] == "18/12/2007"
    assert by_name["Trần Thị Minh Khuê"]["class_code"] == "12A13"

    seed = parse_user_prompt("Minh Khuê, THPT Ánh Dương, 2007")
    ok_good, score_good, reason_good = verify_same_person_consistency(seed, by_name["Trần Thị Minh Khuê"])
    assert ok_good is True and score_good > 3.0 and reason_good == ""

    ok_bad, _, reason_bad = verify_same_person_consistency(seed, by_name["Lê Minh Khuê"])
    assert ok_bad is False and "năm sinh" in reason_bad.lower()


def test_adaptive_sufficiency_trigger_avoids_mechanical_execution() -> None:
    """Verify tree does NOT fire mechanically when direct search already found abundant strong evidence."""
    parsed = parse_user_prompt("Trần Thị Minh Khuê, THPT Ánh Dương, 18/12/2007")
    ctx = InvestigationContext(
        workspace_id="ws-1",
        raw_prompt="Trần Thị Minh Khuê, THPT Ánh Dương, 18/12/2007",
        parsed=parsed,
        anchors={},
        region="vn",
        target_name=parsed["target_name"],
    )
    gk = OuterGatekeeper(ctx)
    # 0 hits -> must activate Divide-and-Conquer
    should_run_empty, _ = should_activate_divide_and_conquer(ctx, gk)
    assert should_run_empty is True

    # 3 strong hits with full name & DOB -> must NOT fire mechanically
    for i in range(3):
        gk.ranked_sources.append({"title": f"Doc {i}", "url": f"https://ex{i}.edu.vn/p", "match_score": 4})
    should_run_full, reason_full = should_activate_divide_and_conquer(ctx, gk)
    assert should_run_full is False and reason_full == "direct_evidence_sufficient"


def test_end_to_end_divide_and_conquer_tree_crawl_prune_snowball_and_backtrack(tmp_path: Path, monkeypatch) -> None:
    """End-to-end offline simulation: Partial Name + Org -> Portal HTML -> PDF Row -> Prune Wrong Homonym -> Snowball Confirm."""
    db = tmp_path / "tree_test.db"
    GraphStore(db)
    ws_conn = WebSearchConnector(db)

    parsed = parse_user_prompt("Minh Khuê, THPT Ánh Dương, 2007")
    ctx = InvestigationContext(
        workspace_id="ws-tree",
        raw_prompt="Minh Khuê, THPT Ánh Dương, 2007",
        parsed=parsed,
        anchors={},
        region="vn",
        target_name="Minh Khuê",
    )
    gk = OuterGatekeeper(ctx)
    bb = InvestigationBlackboard(workspace_id="ws-tree", target_name="Minh Khuê")

    # Mock search_fn: Depth 1 returns portal HTML page; Depth 3 snowball returns corroborating university hit
    async def mock_search(query: str, max_res: int) -> list[dict[str, Any]]:
        if "danh sách học sinh" in query.lower():
            return [
                {
                    "title": "Danh sách học sinh khối 12 THPT Ánh Dương năm học 2024-2025",
                    "url": "https://thptanhduong.edu.vn/danh-sach-khoi-12",
                    "snippet": "Danh sách lớp khối 12 đính kèm file PDF",
                    "consensus_score": 2,
                }
            ]
        if "Trần Thị Minh Khuê" in query and "18/12/2007" in query:
            return [
                {
                    "title": "Danh sách trúng tuyển ĐH Y Dược - Trần Thị Minh Khuê (18/12/2007)",
                    "url": "https://ump-sample.edu.vn/trung-tuyen-2025",
                    "snippet": "Trần Thị Minh Khuê ngày sinh 18/12/2007 học sinh THPT Ánh Dương trúng tuyển ngành Y khoa",
                    "consensus_score": 3,
                }
            ]
        return []

    # Mock HTTP transport for portal HTML page + PDF download
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://thptanhduong.edu.vn/danh-sach-khoi-12":
            html = '<html><body><a href="/uploads/khoi12.pdf">PDF</a></body></html>'
            return httpx.Response(200, headers={"content-type": "text/html"}, text=html)
        return httpx.Response(404)

    async def fake_inspect_doc(url: str, target_terms: list[str], timeout: float = 10.0, client: Any = None) -> dict[str, Any]:
        if url.endswith("/uploads/khoi12.pdf"):
            return {
                "ok": True,
                "url": url,
                "doc_type": "pdf",
                "header_hint": "DANH SÁCH HỌC SINH KHỐI 12 - THPT ÁNH DƯƠNG",
                "excerpts": [
                    {"page": 1, "line": "12A13 13 Trần Thị Minh Khuê 18/12/2007", "matched_terms": ["Minh Khuê"]},
                    {"page": 1, "line": "12A02 04 Lê Minh Khuê 10/01/1999", "matched_terms": ["Minh Khuê"]},
                ],
            }
        return {"ok": False, "url": url, "excerpts": []}

    monkeypatch.setattr("app.pipeline.investigation_tree.fetch_and_inspect_document", fake_inspect_doc)

    async def _run() -> dict[str, Any]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as mock_client:
            tree = InvestigationTree("Minh Khuê", {"target_name": "Minh Khuê", "organizations": ["THPT Ánh Dương"]})
            return await tree.run_recursive_search(
                ctx=ctx,
                gatekeeper=gk,
                ws_conn=ws_conn,
                bb=bb,
                client=mock_client,
                search_fn=mock_search,
            )

    summary = asyncio.run(_run())
    assert summary["activated"] is True
    assert summary["pruned_count"] == 1  # Lê Minh Khuê (1999) pruned due to birth-year conflict!
    assert len(summary["confirmed_expansions"]) == 1
    assert summary["confirmed_expansions"][0]["full_name"] == "Trần Thị Minh Khuê"
    assert summary["confirmed_expansions"][0]["birth_date"] == "18/12/2007"
    assert summary["confirmed_expansions"][0]["class_code"] == "12A13"
    # Back-propagated into ctx.parsed & gatekeeper kept the corroborating university hit!
    assert ctx.parsed.get("expanded_full_name") == "Trần Thị Minh Khuê"
    assert ctx.parsed.get("birth_date") == "18/12/2007"
    assert any("ump-sample.edu.vn" in s["url"] for s in gk.ranked_sources)
