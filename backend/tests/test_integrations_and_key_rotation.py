"""Tests for n8n-style Multi-Key Rotation Pool, 429 Cooldown Failover, Local Host Config, and MCP Agent Configs."""

from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.core.graph_store import GraphStore
from app.core.key_pool import APIKeyCreate, IntegrationStore, LocalHostConfig


def test_key_pool_round_robin_and_429_cooldown_failover(tmp_path: Path) -> None:
    pool = IntegrationStore(tmp_path / "keys.db")

    k1 = pool.add_key(APIKeyCreate(name="Gemini Free #1", provider="gemini", api_key="TEST_KEY_ONE_1111"))
    k2 = pool.add_key(APIKeyCreate(name="Gemini Free #2", provider="gemini", api_key="TEST_KEY_TWO_2222"))

    # Masked keys must never expose raw secrets
    assert k1["masked_key"] == "TEST...1111"
    assert "KEY_ONE" not in str(pool.list_keys())

    # Round-Robin: 1st call -> Key #1, 2nd call -> Key #2, 3rd call -> Key #1
    a1 = pool.acquire_key("gemini")
    a2 = pool.acquire_key("gemini")
    a3 = pool.acquire_key("gemini")
    assert a1 is not None and a2 is not None and a3 is not None
    assert a1["id"] == k1["id"]
    assert a2["id"] == k2["id"]
    assert a3["id"] == k1["id"]

    # Simulate HTTP 429 Rate Limit on Key #1 -> automatically puts Key #1 into cooldown
    pool.report_key_error(k1["id"], is_rate_limit=True, cooldown_sec=60.0)
    a4 = pool.acquire_key("gemini")
    a5 = pool.acquire_key("gemini")
    assert a4 is not None and a5 is not None
    assert a4["id"] == k2["id"]
    assert a5["id"] == k2["id"]

    status_map = {k["id"]: k["status"] for k in pool.list_keys("gemini")}
    assert status_map[k1["id"]] == "COOLDOWN"
    assert status_map[k2["id"]] == "ACTIVE"


