"""Deep Public Document Reader (PDF & Excel/XLSX) for Stalker++ OSINT Agents.

Downloads publicly accessible `.pdf` / `.xlsx` documents (strictly size-capped, no auth bypass)
and extracts exact matching lines/rows around target names, student IDs, or exact birth dates.
"""

from __future__ import annotations

import io
import re
from typing import Any, Optional

import httpx

from app.core.normalizer import normalize_text

MAX_DOC_BYTES = 12 * 1024 * 1024  # 12 MB safety ceiling


def _build_search_tokens(target_terms: list[str]) -> list[tuple[str, str]]:
    """Return list of (original_term, normalized_term) sorted longest-first."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for t in target_terms:
        clean = str(t or "").strip()
        if len(clean) < 3:
            continue
        norm = normalize_text(clean)
        key = norm or clean.lower()
        if key not in seen:
            seen.add(key)
            out.append((clean, key))
    out.sort(key=lambda pair: len(pair[1]), reverse=True)
    return out


def extract_matching_rows_from_pdf(
    pdf_bytes: bytes,
    target_terms: list[str],
    max_pages: int = 120,
    max_excerpts: int = 6,
) -> dict[str, Any]:
    """Parse text layer of a PDF and return exact matching lines + surrounding row context."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(pdf_bytes))
    total_pages = len(reader.pages)
    tokens = _build_search_tokens(target_terms)

    excerpts: list[dict[str, Any]] = []
    total_chars = 0
    header_hint = ""

    for page_idx in range(min(total_pages, max_pages)):
        try:
            page_text = reader.pages[page_idx].extract_text() or ""
        except Exception:
            continue
        total_chars += len(page_text.strip())
        lines = [ln.strip() for ln in page_text.splitlines() if ln.strip()]
        if page_idx == 0 and lines and not header_hint:
            header_hint = " | ".join(lines[:4])[:240]

        for line_idx, line in enumerate(lines):
            norm_line = normalize_text(line)
            raw_low = line.lower()
            matched_terms = [
                orig
                for orig, norm_t in tokens
                if (norm_t and norm_t in norm_line) or (orig.lower() in raw_low)
            ]
            if not matched_terms:
                continue

            start_i = max(0, line_idx - 1)
            end_i = min(len(lines), line_idx + 2)
            context_block = " \n ".join(lines[start_i:end_i])
            excerpts.append(
                {
                    "page": page_idx + 1,
                    "matched_terms": matched_terms,
                    "line": line[:400],
                    "context": context_block[:700],
                }
            )
            if len(excerpts) >= max_excerpts:
                break
        if len(excerpts) >= max_excerpts:
            break

    is_scanned = total_pages > 0 and total_chars < 40
    return {
        "doc_type": "pdf",
        "total_pages": total_pages,
        "scanned_pages_detected": is_scanned,
        "header_hint": header_hint,
        "excerpts": excerpts,
    }


