"""Dupin Verified Dossier & Multi-Format Deep-Read Exporters.

Supports:
1. Strictly Verified-Only Mode (`verified_only=True`): Exports ONLY user-confirmed Dossier items,
   deep-read excerpts from confirmed PDF/XLSX/Scribd/Studocu links, and verified claims (zero unverified search noise).
2. Automatic Deep-Read Extraction on Confirmed Documents (`collect_verified_dossier_deep_excerpts`):
   Reads confirmed `.pdf`, `.xlsx`, `scribd.com/document`, and `studocu.com/.vn` URLs and embeds exact matching rows/pages.
3. Multi-Format Export Suite (zero new pip dependencies):
   - Word `.docx` (Pure-Python OpenXML ZIP package with styled tables & Deep-Read Excerpt blocks)
   - PDF `.pdf` (Pure-Python multi-page PDF 1.4 document)
   - Excel `.xlsx` (Multi-sheet `openpyxl` workbook)
   - Editorial Print HTML `.html` (Full Vietnamese typography + `@media print`)
   - Obsidian Markdown `.md`
   - CSV `.csv`
   - JSON `.json` & STIX 2.1 `.stix.json`
"""

from __future__ import annotations

import asyncio
import html as html_lib
import io
import re
import zipfile
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4
from xml.sax.saxutils import escape as xml_escape

import httpx

from app.connectors.doc_mirror_reader import fetch_and_inspect_doc_mirror, is_doc_mirror_url
from app.connectors.document_reader import fetch_and_inspect_document, is_inspectable_document_url
from app.core.normalizer import strip_vietnamese_accents
from app.core.schemas import GraphSnapshot

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:\+84|0)(?:3|5|7|8|9)\d{8}\b")
DOB_RE = re.compile(r"\b\d{1,2}/\d{1,2}/(?:19\d{2}|20\d{2})\b")
LONG_ID_RE = re.compile(r"\b\d{8,12}\b")


def redact_pii(text: str) -> str:
    """Mask sensitive personal identifiers (emails, phone numbers, exact DOBs, 8-12 digit IDs)."""
    s = EMAIL_RE.sub("[REDACTED_EMAIL]", str(text or ""))
    s = PHONE_RE.sub("[REDACTED_PHONE]", s)
    s = DOB_RE.sub("[REDACTED_DOB]", s)
    s = LONG_ID_RE.sub(lambda m: m.group(0)[:2] + "****" + m.group(0)[-2:], s)
    return s


def _norm_url(u: str) -> str:
    return str(u or "").strip().rstrip("/").lower()


def _extract_verified_claims(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    verified_only: bool = True,
) -> list[dict[str, Any]]:
    """Return claims filtered strictly to user-confirmed dossier URLs (or manual seed facts) when verified_only=True."""
    verified_urls = {_norm_url(it.get("source_url", "")) for it in dossier_items if it.get("source_url")}
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    for n in snapshot.nodes:
        for c in n.claims:
            if c.key in ("stylometry_vector", "temporal_activity_signature"):
                continue
            c_url = _norm_url(c.source_url)
            if verified_only:
                is_confirmed_src = (
                    c_url == "manual://user_verified"
                    or (c_url and c_url in verified_urls)
                )
                if not is_confirmed_src:
                    continue
            sig = (n.label, c.key, str(c.value))
            if sig in seen:
                continue
            seen.add(sig)
            out.append(
                {
                    "entity": n.label,
                    "entity_type": n.type,
                    "category": c.category.value,
                    "key": c.key,
                    "value": str(c.value),
                    "polarity": c.polarity,
                    "confidence": c.confidence,
                    "source_url": c.source_url,
                    "evidence_quote": c.evidence_quote,
                }
            )
    return out


