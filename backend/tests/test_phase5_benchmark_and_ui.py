"""Unit & integration tests for Phase 5: Interactive Cytoscape.js UI & Thesis Quantitative Benchmark."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.core.graph_store import GraphStore
from app.evaluation.benchmark_thesis import run_thesis_benchmark


@pytest.mark.asyncio
async def test_thesis_benchmark_outperforms_sherlock_and_maigret() -> None:
    report = await run_thesis_benchmark()
    comp = {row["method"].split()[0]: row for row in report["comparison"]}

    sherlock = comp["Sherlock"]
    maigret = comp["Maigret"]
    stalker = comp["Stalker++"]

    # Stalker++ achieves higher F1-score, lower False Positives than Maigret, and higher Recall than Sherlock
    assert stalker["f1_score"] > sherlock["f1_score"]
    assert stalker["f1_score"] > maigret["f1_score"]
    assert stalker["false_positives"] == 0
    assert stalker["recall"] == 1.0
    assert stalker["hop_efficiency_tp_per_query"] > sherlock["hop_efficiency_tp_per_query"]


def test_phase5_workbench_ui_and_benchmark_endpoint(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "p5_api.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    ui_resp = client.get("/")
    assert ui_resp.status_code == 200
    assert "Hồ sơ Tổng hợp" in ui_resp.text
    assert "gemini-4-hydrogen" in ui_resp.text
    assert "Dupin" in ui_resp.text

    bench_resp = client.get("/api/evaluation/benchmark")
    assert bench_resp.status_code == 200
    assert len(bench_resp.json()["comparison"]) == 3
