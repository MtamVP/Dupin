"""Multimodal Layer-1 Intake Engine: Pure-Python EXIF/GPS Extractor, Visual OSINT (IMINT/GEOINT) Prompting,
and Local Document (PDF / Excel XLSX / CSV / vCard / Text) Intake Parser.

Strictly Public OSINT & Local-First:
- Zero external binary dependencies required for JPEG/PNG EXIF & GPS parsing.
- Uses existing `pypdf` and `openpyxl` for local PDF/XLSX file attachments.
"""

from __future__ import annotations

import base64
import csv
import io
import re
import struct
from typing import Any

# Standard EXIF Tag IDs
_EXIF_TAGS: dict[int, str] = {
    0x010F: "make",
    0x0110: "model",
    0x0131: "software",
    0x0132: "datetime",
    0x013B: "artist",
    0x8769: "exif_ifd",
    0x8825: "gps_ifd",
    0x9003: "datetime_original",
    0x9004: "datetime_digitized",
    0xA420: "image_unique_id",
    0xA430: "camera_owner",
    0xA431: "body_serial_number",
}

_GPS_TAGS: dict[int, str] = {
    0x0001: "lat_ref",
    0x0002: "lat",
    0x0003: "lng_ref",
    0x0004: "lng",
    0x0006: "alt",
}

_TIFF_TYPE_SIZES: dict[int, int] = {
    1: 1,  # BYTE
    2: 1,  # ASCII
    3: 2,  # SHORT
    4: 4,  # LONG
    5: 8,  # RATIONAL
    7: 1,  # UNDEFINED
    9: 4,  # SLONG
    10: 8,  # SRATIONAL
}


def _read_tiff_value(tiff: bytes, endian: str, val_type: int, count: int, val_offset_bytes: bytes) -> Any:
    unit = _TIFF_TYPE_SIZES.get(val_type, 0)
    if unit == 0 or count <= 0:
        return None
    total_len = unit * count
    if total_len <= 4:
        raw = val_offset_bytes[:total_len]
    else:
        off = struct.unpack(f"{endian}I", val_offset_bytes)[0]
        if off < 0 or off + total_len > len(tiff):
            return None
        raw = tiff[off : off + total_len]

    if val_type == 2:  # ASCII
        return raw.rstrip(b"\x00").decode("utf-8", errors="replace").strip()
    if val_type == 3:  # SHORT
        vals = struct.unpack(f"{endian}{count}H", raw)
        return vals[0] if count == 1 else list(vals)
    if val_type == 4:  # LONG
        vals = struct.unpack(f"{endian}{count}I", raw)
        return vals[0] if count == 1 else list(vals)
    if val_type == 5:  # RATIONAL
        rats: list[float] = []
        for i in range(count):
            num, den = struct.unpack(f"{endian}II", raw[i * 8 : (i + 1) * 8])
            rats.append(float(num) / float(den) if den else 0.0)
        return rats[0] if count == 1 else rats
    return None


