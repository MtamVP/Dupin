"""Deep Public Document Reader (PDF & Excel/XLSX) for Stalker++ OSINT Agents.

Downloads publicly accessible `.pdf` / `.xlsx` documents (strictly size-capped, no auth bypass)
and extracts exact matching lines/rows around target names, student IDs, or exact birth dates.
"""

from __future__ import annotations

import asyncio
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


_EMBEDDED_LINK_ATTR_RE = re.compile(
    r"""(?:href|src|data)\s*=\s*["']([^"'\s<>]{4,400})["']""",
    re.IGNORECASE,
)
_GDRIVE_FILE_RE = re.compile(
    r"https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]{16,64})",
    re.IGNORECASE,
)
_ROSTER_DOB_RE = re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.](?:19[5-9]\d|20[0-2]\d))\b")
_ROSTER_CLASS_RE = re.compile(r"\b(\d{1,2}[A-Z]{1,3}\d{1,2}|(?:DH|K|CQ|CLC)\d{2}[A-Z]{2,5}\d{1,4})\b")
_ROSTER_FULLNAME_RE = re.compile(
    r"\b([A-ZÀ-Ỹ][a-zà-ỹ]+(?:[ \t]+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,4})\b"
)


def extract_embedded_document_links(base_url: str, html_text: str, max_links: int = 5) -> list[str]:
    """Discover public PDF/XLSX/Drive document links embedded inside an HTML portal or article page."""
    from urllib.parse import urljoin, urlparse

    if not html_text:
        return []

    found: list[str] = []
    seen: set[str] = set()

    # 1. Direct href/src/data links inside <a>, <iframe>, <embed>, <object>
    for raw_ref in _EMBEDDED_LINK_ATTR_RE.findall(html_text):
        ref = raw_ref.strip().replace("&amp;", "&")
        if ref.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        abs_url = urljoin(base_url, ref)
        parsed = urlparse(abs_url)
        if parsed.scheme not in ("http", "https"):
            continue
        host_low = (parsed.hostname or "").lower()
        if host_low in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host_low.startswith(("10.", "192.168.")):
            continue

        # Convert Google Drive viewer links inside iframes/anchors into direct public download URLs
        gd_m = _GDRIVE_FILE_RE.search(abs_url)
        if gd_m:
            abs_url = f"https://drive.google.com/uc?export=download&id={gd_m.group(1)}"
        elif not is_inspectable_document_url(abs_url):
            continue

        if abs_url not in seen:
            seen.add(abs_url)
            found.append(abs_url)
            if len(found) >= max_links:
                break

    # 2. Fallback scan for bare Google Drive file links in scripts/JSON blobs
    if len(found) < max_links:
        for fid in _GDRIVE_FILE_RE.findall(html_text):
            dl_url = f"https://drive.google.com/uc?export=download&id={fid}"
            if dl_url not in seen:
                seen.add(dl_url)
                found.append(dl_url)
                if len(found) >= max_links:
                    break

    return found


_ROSTER_IMAGE_URL_RE = re.compile(
    r"https?://[^\s\"'<>]+\.(?:png|jpg|jpeg|webp)(?:\?[^\s\"'<>]*)?",
    re.IGNORECASE,
)
_ROSTER_CLASS_IMG_HINT_RE = re.compile(
    r"(?:^|[/_-])((?:10|11|12|[6-9])[a-z]{1,3}\d{0,2})(?:[_.-]|$)",
    re.IGNORECASE,
)


