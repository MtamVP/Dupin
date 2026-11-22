"""Tests for the 5 real-world readiness upgrades (SQLite blackboards, zero-junk veto, live MCTS collection, rich VN extraction, UI controls)."""

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.agents.planner import PlannerAgent
from app.agents.reader import ReaderAgent
from app.core.graph_store import GraphStore
from app.core.schemas import FeatureCategory, FeatureClaim, NodeCreate, WorkspaceCreate


@pytest.mark.asyncio
async def test_rich_vietnamese_reader_extracts_dob_major_phone_and_nickname() -> None:
    reader = ReaderAgent()
    text = (
        "Nguyễn Văn An (An Dev) sinh ngày 15/08/2002, học chuyên ngành An toàn Thông tin "
        "tại Đại học Bách Khoa. Số liên hệ công khai: 0912345678."
    )
    res = await reader.extract(text, subject_label="Nguyễn Văn An", source_url="https://cv.vn/an")
    keys = {c.key: c.value for c in res.claims}
    assert keys["birth_date"] == "15/08/2002"
    assert keys["public_phone"] == "0912345678"
    assert keys["nickname"] == "An Dev"
    assert "An toàn Thông tin" in str(keys["major_department"])
    assert any(t.relation == "ALSO_KNOWN_AS" and t.object_label == "An Dev" for t in res.triples)


@pytest.mark.asyncio
async def test_vetoed_noise_leaves_zero_junk_nodes_in_sqlite(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "clean_graph.db")
    ws = store.create_workspace(WorkspaceCreate(name="Cleanliness Test"))
    planner = PlannerAgent(store=store)

    store.upsert_node(
        ws.id,
        NodeCreate(
            type="Person",
            label="Nguyễn Văn An",
            claims=[
                FeatureClaim(
                    category=FeatureCategory.NEGATIVE_CONSTRAINT,
                    key="location",
                    value="Hà Nội",
                    polarity="NEGATIVE",
                    source_url="https://seed.local",
                )
            ],
        ),
    )

    bb = planner.initialize_blackboard(ws.id, "Nguyễn Văn An", organizations=["HCMUT"])
    h1 = planner.select_next_hypothesis(bb)
    assert h1 is not None

    # Feed off-target noisy document -> must be vetoed AND leave zero junk Alias nodes in SQLite!
    await planner.evaluate_and_expand(
        bb,
        h1.id,
        [
            {
                "text": "Nguyễn Văn An sống tại Hà Nội, là cầu thủ bóng đá.",
                "source_url": "https://sport.vn/noise",
            }
        ],
    )
    snapshot = store.get_graph(ws.id)
    assert snapshot is not None
    # Only the original Person node should exist — zero junk Alias nodes!
    assert len(snapshot.nodes) == 1
    assert snapshot.nodes[0].label == "Nguyễn Văn An"


@pytest.mark.asyncio
async def test_live_collector_and_sqlite_blackboard_persistence(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "live_mcts.db")
    ws = store.create_workspace(WorkspaceCreate(name="Live MCTS"))
    planner = PlannerAgent(store=store)

    bb = planner.initialize_blackboard(ws.id, "Nguyễn Văn An", organizations=["HCMUT"])
    store.save_blackboard(bb)

    # Verify Blackboard survives reloading from SQLite
    loaded = store.get_blackboard(bb.id)
    assert loaded is not None
    assert loaded["target_name"] == "Nguyễn Văn An"

    # Mock DuckDuckGo HTML response + target webpage
    ddg_html = (
        '<a class="result__a" href="https://hcmut.edu.vn/an">An HCMUT</a>'
        '<a class="result__snippet">Nguyễn Văn An học tại HCMUT</a>'
    )
    page_html = "<html><title>An Profile</title><body>Nguyễn Văn An làm việc tại VNG.</body></html>"

    def mock_handler(req: httpx.Request) -> httpx.Response:
        if "duckduckgo" in str(req.url):
            return httpx.Response(200, text=ddg_html)
        return httpx.Response(200, text=page_html)

    h1 = planner.select_next_hypothesis(bb)
    assert h1 is not None
    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        docs = await planner.collect_live_for_hypothesis(bb, h1, max_pages=1, client=client)
    assert len(docs) >= 2
    assert any("VNG" in d["text"] for d in docs)


