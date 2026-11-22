"""Layer 1 (Outermost Perimeter): Intake, Multimodal OCR, Clue Parsing & High-Entropy Anchor Decoding.

Responsibilities:
- Parse user prompts cleanly into structured 8D seed clues (isolating pure numeric MSSV/IDs from social aliases).
- Extract OCR text from attached screenshots via Gemini/Ollama Vision.
- Hydrate verified Dossier items, Geo pin coordinates, multi-turn conversation history, and existing GraphStore claims.
- Decode immutable high-entropy anchors (MSSV/student IDs, institutional emails, class codes, official doc numbers, phones).
- Produce an `InvestigationContext` contract for Layer 2 (Gatekeeper) and inner layers.
"""

from __future__ import annotations

import re
from typing import Any, Optional

import httpx

from app.config import settings
from app.connectors.phone_recon import extract_phone_candidates
from app.connectors.web_search import infer_query_region
from app.core.anchor_decoder import decode_high_entropy_anchors
from app.core.graph_store import GraphStore
from app.core.llm_provider import GeminiProvider, OllamaProvider
from app.core.normalizer import normalize_text
from app.pipeline.models import InvestigationContext

URL_RE = re.compile(r"https?://[^\s,]+", re.IGNORECASE)
HANDLE_RE = re.compile(r"^@?[a-zA-Z0-9_.-]{3,32}$")
YEAR_RE = re.compile(r"^(?:19[6-9]\d|20[0-2]\d)$")
DOB_TOKEN_RE = re.compile(r"^(\d{1,2})[/\-\.](\d{1,2})[/\-\.](19[6-9]\d|20[0-2]\d)$")
DOB_ISO_RE = re.compile(r"^(19[6-9]\d|20[0-2]\d)[/\-\.](\d{1,2})[/\-\.](\d{1,2})$")

ORG_HINTS = (
    # Vietnamese academic & corporate
    "đh",
    "đại học",
    "thpt",
    "thcs",
    "hcmut",
    "hcmus",
    "hcmussh",
    "ussh",
    "hust",
    "uit",
    "uel",
    "ftu",
    "ptit",
    "fpt",
    "neu",
    "ueh",
    "ump",
    "sgu",
    "tdtu",
    "rmit",
    "hnue",
    "hutech",
    "vlu",
    "vnu",
    "vnu-hcm",
    "dhqg",
    "đhqg",
    "bách khoa",
    "nhân văn",
    "khoa học xã hội",
    "khoa học tự nhiên",
    "kinh tế",
    "ngoại thương",
    "sư phạm",
    "y dược",
    "công ty",
    "tập đoàn",
    "clb",
    "vng",
    "viettel",
    # Global academic, research & corporate
    "university",
    "univ",
    "institute",
    "college",
    "school",
    "academy",
    "polytechnic",
    "laboratory",
    "lab",
    "foundation",
    "corp",
    "inc",
    "ltd",
    "llc",
    "gmbh",
    "technologies",
    "systems",
    "mit",
    "stanford",
    "harvard",
    "oxford",
    "cambridge",
    "berkeley",
    "cmu",
    "eth zurich",
    "caltech",
    "google",
    "deepmind",
    "openai",
    "anthropic",
    "microsoft",
    "meta",
    "amazon",
    "apple",
    "nvidia",
    "ibm",
    "tesla",
    "cern",
    "nasa",
)

