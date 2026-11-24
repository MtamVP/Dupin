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

# Public Vietnamese CCCD 12-digit province codes (Circular 07/2016/TT-BCA, 63 provinces/cities)
VN_CCCD_PROVINCE_CODES: dict[str, str] = {
    "001": "Hà Nội", "002": "Hà Giang", "004": "Cao Bằng", "006": "Bắc Kạn",
    "008": "Tuyên Quang", "010": "Lào Cai", "011": "Điện Biên", "012": "Lai Châu",
    "014": "Sơn La", "015": "Yên Bái", "017": "Hòa Bình", "019": "Thái Nguyên",
    "020": "Lạng Sơn", "022": "Quảng Ninh", "024": "Bắc Giang", "025": "Phú Thọ",
    "026": "Vĩnh Phúc", "027": "Bắc Ninh", "030": "Hải Dương", "031": "Hải Phòng",
    "033": "Hưng Yên", "034": "Thái Bình", "035": "Hà Nam", "036": "Nam Định",
    "037": "Ninh Bình", "038": "Thanh Hóa", "040": "Nghệ An", "042": "Hà Tĩnh",
    "044": "Quảng Bình", "045": "Quảng Trị", "046": "Thừa Thiên Huế", "048": "Đà Nẵng",
    "049": "Quảng Nam", "051": "Quảng Ngãi", "052": "Bình Định", "054": "Phú Yên",
    "056": "Khánh Hòa", "058": "Ninh Thuận", "060": "Bình Thuận", "062": "Kon Tum",
    "064": "Gia Lai", "066": "Đắk Lắk", "067": "Đắk Nông", "068": "Lâm Đồng",
    "070": "Bình Phước", "072": "Tây Ninh", "074": "Bình Dương", "075": "Đồng Nai",
    "077": "Bà Rịa - Vũng Tàu", "079": "TP.HCM", "080": "Long An", "082": "Tiền Giang",
    "083": "Bến Tre", "084": "Trà Vinh", "086": "Vĩnh Long", "087": "Đồng Tháp",
    "089": "An Giang", "091": "Kiên Giang", "092": "Cần Thơ", "093": "Hậu Giang",
    "094": "Sóc Trăng", "095": "Bạc Liêu", "096": "Cà Mau",
}

VN_PLATE_PROVINCE_CODES: dict[str, str] = {
    "29": "Hà Nội", "30": "Hà Nội", "31": "Hà Nội", "32": "Hà Nội", "33": "Hà Nội", "40": "Hà Nội",
    "43": "Đà Nẵng", "50": "TP.HCM", "51": "TP.HCM", "52": "TP.HCM", "53": "TP.HCM", "54": "TP.HCM",
    "55": "TP.HCM", "56": "TP.HCM", "57": "TP.HCM", "58": "TP.HCM", "59": "TP.HCM", "41": "TP.HCM",
    "15": "Hải Phòng", "16": "Hải Phòng", "65": "Cần Thơ", "61": "Bình Dương", "60": "Đồng Nai",
    "72": "Bà Rịa - Vũng Tàu", "75": "Thừa Thiên Huế", "77": "Bình Định", "78": "Phú Yên",
    "79": "Khánh Hòa", "49": "Lâm Đồng", "47": "Đắk Lắk", "81": "Gia Lai", "92": "Quảng Nam",
    "76": "Quảng Ngãi", "37": "Nghệ An", "36": "Thanh Hóa", "14": "Quảng Ninh", "99": "Bắc Ninh",
}

LABELED_CCCD_RE = re.compile(
    r"\b(?:cccd|căn\s*cước(?:\s*công\s*dân)?|mã\s*định\s*danh(?:\s*cá\s*nhân)?|cmnd|citizen\s*id)[:\s#]+(\d{9,12})\b",
    re.IGNORECASE,
)
BARE_CCCD_RE = re.compile(r"\b(0[0-9]{2}[0-3]\d{2}\d{6})\b")
LABELED_TAX_ID_RE = re.compile(
    r"\b(?:mst|mã\s*số\s*thuế|tax\s*id|tin)[:\s#]+(\d{10}(?:-\d{3})?)\b",
    re.IGNORECASE,
)
ORCID_RE = re.compile(r"\b(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\b")
LABELED_EXAM_ID_RE = re.compile(
    r"\b(?:sbd|số\s*báo\s*danh|mã\s*thí\s*sinh|candidate\s*id)[:\s#]+([A-Za-z0-9]{5,12})\b",
    re.IGNORECASE,
)
VN_LICENSE_PLATE_RE = re.compile(
    r"\b(\d{2}[A-Z]\d?[-.\s]\d{3}\.?\d{2})\b",
)
SOCIAL_UID_RE = re.compile(
    r"(?:(?:facebook\.com/profile\.php\?id=|fb\.com/|uid[:\s#]+)(1000\d{10,12})|"
    r"(?:t\.me|telegram\.me)/([a-zA-Z0-9_]{4,32})|"
    r"linkedin\.com/in/([a-zA-Z0-9_%-]{3,60}))",
    re.IGNORECASE,
)
EVM_WALLET_RE = re.compile(r"\b(0x[a-fA-F0-9]{40})\b")