async def collect_verified_dossier_deep_excerpts(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    timeout: float = 8.0,
    client: Optional[httpx.AsyncClient] = None,
) -> list[dict[str, Any]]:
    """Deep-read all confirmed PDF, XLSX, Scribd, and Studocu URLs in the user's Verified Dossier."""
    target_terms: list[str] = []
    for n in snapshot.nodes:
        if n.type == "Person" and n.label and n.label not in target_terms:
            target_terms.append(n.label)
        for c in n.claims:
            if c.key in ("full_name", "birth_date", "student_id", "phone") and str(c.value) not in target_terms:
                target_terms.append(str(c.value))

    for it in dossier_items:
        fv = str(it.get("field_value") or "").strip()
        fk = str(it.get("field_key") or "").lower()
        if fv and len(fv) <= 50 and any(k in fk for k in ("tên", "name", "mssv", "sđt", "phone", "sinh", "dob")):
            if fv not in target_terms:
                target_terms.append(fv)

    if not target_terms and snapshot.workspace.name:
        target_terms.append(snapshot.workspace.name)

    candidate_urls: list[tuple[str, str]] = []
    seen_u: set[str] = set()
    for it in dossier_items:
        u = str(it.get("source_url") or "").strip()
        nu = _norm_url(u)
        if not u or not u.startswith(("http://", "https://")) or nu in seen_u:
            continue
        if is_inspectable_document_url(u) or is_doc_mirror_url(u):
            seen_u.add(nu)
            candidate_urls.append((str(it.get("field_value") or it.get("field_key") or u), u))
        if len(candidate_urls) >= 5:
            break

    async def _inspect_one(label: str, url: str) -> Optional[dict[str, Any]]:
        try:
            if is_inspectable_document_url(url):
                res = await fetch_and_inspect_document(url, target_terms=target_terms, timeout=timeout, client=client)
                if res.get("ok"):
                    return {
                        "title": label[:180],
                        "url": url,
                        "doc_type": str(res.get("doc_type") or "pdf").upper(),
                        "total_pages": res.get("total_pages"),
                        "scanned_pdf": bool(res.get("scanned_pages_detected")),
                        "header_hint": str(res.get("header_hint") or ""),
                        "metadata": {},
                        "excerpts": res.get("excerpts") or [],
                    }
            elif is_doc_mirror_url(url):
                res = await fetch_and_inspect_doc_mirror(url, target_terms=target_terms, timeout=timeout, client=client)
                if res.get("ok"):
                    meta = res.get("metadata") or {}
                    return {
                        "title": str(meta.get("title") or label)[:180],
                        "url": url,
                        "doc_type": str(meta.get("platform") or "mirror").upper(),
                        "total_pages": meta.get("page_count") or None,
                        "scanned_pdf": False,
                        "header_hint": " | ".join(
                            x for x in (meta.get("university"), meta.get("course"), meta.get("author")) if x
                        ),
                        "metadata": meta,
                        "excerpts": res.get("excerpts") or [],
                        "public_text_summary": str(res.get("public_text_summary") or "")[:600],
                    }
        except Exception:
            return None
        return None

    if not candidate_urls:
        return []

    results = await asyncio.gather(*(_inspect_one(lbl, u) for lbl, u in candidate_urls))
    return [r for r in results if r is not None]


def export_obsidian_markdown(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    redact: bool = False,
    verified_only: bool = False,
    deep_docs: Optional[list[dict[str, Any]]] = None,
) -> str:
    """Generate an Obsidian-ready Markdown dossier note with YAML frontmatter and [[wikilinks]]."""
    clean = redact_pii if redact else (lambda x: str(x or ""))
    ws_name = clean(snapshot.workspace.name)
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: list[str] = [
        "---",
        f'title: "OSINT Verified Dossier — {ws_name}"',
        f"workspace_id: {snapshot.workspace.id}",
        f"exported_at: {now_iso}",
        f"verified_only: {'true' if verified_only else 'false'}",
        f"redacted: {'true' if redact else 'false'}",
        "tags: [dupin, stalker-pp, osint, verified-dossier]",
        "---",
        "",
        f"# {ws_name}",
        "",
        "## 1. Hồ sơ Đã Xác nhận (Verified Dossier Items)",
        "",
    ]
    if dossier_items:
        lines.append("| Trường thông tin | Giá trị Đã Xác nhận | Nguồn kiểm chứng |")
        lines.append("|---|---|---|")
        for it in dossier_items:
            fk = clean(it.get("field_key", "")).replace("|", "\\|")
            fv = clean(it.get("field_value", "")).replace("|", "\\|")
            src = clean(it.get("source_url", ""))
            src_md = f"[Nguồn]({src})" if src.startswith(("http://", "https://")) else (src or "Xác nhận thủ công")
            lines.append(f"| **{fk}** | {fv} | {src_md} |")
    else:
        lines.append("_Chưa có mục hồ sơ nào được ghim xác nhận._")

    if deep_docs:
        lines.extend(["", "## 2. Trích xuất Đọc sâu từ Tài liệu PDF / Excel / Scribd / Studocu Đã Xác nhận", ""])
        for d_idx, doc in enumerate(deep_docs, 1):
            lines.append(f"### {d_idx}. [{clean(doc['title'])}]({clean(doc['url'])}) (`{doc['doc_type']}`)")
            if doc.get("header_hint"):
                lines.append(f"- **Ngữ cảnh / Tiêu đề tài liệu:** {clean(doc['header_hint'])}")
            if doc.get("total_pages"):
                lines.append(f"- **Số trang:** {doc['total_pages']}")
            excerpts = doc.get("excerpts") or []
            if excerpts:
                for ex in excerpts[:6]:
                    pg = ex.get("page") or ex.get("sheet") or 1
                    lines.append(f"  - **[Trang/Sheet {pg}]** `{clean(ex.get('line', ''))}`")
                    if ex.get("context") and ex["context"] != ex.get("line"):
                        ctx_one = re.sub(r"\s+", " ", str(ex["context"])).strip()
                        lines.append(f"    > {clean(ctx_one[:360])}")
            elif doc.get("public_text_summary"):
                lines.append(f"  - **Tóm tắt nội dung công khai:** {clean(doc['public_text_summary'][:360])}")
            lines.append("")

    if verified_only:
        v_claims = _extract_verified_claims(snapshot, dossier_items, verified_only=True)
        if v_claims:
            lines.extend(["", "## 3. Đặc trưng Thực thể Đã Xác thực (Verified 8D Claims)", ""])
            for vc in v_claims:
                lines.append(
                    f"- **[[{clean(vc['entity'])}]]** · `{vc['category']}:{vc['key']}` = "
                    f"{clean(vc['value'])} (src: {clean(vc['source_url'])})"
                )
        return "\n".join(lines).strip() + "\n"

    # Full graph mode (backwards-compatible when verified_only=False)
    lines.extend(["", "## Knowledge Graph Entities (8D)", ""])
    node_map = {n.id: n for n in snapshot.nodes}
    for n in snapshot.nodes:
        lines.append(f"### [[{clean(n.label)}]] (`{n.type}` · confidence `{n.confidence:.2f}`)")
        for c in n.claims:
            if c.key in ("stylometry_vector", "temporal_activity_signature"):
                continue
            pol = "POSITIVE" if c.polarity == "POSITIVE" else "NEGATIVE"
            lines.append(
                f"- **[{pol}]** `{c.category.value}:{c.key}` = {clean(str(c.value))} "
                f"(conf `{c.confidence:.2f}`, src: {clean(c.source_url)})"
            )
        lines.append("")

    if snapshot.edges:
        lines.extend(["## Verified & Hypothesis Relationships", ""])
        for e in snapshot.edges:
            src_lbl = clean(node_map[e.source_id].label) if e.source_id in node_map else e.source_id
            dst_lbl = clean(node_map[e.target_id].label) if e.target_id in node_map else e.target_id
            lines.append(
                f"- [[{src_lbl}]] — **{e.relation}** (`{e.status}`, `{e.confidence:.2f}`) → [[{dst_lbl}]]"
            )

    return "\n".join(lines).strip() + "\n"