def extract_roster_image_links(
    base_url: str,
    html_text: str,
    grade_hint: Optional[int] = None,
    max_images: int = 16,
) -> list[str]:
    """Extract class-roster slide images (e.g. `12a10_...png` on *.hcm.edu.vn portals) while filtering out banners/logos."""
    if not html_text:
        return []
    raw_urls = _ROSTER_IMAGE_URL_RE.findall(html_text)
    candidates: list[str] = []
    seen: set[str] = set()
    skip_markers = (
        "advertising",
        "anh_dai_dien",
        "logohcm",
        "logo",
        "banner",
        "bia-web",
        "bia_web",
        "icon",
        "favicon",
        "avatar",
        "share",
        "vlib.png",
        "cosodulieunganh",
    )
    class_matched: list[str] = []
    other_matched: list[str] = []
    for u in raw_urls:
        clean_u = u.strip().rstrip("\"',;)")
        low_u = clean_u.lower()
        if any(sk in low_u for sk in skip_markers):
            continue
        base_path = low_u.split("?")[0]
        if base_path in seen:
            continue
        fname = base_path.rsplit("/", 1)[-1]
        m_cls = _ROSTER_CLASS_IMG_HINT_RE.search(fname)
        is_generic_roster_img = any(
            k in low_u for k in ("uploadimages/news", "tailen/anh", "danh-sach", "ds-")
        )
        if not m_cls and not is_generic_roster_img:
            continue
        if grade_hint is not None:
            if m_cls:
                if not m_cls.group(1).startswith(str(grade_hint)):
                    continue
                seen.add(base_path)
                class_matched.append(clean_u.split("?")[0])
                continue
            # Skip non-class cover thumbnails when we already have explicit class-named images
            seen.add(base_path)
            other_matched.append(clean_u.split("?")[0])
            continue
        seen.add(base_path)
        if m_cls:
            class_matched.append(clean_u.split("?")[0])
        else:
            other_matched.append(clean_u.split("?")[0])
    ordered = class_matched if class_matched else other_matched
    return ordered[:max_images]


