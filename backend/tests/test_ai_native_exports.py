"""Tests for AI-Native Agent files (AGENTS.md, SKILL.md, llms.txt, llms-full.txt, catalog.json) and JSONL/CSV exports."""

import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.graph_store import GraphStore
from app.core.llm_provider import GeminiProvider


def test_ai_native_files_and_endpoints(tmp_path: Path, monkeypatch) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    for fname in ("AGENTS.md", "SKILL.md", "llms.txt", "llms-full.txt", "catalog.json"):
        assert (repo_root / fname).exists(), f"Missing AI-native file: {fname}"

    catalog = json.loads((repo_root / "catalog.json").read_text(encoding="utf-8"))
    assert len(catalog["agents"]) == 5
    assert len(catalog["feature_dimensions"]) == 8
    assert "stalker_analyze_and_verify" in catalog["mcp_tools"]

    test_store = GraphStore(tmp_path / "ai_native.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    assert client.get("/llms.txt").status_code == 200
    assert "Stalker++" in client.get("/llms-full.txt").text
    assert client.get("/api/catalog.json").json()["name"] == "Dupin"

    # Create workspace, run Reader+Critic, and verify JSONL & CSV dataset exports
    ws_id = client.post("/api/workspaces", json={"name": "Export Dataset"}).json()["id"]
    client.post(
        f"/api/workspaces/{ws_id}/agents/analyze-text",
        json={
            "subject_label": "Nguyễn Văn An",
            "text": "Nguyễn Văn An học tại Trường ĐH Bách Khoa và làm việc tại VNG Corporation.",
            "source_url": "https://hcmut.edu.vn/an",
        },
    )

    jsonl_resp = client.get(f"/api/workspaces/{ws_id}/export/jsonl")
    assert jsonl_resp.status_code == 200
    records = [json.loads(line) for line in jsonl_resp.text.strip().splitlines()]
    assert any(r["record_type"] == "node" for r in records)
    assert any(r["record_type"] == "edge" for r in records)

    csv_resp = client.get(f"/api/workspaces/{ws_id}/export/csv")
    assert csv_resp.status_code == 200
    assert "record_type,entity_or_source,relation_or_key" in csv_resp.text
    assert "VNG Corporation" in csv_resp.text


@pytest.mark.asyncio
async def test_gemini_google_search_grounding_and_settings_api(tmp_path: Path, monkeypatch) -> None:
    # Verify GeminiProvider sends google_search tool and parses groundingChunks
    mock_body = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Nguyễn Văn An học tại HCMUT và làm tại VNG."}]},
                "groundingMetadata": {
                    "groundingChunks": [
                        {"web": {"uri": "https://hcmut.edu.vn/an", "title": "HCMUT Profile"}}
                    ]
                },
            }
        ]
    }
    captured_payload = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured_payload.update(json.loads(req.content.decode("utf-8")))
        return httpx.Response(200, json=mock_body)

    provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        res = await provider.generate_with_google_search("Tìm Nguyễn Văn An HCMUT", client=client)

    assert captured_payload["tools"] == [{"google_search": {}}]
    assert "HCMUT" in res["text"]
    assert res["sources"][0]["url"] == "https://hcmut.edu.vn/an"

    # Verify runtime LLM settings endpoint does not leak API key
    test_store = GraphStore(tmp_path / "llm_cfg.db")
    monkeypatch.setattr(main, "store", test_store)
    api_client = TestClient(main.app)
    upd = api_client.post(
        "/api/settings/llm",
        json={"llm_provider": "gemini", "gemini_api_key": "secret-demo-key"},
    )
    assert upd.status_code == 200
    assert upd.json()["llm_provider"] == "gemini"
    assert upd.json()["has_gemini_key"] is True
    assert "secret-demo-key" not in upd.text