VN_PROVINCES_AND_CITIES = (
    "hà nội",
    "ha noi",
    "tp.hcm",
    "tphcm",
    "hồ chí minh",
    "ho chi minh",
    "sài gòn",
    "sai gon",
    "thủ đức",
    "đà nẵng",
    "da nang",
    "cần thơ",
    "can tho",
    "hải phòng",
    "hai phong",
    "huế",
    "thừa thiên huế",
    "phú yên",
    "phu yen",
    "khánh hòa",
    "nha trang",
    "bình định",
    "quy nhơn",
    "lâm đồng",
    "đà lạt",
    "gia lai",
    "đắk lắk",
    "buôn ma thuột",
    "đắk nông",
    "kon tum",
    "quảng nam",
    "quảng ngãi",
    "quảng bình",
    "quảng trị",
    "quảng ninh",
    "nghệ an",
    "vinh",
    "hà tĩnh",
    "thanh hóa",
    "bình dương",
    "đồng nai",
    "biên hòa",
    "bà rịa",
    "vũng tàu",
    "tây ninh",
    "bình phước",
    "bình thuận",
    "ninh thuận",
    "long an",
    "tiền giang",
    "bến tre",
    "trà vinh",
    "vĩnh long",
    "đồng tháp",
    "an giang",
    "kiên giang",
    "cà mau",
    "bạc liêu",
    "sóc trăng",
    "hậu giang",
    "bắc ninh",
    "bắc giang",
    "hải dương",
    "hưng yên",
    "nam định",
    "thái bình",
    "ninh bình",
    "hà nam",
    "vĩnh phúc",
    "phú thọ",
    "thái nguyên",
    "lạng sơn",
    "lào cai",
    "yên bái",
    "sơn la",
    "điện biên",
    "lai châu",
    "hòa bình",
    "cao bằng",
    "bắc kạn",
    "tuyên quang",
    "hà giang",
    "vietnam",
    "việt nam",
)

LOC_HINTS = VN_PROVINCES_AND_CITIES + (
    # Global cities & countries
    "usa",
    "united states",
    "california",
    "san francisco",
    "new york",
    "seattle",
    "boston",
    "london",
    "united kingdom",
    "uk",
    "canada",
    "toronto",
    "montreal",
    "germany",
    "berlin",
    "munich",
    "france",
    "paris",
    "japan",
    "tokyo",
    "korea",
    "seoul",
    "singapore",
    "australia",
    "sydney",
    "melbourne",
    "switzerland",
    "zurich",
    "netherlands",
    "amsterdam",
)

# Metadata labels / prose headers that must NEVER be selected as target_name
_NON_NAME_PREFIXES = (
    "giới tính",
    "gioi tinh",
    "nơi sinh",
    "noi sinh",
    "quê quán",
    "que quan",
    "ngày sinh",
    "ngay sinh",
    "năm sinh",
    "nam sinh",
    "mã số",
    "ma so",
    "họ tên",
    "ho ten",
    "họ và tên",
    "ho va ten",
    "hồ sơ",
    "ho so",
    "nguồn",
    "dựa trên",
    "kết quả",
    "thông tin",
    "công tác",
    "giảng dạy",
    "xuất hiện",
    "chi tiết",
    "tiểu sử",
    "gender",
    "date of birth",
    "birthplace",
    "hometown",
    "summary",
)

_LABELED_NAME_RE = re.compile(
    r"(?:Họ(?:\s+và)?\s+tên|cá\s+nhân|mục\s+tiêu|giảng\s+viên|sinh\s+viên|ThS\.|TS\.|PGS\.TS\.)"
    r"[\s:]+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,4})",
)
_EMBEDDED_DOB_RE = re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.](?:19[6-9]\d|20[0-2]\d))\b")


# Natural-language relational connectors (Vietnamese & English, comma-free sentences)
_NL_RELATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\s+(?:là\s+)?con(?:\s+(?:trai|gái|ruột|đầu|út))?\s+của\s+(?:ông|bà|anh|chị|chú|cô|bác|thầy|cô\s+giáo)?\s*",
            re.IGNORECASE,
        ),
        "CHILD_OF",
    ),
    (
        re.compile(
            r"\s+(?:là\s+)?(?:vợ|chồng)\s+của\s+(?:ông|bà|anh|chị)?\s*",
            re.IGNORECASE,
        ),
        "SPOUSE_OF",
    ),
    (
        re.compile(
            r"\s+(?:là\s+)?(?:cha|bố|ba|mẹ|má)\s+của\s+(?:ông|bà|anh|chị|em)?\s*",
            re.IGNORECASE,
        ),
        "PARENT_OF",
    ),
    (
        re.compile(
            r"\s+(?:là\s+)?(?:anh(?:\s+trai)?|chị(?:\s+gái)?|em(?:\s+trai|\s+gái)?)\s+của\s+(?:ông|bà|anh|chị|em)?\s*",
            re.IGNORECASE,
        ),
        "SIBLING_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:son|daughter|child)\s+of\s+(?:mr\.?|mrs\.?|ms\.?|dr\.?)?\s*", re.IGNORECASE),
        "CHILD_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:wife|husband|spouse)\s+of\s+(?:mr\.?|mrs\.?|ms\.?|dr\.?)?\s*", re.IGNORECASE),
        "SPOUSE_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:father|mother|parent)\s+of\s+(?:mr\.?|mrs\.?|ms\.?|dr\.?)?\s*", re.IGNORECASE),
        "PARENT_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:brother|sister|sibling)\s+of\s+", re.IGNORECASE),
        "SIBLING_OF",
    ),
)

