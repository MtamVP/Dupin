"""Unit & integration tests for Phase 4: MCTS/UCB1 Planner, Backtracking, Reflexion, Playbooks, and Adamic-Adar Link Prediction."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agents.planner import PlannerAgent
from app.core.graph_analytics import analyze_communities_and_bridges, predict_hidden_links
from app.core.graph_store import GraphStore
from app.core.schemas import EdgeCreate, FeatureCategory, FeatureClaim, NodeCreate, WorkspaceCreate


@pytest.mark.asyncio
async def test_mcts_planner_backtracking_and_reflexion(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "mcts_test.db")
    ws = store.create_workspace(WorkspaceCreate(name="MCTS Case"))
    planner = PlannerAgent(store=store)

    # Seed target with a known NEGATIVE constraint: never lived in Ha Noi
    store.upsert_node(
        ws.id,
        NodeCreate(
            type="Person",
            label="Nguyễn Văn An",
            claims=[
                FeatureClaim(
                    category=FeatureCategory.NEGATIVE_CONSTRAINT,
                    key="location",
                    value="Ha Noi",
                    polarity="NEGATIVE",
                    source_url="https://seed.local",
                )
            ],
        ),
    )

    bb = planner.initialize_blackboard(
        workspace_id=ws.id,
        target_name="Nguyễn Văn An",
        playbook_id="vietnam_student_alumni",
        organizations=["HCMUT"],
    )
    assert len(bb.tree) >= 4

    # Step 1: Select highest UCB1 hypothesis and feed it NOISY off-target documents
    # (about a footballer in Ha Noi) -> should trigger VETO, Dead-End Backtracking & Reflexion!
    h1 = planner.select_next_hypothesis(bb)
    assert h1 is not None

    noisy_docs = [
        {
            "text": "Nguyễn Văn An sống tại Hà Nội, là cầu thủ bóng đá chuyên nghiệp của câu lạc bộ thủ đô.",
            "source_url": "https://sport1.vn/an",
        },
        {
            "text": "Nguyễn Văn An quê ở Hà Nội, cầu thủ bóng đá vừa ghi bàn thắng đẹp mắt.",
            "source_url": "https://sport2.vn/an",
        },
    ]
    res1 = await planner.evaluate_and_expand(bb, h1.id, noisy_docs)
    assert res1["reward"] == 0.0
    assert bb.tree[h1.id].status == "DEAD_END_BACKTRACKED"
    assert len(res1["learned_negative_keywords"]) >= 1
    assert any(c["strategy"] == "reflexion:noise_filtered" for c in res1["spawned_hypotheses"])

    # Step 2: Select next hypothesis and feed an ON-TARGET document -> should expand child leads!
    h2 = planner.select_next_hypothesis(bb)
    assert h2 is not None and h2.id != h1.id
    valid_docs = [
        {
            "text": "Nguyễn Văn An học tại Trường ĐH Bách Khoa và làm việc tại VNG Corporation.",
            "source_url": "https://hcmut.edu.vn/alumni/an",
        }
    ]
    res2 = await planner.evaluate_and_expand(bb, h2.id, valid_docs)
    assert res2["reward"] > 0.35
    assert bb.tree[h2.id].status == "EXPANDED"
    assert any(c["strategy"].startswith("pivot:") for c in res2["spawned_hypotheses"])


def test_adamic_adar_hidden_link_prediction_and_bridges(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "analytics_test.db")
    ws = store.create_workspace(WorkspaceCreate(name="Network Science"))

    # Two unconnected profiles (Person A and Alias B) both connected to a small rare club ("CLB CyberSec")
    p_a = store.upsert_node(ws.id, NodeCreate(type="Person", label="Trần Minh Quân"))
    alias_b = store.upsert_node(ws.id, NodeCreate(type="Alias", label="quan_ctf_03"))
    rare_club = store.upsert_node(ws.id, NodeCreate(type="Org", label="CLB CyberSec Lab"))

    store.add_edge(ws.id, EdgeCreate(source_id=p_a.id, target_id=rare_club.id, relation="MEMBER_OF"))
    store.add_edge(ws.id, EdgeCreate(source_id=alias_b.id, target_id=rare_club.id, relation="MEMBER_OF"))

    g = store.to_networkx(ws.id)
    predicted = predict_hidden_links(g, top_k=5)
    assert len(predicted) >= 1
    top_pred = predicted[0]
    assert {top_pred["source_id"], top_pred["target_id"]} == {p_a.id, alias_b.id}
    assert "CLB CyberSec Lab" in top_pred["shared_bridges"]
    assert top_pred["adamic_adar_score"] > 1.0

    comm_bridges = analyze_communities_and_bridges(g)
    assert len(comm_bridges["communities"]) >= 1
    assert comm_bridges["bridge_nodes"][0]["node_id"] == rare_club.id


def test_phase4_api_playbooks_and_gexf_export(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "p4_api.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    # 1. List and register custom playbook
    pbs = client.get("/api/playbooks").json()
    assert len(pbs) >= 3
    custom_pb = {
        "id": "custom_osint_tactic",
        "title": "Chiến thuật Cá nhân hóa của Tôi",
        "description": "Truy vết theo thói quen riêng",
        "target_persona": "Custom",
        "steps": [
            {
                "step_name": "Bước 1",
                "strategy_tag": "custom_step_1",
                "description": "Tìm theo tên",
                "query_template": '"{name}"',
                "priority_bonus": 0.3,
            }
        ],
    }
    reg_resp = client.post("/api/playbooks", json=custom_pb)
    assert reg_resp.status_code == 201

    # 2. Start investigation & export GEXF
    ws_id = client.post("/api/workspaces", json={"name": "Phase 4 API"}).json()["id"]
    inv = client.post(
        f"/api/workspaces/{ws_id}/investigations",
        json={"target_name": "Phạm Hoàng Long", "playbook_id": "custom_osint_tactic"},
    )
    assert inv.status_code == 201
    bb_id = inv.json()["id"]

    step = client.post(
        f"/api/investigations/{bb_id}/step",
        json={
            "collected_texts": [
                {
                    "text": "Phạm Hoàng Long học tại Đại học FPT và sống tại Đà Nẵng.",
                    "source_url": "https://fpt.edu.vn/long",
                }
            ]
        },
    )
    assert step.status_code == 200
    assert step.json()["reward"] > 0.0

    gexf = client.get(f"/api/workspaces/{ws_id}/export/gexf")
    assert gexf.status_code == 200
    assert "<gexf" in gexf.text
