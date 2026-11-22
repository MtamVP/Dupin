"""Comprehensive tests for Stalker++ v1.0 Public-Release Upgrades:
- Fernet API key encryption-at-rest
- Deep Document Reader (Excel XLSX & PDF)
- Extensible Plugin SDK & Community Plugin Discovery
- Obsidian Markdown Export (with PII Redaction) & STIX 2.1 Bundle
- Browser Companion Extension Bridge (/clip)
- Timeline Conflict Detection & Human-in-the-Loop Disambiguation Cards
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook
from pypdf import PdfWriter

from app import main
from app.agents.chat_orchestrator import build_disambiguation_cards, build_timeline_events
from app.connectors.document_reader import (
    extract_matching_rows_from_pdf,
    extract_matching_rows_from_xlsx,
)
from app.core.crypto import ENC_PREFIX, SecretBox
from app.core.graph_store import GraphStore
from app.core.key_pool import APIKeyCreate, IntegrationStore
from app.core.schemas import FeatureCategory, FeatureClaim, NodeCreate, WorkspaceCreate
from app.plugins.registry import PluginRegistry


def test_fernet_encryption_at_rest_and_legacy_plaintext_compat(tmp_path: Path) -> None:
    db_path = tmp_path / "vault_test.db"
    pool = IntegrationStore(db_path)

    added = pool.add_key(
        APIKeyCreate(name="Encrypted Gemini", provider="gemini", api_key="TEST_VAULT_SECRET_9999")
    )
    assert added["encrypted"] is True
    assert added["masked_key"] == "TEST...9999"

    # Raw SQLite column MUST be ciphertext, never plaintext
    with sqlite3.connect(db_path) as conn:
        raw_stored = conn.execute("SELECT api_key FROM api_keys WHERE id = ?", (added["id"],)).fetchone()[0]
    assert raw_stored.startswith(ENC_PREFIX)
    assert "VAULT_SECRET" not in raw_stored

    # Acquiring key decrypts transparently
    acquired = pool.acquire_key("gemini")
    assert acquired is not None
    assert acquired["api_key"] == "TEST_VAULT_SECRET_9999"

    # Legacy plaintext compatibility check
    box = SecretBox(db_path)
    assert box.decrypt("legacy_plain_key_1234") == "legacy_plain_key_1234"


def test_deep_document_reader_xlsx_and_scanned_pdf_detection() -> None:
    # 1. Build a real in-memory Excel workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "DanhSach2025"
    ws.append(["STT", "MSSV", "Họ và tên", "Ngày sinh", "Lớp", "GPA"])
    ws.append([1, "20520001", "Trần Văn B", "01/01/2005", "KHMT2025.1", "8.50"])
    ws.append([2, "20529999", "Trần Hoàng Nam", "15/05/2005", "KHMT2025.4", "9.46"])
    buf = io.BytesIO()
    wb.save(buf)

    res_xlsx = extract_matching_rows_from_xlsx(buf.getvalue(), ["Trần Hoàng Nam", "20529999"])
    assert res_xlsx["doc_type"] == "xlsx"
    assert len(res_xlsx["excerpts"]) == 1
    assert "KHMT2025.4" in res_xlsx["excerpts"][0]["line"]
    assert "9.46" in res_xlsx["excerpts"][0]["line"]

    # 2. Blank single-page PDF -> safely detected as scanned/no-text PDF
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    pdf_buf = io.BytesIO()
    writer.write(pdf_buf)
    res_pdf = extract_matching_rows_from_pdf(pdf_buf.getvalue(), ["Nguyễn Minh Anh"])
    assert res_pdf["doc_type"] == "pdf"
    assert res_pdf["total_pages"] == 1
    assert res_pdf["scanned_pages_detected"] is True
    assert res_pdf["excerpts"] == []


def test_plugin_sdk_discovery_exports_redaction_and_browser_clip(tmp_path: Path, monkeypatch) -> None:
    test_store = GraphStore(tmp_path / "v1_api.db")
    monkeypatch.setattr(main, "store", test_store)

    # Create a community plugin on disk to test dynamic discovery
    ext_dir = tmp_path / "ext_plugins"
    ext_dir.mkdir()
    (ext_dir / "sample_community.py").write_text(
        """