def test_integrations_api_local_host_and_mcp_configs(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "int_api.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    # 1. Local Host config (Ollama + SearXNG)
    save_local = client.post(
        "/api/integrations/local",
        json={
            "active_mode": "ollama_local",
            "ollama_base_url": "http://localhost:11434",
            "ollama_model": "qwen2.5vl:7b",
            "searxng_url": "http://localhost:8888",
        },
    )
    assert save_local.status_code == 200
    assert client.get("/api/integrations/local").json()["searxng_url"] == "http://localhost:8888"

    # 2. Key Pool CRUD via REST API
    created = client.post(
        "/api/integrations/keys",
        json={"name": "Serper Google #1", "provider": "serper", "api_key": "serp_secret_987654"},
    )
    assert created.status_code == 201
    key_id = created.json()["id"]
    assert "serp_secret_987654" not in created.text

    toggled = client.patch(f"/api/integrations/keys/{key_id}", json={"enabled": False})
    assert toggled.status_code == 200
    assert toggled.json()["status"] == "DISABLED"

    deleted = client.delete(f"/api/integrations/keys/{key_id}")
    assert deleted.status_code == 200

    # 3. MCP Configs for Antigravity, Claude Code, Codex + new MCP tools
    mcp_cfg = client.get("/api/integrations/mcp-config").json()
    assert "stalker-pp" in mcp_cfg["antigravity_config"]
    assert "claude mcp add stalker-pp" in mcp_cfg["claude_code_cli"]
    assert "/api/mcp" in mcp_cfg["codex_cursor_config"]

    tools_resp = client.post("/api/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    tool_names = {t["name"] for t in tools_resp.json()["result"]["tools"]}
    assert "stalker_deep_investigate" in tool_names
    assert "stalker_decode_anchors" in tool_names


def test_parallel_searxng_and_ddgs_consensus_fusion_and_fallback(tmp_path: Path, monkeypatch) -> None:
    import asyncio
    import httpx
    from app.connectors import web_search as ws_mod
    from app.connectors.web_search import (
        WebSearchConnector,
        merge_parallel_search_results,
        test_searxng_connection,
    )

    # 1. Pure consensus fusion: shared URL ranks #1, prefers clean SearXNG title, drops >180 char mashups
    sx_items = [
        {
            "url": "https://example.edu.vn/only-searxng",
            "title": "Only SearXNG",
            "snippet": "From Google via SearXNG",
            "engines": ["google"],
        },
        {
            "url": "https://www.scribd.com/document/12345/Danh-Sach/",
            "title": "Danh Sach Sinh Vien Chuan (Clean SearXNG Title)",
            "snippet": "Clean structured snippet from SearXNG",
            "engines": ["google", "bing"],
        },
    ]
    ddgs_items = [
        {
            "url": "https://scribd.com/document/12345/Danh-Sach",
            "title": "Noisy ddgs title",
            "snippet": "ddgs snippet",
        },
        {
            "url": "https://junk.example.com/mashup",
            "title": "A" * 200,  # malformed concatenated ddgs title -> must be dropped
            "snippet": "noise",
        },
        {
            "url": "https://github.com/only-ddgs",
            "title": "Only DDGS Repo",
            "snippet": "Found by ddgs",
        },
    ]
    merged = merge_parallel_search_results(sx_items, ddgs_items, max_results=5)
    assert len(merged) == 3
    assert merged[0]["url"] == "https://www.scribd.com/document/12345/Danh-Sach/"
    assert merged[0]["consensus_score"] == 3
    assert merged[0]["sources"] == ["searxng", "ddgs"]
    assert merged[0]["title"] == "Danh Sach Sinh Vien Chuan (Clean SearXNG Title)"
    assert all("mashup" not in r["url"] for r in merged)

    # 2. Live parallel execution inside WebSearchConnector.collect()
    db_path = tmp_path / "parallel_search.db"
    GraphStore(db_path)  # Initialize core schema including http_cache
    int_store = IntegrationStore(db_path)
    int_store.save_local_config(LocalHostConfig(searxng_url="http://localhost:8888"))

    conn = WebSearchConnector(db_path)

    async def fake_searxng(query: str, base_url: str, max_results: int = 8, **kwargs):
        return sx_items

    def fake_ddgs(query: str, max_results: int = 8):
        return ddgs_items

    monkeypatch.setattr(conn, "_search_searxng", fake_searxng)
    monkeypatch.setattr(ws_mod, "_ddgs_live_search_sync", fake_ddgs)

    doc = asyncio.run(conn.collect("test parallel query", max_results=5))
    assert doc.metadata["searxng_active"] is True
    assert doc.metadata["engines_used"] == ["searxng", "ddgs"]
    assert doc.metadata["consensus_hits"] == 1
    assert doc.metadata["results"][0]["sources"] == ["searxng", "ddgs"]

    # 3. Graceful fallback when SearXNG is offline -> ddgs still succeeds without crashing
    async def broken_searxng(query: str, base_url: str, max_results: int = 8, **kwargs):
        raise httpx.ConnectError("Connection refused")

    monkeypatch.setattr(conn, "_search_searxng", broken_searxng)
    doc_fb = asyncio.run(conn.collect("test fallback query", max_results=5))
    assert doc_fb.metadata["searxng_active"] is False
    assert doc_fb.metadata["engines_used"] == ["ddgs"]
    assert len(doc_fb.metadata["results"]) == 2  # mashup filtered out, 2 valid ddgs results remain

    # 4. Probe helper test_searxng_connection (200 JSON OK & 403 JSON disabled)
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={"results": [{"url": "https://vi.wikipedia.org", "engines": ["google", "bing"]}]},
        )

    def forbidden_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    async def _run_probes():
        async with httpx.AsyncClient(transport=httpx.MockTransport(ok_handler)) as c_ok:
            r_ok = await test_searxng_connection("http://localhost:8888", client=c_ok)
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden_handler)) as c_403:
            r_403 = await test_searxng_connection("http://localhost:8888", client=c_403)
        return r_ok, r_403

    r_ok, r_403 = asyncio.run(_run_probes())
    assert r_ok["reachable"] is True and r_ok["json_enabled"] is True
    assert r_ok["sample_count"] == 1 and "google" in r_ok["engines"]
    assert r_403["reachable"] is True and r_403["json_enabled"] is False
    assert "403" in r_403["error"]