async def scan_roster_portal_page(
    url: str,
    target_terms: list[str],
    birth_year: Optional[int] = None,
    db_path: Optional[Any] = None,
    timeout: float = 10.0,
    max_ocr_images: int = 12,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Deep-inspect a school/org roster HTML portal page across ALL 3 formats:
    1. Inline HTML tables (like THCS Nguyen Gia Thieu's 1.6 MB HTML table)
    2. Embedded PDF/XLSX/Google Drive attachments
    3. Embedded class-roster slide images (`12a10.png`...) via batched Gemini Vision OCR!
    """
    import base64
    from app.connectors.web_fetcher import clean_html_to_text

    clean_url = (url or "").strip()
    out: dict[str, Any] = {
        "ok": False,
        "url": clean_url,
        "title": "",
        "attachments": [],
        "html_excerpts": [],
        "ocr_excerpts": [],
        "scanned_image_count": 0,
    }
    if not clean_url.startswith(("http://", "https://")):
        return out

    async def _get(c: httpx.AsyncClient, u: str) -> httpx.Response:
        return await c.get(
            u,
            headers={"User-Agent": "Dupin-ResearchBot/2.0 (+public-osint)"},
            follow_redirects=True,
        )

    try:
        if client is not None:
            resp = await _get(client, clean_url)
        else:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as temp_c:
                resp = await _get(temp_c, clean_url)
        if resp.status_code != 200:
            return out
        html_body = resp.text[:2_500_000]
        title, clean_txt, _ = clean_html_to_text(html_body)
        out["ok"] = True
        out["title"] = title
        out["attachments"] = extract_embedded_document_links(str(resp.url), html_body, max_links=5)

        # 1. Check inline HTML tables directly for target_terms
        norm_txt = normalize_text(clean_txt)
        for term in target_terms:
            nt = normalize_text(term)
            if not nt or len(nt) < 4:
                continue
            pos = norm_txt.find(nt)
            if pos >= 0:
                # Map approximate window in original clean_txt
                raw_pos = clean_txt.lower().find(term.lower())
                anchor = raw_pos if raw_pos >= 0 else min(pos, max(0, len(clean_txt) - 1))
                snippet_line = clean_txt[max(0, anchor - 90) : anchor + 170].strip()
                out["html_excerpts"].append(
                    {
                        "page": 1,
                        "matched_terms": [term],
                        "line": snippet_line,
                        "context": snippet_line,
                    }
                )
                break

        # 2. If no inline HTML text hit and no PDF/XLSX attachment, inspect embedded class-roster images via Vision OCR!
        if not out["html_excerpts"] and not out["attachments"] and db_path is not None:
            grade_hint: Optional[int] = None
            yr_m = re.search(r"(20\d{2})\s*[-–]\s*(20\d{2})", f"{title} {clean_url}")
            if birth_year and yr_m:
                start_yr = int(yr_m.group(1))
                est_grade = start_yr - int(birth_year) - 5  # e.g., 2024 - 2007 - 5 = 12
                if 6 <= est_grade <= 12:
                    grade_hint = est_grade

            img_urls = extract_roster_image_links(str(resp.url), html_body, grade_hint=grade_hint, max_images=max_ocr_images)
            if not img_urls and grade_hint is not None:
                img_urls = extract_roster_image_links(str(resp.url), html_body, grade_hint=None, max_images=max_ocr_images)

            if img_urls:
                from app.core.key_pool import IntegrationStore
                from app.core.llm_provider import GeminiProvider

                int_store = IntegrationStore(db_path)
                active_keys = [k for k in int_store.list_keys("gemini") if k.get("enabled")]
                pool_api_keys: list[str] = []
                seen_k_ids: set[str] = set()
                for _ in range(max(1, len(active_keys))):
                    ko = int_store.acquire_key("gemini")
                    if ko and ko["id"] not in seen_k_ids and ko.get("api_key"):
                        seen_k_ids.add(ko["id"])
                        pool_api_keys.append(ko["api_key"])
                if pool_api_keys:
                    ocr_terms_str = ", ".join(target_terms[:3])
                    ocr_prompt = (
                        f"Check if ANY student row in this Vietnamese school class roster image matches "
                        f"these target clues: [{ocr_terms_str}]. "
                        "If YES, reply ONLY with: FOUND: <full exact row including class name, STT, full name, DOB/gender>. "
                        "If NO match is present in the image, reply ONLY with: NONE."
                    )

                    async def _ocr_one(idx: int, img_u: str) -> Optional[dict[str, Any]]:
                        api_key = pool_api_keys[idx % len(pool_api_keys)]
                        try:
                            async with httpx.AsyncClient(timeout=15.0, verify=False) as ic:
                                ir = await ic.get(img_u, follow_redirects=True)
                                if ir.status_code != 200 or len(ir.content) < 4000 or len(ir.content) > 4_000_000:
                                    return None
                                b64 = base64.b64encode(ir.content).decode("ascii")
                                mime = ir.headers.get("content-type", "image/png").split(";")[0].strip() or "image/png"
                                ans = await GeminiProvider(api_key, "gemini-3.5-flash-lite", timeout=25.0).analyze_image_and_text(
                                    ocr_prompt, b64, mime_type=mime
                                )
                                ans_clean = (ans or "").strip()
                                if ans_clean and ans_clean.upper() != "NONE" and not ans_clean.upper().startswith("NONE"):
                                    body = ans_clean[6:].strip(" :") if ans_clean.upper().startswith("FOUND") else ans_clean
                                    fname = img_u.rsplit("/", 1)[-1]
                                    return {
                                        "page": 1,
                                        "matched_terms": target_terms[:2],
                                        "line": f"[{fname}] {body}",
                                        "context": f"Ảnh danh sách lớp ({img_u}): {body}",
                                        "image_url": img_u,
                                    }
                        except Exception:
                            return None
                        return None

                    # Scan images in parallel batches of 6 rotating across all Gemini keys so 18 class slides finish in ~5s!
                    sem = asyncio.Semaphore(min(6, max(2, len(pool_api_keys) * 2)))

                    async def _guarded(idx: int, u_item: str) -> Optional[dict[str, Any]]:
                        async with sem:
                            return await _ocr_one(idx, u_item)

                    ocr_results = await asyncio.gather(*(_guarded(i, u) for i, u in enumerate(img_urls)), return_exceptions=True)
                    out["scanned_image_count"] = len(img_urls)
                    for r_item in ocr_results:
                        if isinstance(r_item, dict):
                            out["ocr_excerpts"].append(r_item)
        return out
    except Exception:
        return out


async def fetch_page_and_find_attachments(
    url: str,
    timeout: float = 8.0,
    max_links: int = 4,
    client: Optional[httpx.AsyncClient] = None,
) -> list[str]:
    """Fetch a public HTML page (e.g., school/org roster article) and extract embedded PDF/XLSX links."""
    clean_url = (url or "").strip()
    if not clean_url.startswith(("http://", "https://")):
        return []
    if is_inspectable_document_url(clean_url):
        return [clean_url]

    async def _get(c: httpx.AsyncClient) -> httpx.Response:
        return await c.get(
            clean_url,
            headers={"User-Agent": "Dupin-ResearchBot/2.0 (+public-osint)"},
            follow_redirects=True,
        )

    try:
        if client is not None:
            resp = await _get(client)
        else:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as temp_client:
                resp = await _get(temp_client)
        if resp.status_code != 200:
            return []
        ctype = resp.headers.get("content-type", "").lower()
        if "pdf" in ctype or "spreadsheet" in ctype:
            return [clean_url]
        if "html" not in ctype and "text" not in ctype:
            return []
        html_body = resp.text[:1_500_000]
        return extract_embedded_document_links(str(resp.url), html_body, max_links=max_links)
    except Exception:
        return []


def extract_roster_candidates_from_excerpts(
    excerpts: list[dict[str, Any]],
    partial_name: str,
) -> list[dict[str, Any]]:
    """Expand partial names into structured candidate identities from matched PDF/XLSX table rows.

    Example row: '12A13 13 Trần Thị Minh Ngọc 18/12/2007' matched by 'Minh Ngọc'
    -> {'full_name': 'Trần Thị Minh Ngọc', 'birth_date': '18/12/2007', 'class_code': '12A13', ...}
    """
    partial_norm = normalize_text(partial_name)
    if not partial_norm:
        return []

    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    for ex in excerpts:
        line = str(ex.get("line") or "").strip()
        if not line:
            continue

        # Find the capitalized name span in this row that contains the partial target name
        best_full_name = ""
        for m in _ROSTER_FULLNAME_RE.finditer(line):
            cand = m.group(1).strip()
            cand_norm = normalize_text(cand)
            if partial_norm in cand_norm and len(cand.split()) >= 2:
                if len(cand) > len(best_full_name):
                    best_full_name = cand

        if not best_full_name:
            continue

        dob_m = _ROSTER_DOB_RE.search(line)
        birth_date = ""
        birth_year: Optional[int] = None
        if dob_m:
            raw_d = dob_m.group(1)
            parts = re.split(r"[/\-.]", raw_d)
            if len(parts) == 3 and all(p.isdigit() for p in parts):
                d_i, m_i, y_i = int(parts[0]), int(parts[1]), int(parts[2])
                if 1 <= d_i <= 31 and 1 <= m_i <= 12:
                    birth_date = f"{d_i:02d}/{m_i:02d}/{y_i}"
                    birth_year = y_i

        cls_m = _ROSTER_CLASS_RE.search(line)
        class_code = cls_m.group(1) if cls_m else ""

        sid_m = re.search(r"\b(\d{7,12})\b", line)
        student_id = sid_m.group(1) if sid_m else ""

        dedup_key = (normalize_text(best_full_name), birth_date or class_code)
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        candidates.append(
            {
                "full_name": best_full_name,
                "birth_date": birth_date,
                "birth_year": birth_year,
                "class_code": class_code,
                "student_id": student_id,
                "page": ex.get("page"),
                "row_line": line[:240],
            }
        )

    return candidates
