"""Unit & integration tests for Stylometry, Handle Anatomy, ReaderAgent, EntityResolutionAgent, and CriticVerifierAgent."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main
from app.agents.critic import CriticVerifierAgent, verify_quote_grounding
from app.agents.reader import ExtractedTriple, ExtractionResult, ReaderAgent
from app.agents.resolver import EntityResolutionAgent
from app.core.fingerprints import (
    extract_handle_fingerprint,
    gravatar_md5,
    handle_pattern_similarity,
    stylometry_similarity,
)
from app.core.graph_store import GraphStore
from app.core.schemas import FeatureCategory, FeatureClaim, NodeCreate, WorkspaceCreate


def test_handle_anatomy_and_stylometry_fingerprinting() -> None:
    fp = extract_handle_fingerprint("minhtuan_dev02")
    assert 2002 in fp["inferred_years"]
    assert "dev" in fp["affixes"]
    assert fp["core_alpha"] == "minhtuan"

    # Two handles from the same person with different formats ('minhtuan_dev02' vs 'tuanm_2002_dev')
    sim_same = handle_pattern_similarity("minhtuan_dev02", "tuanm_2002_dev")
    sim_diff = handle_pattern_similarity("minhtuan_dev02", "hoanglong95")
    assert sim_same >= 0.75
    assert sim_diff < 0.25

    text_1 = (
        "Mình đang làm backend với Python và Rust! Hệ thống cloud api chạy rất mượt... "
        "Anh em nào thích ctf và osint thì lập team code chung nhé!"
    )
    text_2 = (
        "Dạo này mình tập trung code backend bằng Python cùng Rust! Dự án osint với ctf "
        "trên cloud api khá thú vị... Rất vui được giao lưu cùng anh em!"
    )
    text_unrelated = (
        "Công thức nấu phở bò truyền thống cần ninh xương kỹ trong nhiều giờ liền để nước dùng "
        "có vị ngọt thanh tự nhiên của thảo quả và quế hồi."
    )
    s_same = stylometry_similarity(text_1, text_2)["overall_similarity"]
    s_diff = stylometry_similarity(text_1, text_unrelated)["overall_similarity"]
    assert s_same > s_diff
    assert s_same > 0.70
    assert gravatar_md5("An.Nguyen@Example.com ") == gravatar_md5("an.nguyen@example.com")


@pytest.mark.asyncio
async def test_reader_and_critic_anti_hallucination() -> None:
    reader = ReaderAgent()
    critic = CriticVerifierAgent()

    bio_text = (
        "Nguyễn Văn An (sinh năm 2002) quê ở Đà Nẵng. "
        "An từng học tại Trường ĐH Bách Khoa và hiện làm việc tại VNG Corporation. "
        "An chưa từng sống tại Hà Nội. Email: an.nguyen02@vng.com.vn"
    )
    extraction = await reader.extract(bio_text, subject_label="Nguyễn Văn An", source_url="https://example.com/bio")

    relations = {t.relation: t.object_label for t in extraction.triples}
    assert "STUDIED_AT" in relations
    assert "WORKS_AT" in relations
    assert "LOCATED_IN" in relations
    assert any(c.polarity == "NEGATIVE" for c in extraction.claims)
    assert any(c.key == "gravatar_md5" for c in extraction.claims)

    # Inject a hallucinated triple whose evidence_quote does NOT exist in bio_text
    extraction.triples.append(
        ExtractedTriple(
            subject_label="Nguyễn Văn An",
            relation="WORKS_AT",
            object_label="Fake Hallucinated Corp",
            object_type="Org",
            confidence=0.95,
            evidence_quote="This quote was completely invented by an LLM hallucination.",
            source_url="https://example.com/bio",
        )
    )

    _, audited = critic.audit_extraction(extraction, bio_text)
    status_by_obj = {t.object_label: status for t, status in audited}
    assert status_by_obj["Fake Hallucinated Corp"] == "REJECTED"
    assert verify_quote_grounding("quê ở Đà Nẵng", bio_text) == 1.0


def test_entity_resolution_8d_and_negative_veto(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "er_test.db")
    ws = store.create_workspace(WorkspaceCreate(name="ER Test"))
    resolver = EntityResolutionAgent()

    node_a = store.upsert_node(
        ws.id,
        NodeCreate(
            type="Person",
            label="Nguyễn Văn An",
            claims=[
                FeatureClaim(
                    category=FeatureCategory.EDUCATION_CAREER,
                    key="school",
                    value="HCMUT",
                    source_url="https://a.com",
                ),
                FeatureClaim(
                    category=FeatureCategory.SPATIOTEMPORAL,
                    key="associated_year",
                    value=2002,
                    source_url="https://a.com",
                ),
                FeatureClaim(
                    category=FeatureCategory.NEGATIVE_CONSTRAINT,
                    key="location",
                    value="Ha Noi",
                    polarity="NEGATIVE",
                    source_url="https://a.com",
                ),
            ],
        ),
    )

    # Node B uses full school name ("Đại học Bách Khoa TP.HCM") and unaccented name ("Nguyen Van An")
    node_b_match = store.upsert_node(
        ws.id,
        NodeCreate(
            type="Alias",
            label="An Nguyen",
            claims=[
                FeatureClaim(
                    category=FeatureCategory.EDUCATION_CAREER,
                    key="school",
                    value="Đại học Bách Khoa Thành phố Hồ Chí Minh",
                    source_url="https://b.com",
                ),
                FeatureClaim(
                    category=FeatureCategory.SPATIOTEMPORAL,
                    key="associated_year",
                    value=2002,
                    source_url="https://b.com",
                ),
            ],
        ),
    )

    # Node C violates Node A's NEGATIVE constraint (lives in Ha Noi, born 1995)
    node_c_conflict = store.upsert_node(
        ws.id,
        NodeCreate(
            type="Alias",
            label="Nguyen Van An HN",
            claims=[
                FeatureClaim(
                    category=FeatureCategory.SPATIOTEMPORAL,
                    key="location",
                    value="Hà Nội",
                    source_url="https://c.com",
                ),
                FeatureClaim(
                    category=FeatureCategory.SPATIOTEMPORAL,
                    key="associated_year",
                    value=1995,
                    source_url="https://c.com",
                ),
            ],
        ),
    )

    rep_match = resolver.compare_nodes(node_a, node_b_match)
    rep_conflict = resolver.compare_nodes(node_a, node_c_conflict)

    assert rep_match.overall_probability > 0.65
    assert rep_conflict.overall_probability < 0.25
    assert rep_conflict.decision == "DIFFERENT_ENTITY"
    assert any("Negative constraint violated" in r for r in rep_conflict.conflicting_reasons)


def test_phase3_api_analyze_and_timeline_anomalies(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "p3_api.db")
    monkeypatch.setattr(main, "store", test_store)
    client = TestClient(main.app)

    ws_id = client.post("/api/workspaces", json={"name": "Phase 3"}).json()["id"]

    # Text with a deliberate timeline anomaly (born 2005, but worked at Corp X in 2015 at age 10)
    # and a timeline gap (2015 -> 2024 = 9-year gap)
    resp = client.post(
        f"/api/workspaces/{ws_id}/agents/analyze-text",
        json={
            "subject_label": "Lê Minh Khôi",
            "text": (
                "Lê Minh Khôi (sinh năm 2005) làm việc tại FPT Software năm 2015. "
                "Sau đó học tại Đại học Bách Khoa năm 2024."
            ),
            "source_url": "https://example.com/khoi",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["committed_edges"]) >= 2
    audit = data["timeline_audit"]
    assert len(audit["anomalies"]) >= 1
    assert len(audit["unexplored_gaps"]) >= 1