# Inline natural-language clause splitters for comma-free Vietnamese & English prompts
_NL_CLAUSE_SPLIT_RE = re.compile(
    r"\s+(?="
    r"(?:sinh\s+ngày|sinh\s+năm|sn\s+\d{4}|"
    r"(?:đang\s+|từng\s+)?(?:học|làm\s+việc|công\s+tác|tốt\s+nghiệp)\s+(?:tại|ở|trường)\b|"
    r"học\s+(?:trường|thpt|thcs|đh|đại\s+học|[A-Z]{2,6})\b|"
    r"là\s+sinh\s+viên\s+(?:tại|ở|trường)?\b|"
    r"(?:sống\s+tại|quê\s+ở|quê\s+tại|tại\s+(?:tp|hà\s+nội|hồ\s+chí\s+minh|đà\s+nẵng)|ở\s+(?:tp|tphcm|hà\s+nội|hồ\s+chí\s+minh|sài\s+gòn|đà\s+nẵng))\b|"
    r"ngành\s+|lớp\s+|mssv\s+|email\s+|không\s+phải\s+|loại\s+trừ\s+|"
    r"born\s+(?:on\s+)?\d{4}|born\s+\d{1,2}[/\-.]|"
    r"(?:works?|worked|studying|studied|student|alumni|professor)\s+(?:at|in|of)\b|"
    r"(?:based\s+in|living\s+in|from)\s+[A-Z])"
    r")",
    re.IGNORECASE,
)

_NL_CLAUSE_PREFIX_STRIP_RE = re.compile(
    r"^(?:(?:đang|từng)\s+)?(?:học|làm\s+việc|công\s+tác|tốt\s+nghiệp)\s+(?:tại|ở)\s+|"
    r"^(?:đang|từng)?\s*học\s+(?=(?:trường|thpt|thcs|đh|đại\s+học|[A-Z]{2,6})\b)|"
    r"^là\s+sinh\s+viên\s+(?:tại|ở|trường\s+)?|"
    r"^(?:sống\s+tại|quê\s+ở|quê\s+tại|ở|tại)\s+|"
    r"^sinh\s+ngày\s+|"
    r"^born\s+(?:on\s+)?|"
    r"^(?:works?|worked|studying|studied|student|alumni|professor)\s+(?:at|in|of)\s+|"
    r"^(?:based\s+in|living\s+in|from)\s+",
    re.IGNORECASE,
)


