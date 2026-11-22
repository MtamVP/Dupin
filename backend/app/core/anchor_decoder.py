"""High-Entropy OSINT Anchor Decoder (Student IDs, Academic Emails, Document Numbers) & ID Bracketing."""

from __future__ import annotations

import re
from typing import Any, Optional

# Known Vietnamese university email domains -> canonical institution names
ACADEMIC_EMAIL_DOMAINS: dict[str, str] = {
    "st.ueh.edu.vn": "UEH (Đại học Kinh tế TP.HCM)",
    "ueh.edu.vn": "UEH (Đại học Kinh tế TP.HCM)",
    "hcmut.edu.vn": "HCMUT (ĐH Bách Khoa TP.HCM)",
    "sis.hust.edu.vn": "HUST (ĐH Bách Khoa Hà Nội)",
    "hust.edu.vn": "HUST (ĐH Bách Khoa Hà Nội)",
    "gm.uit.edu.vn": "UIT (ĐH Công nghệ Thông tin)",
    "uit.edu.vn": "UIT (ĐH Công nghệ Thông tin)",
    "fpt.edu.vn": "Đại học FPT",
    "stu.ptit.edu.vn": "PTIT (Học viện CNBCVT)",
    "st.neu.edu.vn": "NEU (ĐH Kinh tế Quốc dân)",
    "vnu.edu.vn": "ĐH Quốc gia Hà Nội (VNU)",
    "vnuhcm.edu.vn": "ĐH Quốc gia TP.HCM",
}

EMAIL_RE = re.compile(r"\b([a-zA-Z0-9._%+-]+)@([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b")
URL_STRIP_RE = re.compile(r"https?://\S+", re.IGNORECASE)
DOC_NUMBER_RE = re.compile(
    r"\b(\d{1,5}/(?:QĐ|TB|CV|KH|ĐHKT|BGDĐT)[A-Za-zÀ-ỹ0-9\-/]*)\b", re.IGNORECASE
)
STUDENT_ID_RE = re.compile(r"\b(\d{7,12})\b")
LABELED_ALNUM_SID_RE = re.compile(
    r"\b(?:mssv|msv|mã\s*(?:số\s*)?(?:sinh\s*viên|sv)|student\s*id)[:\s#]+([A-Za-z0-9]{6,14})\b",
    re.IGNORECASE,
)
CLASS_CODE_RE = re.compile(r"\b((?:DH|K|CQ|CLC)\d{2}[A-Z]{2,5}\d{2,4})\b")
LHP_CODE_RE = re.compile(r"\b(\d{2}[CD]\d[A-Z]{3}\d{6,8})\b")


def decode_student_id_schema(student_id: str, org_hint: str = "") -> dict[str, Any]:
    """Reverse-engineer intake year / cohort metadata from Vietnamese university student IDs."""
    sid = student_id.strip()
    info: dict[str, Any] = {"student_id": sid}
    org_low = org_hint.lower()

    # UEH 11-digit pattern: e.g. 31251029999 -> 31 (bachelor), 25 (intake 2025 = K51), 102 (campus)
    if len(sid) == 11 and sid.isdigit() and sid.startswith("31") and ("ueh" in org_low or sid[4:7] == "102"):
        intake_yy = int(sid[2:4])
        intake_year = 2000 + intake_yy
        cohort = intake_year - 1974  # 2025 -> K51
        info.update(
            {
                "institution": "UEH",
                "intake_year": intake_year,
                "cohort": f"K{cohort}",
                "campus_code": sid[4:7],
                "sequence_num": int(sid[7:]),
            }
        )
    # HUST 8-digit pattern starting with 20xx (e.g. 20225123)
    elif len(sid) == 8 and sid.isdigit() and sid.startswith("20"):
        info["intake_year"] = int(sid[:4])
        if "hust" in org_low or "bách khoa hà nội" in org_low:
            info["institution"] = "HUST"
    # HCMUT (ĐH Bách Khoa TP.HCM) 7-digit pattern: YY + program digit + 4-digit seq (e.g. 2550999 -> K25)
    elif len(sid) == 7 and sid.isdigit() and 15 <= int(sid[:2]) <= 30:
        intake_yy = int(sid[:2])
        info["intake_year"] = 2000 + intake_yy
        info["cohort"] = f"K{intake_yy}"
        if any(k in org_low for k in ("hcmut", "bách khoa", "bach khoa", "bk")):
            info["institution"] = "HCMUT"
    # UIT / VNU-HCM 8-digit pattern starting with YY (e.g. 22520123 -> K22)
    elif len(sid) == 8 and sid.isdigit() and 15 <= int(sid[:2]) <= 30:
        intake_yy = int(sid[:2])
        info["intake_year"] = 2000 + intake_yy
        info["cohort"] = f"K{intake_yy}"
        if "uit" in org_low:
            info["institution"] = "UIT"
    return info


