"""Unit tests for Multimodal Layer-1 Intake: EXIF/GPS, Visual OSINT (IMINT), vCard/CSV/XLSX File Extraction,
and Attachment-Only Investigation Hydration.
"""

from __future__ import annotations

import base64
import io
import struct
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.connectors.multimodal_intake import (
    build_imint_vision_prompt,
    extract_image_exif_metadata,
    extract_uploaded_file_text,
)
from app.core.graph_store import GraphStore
from app.main import app
from app.pipeline.layer1_intake import run_layer1_intake


def _build_synthetic_jpeg_with_exif() -> str:
    """Construct a minimal valid JPEG APP1 EXIF binary with Make, Model, and GPS coordinates."""
    # Little-endian TIFF ('II', 42, offset 8)
    # Root IFD at offset 8 with 3 entries: Make (0x010F), Model (0x0110), GPS IFD Pointer (0x8825)
    make_bytes = b"Canon\x00"
    model_bytes = b"EOS R5\x00\x00"
    # Root IFD: 2 + 3*12 + 4 = 42 bytes -> ends at offset 50
    # Make string at offset 50 (len 6), Model string at offset 56 (len 8), GPS IFD at offset 64
    root_ifd = struct.pack("<H", 3)
    root_ifd += struct.pack("<HHII", 0x010F, 2, len(make_bytes), 50)
    root_ifd += struct.pack("<HHII", 0x0110, 2, len(model_bytes), 56)
    root_ifd += struct.pack("<HHII", 0x8825, 4, 1, 64)
    root_ifd += struct.pack("<I", 0)

    # GPS IFD at offset 64 with 4 entries: LatRef ('N'), Lat (3 rationals), LngRef ('E'), Lng (3 rationals)
    # GPS IFD size: 2 + 4*12 + 4 = 54 bytes -> ends at offset 118
    # Lat rationals at 118 (24 bytes: 10 deg, 46 min, 36 sec -> 10.776667)
    # Lng rationals at 142 (24 bytes: 106 deg, 42 min, 0 sec -> 106.7)
    gps_ifd = struct.pack("<H", 4)
    gps_ifd += struct.pack("<HHI4s", 0x0001, 2, 2, b"N\x00\x00\x00")
    gps_ifd += struct.pack("<HHII", 0x0002, 5, 3, 118)
    gps_ifd += struct.pack("<HHI4s", 0x0003, 2, 2, b"E\x00\x00\x00")
    gps_ifd += struct.pack("<HHII", 0x0004, 5, 3, 142)
    gps_ifd += struct.pack("<I", 0)

    lat_rats = struct.pack("<IIIIII", 10, 1, 46, 1, 36, 1)
    lng_rats = struct.pack("<IIIIII", 106, 1, 42, 1, 0, 1)

    tiff = b"II" + struct.pack("<HI", 42, 8) + root_ifd + make_bytes + model_bytes + gps_ifd + lat_rats + lng_rats
    app1_payload = b"Exif\x00\x00" + tiff
    jpeg = b"\xff\xd8\xff\xe1" + struct.pack(">H", len(app1_payload) + 2) + app1_payload + b"\xff\xd9"
    return base64.b64encode(jpeg).decode("ascii")


def test_pure_python_exif_gps_and_imint_prompt() -> None:
    b64 = _build_synthetic_jpeg_with_exif()
    meta = extract_image_exif_metadata(b64)
    assert meta["has_exif"] is True
    assert "Canon" in meta["summary_text"]
    assert "EOS R5" in meta["summary_text"]
    assert abs(meta["gps_lat"] - 10.776667) < 0.001
    assert abs(meta["gps_lng"] - 106.7) < 0.001

    v_prompt = build_imint_vision_prompt("")
    assert "Đồng phục" in v_prompt
    assert "GEOINT" in v_prompt
    assert "Họ và tên:" in v_prompt


def test_extract_uploaded_vcard_csv_xlsx_and_api_endpoints() -> None:
    # 1. vCard (.vcf)
    vcf_raw = (
        "BEGIN:VCARD\n"
        "VERSION:3.0\n"
        "FN:Trần Minh Mẫu\n"
        "ORG:Đại học Kinh tế TP.HCM (UEH)\n"
        "TEL;TYPE=CELL:0901234567\n"
        "BDAY:1998\n"
        "ADR:;;Quận 3;TP.HCM;;;\n"
        "END:VCARD\n"
    )
    vcf_b64 = base64.b64encode(vcf_raw.encode("utf-8")).decode("ascii")
    res_vcf = extract_uploaded_file_text(vcf_b64, "contact.vcf")
    assert res_vcf["ok"] is True
    assert "Họ và tên: Trần Minh Mẫu" in res_vcf["extracted_text"]
    assert "Điện thoại: 0901234567" in res_vcf["extracted_text"]

    # 2. Excel (.xlsx)
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "DanhSach"
    ws.append(["Họ và tên", "MSSV", "Trường", "Điện thoại"])
    ws.append(["Trần Minh Mẫu", "31231024455", "UEH", "0901234567"])
    buf = io.BytesIO()
    wb.save(buf)
    xlsx_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    res_xlsx = extract_uploaded_file_text(xlsx_b64, "roster.xlsx")
    assert res_xlsx["ok"] is True
    assert res_xlsx["doc_type"] == "xlsx"
    assert "31231024455" in res_xlsx["extracted_text"]

    # 3. FastAPI Endpoints (/api/tools/extract-file & /api/tools/extract-image-exif)
    client = TestClient(app)
    r1 = client.post("/api/tools/extract-file", json={"filename": "contact.vcf", "content_b64": vcf_b64})
    assert r1.status_code == 200 and r1.json()["ok"] is True

    r2 = client.post(
        "/api/tools/extract-image-exif",
        json={"filename": "photo.jpg", "content_b64": _build_synthetic_jpeg_with_exif()},
    )
    assert r2.status_code == 200 and r2.json()["has_exif"] is True


@pytest.mark.asyncio
async def test_layer1_intake_hydrates_from_attached_file_without_text_prompt() -> None:
    attached_text = (
        "Họ và tên: Trần Minh Mẫu\n"
        "Năm sinh: 1998\n"
        "Đơn vị công tác: UEH\n"
        "Điện thoại: 0901234567\n"
        "Địa điểm: TP.HCM"
    )
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        store = GraphStore(db_path=Path(tmpdir) / "mm.db")
        ws = store.create_workspace(SimpleNamespace(name="MM Test", description=""))
        ctx = await run_layer1_intake(
            store=store,
            workspace_id=ws.id,
            prompt="Phân tích dữ liệu đính kèm và truy vết mục tiêu",
            attached_file_text=attached_text,
            image_b64=_build_synthetic_jpeg_with_exif(),
        )
        assert ctx.parsed["target_name"] == "Trần Minh Mẫu"
        assert ctx.parsed["birth_year"] == 1998
        assert "UEH" in ctx.parsed["organizations"]
        assert "0901234567" in ctx.parsed["phone_candidates"]
        assert "10.776667" in ctx.geo_blob
