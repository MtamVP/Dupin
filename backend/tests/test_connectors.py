"""Unit & integration tests for Phase 2 public connectors, SQLite HTTP cache, and MCP server."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.connectors.base import detect_soft_404
from app.connectors.github_api import GitHubPublicConnector, analyze_active_hours_utc
from app.connectors.web_fetcher import PublicWebFetcher, ingest_manual_snippet
from app.connectors.web_search import DorkRequest, generate_smart_dorks
from app.core.graph_store import GraphStore


def test_smart_dork_generator_vietnamese_and_negatives() -> None:
    req = DorkRequest(
        full_name="Nguyễn Văn An",
        aliases=["nva_dev"],
        organizations=["HCMUT", "ĐH Bách Khoa"],
        locations=["TP.HCM"],
        keywords=["CTF", "Cybersecurity"],
        negative_keywords=["ca sĩ", "bóng đá"],
        target_sites=["github.com"],
    )
    dorks = generate_smart_dorks(req)
    assert len(dorks) >= 3
    anchor_q = dorks[0]["query"]
    assert '"Nguyễn Văn An"' in anchor_q
    assert '"Nguyen Van An"' in anchor_q
    assert '"HCMUT"' in anchor_q
    assert '-"ca sĩ"' in anchor_q
    assert any(d["strategy"] == "site_pivot:github.com" for d in dorks)


def test_soft_404_detection_and_manual_snippet_extraction() -> None:
    assert detect_soft_404("404 Page Not Found", "Sorry, user not found on this server.", 200)
    assert not detect_soft_404("An Nguyen - Portfolio", "Software engineer graduated from HCMUT.", 200)

    snippet = (
        "Nguyễn Văn An (sinh năm 2002) hiện là sinh viên HCMUT. "
        "Liên hệ qua email an.nguyen02@hcmut.edu.vn hoặc https://github.com/nva_dev02"
    )
    doc = ingest_manual_snippet(snippet, source_url="https://example.edu.vn/student")
    keys = {c.key: c.value for c in doc.claims}
    assert keys["email"] == "an.nguyen02@hcmut.edu.vn"
    assert keys["associated_year"] == 2002
    assert "https://github.com/nva_dev02" in doc.outbound_links


def test_temporal_activity_signature_inference() -> None:
    # 09:00 UTC corresponds to ~16:00 UTC+7 (Vietnam afternoon peak)
    timestamps = [
        "2026-03-01T09:15:00Z",
        "2026-03-02T09:45:00Z",
        "2026-03-03T10:05:00Z",
    ]
    sig = analyze_active_hours_utc(timestamps)
    assert sig["peak_utc_hour"] == 9
    assert sig["inferred_local_tz_approx"] == "UTC+7"


@pytest.mark.asyncio
async def test_github_connector_and_sqlite_cache(tmp_path: Path) -> None:
    db_path = tmp_path / "cache_test.db"
    GraphStore(db_path)  # Initializes http_cache table
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if request.url.path == "/users/nva_dev02":
            return httpx.Response(
                200,
                text=json.dumps(
                    {
                        "login": "nva_dev02",
                        "name": "Nguyen Van An",
                        "company": "@HCMUT",
                        "location": "Ho Chi Minh City",
                        "email": "an@hcmut.edu.vn",
                        "bio": "Security Researcher",
                        "public_repos": 5,
                    }
                ),
            )
        return httpx.Response(
            200,
            text=json.dumps(
                [
                    {"language": "Python", "pushed_at": "2026-05-10T09:20:00Z"},
                    {"language": "Rust", "pushed_at": "2026-05-11T09:10:00Z"},
                ]
            ),
        )

    transport = httpx.MockTransport(handler)
    connector = GitHubPublicConnector(db_path)
    async with httpx.AsyncClient(transport=transport) as client:
        doc1 = await connector.collect("nva_dev02", client=client)
        assert not doc1.cached
        assert call_count == 2
        claim_keys = {c.key for c in doc1.claims}
        assert "full_name" in claim_keys
        assert "programming_languages" in claim_keys
        assert "temporal_activity_signature" in claim_keys

        # Second call must be served from SQLite http_cache without hitting network
        doc2 = await connector.collect("nva_dev02", client=client)
        assert doc2.cached
        assert call_count == 2


@pytest.mark.asyncio
async def test_web_fetcher_html_cleaning(tmp_path: Path) -> None:
    db_path = tmp_path / "web_test.db"
    GraphStore(db_path)

    sample_html = """
    <html>
      <head>
        <title>An Nguyen | Personal Blog</title>
        <meta property="og:description" content="Cybersecurity notes" />
        <script>console.log("ignore me");</script>
      </head>
      <body>
        <h1>Hello</h1>
        <p>Contact me at an.sec@proton.me or https://linkedin.com/in/an-nguyen-sec</p>
      </body>
    </html>
    """
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text=sample_html))
    fetcher = PublicWebFetcher(db_path)
    async with httpx.AsyncClient(transport=transport) as client:
        doc = await fetcher.collect("https://anblog.example.com", client=client)
        assert doc.title == "An Nguyen | Personal Blog"
        assert "console.log" not in doc.content
        assert any(c.value == "an.sec@proton.me" for c in doc.claims)
        assert "https://linkedin.com/in/an-nguyen-sec" in doc.outbound_links


def test_phase2_api_and_mcp_server(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "mcp_api.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    ws = client.post("/api/workspaces", json={"name": "Phase 2 Case"}).json()
    ws_id = ws["id"]

    # 1. Test MCP tools/list
    mcp_list = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert mcp_list.status_code == 200
    tool_names = {t["name"] for t in mcp_list.json()["result"]["tools"]}
    assert "stalker_generate_dorks" in tool_names
    assert "stalker_ingest_snippet" in tool_names

    # 2. Test MCP stalker_ingest_snippet -> auto-extracts claims & creates/updates node
    mcp_call = client.post(
        "/api/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "stalker_ingest_snippet",
                "arguments": {
                    "workspace_id": ws_id,
                    "target_label": "Nguyễn Văn An",
                    "text": "Sinh năm 2003, email: nva2003@gmail.com, github: https://github.com/nva2003",
                    "source_url": "https://example.com/cv",
                },
            },
        },
    )
    assert mcp_call.status_code == 200
    node_data = json.loads(mcp_call.json()["result"]["content"][0]["text"])
    assert len(node_data["claims"]) >= 3