def decode_high_entropy_anchors(text: str) -> dict[str, Any]:
    """Extract & decode unique OSINT anchors: academic emails, student IDs, doc numbers, class/LHP codes."""
    emails: list[dict[str, Any]] = []
    student_ids: list[dict[str, Any]] = []
    inferred_orgs: list[str] = []
    seen_sids: set[str] = set()

    for local_part, domain in EMAIL_RE.findall(text):
        dom_low = domain.lower()
        org = ACADEMIC_EMAIL_DOMAINS.get(dom_low, "")
        if org and org not in inferred_orgs:
            inferred_orgs.append(org)

        embedded_ids = re.findall(r"\d{7,12}", local_part)
        email_info: dict[str, Any] = {
            "email": f"{local_part}@{dom_low}",
            "local_part": local_part,
            "domain": dom_low,
            "inferred_org": org,
            "embedded_ids": embedded_ids,
        }
        emails.append(email_info)

        for sid in embedded_ids:
            if sid not in seen_sids:
                seen_sids.add(sid)
                student_ids.append(decode_student_id_schema(sid, org_hint=org or dom_low))

    text_no_urls = URL_STRIP_RE.sub(" ", text)
    org_context = " ".join(inferred_orgs) + " " + text_no_urls
    for sid in LABELED_ALNUM_SID_RE.findall(text_no_urls):
        sid_clean = sid.strip()
        if any(c.isdigit() for c in sid_clean) and sid_clean not in seen_sids:
            seen_sids.add(sid_clean)
            student_ids.append(decode_student_id_schema(sid_clean, org_hint=org_context))

    for sid in STUDENT_ID_RE.findall(text_no_urls):
        # Skip Vietnamese phone numbers (10 digits starting with 03/05/07/08/09)
        if len(sid) == 10 and sid.startswith(("03", "05", "07", "08", "09")):
            continue
        if sid not in seen_sids:
            seen_sids.add(sid)
            student_ids.append(decode_student_id_schema(sid, org_hint=org_context))

    doc_numbers = sorted(set(DOC_NUMBER_RE.findall(text)))
    class_codes = sorted(set(CLASS_CODE_RE.findall(text)))
    lhp_codes = sorted(set(LHP_CODE_RE.findall(text)))

    return {
        "emails": emails,
        "student_ids": student_ids,
        "doc_numbers": doc_numbers,
        "class_codes": class_codes,
        "lhp_codes": lhp_codes,
        "inferred_orgs": inferred_orgs,
    }


def bracket_numeric_ids(
    target_id: int,
    observed_pairs: list[tuple[int, str]],
) -> dict[str, Any]:
    """Perform ID Bracketing / Interpolation with calibrated uncertainty (Anti-Confirmation-Bias).

    Given a target numeric ID (e.g. 31251029999) and observed `(id, category_label)` pairs from
    public lists, finds the tightest lower and upper bounds and returns ranked candidate hypotheses
    with calibrated probabilities instead of overconfident 100% claims.
    """
    if not observed_pairs:
        return {"target_id": target_id, "candidates": []}

    sorted_pairs = sorted(observed_pairs, key=lambda x: x[0])
    lower: Optional[tuple[int, str]] = None
    upper: Optional[tuple[int, str]] = None

    for oid, label in sorted_pairs:
        if oid == target_id:
            return {
                "target_id": target_id,
                "exact_match": label,
                "lower_bound": (oid, label),
                "upper_bound": (oid, label),
                "candidates": [{"label": label, "probability": 0.98, "basis": "Exact ID match"}],
            }
        if oid < target_id:
            lower = (oid, label)
        elif oid > target_id and upper is None:
            upper = (oid, label)
            break

    candidates: list[dict[str, Any]] = []
    if lower and upper:
        if lower[1] == upper[1]:
            candidates.append(
                {
                    "label": lower[1],
                    "probability": 0.92,
                    "basis": f"Sandwiched between {lower[0]} and {upper[0]} (same category)",
                }
            )
        else:
            dist_low = target_id - lower[0]
            dist_high = upper[0] - target_id
            total_span = max(1, dist_low + dist_high)
            # Inverse-distance weighting with conservative cap (<= 0.80) to avoid Confirmation Bias
            p_low = round(min(0.80, max(0.15, (1.0 - dist_low / total_span) * 0.85)), 2)
            p_high = round(min(0.80, max(0.15, (1.0 - dist_high / total_span) * 0.85)), 2)
            p_mid = round(max(0.05, 1.0 - min(0.95, p_low + p_high)), 2)
            candidates = sorted(
                [
                    {"label": lower[1], "probability": p_low, "basis": f"Lower neighbor {lower[0]} (Δ={dist_low})"},
                    {"label": upper[1], "probability": p_high, "basis": f"Upper neighbor {upper[0]} (Δ={dist_high})"},
                ],
                key=lambda x: x["probability"],
                reverse=True,
            )
            if total_span > 2:
                candidates.append(
                    {
                        "label": f"Intermediate category between '{lower[1]}' and '{upper[1]}'",
                        "probability": p_mid,
                        "basis": f"Unobserved gap of {total_span - 1} IDs — verify directly before concluding",
                    }
                )
    elif lower:
        candidates.append(
            {"label": lower[1], "probability": 0.55, "basis": f"Nearest lower ID {lower[0]} (no upper bound)"}
        )
    elif upper:
        candidates.append(
            {"label": upper[1], "probability": 0.55, "basis": f"Nearest upper ID {upper[0]} (no lower bound)"}
        )

    return {
        "target_id": target_id,
        "lower_bound": lower,
        "upper_bound": upper,
        "candidates": candidates,
    }