def _preprocess_natural_language(text: str) -> tuple[list[str], list[dict[str, str]]]:
    """Break comma-free Vietnamese/English natural language prompts into structured clue parts + related people.

    Examples:
    - "nguyễn minh an con của ông nguyễn văn bình"
      -> parts=["nguyễn minh an"], related_people=[{"name": "nguyễn văn bình", "relation": "CHILD_OF"}]
    - "Trần Minh Anh sinh ngày 15/05/2007 học tại UEH ở TPHCM"
      -> parts=["Trần Minh Anh", "15/05/2007", "UEH", "TPHCM"], related_people=[]
    """
    related_people: list[dict[str, str]] = []
    raw_segments = [p.strip() for p in re.split(r"[,;\n]+", text) if p.strip()]
    expanded_parts: list[str] = []

    for seg in raw_segments:
        # Step 1: Check natural relational phrase ("A con của ông B", "John Doe son of Robert Doe")
        matched_rel = False
        for rel_re, rel_type in _NL_RELATION_PATTERNS:
            m = rel_re.search(seg)
            if m:
                left = seg[: m.start()].strip(" ,.-")
                right_full = seg[m.end() :].strip(" ,.-")
                # Right side may still contain trailing bio clauses (e.g., "... con của ông B ở TPHCM")
                right_clauses = [c.strip() for c in _NL_CLAUSE_SPLIT_RE.split(right_full) if c.strip()]
                rel_name = right_clauses[0] if right_clauses else right_full
                if left:
                    expanded_parts.extend(c.strip() for c in _NL_CLAUSE_SPLIT_RE.split(left) if c.strip())
                if rel_name and len(rel_name.split()) <= 6:
                    related_people.append({"name": rel_name, "relation": rel_type})
                elif rel_name:
                    expanded_parts.append(rel_name)
                if len(right_clauses) > 1:
                    expanded_parts.extend(right_clauses[1:])
                matched_rel = True
                break
        if matched_rel:
            continue

        # Step 2: Split comma-free biographical sentences into clean clue chunks
        sub_clauses = [c.strip() for c in _NL_CLAUSE_SPLIT_RE.split(seg) if c.strip()]
        expanded_parts.extend(sub_clauses)

    cleaned_parts: list[str] = []
    for idx, p in enumerate(expanded_parts):
        if idx == 0:
            cleaned_parts.append(p.strip())
        else:
            stripped = _NL_CLAUSE_PREFIX_STRIP_RE.sub("", p).strip()
            cleaned_parts.append(stripped or p.strip())
    return [c for c in cleaned_parts if c], related_people


