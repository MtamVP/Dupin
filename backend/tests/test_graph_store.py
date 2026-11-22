"""Unit tests for SQLite + FTS5 + NetworkX GraphStore."""

from pathlib import Path

from app.core.graph_store import GraphStore
from app.core.schemas import (
    EdgeCreate,
    EdgeStatusUpdate,
    FeatureCategory,
    FeatureClaim,
    NodeCreate,
    WorkspaceCreate,
)


def test_workspace_node_merge_fts_search_and_pivots(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "test.db")
    ws = store.create_workspace(WorkspaceCreate(name="Thesis Self-Audit"))

    # Upsert same person twice with positive supporting claims -> Bayesian confidence rises
    p1 = store.upsert_node(
        ws.id,
        NodeCreate(
            type="Person",
            label="Nguyễn Văn An",
            confidence=0.6,
            claims=[
                FeatureClaim(
                    category=FeatureCategory.SPATIOTEMPORAL,
                    key="birth_year_range",
                    value=[2002, 2003],
                    confidence=0.8,
                    source_url="https://site1.com/a",
                    evidence_quote="Born around 2002-2003 in Da Nang",
                )
            ],
        ),
    )
    p1_merged = store.upsert_node(
        ws.id,
        NodeCreate(
            type="Person",
            label="nguyen van an",
            confidence=0.6,
            claims=[
                FeatureClaim(
                    category=FeatureCategory.EDUCATION_CAREER,
                    key="club",
                    value="CLB An Toan Thong Tin",
                    confidence=0.85,
                    source_url="https://site2.org/b",
                    evidence_quote="Leader of CLB An Toan Thong Tin",
                )
            ],
            dynamic_traits={"github_active_utc_offset": "+07:00"},
        ),
    )

    assert p1.id == p1_merged.id
    assert len(p1_merged.claims) == 2
    assert p1_merged.confidence > p1.confidence
    assert p1_merged.dynamic_traits["github_active_utc_offset"] == "+07:00"

    school = store.upsert_node(ws.id, NodeCreate(type="Org", label="HCMUT", confidence=0.5))
    alias = store.upsert_node(ws.id, NodeCreate(type="Alias", label="nva_dev03", confidence=0.85))

    # FTS5 search should find p1 by claim text ("An Toan Thong Tin") even though it's not in the label
    fts_results = store.search_candidates(ws.id, "An Toan Thong Tin")
    assert any(r["node"].id == p1.id for r in fts_results)

    # Pivot recommendation should prioritize high-specificity frontier nodes
    pivots = store.suggest_pivots(ws.id, top_k=3)
    assert len(pivots) == 3
    assert pivots[0]["information_gain_score"] >= pivots[1]["information_gain_score"]

    e1 = store.add_edge(
        ws.id,
        EdgeCreate(
            source_id=p1.id,
            target_id=school.id,
            relation="STUDIED_AT",
            confidence=0.85,
            status="HYPOTHESIS",
            evidence_quote="Student at HCMUT",
            source_url="https://example.com/c",
        ),
    )
    store.add_edge(
        ws.id,
        EdgeCreate(
            source_id=p1.id,
            target_id=alias.id,
            relation="OWNS_ACCOUNT",
            confidence=0.92,
            status="VERIFIED",
            evidence_quote="Bio links to nva_dev03",
            source_url="https://github.com/nva_dev03",
        ),
    )

    paths = store.find_paths(ws.id, alias.id, school.id)
    assert paths == [[alias.id, p1.id, school.id]]

    updated = store.update_edge_status(e1.id, EdgeStatusUpdate(status="REJECTED", confidence=0.1))
    assert updated is not None and updated.status == "REJECTED"
    assert store.find_paths(ws.id, alias.id, school.id) == []


def test_dossier_item_deduplication_by_url_and_key_value(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "dossier_dedup.db")
    ws = store.create_workspace(WorkspaceCreate(name="Dossier Dedup"))

    first = store.add_dossier_item(
        ws.id,
        field_key="Nguồn đã xác nhận",
        field_value="Danh sách sinh viên",
        source_url="https://ctsv.uit.edu.vn/file.pdf/",
    )
    assert first["already_exists"] is False

    # Same URL (case/trailing-slash normalized) must not duplicate
    dup_url = store.add_dossier_item(
        ws.id,
        field_key="Nguồn khác",
        field_value="Giá trị khác",
        source_url="https://CTSV.UIT.EDU.VN/file.pdf",
    )
    assert dup_url["already_exists"] is True
    assert dup_url["id"] == first["id"]

    # Manual entry with same key + value must not duplicate
    manual = store.add_dossier_item(ws.id, field_key="MSSV", field_value="20529999")
    assert manual["already_exists"] is False
    dup_kv = store.add_dossier_item(ws.id, field_key="mssv", field_value="20529999")
    assert dup_kv["already_exists"] is True
    assert dup_kv["id"] == manual["id"]

    assert len(store.list_dossier_items(ws.id)) == 2
