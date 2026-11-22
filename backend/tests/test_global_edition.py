"""Tests for Global Edition: Auto Region Detection, ISO DOB, OpenAlex/ORCID, RDAP+crt.sh, GitHub Name Search, and Global Mirror Pivots."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main
from app.agents.chat_orchestrator import parse_user_prompt
from app.connectors.global_intel import (
    inspect_domain_infrastructure,
    is_custom_org_domain,
    search_github_by_name,
    search_openalex_authors,
)
from app.connectors.mirror_pivots import build_mirror_pivot_queries
from app.connectors.web_search import infer_query_region


def test_global_vs_vn_region_detection_and_iso_dob_parsing() -> None:
    assert infer_query_region("Geoffrey Hinton, University of Toronto") == "global"
    assert infer_query_region("Nguyễn Minh Anh, UEH, 15/06/2005") == "vn"

    parsed = parse_user_prompt("Alex Chen, Stanford University, 2001-05-14, California, -actor")
    assert parsed["region"] == "global"
    assert parsed["target_name"] == "Alex Chen"
    assert parsed["birth_date"] == "14/05/2001"
    assert parsed["birth_year"] == 2001
    assert "Stanford University" in parsed["organizations"]
    assert "California" in parsed["locations"]
    assert "actor" in parsed["negative_keywords"]

    # Global mirror pivots must target LinkedIn/GitHub/ORCID/.edu/PDF instead of site:edu.vn
    mqs = build_mirror_pivot_queries(parsed, {"emails": [], "student_ids": [], "doc_numbers": [], "class_codes": []})
    strategies = {q["strategy"] for q in mqs}
    assert "mirror:global_linkedin" in strategies
    assert "mirror:global_github" in strategies
    assert "mirror:global_orcid" in strategies
    assert "mirror:global_pdf" in strategies
    assert all("edu.vn" not in q["query"] for q in mqs)


@pytest.mark.asyncio
async def test_openalex_rdap_crtsh_and_github_name_connectors() -> None:
    def mock_handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if "api.openalex.org/authors" in u:
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "https://openalex.org/A500000001",
                            "orcid": "https://orcid.org/0000-0001-2345-6789",
                            "display_name": "Alex Chen",
                            "works_count": 42,
                            "cited_by_count": 1500,
                            "affiliations": [
                                {"institution": {"display_name": "Stanford University"}, "years": [2021, 2022, 2024]}
                            ],
                        }
                    ]
                },
            )
        if "rdap.org/domain/" in u:
            return httpx.Response(
                200,
                json={
                    "events": [{"eventAction": "registration", "eventDate": "2018-04-12T00:00:00Z"}],
                    "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["fn", {}, "text", "Cloudflare, Inc."]]]}],
                },
            )
        if "crt.sh/" in u:
            return httpx.Response(
                200,
                json=[{"name_value": "api.examplelab.org\ndocs.examplelab.org"}],
            )
        if "api.github.com/search/users" in u:
            return httpx.Response(200, json={"items": [{"login": "alexchen_ml"}]})
        if "api.github.com/users/alexchen_ml" in u:
            return httpx.Response(
                200,
                json={
                    "login": "alexchen_ml",
                    "name": "Alex Chen",
                    "company": "Stanford University",
                    "bio": "ML researcher",
                    "location": "California",
                    "public_repos": 18,
                    "html_url": "https://github.com/alexchen_ml",
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(mock_handler)) as client:
        oa = await search_openalex_authors("Alex Chen", ["Stanford University"], client=client)
        assert len(oa) == 1
        assert oa[0]["orcid"] == "https://orcid.org/0000-0001-2345-6789"
        assert oa[0]["org_matched"] is True

        assert is_custom_org_domain("gmail.com") is False
        assert is_custom_org_domain("examplelab.org") is True
        infra = await inspect_domain_infrastructure("examplelab.org", client=client)
        assert infra["ok"] is True
        assert infra["registrar"] == "Cloudflare, Inc."
        assert "api.examplelab.org" in infra["subdomains"]

        gh = await search_github_by_name("Alex Chen", ["Stanford University"], client=client)
        assert len(gh) == 1
        assert gh[0]["username"] == "alexchen_ml"


def test_plugins_registry_includes_global_plugins() -> None:
    client = TestClient(main.app)
    resp = client.get("/api/plugins")
    assert resp.status_code == 200
    pids = {p["id"] for p in resp.json()["plugins"]}
    assert "openalex_global_research" in pids
    assert "domain_rdap_crtsh" in pids