def export_stix_bundle(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    redact: bool = False,
    verified_only: bool = False,
) -> dict[str, Any]:
    """Generate a STIX 2.1 compliant JSON bundle for interoperability with MISP / OpenCTI / Maltego."""
    clean = redact_pii if redact else (lambda x: str(x or ""))
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    objects: list[dict[str, Any]] = []
    stix_id_map: dict[str, str] = {}
    verified_urls = {_norm_url(it.get("source_url", "")) for it in dossier_items if it.get("source_url")}

    for n in snapshot.nodes:
        filtered_claims = [
            c
            for c in n.claims
            if c.key not in ("stylometry_vector", "temporal_activity_signature")
            and (
                not verified_only
                or _norm_url(c.source_url) == "manual://user_verified"
                or (_norm_url(c.source_url) and _norm_url(c.source_url) in verified_urls)
            )
        ]
        if verified_only and not filtered_claims and n.type != "Person":
            continue
        stix_type = "identity" if n.type in ("Person", "Org") else "note"
        sid = f"{stix_type}--{uuid4()}"
        stix_id_map[n.id] = sid
        if stix_type == "identity":
            objects.append(
                {
                    "type": "identity",
                    "spec_version": "2.1",
                    "id": sid,
                    "created": now_iso,
                    "modified": now_iso,
                    "name": clean(n.label),
                    "identity_class": "individual" if n.type == "Person" else "organization",
                    "confidence": int(round(n.confidence * 100)),
                    "x_stalker_claims": [
                        {
                            "category": c.category.value,
                            "key": c.key,
                            "value": clean(str(c.value)),
                            "polarity": c.polarity,
                            "source_url": clean(c.source_url),
                        }
                        for c in filtered_claims
                    ],
                }
            )
        else:
            objects.append(
                {
                    "type": "note",
                    "spec_version": "2.1",
                    "id": sid,
                    "created": now_iso,
                    "modified": now_iso,
                    "abstract": f"{n.type}: {clean(n.label)}",
                    "content": clean(n.label),
                    "object_refs": [],
                }
            )

    if not verified_only:
        for e in snapshot.edges:
            src_sid = stix_id_map.get(e.source_id)
            dst_sid = stix_id_map.get(e.target_id)
            if src_sid and dst_sid:
                objects.append(
                    {
                        "type": "relationship",
                        "spec_version": "2.1",
                        "id": f"relationship--{uuid4()}",
                        "created": now_iso,
                        "modified": now_iso,
                        "relationship_type": e.relation.lower().replace("_", "-"),
                        "source_ref": src_sid,
                        "target_ref": dst_sid,
                        "confidence": int(round(e.confidence * 100)),
                        "description": clean(e.evidence_quote),
                    }
                )

    if dossier_items:
        target_refs = [sid for sid in stix_id_map.values() if sid.startswith("identity--")][:5]
        dossier_summary = "\n".join(
            f"- {clean(it.get('field_key', ''))}: {clean(it.get('field_value', ''))} ({clean(it.get('source_url', ''))})"
            for it in dossier_items
        )
        objects.append(
            {
                "type": "note",
                "spec_version": "2.1",
                "id": f"note--{uuid4()}",
                "created": now_iso,
                "modified": now_iso,
                "abstract": f"Verified Dossier ({len(dossier_items)} items)",
                "content": dossier_summary,
                "object_refs": target_refs,
            }
        )

    return {
        "type": "bundle",
        "id": f"bundle--{uuid4()}",
        "spec_version": "2.1",
        "x_generator": "Dupin v2.0",
        "x_verified_only": verified_only,
        "x_redacted": redact,
        "objects": objects,
    }


