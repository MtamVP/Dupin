"""Comprehensive Tests for the 5-Layer Concentric OSINT Pipeline & Sherlock/Maigret v2 Engine."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.connectors.username_recon import (
    PUBLIC_SITE_MANIFEST,
    SiteHealthTracker,
    _is_soft_404_redirect,
    scan_username_profiles,
    validate_sites_manifest,
)
from app.core.graph_store import GraphStore
from app.core.schemas import WorkspaceCreate
from app.main import app
from app.pipeline import (
    PIPELINE_ARCHITECTURE_SPEC,
    OuterGatekeeper,
    execute_concentric_pipeline,
    parse_user_prompt,
)
from app.pipeline.models import InvestigationContext


def test_maigret_v2_manifest_self_check_and_55_platforms() -> None:
    """Validate every single entry in sites_manifest.json (zero invalid regex/modes/duplicates)."""
    report = validate_sites_manifest()
    assert report["valid"] is True, f"Manifest errors: {report['errors']}"
    assert report["total_sites"] >= 55
    assert report["verified_json_api_sites"] >= 16
    assert len(PUBLIC_SITE_MANIFEST) == report["total_sites"]


def test_sherlock_response_url_soft_404_and_circuit_breaker() -> None:
    """Verify Sherlock redirect-to-login/404/root Soft-404 detector & Maigret per-site circuit breaker."""
    assert _is_soft_404_redirect("https://example.com/u/alice", "https://example.com/login") is True
    assert _is_soft_404_redirect("https://example.com/u/alice", "https://example.com/404") is True
    assert _is_soft_404_redirect("https://example.com/u/alice", "https://example.com/") is True
    assert _is_soft_404_redirect("https://example.com/u/alice", "https://example.com/u/alice") is False

    cb = SiteHealthTracker(failure_threshold=2, cooldown_seconds=60.0)
    assert cb.is_open("DemoSite") is False
    cb.record_failure("DemoSite")
    assert cb.is_open("DemoSite") is False
    cb.record_failure("DemoSite")
    assert cb.is_open("DemoSite") is True
    cb.record_success("DemoSite")
    assert cb.is_open("DemoSite") is False
    cb.record_failure("RateLimitedSite", hard_rate_limit=True)
    assert cb.is_open("RateLimitedSite") is True


@pytest.mark.asyncio
async def test_maigret_v2_recursive_depth2_and_new_json_engines() -> None:
    """Test recursive depth-2 handle pivoting + Bluesky/Gitea/response_url Soft-404 with MockTransport."""

    def handler(req: httpx.Request) -> httpx.Response:
        url = str(req.url)
        # Depth-1 GitHub profile reveals secondary handle @alice-alt in bio (valid hyphen handle)
        if "api.github.com/users/alice-dev" in url:
            return httpx.Response(
                200,
                json={
                    "login": "alice-dev",
                    "name": "Alice Nguyen",
                    "bio": "Security researcher, alt handle @alice-alt",
                    "avatar_url": "https://avatars.example/alice.png",
                },
            )
        # Depth-2 Bluesky verified JSON API hit on @alice-alt
        if "public.api.bsky.app" in url and "alice-alt" in url:
            return httpx.Response(
                200,
                json={
                    "handle": "alice-alt.bsky.social",
                    "displayName": "Alice Alt",
                    "description": "InfoSec & OSINT",
                    "followersCount": 420,
                },
            )
        # Depth-2 Codeberg (GiteaApi engine) hit on @alice-alt
        if "codeberg.org/api/v1/users/alice-alt" in url:
            return httpx.Response(
                200,
                json={
                    "login": "alice-alt",
                    "full_name": "Alice Nguyen",
                    "description": "Open source maintainer",
                    "website": "https://alice.example.org",
                },
            )
        # Simulate real Sherlock response_url Soft-404: 302 redirect -> HTTP 200 on /login
        if "medium.com/@alice-dev" in url:
            return httpx.Response(302, headers={"location": "https://medium.com/login"})
        if "medium.com/login" in url:
            return httpx.Response(
                200,
                text="<html><title>Login</title><body>alice-dev og:title</body></html>",
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        res = await scan_username_profiles(
            "alice-dev",
            target_hints=["Alice Nguyen"],
            sites=["GitHub", "Bluesky", "Codeberg", "Medium"],
            recursive_depth=2,
            client=client,
        )

    found_sites = {(p["site"], p["username"], p["hop"]) for p in res["found_profiles"]}
    assert ("GitHub", "alice-dev", 1) in found_sites
    assert ("Bluesky", "alice-alt", 2) in found_sites
    assert ("Codeberg", "alice-alt", 2) in found_sites
    # Medium redirected to /login -> MUST be rejected by Sherlock response_url Soft-404 check
    assert all(p["site"] != "Medium" for p in res["found_profiles"])
    assert len(res["recursion_tree"]) == 2
    assert res["recursion_tree"][1]["handle"] == "alice-alt"


def test_layer2_outer_gatekeeper_rejection_telemetry() -> None:
    """Layer 2 OuterGatekeeper must isolate & record exact rejection reasons before Layer 4."""
    parsed = parse_user_prompt("Tran Minh Anh, THPT Chu Van An, 15/05/2007, UEH, -Hanoi")
    ctx = InvestigationContext(
        workspace_id="ws-demo",
        raw_prompt=parsed["raw_prompt"],
        parsed=parsed,
        anchors={"student_ids": [{"student_id": "31251029999", "institution": "UEH", "cohort": "K51"}], "emails": []},
        region="vn",
        target_name="Tran Minh Anh",
    )
    gate = OuterGatekeeper(ctx)

    # 1. Junk URL rejected
    assert gate.evaluate_candidate("Auto Part", "https://partsyx.com/item/31251029999", "31251029999") is False
    # 2. Negative constraint veto
    assert gate.evaluate_candidate("Tran Minh Anh - Hanoi", "https://news.vn/1", "Tran Minh Anh Hanoi UEH") is False
    # 3. Temporal grade-age veto (Grade 11 in 2018 for 2007 target)
    assert (
        gate.evaluate_candidate(
            "Danh sach tinh nguyen 2018",
            "https://news.vn/tinh-nguyen-2018",
            "Tran Minh Anh, Lop 11, THPT Chu Van An",
        )
        is False
    )
    # 4. Unrelated target rejected
    assert gate.evaluate_candidate("Random page", "https://example.vn/other", "Le Van B UEH") is False
    # 5. Valid high-confidence hit accepted
    assert (
        gate.evaluate_candidate(
            "Danh sach UEH 2025",
            "https://ueh.edu.vn/danh-sach-k51.pdf",
            "Tran Minh Anh 15/05/2007 31251029999 UEH",
        )
        is True
    )

    stats = gate.telemetry.to_dict()
    assert stats["accepted"] == 1
    assert stats["rejected"] == 4
    assert stats["rejected_by_reason"]["junk_url"] == 1
    assert stats["rejected_by_reason"]["negative_veto"] == 1
    assert stats["rejected_by_reason"]["temporal_grade_age_veto"] == 1
    assert stats["rejected_by_reason"]["no_target_match"] == 1


@pytest.mark.asyncio
async def test_concentric_5_layer_pipeline_end_to_end_and_architecture_api(tmp_path) -> None:
    """Verify full 5-Layer Concentric Pipeline execution telemetry and GET /api/pipeline/architecture."""
    db_path = str(tmp_path / "concentric.db")
    store = GraphStore(db_path)
    ws = store.create_workspace(WorkspaceCreate(name="Concentric Test"))

    res = await execute_concentric_pipeline(
        store=store,
        workspace_id=ws.id,
        prompt="Tran Minh Anh, THPT Chu Van An, 15/05/2007, UEH, 31251029999",
        live_search=False,
        deep_mode=False,
    )
    assert res["pipeline_telemetry"]["architecture"] == "5-layer-concentric-osint"
    assert "L1_intake_ms" in res["pipeline_telemetry"]["layer_timings_ms"]
    assert "L4b_deep_core_ms" in res["pipeline_telemetry"]["layer_timings_ms"]
    assert "L5_synthesis_ms" in res["pipeline_telemetry"]["layer_timings_ms"]
    assert "31251029999" not in res["parsed_clues"]["aliases"]

    # Check REST API architecture inspection endpoint
    with TestClient(app) as tc:
        r = tc.get("/api/pipeline/architecture")
        assert r.status_code == 200
        body = r.json()
        assert body["architecture"] == "5-layer-concentric-osint"
        assert len(body["layers"]) == len(PIPELINE_ARCHITECTURE_SPEC) == 5
        assert body["username_engine"]["manifest"]["valid"] is True
        assert body["username_engine"]["manifest"]["total_sites"] >= 55


def test_natural_language_relational_and_comma_free_prompts() -> None:
    """Layer 1 must parse comma-free Vietnamese & English relational and biographical sentences cleanly."""
    from app.pipeline.layer2_gatekeeper import score_source_relevance
    from app.pipeline.layer3_collectors import build_intersection_queries

    # 1. Vietnamese natural relational query (zero commas!)
    p_rel = parse_user_prompt("Trần Nguyễn Minh Phúc con của ông Trần Quang Anh Bảo")
    assert p_rel["target_name"] == "Trần Nguyễn Minh Phúc"
    assert p_rel["related_people"] == [{"name": "Trần Quang Anh Bảo", "relation": "CHILD_OF"}]

    qs = build_intersection_queries(p_rel)
    q_strings = [q["query"] for q in qs]
    assert '"Trần Nguyễn Minh Phúc" "Trần Quang Anh Bảo"' in q_strings
    assert '"Trần Nguyễn Minh Phúc"' in q_strings

    # Layer 2 boosts co-occurrence of both target + related person
    ok_both, score_both, clues = score_source_relevance(
        "Công bố thông tin cổ đông: Trần Nguyễn Minh Phúc (con ông Trần Quang Anh Bảo - Chủ tịch HĐQT)",
        "https://cafef.vn/bao-cao-quan-tri-demo",
        p_rel,
    )
    assert ok_both is True
    assert score_both >= 5
    assert any("Trần Quang Anh Bảo" in c for c in clues)

    # 2. Comma-free Vietnamese biographical sentence
    p_vn_nl = parse_user_prompt("tìm Nguyễn Văn An sinh ngày 15/05/2007 học tại UEH ở TPHCM")
    assert p_vn_nl["target_name"] == "Nguyễn Văn An"
    assert p_vn_nl["birth_date"] == "15/05/2007"
    assert "UEH" in p_vn_nl["organizations"]
    assert "TPHCM" in p_vn_nl["locations"]

    # 3. Comma-free English relational + bio sentence
    p_en_nl = parse_user_prompt("John Doe son of Robert Doe works at Stanford University born 1998")
    assert p_en_nl["target_name"] == "John Doe"
    assert p_en_nl["related_people"] == [{"name": "Robert Doe", "relation": "CHILD_OF"}]
    assert "Stanford University" in p_en_nl["organizations"]
    assert p_en_nl["birth_year"] == 1998