def _normalize_dob_safe(raw_dob: str) -> tuple[str, Optional[int]]:
    """Safely validate & normalize DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY, or ISO YYYY-MM-DD into (DD/MM/YYYY, year).

    Returns ("", None) if invalid (e.g., 99/99/2007 or free text) so downstream layers never crash.
    """
    s = (raw_dob or "").strip()
    m1 = DOB_TOKEN_RE.match(s)
    if m1:
        d, m, y = int(m1.group(1)), int(m1.group(2)), int(m1.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{d:02d}/{m:02d}/{y}", y
        return "", None
    m2 = DOB_ISO_RE.match(s)
    if m2:
        y, m, d = int(m2.group(1)), int(m2.group(2)), int(m2.group(3))
        if 1 <= m <= 12 and 1 <= d <= 31:
            return f"{d:02d}/{m:02d}/{y}", y
        return "", None
    return "", None


def parse_user_prompt(prompt: str) -> dict[str, Any]:
    """Parse structured (comma-separated) OR natural-language Vietnamese/English prompts into 8D clues."""
    raw = prompt.strip()
    urls = URL_RE.findall(raw)
    cleaned_no_urls = URL_RE.sub("", raw).strip()

    lead_stripped = re.sub(
        r"^(?:hãy\s+)?(?:tìm(?:\s+kiếm)?(?:\s+thông tin)?(?:\s+về)?|tra cứu(?:\s+về)?|kiểm tra|check|stalk|search|find(?:\s+info\s+about)?)\s+",
        "",
        cleaned_no_urls,
        flags=re.IGNORECASE,
    ).strip()

    parts, related_people = _preprocess_natural_language(lead_stripped)

    target_name = ""
    birth_date = ""
    birth_year: Optional[int] = None
    aliases: list[str] = []
    organizations: list[str] = []
    locations: list[str] = []
    keywords: list[str] = []
    negative_keywords: list[str] = []

    non_org_acronyms = {
        "IELTS", "TOEIC", "TOEFL", "SAT", "HSK", "JLPT", "TOPIK", "GPA",
        "PDF", "DOC", "DOCX", "XLSX", "CSV", "JSON", "HTML", "URL", "HTTP",
        "NAM", "NU", "MALE", "FEMALE", "DOB", "MSSV", "CCCD", "CMND",
    }

    def _is_non_name_label(text_val: str) -> bool:
        low_v = text_val.strip().lower()
        norm_v = normalize_text(text_val)
        if any(low_v.startswith(p) or norm_v.startswith(p) for p in _NON_NAME_PREFIXES):
            return True
        if any(ch in text_val for ch in (":", "(", ")", "•", "[")):
            return True
        return False

    # Long-prose / pasted AI-summary pre-extraction (e.g., pasted Gemini/article bio paragraph)
    is_prose_paste = (
        len(raw) >= 120
        or "•" in raw
        or bool(re.search(r"\b(?:họ(?:\s+và)?\s+tên|giới\s+tính|dựa\s+trên\s+thông\s+tin)\b", raw, re.IGNORECASE))
    )
    if is_prose_paste:
        m_name = _LABELED_NAME_RE.search(raw)
        if m_name:
            cand_name = m_name.group(1).strip()
            if not _is_non_name_label(cand_name):
                target_name = cand_name
        m_dob = _EMBEDDED_DOB_RE.search(raw)
        if m_dob:
            ndob, nyear = _normalize_dob_safe(m_dob.group(1))
            if ndob:
                birth_date = ndob
                birth_year = nyear
        raw_low = raw.lower()
        for loc_hint in VN_PROVINCES_AND_CITIES:
            if len(loc_hint) >= 5 and re.search(rf"(?<!\w){re.escape(loc_hint)}(?!\w)", raw_low):
                pretty_loc = loc_hint.title() if loc_hint not in ("tphcm", "tp.hcm") else loc_hint.upper()
                if not any(normalize_text(pretty_loc) == normalize_text(x) for x in locations):
                    locations.append(pretty_loc)
                    if len(locations) >= 2:
                        break

    for idx, part in enumerate(parts):
        low = part.lower()
        norm = normalize_text(part)

        # Negative constraints
        if part.startswith("-"):
            neg = part[1:].strip().strip('"')
            if neg:
                negative_keywords.append(neg)
            continue
        neg_match = re.match(r"^(?:không phải|ko phải|trừ|loại trừ|not)\s+(.+)$", part, re.IGNORECASE)
        if neg_match:
            negative_keywords.append(neg_match.group(1).strip())
            continue

        # Explicit full birth date: DD/MM/YYYY or ISO YYYY-MM-DD (calendar-validated)
        if DOB_TOKEN_RE.match(part) or DOB_ISO_RE.match(part):
            norm_dob, norm_year = _normalize_dob_safe(part)
            if norm_dob:
                birth_date = norm_dob
                birth_year = norm_year
            continue
        if not birth_date:
            m_part_dob = _EMBEDDED_DOB_RE.search(part)
            if m_part_dob and any(k in low for k in ("sinh", "dob", "birth")):
                norm_dob, norm_year = _normalize_dob_safe(m_part_dob.group(1))
                if norm_dob:
                    birth_date = norm_dob
                    birth_year = norm_year
                    continue

        # Explicit alias/username
        gh_match = re.match(r"^(?:github|user|username|nick|alias)[:\s]+@?([a-zA-Z0-9_.-]+)$", part, re.IGNORECASE)
        if gh_match:
            aliases.append(gh_match.group(1))
            continue
        if part.startswith("@") and HANDLE_RE.match(part):
            aliases.append(part.lstrip("@"))
            continue

        # Year token
        if YEAR_RE.match(part):
            if not birth_date:
                birth_year = int(part)
            continue
        sn_m = re.match(r"^(?:sinh năm|sn)\s*(\d{4})$", low)
        if sn_m:
            if not birth_date:
                birth_year = int(sn_m.group(1))
            continue

        # Skip raw email tokens from being misclassified into organizations (decoded by anchor_decoder)
        if "@" in part and "." in part.split("@")[-1]:
            continue

        # Skip long descriptive sentences (> 65 chars) from being misclassified as org or person name
        if len(part) > 65:
            keywords.append(part)
            continue

        # Class/grade or certificate hints ("lớp 12A7", "IELTS 7.0", "TOEIC 800") -> keyword, never person name
        if (
            re.match(r"^(?:lớp|class)\s+[A-Za-z0-9]+$", low)
            or re.match(r"^\d[0-2x][A-Z]\d{1,2}$", part)
            or re.match(r"^(?:ielts|toeic|toefl|sat|hsk|jlpt|topik)\b", low)
        ):
            keywords.append(part)
            continue

        # Location hints (checked BEFORE uppercase org acronym check so TPHCM, USA, UK map to locations!)
        # Reject noisy prose clauses (> 35 chars or containing ':' / ')') from polluting locations.
        if (
            len(part) <= 35
            and not any(ch in part for ch in (":", ")", "("))
            and any(h in low or h in norm for h in LOC_HINTS)
        ):
            if not any(normalize_text(part) == normalize_text(x) for x in locations):
                locations.append(part)
            continue

        # Organization / School hints (explicit hints OR uppercase institution/company acronyms like USSH, FTU, UEH, MIT)
        is_org_acronym = (
            bool(re.match(r"^[A-Z]{2,8}(?:-[A-Z]{2,8})?$", part))
            and part.upper() not in non_org_acronyms
        )
        if (
            (len(part) <= 45 and not any(ch in part for ch in (":", ")")) and any(h in low or h in norm for h in ORG_HINTS))
            or is_org_acronym
        ):
            if not any(normalize_text(part) == normalize_text(x) for x in organizations):
                organizations.append(part)
            continue

        # Skip metadata labels like "giới tính Nữ", "nơi sinh ..." from becoming target_name
        if _is_non_name_label(part):
            keywords.append(part)
            continue

        # First non-classified multi-word clue is the Target Person's Name
        if not target_name and idx == 0 and len(part.split()) <= 5 and "_" not in part and not part.isdigit():
            target_name = part
            continue

        # Skip pure numeric IDs (MSSV, SBD, phone-like digits) from being misclassified as social aliases
        if part.isdigit() and len(part) >= 6:
            continue

        if (
            " " not in part
            and HANDLE_RE.match(part)
            and any(c.isalpha() for c in part)
            and (any(c.isdigit() for c in part) or "_" in part or "." in part)
        ):
            aliases.append(part)
            continue

        if not target_name and len(part.split()) <= 5:
            target_name = part
        else:
            keywords.append(part)

    if not target_name:
        email_m = re.search(r"\b([a-zA-Z]{4,24})[._]?\d*@", raw)
        if email_m:
            target_name = email_m.group(1)
        else:
            target_name = aliases[0] if aliases else (parts[0][:60] if parts else "Đối tượng chưa rõ tên")

    # Keep birth_year strictly consistent with birth_date when full DOB is known
    if birth_date:
        _, synced_year = _normalize_dob_safe(birth_date)
        if synced_year:
            birth_year = synced_year

    is_long_snippet = is_prose_paste or (len(raw) >= 130 and len(parts) <= 3)
    region = infer_query_region(raw, "auto")

    return {
        "target_name": target_name,
        "birth_date": birth_date,
        "birth_year": birth_year,
        "aliases": aliases,
        "organizations": organizations,
        "locations": locations,
        "keywords": keywords,
        "negative_keywords": negative_keywords,
        "related_people": related_people,
        "urls": urls,
        "is_long_snippet": is_long_snippet,
        "region": region,
        "raw_prompt": raw,
    }


async def run_layer1_intake(
    *,
    store: GraphStore,
    workspace_id: str,
    prompt: str,
    model_override: Optional[str] = None,
    image_b64: Optional[str] = None,
    image_mime: str = "image/png",
    geo_point: Optional[dict[str, Any]] = None,
    attached_file_text: Optional[str] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> InvestigationContext:
    """Execute Layer 1: record user message, run Vision OCR, decode anchors, and merge context."""
    prior_messages = store.list_chat_messages(workspace_id)
    dossier_items = store.list_dossier_items(workspace_id)
    store.add_chat_message(
        workspace_id,
        role="user",
        content=prompt,
        payload={"has_image": bool(image_b64), "geo_point": geo_point, "has_file": bool(attached_file_text)},
    )

    # Vision OCR/Table Extraction if user pasted/uploaded a screenshot
    vision_extracted_text = ""
    if image_b64:
        v_prompt = (
            "Hãy đọc kỹ ảnh chụp màn hình / bảng biểu này và trích xuất toàn bộ thông tin quan trọng "
            "(Họ tên, MSSV, Ngày sinh, Ngành học, Mã lớp, Mã lớp học phần, Ngày nhập học, Địa điểm/Phòng học, Số hiệu văn bản). "
            f"Ngữ cảnh người dùng hỏi: {prompt}"
        )
        try:
            from app.core.key_pool import IntegrationStore

            v_pool = IntegrationStore(store.db_path)
            v_key = v_pool.acquire_key("gemini")
            v_api_key = v_key["api_key"] if v_key else settings.gemini_api_key
            v_model = model_override or (v_key["model"] if (v_key and v_key.get("model")) else settings.gemini_model)
            if v_api_key:
                vision_extracted_text = await GeminiProvider(v_api_key, v_model).analyze_image_and_text(
                    v_prompt, image_b64, mime_type=image_mime, client=client
                )
            elif settings.llm_provider == "ollama":
                vision_extracted_text = await OllamaProvider(
                    settings.ollama_base_url, settings.ollama_model
                ).analyze_image_and_text(v_prompt, image_b64, mime_type=image_mime, client=client)
        except Exception:
            vision_extracted_text = ""

    dossier_blob = "\n".join(f"{it['field_key']}: {it['field_value']}" for it in dossier_items)
    geo_blob = ""
    if geo_point and geo_point.get("lat") is not None and geo_point.get("lng") is not None:
        geo_label = str(geo_point.get("label") or "").strip()
        geo_blob = f"Vị trí bản đồ: {geo_label} ({geo_point['lat']}, {geo_point['lng']})"

    combined_input_text = "\n".join(
        part for part in (prompt, vision_extracted_text, attached_file_text or "", dossier_blob, geo_blob) if part
    ).strip()
    anchors = decode_high_entropy_anchors(combined_input_text)
    parsed = parse_user_prompt(prompt)

    # Hydrate Verified Dossier items into active search context
    for it in dossier_items:
        fk = it["field_key"].lower()
        fv = it["field_value"].strip()
        if not fv:
            continue
        if any(k in fk for k in ("tên", "name", "mục tiêu")) and parsed["target_name"] == "Đối tượng chưa rõ tên":
            parsed["target_name"] = fv
        elif any(k in fk for k in ("trường", "tổ chức", "công ty", "org", "school")) and fv not in parsed["organizations"]:
            parsed["organizations"].append(fv)
        elif any(k in fk for k in ("địa chỉ", "địa điểm", "quê", "location", "tọa độ")) and fv not in parsed["locations"]:
            parsed["locations"].append(fv)
        elif any(k in fk for k in ("ngày sinh", "dob", "birth")) and not parsed["birth_date"]:
            ndob, nyear = _normalize_dob_safe(fv)
            if ndob:
                parsed["birth_date"] = ndob
                if not parsed["birth_year"] and nyear:
                    parsed["birth_year"] = nyear
        elif any(k in fk for k in ("alias", "nick", "username", "github")) and fv not in parsed["aliases"] and not fv.isdigit():
            parsed["aliases"].append(fv)
        elif any(k in fk for k in ("loại trừ", "negative")) and fv not in parsed["negative_keywords"]:
            parsed["negative_keywords"].append(fv)
        elif fv not in parsed["keywords"] and len(fv) <= 60:
            parsed["keywords"].append(fv)

    if geo_point and geo_point.get("label"):
        g_lbl = str(geo_point["label"]).strip()
        if g_lbl and g_lbl not in parsed["locations"]:
            parsed["locations"].append(g_lbl)

    # Inject organizations inferred from academic emails / MSSV
    for inf_org in anchors.get("inferred_orgs", []):
        short_org = inf_org.split("(")[0].strip()
        if short_org and not any(normalize_text(short_org) in normalize_text(o) for o in parsed["organizations"]):
            parsed["organizations"].append(short_org)
    parsed["anchors"] = anchors

    # Multi-Turn Context Accumulation from prior assistant turns in this workspace
    prior_clues_list = [
        m["payload"].get("parsed_clues")
        for m in prior_messages
        if m.get("role") == "assistant" and isinstance(m.get("payload"), dict) and m["payload"].get("parsed_clues")
    ]
    if prior_clues_list:
        last_clues = prior_clues_list[-1]
        prior_name = last_clues.get("target_name", "")
        first_part = [p.strip() for p in re.split(r"[,;\n]+", prompt.strip()) if p.strip()][0] if prompt.strip() else ""
        first_low = first_part.lower()
        prior_mentioned_in_prose = bool(
            prior_name
            and parsed.get("is_long_snippet")
            and normalize_text(prior_name) in normalize_text(prompt)
        )
        is_followup_clue = (
            parsed["target_name"] == "Đối tượng chưa rõ tên"
            or parsed["target_name"] in parsed["organizations"]
            or parsed["target_name"] in parsed["locations"]
            or prior_mentioned_in_prose
            or any(k in first_low for k in ("khoa", "ngành", "lớp", "khóa", "sinh", "quê", "sđt", "email", "fb", "facebook"))
        )
        if prior_name and is_followup_clue:
            if (
                parsed["target_name"] != prior_name
                and parsed["target_name"] != "Đối tượng chưa rõ tên"
                and not prior_mentioned_in_prose
            ):
                parsed["keywords"].append(parsed["target_name"])
            parsed["target_name"] = prior_name

        if prior_name and normalize_text(parsed["target_name"]) == normalize_text(prior_name):
            # Walk newest-first so more recent corrections (e.g., corrected DOB/year) win over older turns
            for pc in reversed(prior_clues_list):
                if not parsed["birth_date"] and pc.get("birth_date"):
                    parsed["birth_date"] = pc["birth_date"]
                if not parsed["birth_year"] and pc.get("birth_year"):
                    parsed["birth_year"] = pc["birth_year"]
                for field_name in ("organizations", "locations", "aliases", "keywords", "negative_keywords"):
                    for val in pc.get(field_name, []):
                        if field_name == "aliases" and str(val).strip().isdigit():
                            continue
                        if field_name == "locations" and (len(str(val)) > 35 or any(c in str(val) for c in (":", ")", "("))):
                            continue
                        if val not in parsed[field_name]:
                            parsed[field_name].append(val)
                # Preserve decoded student_ids across turns for the same target
                prior_sids = (pc.get("anchors") or {}).get("student_ids", [])
                seen_sid_vals = {s["student_id"] for s in anchors.get("student_ids", [])}
                for psid in prior_sids:
                    if isinstance(psid, dict) and psid.get("student_id") and psid["student_id"] not in seen_sid_vals:
                        anchors["student_ids"].append(psid)
                        seen_sid_vals.add(psid["student_id"])

    # Hydrate clues from existing primary Person node in GraphStore
    existing_snapshot = store.get_graph(workspace_id)
    existing_persons = [
        n for n in (existing_snapshot.nodes if existing_snapshot else []) if n.type == "Person"
    ]
    if existing_persons:
        primary_person = existing_persons[0]
        if parsed["target_name"] == "Đối tượng chưa rõ tên" or parsed["target_name"] in parsed["organizations"]:
            parsed["target_name"] = primary_person.label
        if normalize_text(parsed["target_name"]) == normalize_text(primary_person.label):
            for c in primary_person.claims:
                if c.key == "school_or_org" and str(c.value) not in parsed["organizations"]:
                    parsed["organizations"].append(str(c.value))
                elif c.key == "location" and str(c.value) not in parsed["locations"]:
                    parsed["locations"].append(str(c.value))
                elif c.key == "birth_date" and not parsed["birth_date"]:
                    ndob, nyear = _normalize_dob_safe(str(c.value))
                    if ndob:
                        parsed["birth_date"] = ndob
                        if not parsed["birth_year"] and nyear:
                            parsed["birth_year"] = nyear
                elif c.key == "associated_year" and not parsed["birth_year"] and str(c.value).isdigit():
                    parsed["birth_year"] = int(c.value)
                elif c.polarity == "NEGATIVE" and str(c.value) not in parsed["negative_keywords"]:
                    parsed["negative_keywords"].append(str(c.value))

    # Final consistency lock: whenever exact full DOB is present, birth_year MUST match its year
    if parsed.get("birth_date"):
        _, final_y = _normalize_dob_safe(parsed["birth_date"])
        if final_y:
            parsed["birth_year"] = final_y

    region = parsed.get("region") or infer_query_region(prompt, "auto")
    phone_candidates = extract_phone_candidates(prompt)

    return InvestigationContext(
        workspace_id=workspace_id,
        raw_prompt=prompt,
        parsed=parsed,
        anchors=anchors,
        region=region,
        target_name=parsed["target_name"],
        vision_extracted_text=vision_extracted_text,
        dossier_blob=dossier_blob,
        geo_blob=geo_blob,
        phone_candidates=phone_candidates,
    )