def extract_matching_rows_from_xlsx(
    xlsx_bytes: bytes,
    target_terms: list[str],
    max_excerpts: int = 8,
) -> dict[str, Any]:
    """Parse an Excel workbook and return matching rows mapped against detected column headers."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(xlsx_bytes), read_only=True, data_only=True)
    tokens = _build_search_tokens(target_terms)
    excerpts: list[dict[str, Any]] = []
    sheet_names = list(wb.sheetnames)

    for sname in sheet_names[:10]:
        ws = wb[sname]
        headers: list[str] = []
        for row_idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
            vals = [str(c).strip() if c is not None else "" for c in row]
            non_empty = [v for v in vals if v]
            if not non_empty:
                continue
            row_joined = " | ".join(non_empty)
            if not headers and len(non_empty) >= 2 and any(
                h in row_joined.lower() for h in ("họ", "tên", "mssv", "mã", "ngày sinh", "lớp", "name", "id")
            ):
                headers = vals
                continue

            norm_row = normalize_text(row_joined)
            raw_low = row_joined.lower()
            matched_terms = [
                orig
                for orig, norm_t in tokens
                if (norm_t and norm_t in norm_row) or (orig.lower() in raw_low)
            ]
            if not matched_terms:
                continue

            if headers:
                pairs = [
                    f"{headers[i] or f'Col{i+1}'}: {vals[i]}"
                    for i in range(min(len(headers), len(vals)))
                    if vals[i]
                ]
                formatted = " · ".join(pairs)
            else:
                formatted = row_joined

            excerpts.append(
                {
                    "sheet": sname,
                    "row": row_idx,
                    "matched_terms": matched_terms,
                    "line": formatted[:500],
                    "context": formatted[:700],
                }
            )
            if len(excerpts) >= max_excerpts:
                break
        if len(excerpts) >= max_excerpts:
            break

    wb.close()
    return {
        "doc_type": "xlsx",
        "sheets": sheet_names,
        "scanned_pages_detected": False,
        "header_hint": "",
        "excerpts": excerpts,
    }


_DYNAMIC_DOC_URL_HINTS: tuple[str, ...] = (
    "/storage/download",
    "/downloadfile",
    "/download/",
    "/download",
    "/getfile",
    "/viewfile",
    "/attachments/",
    "/attachment/",
    "/tai-file",
    "/file-download",
    "static2.vietstock.vn",
    "cafef1.mediacdn.vn",
)


def is_inspectable_document_url(url: str) -> bool:
    """Detect both direct `.pdf`/`.xlsx` URLs AND dynamic click-to-download PDF endpoints."""
    raw_low = (url or "").lower()
    path_low = raw_low.split("?")[0]
    if path_low.endswith((".pdf", ".xlsx")):
        return True
    if ".edu." in raw_low and any(seg in raw_low for seg in ("/uploads/", "/files/", "download")):
        return True
    if any(hint in raw_low for hint in _DYNAMIC_DOC_URL_HINTS):
        return True
    if "file=" in raw_low and ".pdf" in raw_low:
        return True
    return False


async def fetch_and_inspect_document(
    url: str,
    target_terms: list[str],
    timeout: float = 10.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Download a public PDF/XLSX and extract matching rows for target_terms."""
    clean_url = url.strip()
    if not clean_url.startswith(("http://", "https://")):
        return {"ok": False, "url": clean_url, "error": "Unsupported URL scheme", "excerpts": []}

    async def _download(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get(
            clean_url,
            headers={"User-Agent": "StalkerPlusPlus-ResearchBot/1.0 (+public-osint)"},
            follow_redirects=True,
        )

    try:
        if client is not None:
            resp = await _download(client)
        else:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as temp_client:
                resp = await _download(temp_client)
        if resp.status_code != 200:
            return {
                "ok": False,
                "url": clean_url,
                "error": f"HTTP {resp.status_code}",
                "excerpts": [],
            }
        raw = resp.content
        if len(raw) > MAX_DOC_BYTES:
            return {
                "ok": False,
                "url": clean_url,
                "error": "Document exceeds 12 MB safety limit",
                "excerpts": [],
            }
        ctype = resp.headers.get("content-type", "").lower()
        low_path = clean_url.lower().split("?")[0]
        if "pdf" in ctype or low_path.endswith(".pdf") or raw[:4] == b"%PDF":
            parsed = extract_matching_rows_from_pdf(raw, target_terms)
            return {"ok": True, "url": clean_url, **parsed}
        if "spreadsheet" in ctype or low_path.endswith(".xlsx") or raw[:2] == b"PK":
            parsed = extract_matching_rows_from_xlsx(raw, target_terms)
            return {"ok": True, "url": clean_url, **parsed}
        return {"ok": False, "url": clean_url, "error": "Not a PDF/XLSX binary", "excerpts": []}
    except Exception as exc:
        return {
            "ok": False,
            "url": clean_url,
            "error": re.sub(r"\s+", " ", str(exc))[:160],
            "excerpts": [],
        }
