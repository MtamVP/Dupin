"""Unit tests for Scribd & Studocu Public Deep-Reader and Additive Mirror Pivots."""

from __future__ import annotations

import httpx
import pytest

from app.connectors.doc_mirror_reader import (
    extract_doc_mirror_public_html,
    fetch_and_inspect_doc_mirror,
    is_doc_mirror_url,
    parse_doc_mirror_url_metadata,
)
from app.connectors.mirror_pivots import build_mirror_pivot_queries
from app.pipeline.layer1_intake import parse_user_prompt


def test_doc_mirror_url_detection_and_slug_metadata() -> None:
    studocu_url = (
        "https://www.studocu.vn/vn/document/"
        "truong-dai-hoc-kinh-te-thanh-pho-ho-chi-minh/nguyen-ly-ke-toan/"
        "tran-minh-mau-31231024455/35767732"
    )
    scribd_url = "https://www.scribd.com/document/653982513/danh-sach-hoc-vien-2024"

    assert is_doc_mirror_url(studocu_url) is True
    assert is_doc_mirror_url(scribd_url) is True
    assert is_doc_mirror_url("https://example.com/blog/post") is False

    st_meta = parse_doc_mirror_url_metadata(studocu_url)
    assert st_meta["platform"] == "studocu"
    assert st_meta["doc_id"] == "35767732"
    assert "kinh te" in st_meta["university_slug"].lower()
    assert "ke toan" in st_meta["course_slug"].lower()
    assert "31231024455" in st_meta["title_slug"]

    sc_meta = parse_doc_mirror_url_metadata(scribd_url)
    assert sc_meta["platform"] == "scribd"
    assert sc_meta["doc_id"] == "653982513"
    assert "danh sach hoc vien" in sc_meta["title_slug"].lower()


def test_extract_doc_mirror_public_html_jsonld_preview_and_phone_match() -> None:
    sample_html = """
    <html>
      <head>
        <title>Danh sách học viên UEH - Scribd</title>
        <meta property="og:title" content="Danh sách học viên Khóa 48 UEH" />
        <meta property="og:description" content="Quyết định 2623/QĐ-ĐHKT kèm danh sách sinh viên." />
        <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "DigitalDocument",
            "name": "Danh sách học viên Khóa 48 UEH",
            "author": {"@type": "Person", "name": "Phong Dao Tao"},
            "numberOfPages": 18,
            "isPartOf": {"@type": "Course", "name": "Ke Toan Kiem Toan", "provider": {"@type": "CollegeOrUniversity", "name": "UEH"}}
          }
        </script>
      </head>
      <body>
        <div class="text_layer">
          <p>STT 12 | Trần Minh Mẫu | MSSV 31231024455 | SĐT: 0901.234.567 | Lớp KT001</p>
          <p>Sign in to download this document</p>
        </div>
      </body>
    </html>
    """
    res = extract_doc_mirror_public_html(
        sample_html,
        "https://www.scribd.com/document/653982513/danh-sach-hoc-vien-ueh",
        target_terms=["Trần Minh Mẫu", "0901234567"],
    )
    assert res["ok"] is True
    assert res["doc_type"] == "scribd_mirror"
    assert res["metadata"]["author"] == "Phong Dao Tao"
    assert res["metadata"]["page_count"] == "18"
    assert res["metadata"]["university"] == "UEH"
    assert len(res["excerpts"]) >= 1
    assert any("Trần Minh Mẫu" in ex["line"] for ex in res["excerpts"])
    assert any("0901234567" in ex["matched_terms"] for ex in res["excerpts"])
    assert "2623/QĐ-ĐHKT" in res["discovered_anchors"]["doc_numbers"]


@pytest.mark.asyncio
async def test_fetch_doc_mirror_slug_fallback_and_additive_pivots() -> None:
    studocu_url = (
        "https://www.studocu.vn/vn/document/"
        "truong-dai-hoc-kinh-te-tp-hcm/tai-chinh-doanh-nghiep/"
        "tran-minh-mau-31231024455/99887766"
    )

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Forbidden")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
        res = await fetch_and_inspect_doc_mirror(
            studocu_url,
            target_terms=["Trần Minh Mẫu"],
            client=client,
        )
    assert res["ok"] is True
    assert res["fetch_source"] == "url_slug_only"
    assert res["metadata"]["doc_id"] == "99887766"
    assert "kinh te" in res["metadata"]["university"].lower()

    # Verify additive mirror pivot queries include Scribd/Studocu operator-free & phone queries
    parsed = parse_user_prompt("Trần Minh Mẫu, UEH, 0901234567")
    parsed["phone_candidates"] = ["0901234567"]
    pivots = build_mirror_pivot_queries(parsed, {"student_ids": [], "emails": [], "doc_numbers": [], "class_codes": []})
    strategies = {p["strategy"] for p in pivots}
    assert "mirror:studocu_name" in strategies
    assert "mirror:studocu_vn_name" in strategies
    assert "mirror:scribd_org_name" in strategies
    assert "mirror:scribd_phone" in strategies
    assert "mirror:studocu_phone" in strategies