def export_verified_docx(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    deep_docs: list[dict[str, Any]],
    redact: bool = False,
    verified_only: bool = True,
) -> bytes:
    """Build a genuine Microsoft Word (.docx) OpenXML report in pure Python stdlib (zero extra dependencies)
    containing ONLY Verified Dossier items, Deep-Read PDF/XLSX/Scribd/Studocu excerpts, and Verified 8D Claims.
    """
    clean = redact_pii if redact else (lambda x: str(x or ""))
    ws_name = clean(snapshot.workspace.name)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    v_claims = _extract_verified_claims(snapshot, dossier_items, verified_only=verified_only)

    def _w_p(text: str, *, bold: bool = False, size_half_pt: int = 22, color: str = "1E1E1C", shading: str = "") -> str:
        t_esc = xml_escape(str(text or ""))
        rpr = f'<w:rPr><w:rFonts w:ascii="Segoe UI" w:hAnsi="Segoe UI"/><w:sz w:val="{size_half_pt}"/><w:color w:val="{color}"/>'
        if bold:
            rpr += "<w:b/>"
        rpr += "</w:rPr>"
        ppr = '<w:pPr><w:spacing w:before="80" w:after="80"/>'
        if shading:
            ppr += f'<w:shd w:val="clear" w:color="auto" w:fill="{shading}"/>'
        ppr += "</w:pPr>"
        return f"<w:p>{ppr}<w:r>{rpr}<w:t xml:space=\"preserve\">{t_esc}</w:t></w:r></w:p>"

    def _w_cell(text: str, *, bold: bool = False, fill: str = "FFFFFF", width_dxa: int = 3000) -> str:
        p = _w_p(text, bold=bold, size_half_pt=20)
        return (
            f"<w:tc><w:tcPr><w:tcW w:w=\"{width_dxa}\" w:type=\"dxa\"/>"
            f"<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"{fill}\"/>"
            f"<w:tcMar><w:top w:w=\"100\" w:type=\"dxa\"/><w:bottom w:w=\"100\" w:type=\"dxa\"/>"
            f"<w:left w:w=\"120\" w:type=\"dxa\"/><w:right w:w=\"120\" w:type=\"dxa\"/></w:tcMar>"
            f"</w:tcPr>{p}</w:tc>"
        )

    body_parts: list[str] = []
    # Title & Metadata Header
    body_parts.append(_w_p(f"HỒ SƠ XÁC MINH OSINT — {ws_name}", bold=True, size_half_pt=34, color="161613"))
    body_parts.append(
        _w_p(
            f"Xuất từ Dupin 5-Layer OSINT Workbench · Thời gian: {now_str} · Chế độ: Chỉ dữ liệu đã xác nhận ({len(dossier_items)} mục)",
            size_half_pt=18,
            color="6E6D68",
        )
    )

    # Section 1: Verified Dossier Table
    body_parts.append(_w_p("1. Danh mục Hồ sơ Đã Xác nhận (Verified Dossier)", bold=True, size_half_pt=26, color="161613"))
    if dossier_items:
        tbl_borders = (
            "<w:tblBorders>"
            '<w:top w:val="single" w:sz="4" w:space="0" w:color="D8D6CE"/>'
            '<w:left w:val="single" w:sz="4" w:space="0" w:color="D8D6CE"/>'
            '<w:bottom w:val="single" w:sz="4" w:space="0" w:color="D8D6CE"/>'
            '<w:right w:val="single" w:sz="4" w:space="0" w:color="D8D6CE"/>'
            '<w:insideH w:val="single" w:sz="4" w:space="0" w:color="E6E4DD"/>'
            '<w:insideV w:val="single" w:sz="4" w:space="0" w:color="E6E4DD"/>'
            "</w:tblBorders>"
        )
        rows_xml: list[str] = [
            "<w:tr>"
            + _w_cell("Trường thông tin", bold=True, fill="F3F2EE", width_dxa=2200)
            + _w_cell("Nội dung Đã Xác nhận", bold=True, fill="F3F2EE", width_dxa=4300)
            + _w_cell("Nguồn kiểm chứng", bold=True, fill="F3F2EE", width_dxa=2800)
            + "</w:tr>"
        ]
        for it in dossier_items:
            fk = clean(it.get("field_key", ""))
            fv = clean(it.get("field_value", ""))
            src = clean(it.get("source_url", "")) or "Xác nhận thủ công"
            rows_xml.append(
                "<w:tr>"
                + _w_cell(fk, bold=True, width_dxa=2200)
                + _w_cell(fv, width_dxa=4300)
                + _w_cell(src, width_dxa=2800)
                + "</w:tr>"
            )
        body_parts.append(f"<w:tbl><w:tblPr><w:tblW w:w=\"9300\" w:type=\"dxa\"/>{tbl_borders}</w:tblPr>{''.join(rows_xml)}</w:tbl>")
    else:
        body_parts.append(_w_p("Chưa có mục nào được ghim vào Hồ sơ đã xác nhận.", size_half_pt=20, color="6E6D68"))

    # Section 2: Deep-Read PDF / XLSX / Scribd / Studocu Excerpts
    body_parts.append(
        _w_p(
            "2. Trích xuất Đọc sâu từ Tài liệu PDF / Excel / Scribd / Studocu Đã Xác nhận",
            bold=True,
            size_half_pt=26,
            color="161613",
        )
    )
    if deep_docs:
        for idx, doc in enumerate(deep_docs, 1):
            body_parts.append(
                _w_p(
                    f"{idx}. [{doc['doc_type']}] {clean(doc['title'])}",
                    bold=True,
                    size_half_pt=22,
                    color="161613",
                )
            )
            body_parts.append(_w_p(f"URL gốc: {clean(doc['url'])}", size_half_pt=18, color="6E6D68"))
            if doc.get("header_hint"):
                body_parts.append(_w_p(f"Thông tin tài liệu: {clean(doc['header_hint'])}", size_half_pt=19, color="4A4945"))
            excerpts = doc.get("excerpts") or []
            if excerpts:
                for ex in excerpts[:8]:
                    pg = ex.get("page") or ex.get("sheet") or 1
                    body_parts.append(
                        _w_p(
                            f"[Trang/Sheet {pg}] Dòng khớp: {clean(ex.get('line', ''))}",
                            bold=True,
                            size_half_pt=20,
                            color="161613",
                            shading="F5F4F0",
                        )
                    )
                    if ex.get("context") and ex["context"] != ex.get("line"):
                        ctx_line = re.sub(r"\s+", " ", str(ex["context"])).strip()
                        body_parts.append(_w_p(f"Ngữ cảnh liền kề: {clean(ctx_line[:450])}", size_half_pt=19, color="4A4945"))
            elif doc.get("public_text_summary"):
                body_parts.append(
                    _w_p(
                        f"Trích đoạn công khai: {clean(doc['public_text_summary'][:450])}",
                        size_half_pt=19,
                        color="4A4945",
                        shading="F5F4F0",
                    )
                )
    else:
        body_parts.append(
            _w_p(
                "Không có liên kết tài liệu PDF / Excel / Scribd / Studocu nào trong danh mục đã xác nhận cần đọc sâu.",
                size_half_pt=20,
                color="6E6D68",
            )
        )

    # Section 3: Verified 8D Claims
    if v_claims:
        body_parts.append(_w_p("3. Đặc trưng Thực thể 8 Chiều Đã Xác thực", bold=True, size_half_pt=26, color="161613"))
        for vc in v_claims:
            body_parts.append(
                _w_p(
                    f"• [{clean(vc['entity'])}] {vc['category']}.{vc['key']} = {clean(vc['value'])} (Nguồn: {clean(vc['source_url'])})",
                    size_half_pt=20,
                )
            )

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{''.join(body_parts)}<w:sectPr/></w:body></w:document>"
    )
    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml)
        zf.writestr("_rels/.rels", rels_xml)
        zf.writestr("word/document.xml", document_xml.encode("utf-8"))
    return buf.getvalue()


