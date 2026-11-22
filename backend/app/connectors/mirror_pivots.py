"""Network Diagnostics, Wayback Machine Recovery, and Generalizable Secondary Document Mirror Pivoting."""

from __future__ import annotations

import re
from typing import Any, Optional
from urllib.parse import quote_plus

import httpx

# Generic non-document / directory URL segments that produce useless topic pages
JUNK_URL_SEGMENTS: tuple[str, ...] = (
    "help.studocu.com",
    "/institution/",
    "/course/",
    "/pub/dir/",
    "/hc/",
    "studocu.com/pl/",
    "studocu.com/de/",
    "studocu.com/row/institution/",
    "universite-detat-dhaiti",
    "marinetraffic.com",
    "ebay.com",
    "sweetwater.com",
    "aliexpress.com",
    "b-parts.com",
    "/auto-parts/",
    "amazon.com",
    "walmart.com",
    "rockauto.com",
    "autodoc.",
    "discogs.com",
    "partsyx.com",
    "shipfinder.com",
    "vesselfinder.com",
    "wasmarcade.com",
    "hanzii.net",
    "commons.wikimedia.org/wiki/category:",
)

# General Vietnamese/English document-type hint keywords (zero overfitting to any single school)
DOC_HINT_TERMS: tuple[str, ...] = (
    "ielts",
    "toeic",
    "toefl",
    "chuẩn đầu ra",
    "miễn học phần",
    "học bổng",
    "danh sách",
    "trúng tuyển",
    "quyết định",
    "thời khóa biểu",
    "lịch thi",
    "quân sự",
    "gdqp",
    "kết quả",
    "chứng chỉ",
    "giải thưởng",
)


def is_junk_category_url(url: str) -> bool:
    """Return True if URL is a generic category/help/directory page rather than a specific document/profile."""
    low = url.lower()
    return any(seg in low for seg in JUNK_URL_SEGMENTS)


def extract_root_org_domain(email_domain: str) -> str:
    """Convert subdomain like 'st.ueh.edu.vn' or 'sis.hust.edu.vn' into root institutional domain 'ueh.edu.vn'."""
    parts = [p for p in email_domain.lower().strip().split(".") if p]
    if len(parts) >= 4 and parts[-2] in ("edu", "gov", "org", "com", "ac"):
        return ".".join(parts[-3:])
    if len(parts) >= 3 and parts[-2] in ("edu", "gov", "org", "com", "ac"):
        return ".".join(parts[-3:])
    return email_domain.lower().strip()