def decode_vn_cccd(cccd: str) -> Optional[dict[str, Any]]:
    """Decode public metadata encoded in a 12-digit Vietnamese CCCD (province, gender, birth year)."""
    s = re.sub(r"\D+", "", cccd or "")
    if len(s) != 12:
        return None
    prov_code = s[:3]
    province = VN_CCCD_PROVINCE_CODES.get(prov_code)
    if not province:
        return None
    cg = int(s[3])
    if cg not in (0, 1, 2, 3):
        return None
    century = 1900 if cg in (0, 1) else 2000
    gender = "Nam" if cg in (0, 2) else "Nữ"
    birth_year = century + int(s[4:6])
    return {
        "cccd": s,
        "province_code": prov_code,
        "birth_province": province,
        "gender": gender,
        "birth_year": birth_year,
    }


def decode_vn_license_plate(plate: str) -> dict[str, Any]:
    """Normalize a Vietnamese license plate and decode its registered province/city."""
    clean = re.sub(r"\s+", "-", plate.strip().upper())
    code = clean[:2]
    return {
        "plate": clean,
        "province": VN_PLATE_PROVINCE_CODES.get(code, ""),
    }


def is_vn_major_code(value: str) -> bool:
    """Return True if value matches Vietnam MOET 7-digit university major code (Circular 09/2022/TT-BGDDT, e.g. 7340404)."""
    s = str(value or "").strip()
    return len(s) == 7 and s.isdigit() and s.startswith("7")


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

    # 1. CCCD / Citizen ID (12-digit public Vietnamese schema + labeled 9-digit legacy CMND)
    cccds: list[dict[str, Any]] = []
    seen_cccds: set[str] = set()
    claimed_numeric_ids: set[str] = set()
    for raw_c in LABELED_CCCD_RE.findall(text_no_urls):
        c_clean = re.sub(r"\D+", "", raw_c)
        if c_clean and c_clean not in seen_cccds:
            seen_cccds.add(c_clean)
            claimed_numeric_ids.add(c_clean)
            decoded = decode_vn_cccd(c_clean)
            cccds.append(decoded if decoded else {"cccd": c_clean, "legacy_cmnd": len(c_clean) == 9})
    for raw_c in BARE_CCCD_RE.findall(text_no_urls):
        if raw_c not in seen_cccds:
            decoded = decode_vn_cccd(raw_c)
            if decoded:
                seen_cccds.add(raw_c)
                claimed_numeric_ids.add(raw_c)
                cccds.append(decoded)

    # 2. Tax IDs (MST: 10 digits or 10-3 digits)
    tax_ids: list[str] = []
    for raw_t in LABELED_TAX_ID_RE.findall(text_no_urls):
        t_clean = raw_t.strip()
        if t_clean not in tax_ids:
            tax_ids.append(t_clean)
            claimed_numeric_ids.add(t_clean.split("-")[0])

    # 3. Exam / Candidate IDs (SBD)
    exam_ids: list[str] = []
    for raw_e in LABELED_EXAM_ID_RE.findall(text_no_urls):
        e_clean = raw_e.strip()
        if e_clean not in exam_ids:
            exam_ids.append(e_clean)
            claimed_numeric_ids.add(e_clean)

    # 4. ORCID IDs, Vietnamese License Plates, Social UIDs/Handles, EVM Crypto Wallets
    orcid_ids = sorted(set(ORCID_RE.findall(text)))
    license_plates: list[dict[str, Any]] = []
    seen_plates: set[str] = set()
    for raw_p in VN_LICENSE_PLATE_RE.findall(text_no_urls):
        p_info = decode_vn_license_plate(raw_p)
        if p_info["plate"] not in seen_plates:
            seen_plates.add(p_info["plate"])
            license_plates.append(p_info)

    social_ids: list[dict[str, str]] = []
    seen_social: set[str] = set()
    for fb_uid, tg_user, li_slug in SOCIAL_UID_RE.findall(text):
        if fb_uid and fb_uid not in seen_social:
            seen_social.add(fb_uid)
            claimed_numeric_ids.add(fb_uid)
            social_ids.append({"platform": "facebook", "id": fb_uid})
        elif tg_user and tg_user.lower() not in seen_social:
            seen_social.add(tg_user.lower())
            social_ids.append({"platform": "telegram", "id": tg_user})
        elif li_slug and li_slug.lower() not in seen_social:
            seen_social.add(li_slug.lower())
            social_ids.append({"platform": "linkedin", "id": li_slug})

    crypto_wallets = sorted(set(EVM_WALLET_RE.findall(text)))

    # 5. Student IDs (labeled alphanumeric + bare 7-12 digit IDs not already claimed by CCCD/MST/SBD/Phone)
    for sid in LABELED_ALNUM_SID_RE.findall(text_no_urls):
        sid_clean = sid.strip()
        if any(c.isdigit() for c in sid_clean) and sid_clean not in seen_sids:
            seen_sids.add(sid_clean)
            student_ids.append(decode_student_id_schema(sid_clean, org_hint=org_context))

    for sid in STUDENT_ID_RE.findall(text_no_urls):
        if sid in claimed_numeric_ids:
            continue
        # Skip Vietnamese phone numbers (10 digits starting with 03/05/07/08/09)
        if len(sid) == 10 and sid.startswith(("03", "05", "07", "08", "09")):
            continue
        # Skip Vietnam MOET 7-digit university major codes (7xxxxxx, e.g. 7340404 Quản trị nhân lực)
        if is_vn_major_code(sid):
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
        "cccds": cccds,
        "tax_ids": tax_ids,
        "exam_ids": exam_ids,
        "orcid_ids": orcid_ids,
        "license_plates": license_plates,
        "social_ids": social_ids,
        "crypto_wallets": crypto_wallets,
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
