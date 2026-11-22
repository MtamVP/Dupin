"""FastAPI endpoint tests for Stalker++."""

from pathlib import Path

from fastapi.testclient import TestClient

from app import main
from app.core.graph_store import GraphStore


def test_api_lifecycle(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "api_test.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"

    ws_resp = client.post("/api/workspaces", json={"name": "Demo Case", "description": "Phase 1"})
    assert ws_resp.status_code == 201
    ws_id = ws_resp.json()["id"]

    n1 = client.post(
        f"/api/workspaces/{ws_id}/nodes",
        json={"type": "Person", "label": "Trần Minh Quân", "confidence": 0.8},
    ).json()
    n2 = client.post(
        f"/api/workspaces/{ws_id}/nodes",
        json={"type": "Topic", "label": "Cybersecurity", "confidence": 0.9},
    ).json()

    edge = client.post(
        f"/api/workspaces/{ws_id}/edges",
        json={
            "source_id": n1["id"],
            "target_id": n2["id"],
            "relation": "INTERESTED_IN",
            "confidence": 0.75,
            "evidence_quote": "Wrote CTF writeups",
            "source_url": "https://example.com/ctf",
        },
    )
    assert edge.status_code == 201

    graph = client.get(f"/api/workspaces/{ws_id}/graph")
    assert graph.status_code == 200
    assert len(graph.json()["nodes"]) == 2
    assert len(graph.json()["edges"]) == 1

    norm = client.post("/api/tools/normalize", json={"text": "ĐHBK", "is_person_name": False})
    assert norm.status_code == 200
    assert norm.json()["org_location_expanded"] == "dai hoc bach khoa"

    # Rename workspace
    renamed = client.patch(f"/api/workspaces/{ws_id}", json={"name": "Renamed Project"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed Project"

    # Delete workspace and confirm 404 afterwards
    deleted = client.delete(f"/api/workspaces/{ws_id}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get(f"/api/workspaces/{ws_id}/graph").status_code == 404