def _pdf_escape_ascii(text: str) -> str:
    """Convert Vietnamese UTF-8 text into clean ASCII/Latin-1 for standard PDF Type1 Helvetica streams."""
    ascii_txt = strip_vietnamese_accents(str(text or ""))
    # Keep printable ASCII
    safe = "".join(ch if 32 <= ord(ch) <= 126 else " " for ch in ascii_txt)
    return safe.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_text_lines(text: str, width: int = 86) -> list[str]:
    words = str(text or "").split()
    if not words:
        return [""]
    lines: list[str] = []
    cur = words[0]
    for w in words[1:]:
        if len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def export_verified_pdf(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    deep_docs: list[dict[str, Any]],
    redact: bool = False,
    verified_only: bool = True,
) -> bytes:
    """Generate a formatted multi-page PDF 1.4 dossier report in pure Python stdlib
    containing Verified Dossier items, Deep-Read PDF/XLSX/Scribd/Studocu excerpts, and Verified Claims.
    """
    clean = redact_pii if redact else (lambda x: str(x or ""))
    ws_name = clean(snapshot.workspace.name)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    v_claims = _extract_verified_claims(snapshot, dossier_items, verified_only=verified_only)

    # Build structured report lines: (font_code, font_size, line_spacing, text)
    styled_lines: list[tuple[str, int, int, str]] = [
        ("F2", 16, 24, f"DUPIN VERIFIED OSINT DOSSIER - {ws_name}"),
        ("F1", 9, 16, f"Exported: {now_str} | Mode: Verified Only ({len(dossier_items)} confirmed items)"),
        ("F1", 9, 14, "-" * 92),
        ("F2", 12, 20, "1. HO SO DA XAC NHAN (VERIFIED DOSSIER ITEMS)"),
    ]

    if dossier_items:
        for idx, it in enumerate(dossier_items, 1):
            fk = clean(it.get("field_key", ""))
            fv = clean(it.get("field_value", ""))
            src = clean(it.get("source_url", "")) or "Manual Verification"
            for w_ln in _wrap_text_lines(f"{idx}. [{fk}] {fv}", 84):
                styled_lines.append(("F2", 10, 14, w_ln))
            for s_ln in _wrap_text_lines(f"   Source: {src}", 88):
                styled_lines.append(("F1", 9, 13, s_ln))
    else:
        styled_lines.append(("F1", 10, 15, "No verified dossier items pinned yet."))

    styled_lines.append(("F1", 9, 14, ""))
    styled_lines.append(("F2", 12, 20, "2. TRICH XUAT DOC SAU TAI LIEU DA XAC NHAN (DEEP-READ PDF / MIRRORS)"))
    if deep_docs:
        for idx, doc in enumerate(deep_docs, 1):
            for t_ln in _wrap_text_lines(f"{idx}. [{doc['doc_type']}] {clean(doc['title'])}", 82):
                styled_lines.append(("F2", 10, 15, t_ln))
            for u_ln in _wrap_text_lines(f"   URL: {clean(doc['url'])}", 88):
                styled_lines.append(("F1", 8, 12, u_ln))
            if doc.get("header_hint"):
                for h_ln in _wrap_text_lines(f"   Header/Meta: {clean(doc['header_hint'])}", 86):
                    styled_lines.append(("F1", 9, 13, h_ln))
            excerpts = doc.get("excerpts") or []
            if excerpts:
                for ex in excerpts[:8]:
                    pg = ex.get("page") or ex.get("sheet") or 1
                    for e_ln in _wrap_text_lines(f"   * [Page/Sheet {pg}] {clean(ex.get('line', ''))}", 84):
                        styled_lines.append(("F2", 9, 13, e_ln))
                    if ex.get("context") and ex["context"] != ex.get("line"):
                        ctx_one = re.sub(r"\s+", " ", str(ex["context"])).strip()
                        for c_ln in _wrap_text_lines(f"     Context: {clean(ctx_one[:320])}", 86):
                            styled_lines.append(("F1", 8, 12, c_ln))
            elif doc.get("public_text_summary"):
                for p_ln in _wrap_text_lines(f"   Public Preview: {clean(doc['public_text_summary'][:320])}", 86):
                    styled_lines.append(("F1", 9, 13, p_ln))
    else:
        styled_lines.append(("F1", 10, 15, "No confirmed PDF/XLSX/Scribd/Studocu document URLs required deep extraction."))

    if v_claims:
        styled_lines.append(("F1", 9, 14, ""))
        styled_lines.append(("F2", 12, 20, "3. DAC TRUNG THUC THE 8D DA XAC THUC (VERIFIED 8D CLAIMS)"))
        for vc in v_claims:
            for v_ln in _wrap_text_lines(
                f"- [{clean(vc['entity'])}] {vc['category']}.{vc['key']} = {clean(vc['value'])} ({clean(vc['source_url'])})",
                86,
            ):
                styled_lines.append(("F1", 9, 13, v_ln))

    # Paginate into A4 pages (height 842pt, top 790pt -> bottom 55pt)
    pages_streams: list[str] = []
    cur_cmds: list[str] = ["BT"]
    y = 790
    for font_code, fsize, spacing, txt in styled_lines:
        if y - spacing < 55:
            cur_cmds.append("ET")
            pages_streams.append("\n".join(cur_cmds))
            cur_cmds = ["BT"]
            y = 790
        y -= spacing
        esc = _pdf_escape_ascii(txt)
        cur_cmds.append(f"/{font_code} {fsize} Tf 1 0 0 1 45 {y} Tm ({esc}) Tj")
    cur_cmds.append("ET")
    pages_streams.append("\n".join(cur_cmds))

    # Assemble valid PDF 1.4 objects
    objects: list[bytes] = []

    def _add_obj(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font1_id = _add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font2_id = _add_obj(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    pages_root_id = _add_obj(b"")  # placeholder for /Pages

    page_obj_ids: list[int] = []
    for stream_txt in pages_streams:
        s_bytes = stream_txt.encode("latin1", errors="replace")
        content_id = _add_obj(
            f"<< /Length {len(s_bytes)} >>\nstream\n".encode("ascii") + s_bytes + b"\nendstream"
        )
        p_id = _add_obj(
            f"<< /Type /Page /Parent {pages_root_id} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font1_id} 0 R /F2 {font2_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>".encode("ascii")
        )
        page_obj_ids.append(p_id)

    kids_str = " ".join(f"{pid} 0 R" for pid in page_obj_ids)
    objects[pages_root_id - 1] = f"<< /Type /Pages /Kids [{kids_str}] /Count {len(page_obj_ids)} >>".encode("ascii")
    catalog_id = _add_obj(f"<< /Type /Catalog /Pages {pages_root_id} 0 R >>".encode("ascii"))

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = [0]
    for idx, obj_bytes in enumerate(objects, 1):
        offsets.append(len(out))
        out.extend(f"{idx} 0 obj\n".encode("ascii"))
        out.extend(obj_bytes)
        out.extend(b"\nendobj\n")
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode(
            "ascii"
        )
    )
    return bytes(out)


def export_verified_xlsx(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    deep_docs: list[dict[str, Any]],
    redact: bool = False,
    verified_only: bool = True,
) -> bytes:
    """Build a multi-sheet Excel (.xlsx) workbook containing Verified Dossier items, Deep-Read PDF excerpts, and Verified Claims."""
    from openpyxl import Workbook

    clean = redact_pii if redact else (lambda x: str(x or ""))
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "HoSoDaXacNhan"
    ws1.append(["Trường thông tin", "Giá trị Đã Xác nhận", "Nguồn kiểm chứng", "Ghi chú"])
    for it in dossier_items:
        ws1.append(
            [
                clean(it.get("field_key", "")),
                clean(it.get("field_value", "")),
                clean(it.get("source_url", "")),
                clean(it.get("note", "")),
            ]
        )

    ws2 = wb.create_sheet("DocSauTaiLieuPDF")
    ws2.append(["Loại tài liệu", "Tiêu đề", "URL", "Trang / Sheet", "Dòng trích xuất khớp mục tiêu", "Ngữ cảnh liền kề"])
    for doc in deep_docs:
        excerpts = doc.get("excerpts") or []
        if excerpts:
            for ex in excerpts:
                ws2.append(
                    [
                        doc.get("doc_type", "PDF"),
                        clean(doc.get("title", "")),
                        clean(doc.get("url", "")),
                        str(ex.get("page") or ex.get("sheet") or 1),
                        clean(ex.get("line", "")),
                        clean(re.sub(r"\s+", " ", str(ex.get("context") or "")).strip()),
                    ]
                )
        else:
            ws2.append(
                [
                    doc.get("doc_type", "MIRROR"),
                    clean(doc.get("title", "")),
                    clean(doc.get("url", "")),
                    "1",
                    clean(doc.get("header_hint", "")),
                    clean(doc.get("public_text_summary", "")),
                ]
            )

    ws3 = wb.create_sheet("DacTrung8DDaXacThuc")
    ws3.append(["Thực thể", "Nhóm 8D", "Thuộc tính", "Giá trị", "Độ tin cậy", "Nguồn xác thực"])
    for vc in _extract_verified_claims(snapshot, dossier_items, verified_only=verified_only):
        ws3.append(
            [
                clean(vc["entity"]),
                vc["category"],
                vc["key"],
                clean(vc["value"]),
                vc["confidence"],
                clean(vc["source_url"]),
            ]
        )

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_verified_html(
    snapshot: GraphSnapshot,
    dossier_items: list[dict[str, Any]],
    deep_docs: list[dict[str, Any]],
    redact: bool = False,
    verified_only: bool = True,
) -> str:
    """Generate a print-ready Editorial HTML report with full Vietnamese typography and 1-click PDF Print view."""
    clean = redact_pii if redact else (lambda x: str(x or ""))
    esc = lambda x: html_lib.escape(clean(x))
    ws_name = esc(snapshot.workspace.name)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    v_claims = _extract_verified_claims(snapshot, dossier_items, verified_only=verified_only)

    dossier_rows = "".join(
        f"<tr><td><strong>{esc(it.get('field_key', ''))}</strong></td>"
        f"<td>{esc(it.get('field_value', ''))}</td>"
        f"<td class='mono'>{esc(it.get('source_url', '') or 'Xác nhận thủ công')}</td></tr>"
        for it in dossier_items
    ) or "<tr><td colspan='3'>Chưa có mục hồ sơ nào được ghim xác nhận.</td></tr>"

    deep_blocks: list[str] = []
    for idx, doc in enumerate(deep_docs, 1):
        ex_items = "".join(
            f"<div class='excerpt'><strong>[Trang/Sheet {ex.get('page') or ex.get('sheet') or 1}]</strong> "
            f"{esc(ex.get('line', ''))}"
            + (
                f"<div class='ctx'>{esc(re.sub(r'\\s+', ' ', str(ex.get('context') or '')).strip()[:400])}</div>"
                if ex.get("context") and ex.get("context") != ex.get("line")
                else ""
            )
            + "</div>"
            for ex in (doc.get("excerpts") or [])[:8]
        )
        if not ex_items and doc.get("public_text_summary"):
            ex_items = f"<div class='excerpt'>{esc(doc.get('public_text_summary', '')[:400])}</div>"
        deep_blocks.append(
            f"<div class='doc-card'>"
            f"<h3>{idx}. [{html_lib.escape(str(doc.get('doc_type', 'PDF')))}] {esc(doc.get('title', ''))}</h3>"
            f"<div class='meta mono'>{esc(doc.get('url', ''))}</div>"
            + (f"<div class='meta'>{esc(doc.get('header_hint', ''))}</div>" if doc.get("header_hint") else "")
            + ex_items
            + "</div>"
        )
    deep_html = "".join(deep_blocks) or "<p class='muted'>Không có tài liệu PDF/Excel/Scribd/Studocu nào cần đọc sâu.</p>"

    claims_rows = "".join(
        f"<tr><td>{esc(vc['entity'])}</td><td class='mono'>{html_lib.escape(vc['category'])}.{html_lib.escape(vc['key'])}</td>"
        f"<td>{esc(vc['value'])}</td><td class='mono'>{esc(vc['source_url'])}</td></tr>"
        for vc in v_claims
    )
    claims_section = (
        f"<h2>3. Đặc trưng Thực thể 8 Chiều Đã Xác thực</h2>"
        f"<table><thead><tr><th>Thực thể</th><th>Trường 8D</th><th>Giá trị</th><th>Nguồn</th></tr></thead>"
        f"<tbody>{claims_rows}</tbody></table>"
        if claims_rows
        else ""
    )

    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8"/>
<title>Hồ sơ OSINT Đã Xác nhận — {ws_name}</title>
<style>
  body {{ font-family: 'Inter', 'Segoe UI', system-ui, sans-serif; background: #FAF9F6; color: #161613; max-width: 900px; margin: 32px auto; padding: 0 24px; line-height: 1.55; }}
  h1 {{ font-size: 24px; margin-bottom: 4px; }}
  h2 {{ font-size: 17px; margin-top: 28px; border-bottom: 1px solid #E2E0D8; padding-bottom: 6px; }}
  h3 {{ font-size: 14px; margin: 0 0 4px 0; }}
  .sub {{ color: #6E6D68; font-size: 13px; margin-bottom: 20px; }}
  table {{ width: 100%; border-collapse: collapse; background: #FFFFFF; border: 1px solid #E2E0D8; font-size: 13px; }}
  th, td {{ border: 1px solid #E2E0D8; padding: 8px 10px; text-align: left; vertical-align: top; }}
  th {{ background: #F3F2EE; font-weight: 600; }}
  .mono {{ font-family: 'JetBrains Mono', Consolas, monospace; font-size: 12px; word-break: break-all; }}
  .doc-card {{ background: #FFFFFF; border: 1px solid #E2E0D8; padding: 14px; margin-bottom: 12px; }}
  .meta {{ color: #6E6D68; font-size: 12px; margin-bottom: 6px; }}
  .excerpt {{ background: #F5F4F0; border-left: 3px solid #161613; padding: 8px 10px; margin-top: 6px; font-size: 13px; }}
  .ctx {{ color: #4A4945; font-size: 12px; margin-top: 4px; }}
  .muted {{ color: #6E6D68; font-size: 13px; }}
  .toolbar {{ display: flex; justify-content: flex-end; margin-bottom: 12px; }}
  .btn {{ background: #161613; color: #FFFFFF; border: none; padding: 6px 14px; font-size: 13px; cursor: pointer; }}
  @media print {{ .toolbar {{ display: none; }} body {{ background: #FFFFFF; margin: 0; }} }}
</style>
</head>
<body>
  <div class="toolbar"><button class="btn" onclick="window.print()">In / Lưu PDF (Ctrl+P)</button></div>
  <h1>Hồ sơ Xác minh OSINT — {ws_name}</h1>
  <div class="sub">Xuất từ Dupin 5-Layer OSINT Workbench · {now_str} · Chỉ gồm thông tin đã xác nhận ({len(dossier_items)} mục)</div>
  <h2>1. Danh mục Hồ sơ Đã Xác nhận (Verified Dossier)</h2>
  <table>
    <thead><tr><th style="width:22%">Trường thông tin</th><th style="width:48%">Nội dung Đã Xác nhận</th><th>Nguồn kiểm chứng</th></tr></thead>
    <tbody>{dossier_rows}</tbody>
  </table>
  <h2>2. Trích xuất Đọc sâu từ Tài liệu PDF / Excel / Scribd / Studocu Đã Xác nhận</h2>
  {deep_html}
  {claims_section}
</body>
</html>"""
