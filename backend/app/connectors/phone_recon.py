"""Phone Number OSINT Analyzer & 5-Category Footprint Dorker (sundowndev/phoneinfoga Architecture).

Directly mirrors PhoneInfoga v2's `GoogleSearchResponse` 5-category dork taxonomy:
1. `general` (multi-format E.164, RFC 3966, local, spaced/dotted)
2. `social_media` (Facebook, LinkedIn, Instagram, X, GitHub, TikTok)
3. `disposable_providers` (temporary/burner SMS inbox detection: receive-smss, sms24, temp-number)
4. `reputation` (public scam/community caller reports)
5. `individuals` (PDF/XLSX contact sheets, resumes, business/classified directories)

Strictly Public OSINT Only — never accesses private telecom subscriber databases.
"""

from __future__ import annotations

import re
from typing import Any

COUNTRY_CODES: dict[str, tuple[str, str]] = {
    "84": ("VN", "Vietnam"),
    "1": ("US/CA", "United States / Canada"),
    "44": ("GB", "United Kingdom"),
    "65": ("SG", "Singapore"),
    "81": ("JP", "Japan"),
    "82": ("KR", "South Korea"),
    "86": ("CN", "China"),
    "61": ("AU", "Australia"),
    "33": ("FR", "France"),
    "49": ("DE", "Germany"),
    "91": ("IN", "India"),
    "66": ("TH", "Thailand"),
    "60": ("MY", "Malaysia"),
    "62": ("ID", "Indonesia"),
    "63": ("PH", "Philippines"),
}

VN_CARRIER_PREFIXES: dict[str, str] = {
    **{p: "Viettel" for p in ("032", "033", "034", "035", "036", "037", "038", "039", "086", "096", "097", "098")},
    **{p: "MobiFone" for p in ("070", "076", "077", "078", "079", "089", "090", "093")},
    **{p: "VinaPhone" for p in ("081", "082", "083", "084", "085", "088", "091", "094")},
    **{p: "Vietnamobile" for p in ("052", "056", "058", "092")},
    **{p: "Gmobile" for p in ("059", "099")},
    "087": "Itelecom (MVNO)",
    "055": "Wintel (MVNO)",
}

PHONE_EXTRACT_RE = re.compile(
    r"(?<!\d)\+\d{1,3}(?:[\s.\-]?\d{2,4}){2,4}(?!\d)"
    r"|(?<!\d)(?:\(0\)|0)(?:3|5|7|8|9)\d{2}[\s.\-]?\d{3}[\s.\-]?\d{3}(?!\d)"
)


def extract_phone_candidates(text: str) -> list[str]:
    """Extract plausible phone numbers from free-form prompt text."""
    seen: set[str] = set()
    out: list[str] = []
    for m in PHONE_EXTRACT_RE.findall(text or ""):
        digits = re.sub(r"\D", "", m)
        if 9 <= len(digits) <= 15 and digits not in seen:
            if len(digits) == 10 and digits.startswith(("03", "05", "07", "08", "09")):
                seen.add(digits)
                out.append(m.strip())
            elif m.strip().startswith("+") and len(digits) >= 10:
                seen.add(digits)
                out.append(m.strip())
    return out