async def diagnose_url_health(
    url: str,
    timeout: float = 8.0,
    client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Check whether a primary institutional URL is reachable, timed out, or returning 4xx/5xx."""
    try:
        if client is not None:
            resp = await client.head(url, follow_redirects=True)
        else:
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                resp = await temp_client.head(url, follow_redirects=True)
        return {
            "url": url,
            "reachable": 200 <= resp.status_code < 400,
            "status_code": resp.status_code,
            "diagnosis": "OK" if resp.status_code < 400 else f"HTTP {resp.status_code}",
        }
    except httpx.TimeoutException:
        return {
            "url": url,
            "reachable": False,
            "status_code": 0,
            "diagnosis": "CONNECTION_TIMEOUT (Likely de-indexed by Google; pivot to Wayback/Studocu/Scribd)",
        }
    except Exception as exc:
        return {
            "url": url,
            "reachable": False,
            "status_code": 0,
            "diagnosis": f"NETWORK_ERROR: {type(exc).__name__}",
        }


async def check_wayback_snapshot(
    url: str,
    timeout: float = 8.0,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[dict[str, str]]:
    """Query the public Internet Archive Wayback Machine Availability API for a dead/de-indexed URL."""
    api_url = f"https://archive.org/wayback/available?url={quote_plus(url.strip())}"
    try:
        if client is not None:
            resp = await client.get(api_url)
        else:
            async with httpx.AsyncClient(timeout=timeout) as temp_client:
                resp = await temp_client.get(api_url)
        if resp.status_code != 200:
            return None
        closest = (resp.json().get("archived_snapshots") or {}).get("closest") or {}
        if closest.get("available") and closest.get("url"):
            return {
                "archived_url": str(closest["url"]),
                "timestamp": str(closest.get("timestamp", "")),
                "original_url": url,
            }
    except Exception:
        return None
    return None


def _extract_prompt_doc_hints(raw_prompt: str, keywords: list[str]) -> list[str]:
    """Dynamically extract document-type keywords from the user's prompt (no hardcoded single-case bias)."""
    low = f"{raw_prompt} {' '.join(keywords)}".lower()
    found = [term for term in DOC_HINT_TERMS if term in low]
    return found[:3]


def build_mirror_pivot_queries(
    parsed: dict[str, Any],
    anchors: dict[str, Any],
    region: str = "auto",
) -> list[dict[str, str]]:
    """Synthesize region-aware mirror & public registry pivot queries (Global or VN)
    driven dynamically by the user's own anchors and document hints (zero overfitting).
    """
    from app.connectors.web_search import infer_query_region

    queries: list[dict[str, str]] = []
    name = parsed.get("target_name", "")
    orgs = parsed.get("organizations", []) or anchors.get("inferred_orgs", [])
    primary_org = orgs[0].split("(")[0].strip() if orgs else ""
    neg_str = " ".join(f'-"{n}"' for n in parsed.get("negative_keywords", []))
    raw_blob = f"{parsed.get('raw_prompt', '')} {name} {primary_org}"
    resolved_region = infer_query_region(raw_blob, parsed.get("region", region))
    doc_hints = _extract_prompt_doc_hints(parsed.get("raw_prompt", ""), parsed.get("keywords", []))
    hint_str = " ".join(doc_hints[:2]) if doc_hints else ("danh sách" if resolved_region == "vn" else "profile")

    # 1. Highest-Entropy Exact Student/Member ID Sweeps (NEVER over-constrain an exact ID with extra keywords!)
    cohort_fallback_queries: list[dict[str, str]] = []
    covered_sids_by_org_domain: set[str] = set()
    for em in anchors.get("emails", [])[:1]:
        root_dom = extract_root_org_domain(em.get("domain", ""))
        if root_dom and (".edu" in root_dom or ".ac." in root_dom):
            if em.get("embedded_ids"):
                sid_hint = em["embedded_ids"][0]
                covered_sids_by_org_domain.add(sid_hint)
                queries.append(
                    {
                        "strategy": "mirror:org_domain_portal",
                        "query": f'site:{root_dom} "{sid_hint}"',
                    }
                )
            else:
                queries.append(
                    {
                        "strategy": "mirror:org_domain_portal",
                        "query": f'site:{root_dom} "{name}" {hint_str}'.strip(),
                    }
                )

    VN_ORG_OFFICIAL_ALIASES: dict[str, str] = {
        "hcmut": "Bách Khoa",
        "hust": "Bách Khoa",
        "ussh": "Nhân Văn",
        "hcmussh": "Nhân Văn",
        "ueh": "Kinh tế",
        "hcmus": "Khoa học Tự nhiên",
        "uit": "Công nghệ Thông tin",
        "ftu": "Ngoại thương",
        "neu": "Kinh tế Quốc dân",
        "uel": "Kinh tế Luật",
        "sgu": "Sài Gòn",
        "hnue": "Sư phạm",
        "ump": "Y Dược",
    }

    for sid_info in anchors.get("student_ids", [])[:2]:
        sid = sid_info["student_id"]
        cohort = sid_info.get("cohort", "")
        sid_inst = sid_info.get("institution") or primary_org
        vn_official = VN_ORG_OFFICIAL_ALIASES.get(sid_inst.lower(), "")
        if name:
            queries.append(
                {
                    "strategy": "mirror:student_id_name",
                    "query": f'"{name}" {sid}'.strip(),
                }
            )
        queries.append(
            {
                "strategy": "mirror:student_id_exact",
                "query": f'"{sid}" {vn_official or sid_inst}'.strip(),
            }
        )
        if resolved_region == "vn":
            queries.append(
                {
                    "strategy": "mirror:scribd_student_id",
                    "query": f'site:scribd.com/document "{sid}"',
                }
            )
            queries.append(
                {
                    "strategy": "mirror:studocu_student_id",
                    "query": f'site:studocu.com/vn/document "{sid}"',
                }
            )
            if sid not in covered_sids_by_org_domain:
                queries.append(
                    {
                        "strategy": "mirror:edu_vn_student_id",
                        "query": f'site:edu.vn "{sid}"',
                    }
                )
        if cohort and sid_inst:
            cohort_fallback_queries.extend(
                [
                    {
                        "strategy": "mirror:scribd_cohort_list",
                        "query": f"site:scribd.com/document {sid_inst} {cohort} {hint_str} danh sách",
                    },
                    {
                        "strategy": "mirror:studocu_cohort_list",
                        "query": f"site:studocu.com/vn/document {sid_inst} {cohort} {hint_str} danh sách",
                    },
                    {
                        "strategy": "mirror:scribd_cohort_prefix",
                        "query": f"site:scribd.com/document {sid_inst} {cohort} {sid[:6]}",
                    },
                    {
                        "strategy": "mirror:studocu_cohort_prefix",
                        "query": f"site:studocu.com/vn/document {sid_inst} {cohort} {sid[:6]}",
                    },
                ]
            )

    # 3. Exact Official Document Number pivots (e.g. 2623/QĐ-...)
    for doc_no in anchors.get("doc_numbers", [])[:2]:
        queries.append(
            {
                "strategy": "mirror:doc_number_pivot",
                "query": f'"{doc_no}" (site:studocu.com/vn/document OR site:scribd.com/document OR filetype:pdf)',
            }
        )

    # 4. Class code / Course section pivots
    for cls_code in anchors.get("class_codes", [])[:2]:
        queries.append(
            {
                "strategy": "mirror:class_code_pivot",
                "query": f'"{cls_code}" {primary_org} {hint_str}'.strip(),
            }
        )

    # 5. Region-aware Public Registry, Academic, Relational PDF & Profile Mirrors
    dob = parsed.get("birth_date", "")
    related_people = parsed.get("related_people") or []
    for rp in related_people[:1]:
        rp_name = str(rp.get("name") or "").strip()
        if rp_name and name:
            queries.append(
                {
                    "strategy": "mirror:pdf_relational",
                    "query": f'"{name}" "{rp_name}" filetype:pdf {neg_str}'.strip(),
                }
            )
            if resolved_region == "vn":
                queries.append(
                    {
                        "strategy": "mirror:pdf_governance_report",
                        "query": f'"{rp_name}" ("báo cáo quản trị" OR "người có liên quan") filetype:pdf {neg_str}'.strip(),
                    }
                )
    if resolved_region == "vn":
        if name and dob:
            queries.append(
                {
                    "strategy": "mirror:edu_vn_exact_dob",
                    "query": f'site:edu.vn "{name}" "{dob}" {neg_str}'.strip(),
                }
            )
        if name and primary_org:
            vn_official_org = VN_ORG_OFFICIAL_ALIASES.get(primary_org.lower(), "")
            if vn_official_org:
                queries.append(
                    {
                        "strategy": "mirror:vn_official_org",
                        "query": f'"{name}" {vn_official_org} {neg_str}'.strip(),
                    }
                )
            queries.append(
                {
                    "strategy": "mirror:scribd_name",
                    "query": f'"{name}" scribd {neg_str}'.strip(),
                }
            )
            queries.append(
                {
                    "strategy": "mirror:edu_vn_name",
                    "query": f'site:edu.vn "{name}" {neg_str}'.strip(),
                }
            )
            queries.append(
                {
                    "strategy": "mirror:pdf_public_list",
                    "query": f'"{name}" "{primary_org}" filetype:pdf {neg_str}'.strip(),
                }
            )
            queries.append(
                {
                    "strategy": "mirror:studocu_name",
                    "query": f'site:studocu.com/vn/document "{name}" "{primary_org}" {neg_str}'.strip(),
                }
            )
        elif name and len(name.split()) >= 3:
            queries.append(
                {
                    "strategy": "mirror:pdf_name_only",
                    "query": f'"{name}" filetype:pdf {neg_str}'.strip(),
                }
            )
    else:
        # Global strategy: LinkedIn, GitHub, ORCID/Scholar, global .edu/.ac, and public PDF CV/papers
        org_q = f'"{primary_org}"' if primary_org else ""
        if name:
            queries.append(
                {
                    "strategy": "mirror:global_linkedin",
                    "query": f'site:linkedin.com/in "{name}" {org_q} {neg_str}'.strip(),
                }
            )
            queries.append(
                {
                    "strategy": "mirror:global_github",
                    "query": f'site:github.com "{name}" {org_q} {neg_str}'.strip(),
                }
            )
            queries.append(
                {
                    "strategy": "mirror:global_pdf",
                    "query": f'"{name}" {org_q} filetype:pdf {neg_str}'.strip(),
                }
            )
            queries.append(
                {
                    "strategy": "mirror:global_orcid",
                    "query": f'site:orcid.org "{name}" {neg_str}'.strip(),
                }
            )
            if primary_org:
                queries.append(
                    {
                        "strategy": "mirror:global_edu",
                        "query": f'site:.edu "{name}" {org_q} {neg_str}'.strip(),
                    }
                )

    # 6. Append broad cohort-level fallbacks AFTER exact-ID & exact-name mirrors so they never crowd out direct hits
    queries.extend(cohort_fallback_queries)

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for q in queries:
        if q["query"] not in seen:
            seen.add(q["query"])
            unique.append(q)
    return unique