def _parse_ifd(tiff: bytes, endian: str, ifd_offset: int, tag_map: dict[int, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if ifd_offset <= 0 or ifd_offset + 2 > len(tiff):
        return out
    try:
        num_entries = struct.unpack(f"{endian}H", tiff[ifd_offset : ifd_offset + 2])[0]
    except Exception:
        return out
    if num_entries > 256:
        return out
    pos = ifd_offset + 2
    for _ in range(num_entries):
        if pos + 12 > len(tiff):
            break
        tag_id, val_type, count = struct.unpack(f"{endian}HHI", tiff[pos : pos + 8])
        val_bytes = tiff[pos + 8 : pos + 12]
        pos += 12
        name = tag_map.get(tag_id)
        if not name:
            continue
        val = _read_tiff_value(tiff, endian, val_type, count, val_bytes)
        if val is not None:
            out[name] = val
    return out


def _dms_to_decimal(dms: Any, ref: str) -> float | None:
    if not isinstance(dms, list) or len(dms) < 3:
        return None
    try:
        deg, minutes, sec = float(dms[0]), float(dms[1]), float(dms[2])
        dec = deg + (minutes / 60.0) + (sec / 3600.0)
        if str(ref or "").strip().upper() in ("S", "W"):
            dec = -dec
        if -180.0 <= dec <= 180.0 and dec != 0.0:
            return round(dec, 6)
    except Exception:
        return None
    return None


def _parse_tiff_exif(tiff: bytes) -> dict[str, Any]:
    if len(tiff) < 8:
        return {}
    byte_order = tiff[:2]
    if byte_order == b"II":
        endian = "<"
    elif byte_order == b"MM":
        endian = ">"
    else:
        return {}
    magic, first_ifd = struct.unpack(f"{endian}HI", tiff[2:8])
    if magic != 42:
        return {}

    root = _parse_ifd(tiff, endian, first_ifd, _EXIF_TAGS)
    if isinstance(root.get("exif_ifd"), int):
        root.update(_parse_ifd(tiff, endian, int(root["exif_ifd"]), _EXIF_TAGS))
    if isinstance(root.get("gps_ifd"), int):
        gps = _parse_ifd(tiff, endian, int(root["gps_ifd"]), _GPS_TAGS)
        lat = _dms_to_decimal(gps.get("lat"), str(gps.get("lat_ref") or "N"))
        lng = _dms_to_decimal(gps.get("lng"), str(gps.get("lng_ref") or "E"))
        if lat is not None and lng is not None:
            root["gps_lat"] = lat
            root["gps_lng"] = lng
    return root


def extract_image_exif_metadata(image_b64: str) -> dict[str, Any]:
    """Decode base64 image and extract local EXIF / GPS / PNG text metadata in 0ms (no network calls)."""
    if not image_b64:
        return {"has_exif": False, "summary_text": ""}
    try:
        raw_b64 = image_b64.split(",")[-1].strip()
        data = base64.b64decode(raw_b64)
    except Exception:
        return {"has_exif": False, "summary_text": ""}

    meta: dict[str, Any] = {"file_size_bytes": len(data)}

    # 1. JPEG APP1 Exif scanning
    if data.startswith(b"\xff\xd8"):
        idx = 2
        while idx + 4 <= len(data) and data[idx] == 0xFF:
            marker = data[idx + 1]
            if marker == 0xDA or marker == 0xD9:  # SOS / EOI
                break
            seg_len = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
            if seg_len < 2 or idx + 2 + seg_len > len(data):
                break
            seg_data = data[idx + 4 : idx + 2 + seg_len]
            if marker == 0xE1 and seg_data.startswith(b"Exif\x00\x00"):
                meta.update(_parse_tiff_exif(seg_data[6:]))
                break
            idx += 2 + seg_len

    # 2. PNG tEXt / eXIf chunk scanning
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        idx = 8
        png_texts: list[str] = []
        while idx + 8 <= len(data):
            length = struct.unpack(">I", data[idx : idx + 4])[0]
            ctype = data[idx + 4 : idx + 8]
            chunk_data = data[idx + 8 : idx + 8 + length]
            if ctype == b"eXIf":
                meta.update(_parse_tiff_exif(chunk_data))
            elif ctype == b"tEXt" and b"\x00" in chunk_data:
                k, v = chunk_data.split(b"\x00", 1)
                ks = k.decode("latin1", errors="ignore").strip()
                vs = v.decode("utf-8", errors="ignore").strip()
                if ks and vs and len(vs) <= 160:
                    png_texts.append(f"{ks}: {vs}")
            elif ctype == b"IEND":
                break
            idx += 12 + length
        if png_texts:
            meta["png_text"] = " | ".join(png_texts[:4])

    parts: list[str] = []
    cam = " ".join(str(meta.get(k) or "").strip() for k in ("make", "model") if meta.get(k)).strip()
    if cam:
        parts.append(f"Thiết bị chụp: {cam}")
    dt = str(meta.get("datetime_original") or meta.get("datetime") or "").strip()
    if dt:
        parts.append(f"Thời gian chụp EXIF: {dt}")
    owner = str(meta.get("camera_owner") or meta.get("artist") or "").strip()
    if owner:
        parts.append(f"Tác giả/Chủ thiết bị EXIF: {owner}")
    if meta.get("gps_lat") is not None and meta.get("gps_lng") is not None:
        parts.append(f"Tọa độ GPS EXIF: {meta['gps_lat']}, {meta['gps_lng']}")
    if meta.get("png_text"):
        parts.append(f"PNG Metadata: {meta['png_text']}")

    meta["has_exif"] = bool(parts)
    meta["summary_text"] = " · ".join(parts)
    return meta


def build_imint_vision_prompt(user_prompt: str) -> str:
    """Construct a structured Visual OSINT (OCR + Uniform/Badge IMINT + Street/Signage GEOINT) prompt."""
    ctx_line = user_prompt.strip() or "Phân tích toàn diện ảnh này để tìm danh tính, trường học, cơ quan và địa điểm."
    return (
        "Bạn là chuyên gia Visual OSINT (OCR + IMINT + GEOINT). Hãy phân tích kỹ bức ảnh này theo 4 nhóm:\n"
        "1. [OCR Văn bản / Thẻ / Bảng danh sách]: Đọc chính xác mọi chữ xuất hiện (Họ tên, MSSV, CCCD, SBD, Ngày sinh, "
        "Lớp, Ngành học, SĐT, Email, Username/Link mạng xã hội, Số hiệu văn bản QĐ).\n"
        "2. [Đồng phục / Phù hiệu / Logo / Dây đeo thẻ]: Nhận diện logo trường THPT/Đại học, công ty, màu và kiểu đồng phục, "
        "bảng tên trên ngực áo, huy hiệu hoặc thẻ sinh viên/nhân viên.\n"
        "3. [Bối cảnh & Địa lý (GEOINT)]: Nhận diện biển hiệu cửa hàng, tên đường, địa chỉ, biển số xe (mã tỉnh), "
        "backdrop sự kiện/hội trường, kiến trúc đặc trưng để khoanh vùng tỉnh/thành phố hoặc cơ sở trường.\n"
        "4. [Tóm tắt Trường Chuẩn Hóa]: Ở cuối câu trả lời, nếu xác định được thông tin nào, hãy ghi rõ theo từng dòng:\n"
        "Họ và tên: <tên nếu thấy>\n"
        "Năm sinh: <năm hoặc ngày sinh nếu thấy>\n"
        "Đơn vị công tác: <tên trường / công ty từ chữ, logo hoặc đồng phục>\n"
        "Địa điểm: <tỉnh/thành phố hoặc địa chỉ từ biển hiệu/biển số>\n"
        "Điện thoại: <số điện thoại nếu thấy>\n"
        f"Yêu cầu bổ sung từ người dùng: {ctx_line}"
    )


def _parse_vcard_text(raw_text: str) -> str:
    """Convert a .vcf (vCard) contact file into clean Vietnamese Key:Value lines for Layer 1 Intake."""
    lines_out: list[str] = []
    for raw_ln in raw_text.splitlines():
        ln = raw_ln.strip()
        up = ln.upper()
        if up.startswith("FN:"):
            lines_out.append(f"Họ và tên: {ln[3:].strip()}")
        elif up.startswith("ORG:"):
            lines_out.append(f"Đơn vị công tác: {ln[4:].replace(';', ' ').strip()}")
        elif up.startswith("TITLE:"):
            lines_out.append(f"Nghề nghiệp: {ln[6:].strip()}")
        elif up.startswith("TEL"):
            val = ln.split(":", 1)[-1].strip()
            if val:
                lines_out.append(f"Điện thoại: {val}")
        elif up.startswith("EMAIL"):
            val = ln.split(":", 1)[-1].strip()
            if val:
                lines_out.append(f"Email: {val}")
        elif up.startswith("BDAY:"):
            lines_out.append(f"Năm sinh: {ln[5:].strip()}")
        elif up.startswith("ADR"):
            val = ln.split(":", 1)[-1].replace(";", ", ").strip(" ,")
            if val:
                lines_out.append(f"Địa điểm: {val}")
    return "\n".join(lines_out) if lines_out else raw_text[:8000]


def extract_uploaded_file_text(
    content_b64: str,
    filename: str,
    max_chars: int = 12000,
) -> dict[str, Any]:
    """Decode an uploaded local file (.pdf, .xlsx, .csv, .vcf, .txt, .json, .md) into searchable text."""
    fname = (filename or "document.txt").strip()
    ext = fname.lower().rsplit(".", 1)[-1] if "." in fname else "txt"
    try:
        raw_b64 = content_b64.split(",")[-1].strip()
        raw_bytes = base64.b64decode(raw_b64)
    except Exception as exc:
        return {"ok": False, "filename": fname, "doc_type": ext, "error": f"Invalid base64: {exc}", "extracted_text": ""}

    if len(raw_bytes) > 12 * 1024 * 1024:
        return {"ok": False, "filename": fname, "doc_type": ext, "error": "File exceeds 12MB limit", "extracted_text": ""}

    try:
        if ext == "pdf" or raw_bytes.startswith(b"%PDF"):
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw_bytes))
            pages_text: list[str] = []
            total_chars = 0
            for idx, page in enumerate(reader.pages[:80]):
                txt = (page.extract_text() or "").strip()
                if txt:
                    pages_text.append(f"[Trang {idx + 1}] {re.sub(r'[ \t]+', ' ', txt)}")
                    total_chars += len(txt)
                if total_chars >= max_chars:
                    break
            joined = "\n".join(pages_text)[:max_chars]
            return {
                "ok": True,
                "filename": fname,
                "doc_type": "pdf",
                "page_count": len(reader.pages),
                "extracted_text": joined,
                "summary": f"PDF ({len(reader.pages)} trang, {len(joined)} ký tự)",
            }

        if ext in ("xlsx", "xlsm") or raw_bytes.startswith(b"PK\x03\x04"):
            from openpyxl import load_workbook

            wb = load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
            rows_out: list[str] = []
            total_chars = 0
            for sname in wb.sheetnames[:8]:
                ws = wb[sname]
                for r_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                    cells = [str(c).strip() for c in row if c is not None and str(c).strip()]
                    if not cells:
                        continue
                    line = f"[{sname}#{r_idx}] " + " | ".join(cells)
                    rows_out.append(line)
                    total_chars += len(line)
                    if total_chars >= max_chars or len(rows_out) >= 300:
                        break
                if total_chars >= max_chars:
                    break
            wb.close()
            joined = "\n".join(rows_out)[:max_chars]
            return {
                "ok": True,
                "filename": fname,
                "doc_type": "xlsx",
                "sheet_count": len(wb.sheetnames),
                "extracted_text": joined,
                "summary": f"Excel XLSX ({len(rows_out)} dòng trích xuất)",
            }

        text_decoded = raw_bytes.decode("utf-8", errors="replace")
        if ext == "vcf" or "BEGIN:VCARD" in text_decoded[:200].upper():
            parsed_vcf = _parse_vcard_text(text_decoded)[:max_chars]
            return {
                "ok": True,
                "filename": fname,
                "doc_type": "vcf",
                "extracted_text": parsed_vcf,
                "summary": "Danh bạ vCard (.vcf)",
            }

        if ext in ("csv", "tsv"):
            delim = "\t" if ext == "tsv" else ","
            reader_csv = csv.reader(io.StringIO(text_decoded), delimiter=delim)
            csv_lines = [" | ".join(c.strip() for c in row if c.strip()) for row in list(reader_csv)[:300]]
            joined = "\n".join(ln for ln in csv_lines if ln)[:max_chars]
            return {
                "ok": True,
                "filename": fname,
                "doc_type": ext,
                "extracted_text": joined,
                "summary": f"Bảng {ext.upper()} ({len(csv_lines)} dòng)",
            }

        cleaned = text_decoded[:max_chars]
        return {
            "ok": True,
            "filename": fname,
            "doc_type": ext,
            "extracted_text": cleaned,
            "summary": f"Văn bản {ext.upper()} ({len(cleaned)} ký tự)",
        }
    except Exception as exc:
        return {
            "ok": False,
            "filename": fname,
            "doc_type": ext,
            "error": str(exc)[:200],
            "extracted_text": "",
        }