def test_chat_prompt_parsing_and_agent_chat_ui(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "ui_ready.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    html = client.get("/").text
    assert "sendPrompt()" in html
    assert "Cuộc điều tra mới" in html
    assert "Hồ sơ tổng hợp" in html
    assert "openMapPicker()" in html
    assert "gemini-3.8-flash" in html

    # Test comma-separated clues chat endpoint (including full DOB & strict relevance filtering)
    ws_id = client.post("/api/workspaces", json={"name": "Chat Session"}).json()["id"]
    chat_resp = client.post(
        f"/api/workspaces/{ws_id}/chat",
        json={
            "prompt": "Nguyễn Minh Anh, UEH, 15/06/2005, THPT Demo Mẫu, -ca sĩ",
            "live_search": False,
        },
    )
    assert chat_resp.status_code == 200
    body = chat_resp.json()
    assert body["parsed_clues"]["target_name"] == "Nguyễn Minh Anh"
    assert body["parsed_clues"]["birth_date"] == "15/06/2005"
    assert body["parsed_clues"]["birth_year"] == 2005
    assert "UEH" in body["parsed_clues"]["organizations"]
    assert "THPT Demo Mẫu" in body["parsed_clues"]["organizations"]
    assert "ca sĩ" in body["parsed_clues"]["negative_keywords"]
    assert "stylometry_vector" not in body["assistant_reply"]
    assert len(body["suggested_dorks"]) >= 3
    assert body["graph_stats"]["nodes"] >= 3

    # Verify Strict Relevance Gate rejects generic school homepage that doesn't mention the person
    from app.agents.chat_orchestrator import score_source_relevance

    rel_bad, _, _ = score_source_relevance(
        "Chào mừng kỷ niệm 44 năm Ngày Nhà giáo Việt Nam - THPT Demo Mẫu",
        "https://thptdemo.example.edu.vn/",
        body["parsed_clues"],
    )
    assert rel_bad is False

    rel_good, score_good, matched_good = score_source_relevance(
        "Danh sách trúng tuyển UEH: Nguyễn Minh Anh (15/06/2005) - THPT Demo Mẫu",
        "https://ueh.edu.vn/tuyensinh/2025",
        body["parsed_clues"],
    )
    assert rel_good is True
    assert score_good >= 4
    assert "15/06/2005" in matched_good

    # Turn 2: Send follow-up clue WITHOUT repeating the person's name -> must remember context & persist history!
    turn2_resp = client.post(
        f"/api/workspaces/{ws_id}/chat",
        json={"prompt": "khoa Tài chính, TP.HCM", "live_search": False},
    )
    assert turn2_resp.status_code == 200
    t2_body = turn2_resp.json()
    assert t2_body["parsed_clues"]["target_name"] == "Nguyễn Minh Anh"
    assert t2_body["parsed_clues"]["birth_date"] == "15/06/2005"
    assert "UEH" in t2_body["parsed_clues"]["organizations"]
    assert "TP.HCM" in t2_body["parsed_clues"]["locations"]

    # Reload persisted chat history (simulating browser refresh / app restart)
    hist_resp = client.get(f"/api/workspaces/{ws_id}/messages")
    assert hist_resp.status_code == 200
    messages = hist_resp.json()["messages"]
    assert len(messages) == 4  # 2 user turns + 2 assistant turns

    # Test Verified Dossier CRUD & Feedback Loop into next search + SSE stream endpoint
    d_add = client.post(
        f"/api/workspaces/{ws_id}/dossier",
        json={"field_key": "Trường ĐH", "field_value": "UEH", "source_url": "https://ueh.edu.vn"},
    )
    assert d_add.status_code == 201
    item_id = d_add.json()["id"]

    d_upd = client.patch(f"/api/dossier/{item_id}", json={"field_value": "UEH K51"})
    assert d_upd.status_code == 200
    assert d_upd.json()["field_value"] == "UEH K51"

    stream_resp = client.post(
        f"/api/workspaces/{ws_id}/chat/stream",
        json={
            "prompt": "tìm thêm thông tin lớp",
            "live_search": False,
            "model_override": "gemini-4-hydrogen",
            "geo_point": {"lat": 10.7626, "lng": 106.6601, "label": "Cơ sở B UEH"},
        },
    )
    assert stream_resp.status_code == 200
    assert "event: status" in stream_resp.text
    assert "event: done" in stream_resp.text
    assert "Cơ sở B UEH" in stream_resp.text

    d_del = client.delete(f"/api/dossier/{item_id}")
    assert d_del.status_code == 200