from app.plugins.base import ConnectorPlugin, PluginManifest
class SampleExt(ConnectorPlugin):
    manifest = PluginManifest(
        id="community_sample",
        name="Community Sample Plugin",
        category="enrichment",
        description="Test external plugin",
    )
    async def health(self, context):
        return {"ready": True, "detail": "ok"}
def register_plugin():
    return SampleExt()
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "plugin_registry", PluginRegistry(extra_plugin_dir=ext_dir))

    client = TestClient(main.app)

    # 1. Plugins API lists built-ins + discovered community plugin
    p_resp = client.get("/api/plugins")
    assert p_resp.status_code == 200
    pids = {p["id"] for p in p_resp.json()["plugins"]}
    assert "parallel_metasearch" in pids
    assert "deep_document_reader" in pids
    assert "community_sample" in pids

    # 2. Create workspace & clip public text via Browser Companion endpoint
    ws = test_store.create_workspace(WorkspaceCreate(name="V1 Export Case"))
    test_store.upsert_node(
        ws.id,
        NodeCreate(
            type="Person",
            label="Nguyễn Văn Test",
            claims=[
                FeatureClaim(
                    category=FeatureCategory.TECHNICAL_ARTIFACT,
                    key="email",
                    value="demo.31251029999@st.example.edu.vn",
                    confidence=0.95,
                    source_url="https://example.edu.vn",
                    evidence_quote="Email demo.31251029999@st.example.edu.vn",
                )
            ],
        ),
    )

    clip_resp = client.post(
        f"/api/workspaces/{ws.id}/clip",
        json={
            "title": "Public Profile Snapshot",
            "url": "https://example.edu.vn/profile/1",
            "selected_text": "Nguyễn Văn Test sinh ngày 15/06/2005, email demo.31251029999@st.example.edu.vn",
            "field_key": "Browser Clip",
            "pin_to_dossier": True,
        },
    )
    assert clip_resp.status_code == 201
    assert clip_resp.json()["clipped"] is True

    # 3. Obsidian export with PII redaction masks email, DOB, and 11-digit ID
    obs_raw = client.get(f"/api/workspaces/{ws.id}/export/obsidian?redact=false").text
    assert "demo.31251029999@st.example.edu.vn" in obs_raw
    assert "[[Nguyễn Văn Test]]" in obs_raw

    obs_redacted = client.get(f"/api/workspaces/{ws.id}/export/obsidian?redact=true").text
    assert "demo.31251029999@st.example.edu.vn" not in obs_redacted
    assert "[REDACTED_EMAIL]" in obs_redacted
    assert "[REDACTED_DOB]" in obs_redacted

    # 4. STIX 2.1 Bundle export
    stix = client.get(f"/api/workspaces/{ws.id}/export/stix?redact=true").json()
    assert stix["type"] == "bundle"
    assert stix["spec_version"] == "2.1"
    assert stix["x_redacted"] is True
    assert any(obj["type"] == "identity" for obj in stix["objects"])


def test_timeline_conflict_and_disambiguation_cards() -> None:
    parsed = {
        "target_name": "Nguyễn Minh Anh",
        "birth_date": "15/06/2005",
        "birth_year": 2005,
        "organizations": ["UEH", "THPT Demo Mẫu"],
    }
    sources = [
        {
            "title": "Nguyễn Minh Anh - Graduate Engineering Trainee | ExampleCorp",
            "url": "https://vn.linkedin.com/in/nguyen-minh-anh-demo",
            "snippet": "Kinh nghiệm: ExampleCorp · Giáo dục: DemoTech 2015",
            "match_score": 1,
        },
        {
            "title": "Ket Qua Xet Chuan Dau Ra TA Khoa 51 2025",
            "url": "https://www.scribd.com/document/999999999/Ket-qua-UEH-Demo",
            "snippet": "NGUYỄN MINH ANH 15/06/2005 UEH IELTS 7.0 2025",
            "match_score": 8,
        },
    ]
    timeline = build_timeline_events(parsed, sources, {"student_ids": []})
    assert any(ev["year"] == 2005 and ev["status"] == "VERIFIED" for ev in timeline)
    assert any(ev["year"] == 2015 and ev["status"] == "CONFLICT" for ev in timeline)

    cards = build_disambiguation_cards(parsed, sources)
    assert len(cards) == 1
    assert "ExampleCorp" in cards[0]["suggested_negative"]