def analyze_phone_number(raw_phone: str, name_hint: str = "") -> dict[str, Any]:
    """Parse phone metadata (E.164, RFC 3966, carrier) and generate PhoneInfoga 5-category dorks."""
    cleaned = re.sub(r"[^\d+]", "", (raw_phone or "").strip())
    digits_only = re.sub(r"\D", "", cleaned)

    if len(digits_only) < 9 or len(digits_only) > 15:
        return {
            "valid": False,
            "raw": raw_phone,
            "error": "Phone number must contain between 9 and 15 digits.",
            "dorks": [],
            "dork_categories": {},
        }

    country_iso = "UNKNOWN"
    country_name = "Unknown"
    carrier = "Unknown"
    line_type = "mobile_or_fixed"
    e164 = ""
    rfc3966 = ""
    local_format = ""
    variants: list[str] = []

    if (len(digits_only) == 10 and digits_only.startswith("0")) or (
        len(digits_only) == 11 and digits_only.startswith("84")
    ):
        country_iso = "VN"
        country_name = "Vietnam"
        national = digits_only[1:] if digits_only.startswith("0") else digits_only[2:]
        local_format = "0" + national
        e164 = "+84" + national
        rfc3966 = f"+84-{national[:2]}-{national[2:5]}-{national[5:]}"
        prefix3 = local_format[:3]
        carrier = VN_CARRIER_PREFIXES.get(prefix3, "Vietnam Telecom / Landline")
        line_type = "mobile" if prefix3 in VN_CARRIER_PREFIXES else "landline_or_other"
        variants = [
            local_format,
            e164,
            f"{local_format[:4]}.{local_format[4:7]}.{local_format[7:]}",
            f"{local_format[:4]} {local_format[4:7]} {local_format[7:]}",
            f"{local_format[:4]}-{local_format[4:7]}-{local_format[7:]}",
            rfc3966,
            f"84{national}",
        ]
    else:
        cc_matched = ""
        for cc in sorted(COUNTRY_CODES.keys(), key=len, reverse=True):
            if digits_only.startswith(cc):
                cc_matched = cc
                country_iso, country_name = COUNTRY_CODES[cc]
                break
        e164 = f"+{digits_only}"
        local_format = digits_only[len(cc_matched) :] if cc_matched else digits_only
        rfc3966 = f"+{cc_matched}-{local_format}" if cc_matched else e164
        variants = [e164, digits_only, rfc3966]
        if local_format and local_format != digits_only:
            variants.append(local_format)

    unique_variants = list(dict.fromkeys(variants))
    or_clause = " OR ".join(f'"{v}"' for v in unique_variants[:4])

    dork_categories: dict[str, list[dict[str, str]]] = {
        "general": [
            {"strategy": "phone:general_exact", "query": f"({or_clause})"},
        ],
        "social_media": [
            {
                "strategy": "phone:social_media",
                "query": f"({or_clause}) (site:facebook.com OR site:linkedin.com OR site:instagram.com OR site:github.com OR site:tiktok.com)",
            }
        ],
        "disposable_providers": [
            {
                "strategy": "phone:disposable_check",
                "query": f'({or_clause}) (site:receive-smss.com OR site:sms24.me OR site:temp-number.org OR site:quackr.io OR "temporary phone")',
            }
        ],
        "reputation": [
            {
                "strategy": "phone:reputation",
                "query": f'({or_clause}) (site:whocallsme.com OR site:tellows.com OR "lừa đảo" OR "scam" OR "spam")',
            }
        ],
        "individuals": [
            {
                "strategy": "phone:public_documents",
                "query": f'({or_clause}) (filetype:pdf OR filetype:xlsx OR "liên hệ" OR "contact" OR "CV")',
            }
        ],
    }

    if name_hint.strip():
        dork_categories["general"].insert(
            0,
            {
                "strategy": "phone:name_intersection",
                "query": f'"{name_hint.strip()}" ({or_clause})',
            },
        )
    if country_iso == "VN":
        dork_categories["individuals"].append(
            {
                "strategy": "phone:vn_classifieds_directories",
                "query": f"({or_clause}) (site:chotot.com OR site:nhattao.com OR site:topcv.vn OR site:masothue.com)",
            }
        )

    flat_dorks = [
        d
        for cat in ("general", "social_media", "individuals", "disposable_providers", "reputation")
        for d in dork_categories[cat]
    ]

    hitl_notes = (
        [
            "Kiểm tra thủ công (Human-in-the-loop): tìm số trên Zalo / Viber / Telegram công khai nếu có nhu cầu xác minh hợp pháp.",
            "Đã tạo đủ 5 nhóm dork chuẩn PhoneInfoga (Tổng quát, MXH, Cá nhân/PDF, Kiểm tra SIM ảo Disposable, Uy tín/Spam).",
        ]
        if country_iso == "VN"
        else [
            "Generated all 5 PhoneInfoga dork groups (General, Social Media, Individuals/PDFs, Disposable Burner Check, Reputation)."
        ]
    )

    return {
        "valid": True,
        "raw": raw_phone,
        "e164": e164,
        "rfc3966": rfc3966,
        "local_format": local_format,
        "country_iso": country_iso,
        "country_name": country_name,
        "carrier": carrier,
        "line_type": line_type,
        "formatted_variants": unique_variants,
        "dork_categories": dork_categories,
        "dorks": flat_dorks,
        "human_in_the_loop_guidance": hitl_notes,
    }
