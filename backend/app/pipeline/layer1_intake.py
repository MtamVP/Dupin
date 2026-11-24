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
from app.core.anchor_decoder import decode_high_entropy_anchors, is_vn_major_code
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
    # Well-known Vietnamese high schools / middle schools often typed without "THPT"/"THCS" prefix
    "nguyễn thượng hiền",
    "nguyễn thương hiền",
    "lê hồng phong",
    "trần đại nghĩa",
    "nguyễn thị minh khai",
    "mạc đĩnh chi",
    "gia định",
    "bùi thị xuân",
    "lê quý đôn",
    "nguyễn hữu huân",
    "nguyễn công trứ",
    "trưng vương",
    "marie curie",
    "nguyễn gia thiều",
    "hà nội - amsterdam",
    "chu văn an",
    "kim liên",
    "phan đình phùng",
    "quốc học huế",
    "phổ thông năng khiếu",
    "ptnk",
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
    "mã định danh",
    "ma dinh danh",
    "cccd",
    "cmnd",
    "căn cước",
    "mst",
    "mã số thuế",
    "sbd",
    "số báo danh",
    "biển số",
    "orcid",
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

_FORM_KEY_BOUNDARY_RE = re.compile(
    r"(?=[ \t]+(?:Năm\s+sinh|Ngày\s+sinh|Giới\s+tính|Dân\s+tộc|Quốc\s+tịch|Nghề\s+nghiệp|"
    r"Điện\s+thoại|SĐT|Email|CCCD|CMND|Căn\s+cước[^\n:]{0,15}|Mã\s+định\s+danh[^\n:]{0,15}|"
    r"MST|Mã\s+số\s+thuế|SBD|Số\s+báo\s+danh|ORCID|Biển\s+số[^\n:]{0,10}|UID|"
    r"Đơn\s+vị[^\n:]{0,30}|Cơ\s+quan[^\n:]{0,20}|Công\s+ty|Địa\s+chỉ|"
    r"Nơi\s+sinh|Quê\s+quán|Cựu\s+sinh\s+viên[^\n:]{0,30}|Sinh\s+viên[^\n:]{0,30}|Trường|Khoa|Ngành|Chức\s+vụ|"
    r"Birth\s+year|Date\s+of\s+birth|Gender|Phone|Company|Organization|School|Occupation|Tax\s+ID|Citizen\s+ID)\s*:)",
    re.IGNORECASE,
)

# Use horizontal whitespace [ \t] only so names NEVER bleed across newlines into the next label
_LABELED_NAME_RE = re.compile(
    r"(?:Họ(?:[ \t]+và)?[ \t]+tên|Full[ \t]+name|cá[ \t]+nhân|mục[ \t]+tiêu|giảng[ \t]+viên|sinh[ \t]+viên|ThS\.|TS\.|PGS\.TS\.)"
    r"[ \t:]+([A-ZÀ-Ỹ][a-zà-ỹ]+(?:[ \t]+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,4})",
)
_EMBEDDED_DOB_RE = re.compile(r"\b(\d{1,2}[/\-.]\d{1,2}[/\-.](?:19[6-9]\d|20[0-2]\d))\b")
_KV_BIRTH_YEAR_RE = re.compile(
    r"(?:Năm\s+sinh|Sinh\s+năm|Birth\s+year|Born)\s*[:\s]\s*(19[4-9]\d|20[0-2]\d)\b",
    re.IGNORECASE,
)
_KV_ORG_LINE_RE = re.compile(
    r"(?:Đơn\s+vị\s+công\s+tác(?:\s+của\s+[^\n:]{1,20})?|Cơ\s+quan|Công\s+ty|Tổ\s+chức|Trường(?:\s+học)?|Company|Organization|Employer)"
    r"\s*:\s*([^\n]+)",
    re.IGNORECASE,
)
_KV_ALUMNI_ORG_RE = re.compile(
    r"(?:Cựu\s+sinh\s+viên|Sinh\s+viên|Tốt\s+nghiệp|Alumni\s+of)\s+([A-Za-zÀ-ỹ0-9&\-\s]{2,35}?)(?=\s*[:,\n(]|$)",
    re.IGNORECASE,
)
_KV_OCCUPATION_RE = re.compile(
    r"(?:Nghề\s+nghiệp|Chức\s+vụ|Occupation|Role)\s*:\s*([^\n]+)",
    re.IGNORECASE,
)


# Natural-language relational connectors (Vietnamese & English, comma-free sentences)
# Covers family (parents, children, siblings, grandparents, grandchildren, aunts/uncles, cousins, in-laws),
# romantic (spouse, fiance, partner, boyfriend/girlfriend), academic (classmate, teacher, advisor, senior/junior),
# and professional (colleague, manager, co-founder, roommate, friend, neighbor).
_NL_CONNECTOR_PREFIX = r"\s+(?:(?:và|mà|cũng|hiện|từng|đã|vốn)?\s*)*(?:là\s+)?"
_NL_HONORIFIC = r"(?:ông|bà|anh|chị|em|chú|cô|bác|dì|cậu|mợ|dượng|thầy|cô\s+giáo|tiến\s+sĩ|gs\.?|ts\.?|bs\.?|sếp)?\s*"

_NL_RELATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # --- Family: Child / Parent / Grandparent / Grandchild ---
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}con(?:\s+(?:trai|gái|ruột|đầu|cả|thứ|út|nuôi|rể|dâu))?\s+(?:của|nhà|ông|bà)\s*{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "CHILD_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:cha|bố|ba|mẹ|má|phụ\s+huynh)(?:\s+(?:ruột|đẻ|nuôi|chồng|vợ|dượng|kế))?\s+của\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "PARENT_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:ông|bà)(?:\s+(?:nội|ngoại))?\s+của\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "GRANDPARENT_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}cháu(?:\s+(?:trai|gái|nội|ngoại|ruột|họ))?\s+của\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "RELATIVE_OF",
    ),
    # --- Family: Siblings & Extended Relatives ---
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:anh(?:\s+(?:trai|ruột|cả|hai|họ|rể))?|chị(?:\s+(?:gái|ruột|cả|hai|họ|dâu))?|em(?:\s+(?:trai|gái|ruột|họ|út|kết\s+nghĩa))?)\s+(?:của|với)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "SIBLING_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:chú|bác|cô|dì|cậu|mợ|dượng|thím|anh\s+em\s+họ|chị\s+em\s+họ|họ\s+hàng|người\s+nhà|người\s+thân)\s+(?:của|với)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "RELATIVE_OF",
    ),
    # --- Romantic / Spouse ---
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:vợ|chồng|bà\s+xã|ông\s+xã|vợ\s+cũ|chồng\s+cũ|hôn\s+phu|hôn\s+thê|vợ\s+chưa\s+cưới|chồng\s+chưa\s+cưới)\s+(?:của|với)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "SPOUSE_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:bạn\s+trai|bạn\s+gái|người\s+yêu|ny|nyc|người\s+yêu\s+cũ|bồ|partner)\s+(?:của|với)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "PARTNER_OF",
    ),
    # --- Academic / School / Mentor ---
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:bạn\s+cùng\s+lớp|bạn\s+học|cùng\s+lớp|cùng\s+khóa|cùng\s+trường|đồng\s+môn|bạn\s+đại\s+học|bạn\s+cấp\s*[123]|đàn\s+anh|đàn\s+em|tiền\s+bối|hậu\s+bối)\s+(?:của|với)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "CLASSMATE_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:học\s+trò|sinh\s+viên|nghiên\s+cứu\s+sinh|học\s+viên)\s+(?:của|dưới\s+trướng)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "STUDENT_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:thầy|cô|giảng\s+viên|giáo\s+viên|gvhd|người\s+hướng\s+dẫn|cố\s+vấn|mentor)\s+(?:của|cho)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "MENTOR_OF",
    ),
    # --- Work / Professional / Social ---
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:đồng\s+nghiệp|cùng\s+công\s+ty|cùng\s+team|cùng\s+nhóm|cộng\s+sự|đối\s+tác|đồng\s+sáng\s+lập|co-?founder|làm\s+chung\s+với)\s+(?:của|với)?\s*{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "COLLEAGUE_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:sếp|quản\s+lý|trưởng\s+phòng|giám\s+đốc|cấp\s+trên|manager|boss)\s+(?:của)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "MANAGER_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:nhân\s+viên|cấp\s+dưới|trợ\s+lý|thư\s+ký|thực\s+tập\s+sinh)\s+(?:của|cho)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "SUBORDINATE_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:bạn\s+cùng\s+phòng|ở\s+ghép\s+với|roommate|hàng\s+xóm)\s+(?:của|với)?\s*{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "ROOMMATE_OR_NEIGHBOR_OF",
    ),
    (
        re.compile(
            rf"{_NL_CONNECTOR_PREFIX}(?:bạn(?:\s+(?:thân|chơi\s+chung|cũ|mới))?|quen(?:\s+biết)?|có\s+liên\s+quan|liên\s+hệ)\s+(?:của|với|tới)\s+{_NL_HONORIFIC}",
            re.IGNORECASE,
        ),
        "FRIEND_OR_ASSOCIATE_OF",
    ),
    # --- English Relational Connectors ---
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:son|daughter|child)\s+of\s+(?:mr\.?|mrs\.?|ms\.?|dr\.?)?\s*", re.IGNORECASE),
        "CHILD_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:wife|husband|spouse)\s+of\s+(?:mr\.?|mrs\.?|ms\.?|dr\.?)?\s*", re.IGNORECASE),
        "SPOUSE_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:boyfriend|girlfriend|partner|fiance|fiancee)\s+of\s+(?:mr\.?|mrs\.?|ms\.?|dr\.?)?\s*", re.IGNORECASE),
        "PARTNER_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:father|mother|parent)\s+of\s+(?:mr\.?|mrs\.?|ms\.?|dr\.?)?\s*", re.IGNORECASE),
        "PARENT_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:brother|sister|sibling|younger\s+brother|older\s+brother|younger\s+sister|older\s+sister)\s+of\s+", re.IGNORECASE),
        "SIBLING_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:cousin|uncle|aunt|nephew|niece|relative)\s+of\s+", re.IGNORECASE),
        "RELATIVE_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:a\s+|the\s+)?(?:colleague|coworker|co-worker|co-?founder|partner)\s+(?:of|with)\s+", re.IGNORECASE),
        "COLLEAGUE_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:a\s+|the\s+)?(?:classmate|schoolmate|roommate|friend)\s+(?:of|with)\s+", re.IGNORECASE),
        "CLASSMATE_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:student|mentee)\s+of\s+(?:prof\.?|dr\.?)?\s*", re.IGNORECASE),
        "STUDENT_OF",
    ),
    (
        re.compile(r"\s+(?:is\s+)?(?:the\s+)?(?:advisor|supervisor|mentor|professor)\s+of\s+", re.IGNORECASE),
        "MENTOR_OF",
    ),
)

# Inline natural-language clause splitters for comma-free Vietnamese & English prompts
_NL_CLAUSE_SPLIT_RE = re.compile(
    r"\s+(?="
    r"(?:sinh\s+ngày|sinh\s+năm|sn\s+\d{4}|"
    r"(?:đang\s+|từng\s+)?(?:học|làm\s+việc|công\s+tác|tốt\s+nghiệp)\s+(?:tại|ở|trường)\b|"
    r"(?<!đại\s)(?<!trung\s)học\s+(?:trường|thpt|thcs|đh|đại\s+học)\b|"
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
    r"^(?:(?:hiện\s+)?(?:đang|từng|đã)\s+)?(?:theo\s+)?(?:học|làm\s+việc|công\s+tác|tốt\s+nghiệp)(?:\s+cấp\s*[123])?\s+(?:tại|ở)\s+|"
    r"^(?:(?:hiện\s+)?(?:đang|từng|đã)\s+)?(?:theo\s+)?học(?:\s+cấp\s*[123])?\s+(?=(?:trường|thpt|thcs|đh|đại\s+học|[A-Z]{2,8}\b))|"
    r"^(?:cựu\s+học\s+sinh|cựu\s+sinh\s+viên|là\s+sinh\s+viên|sinh\s+viên)\s+(?:tại\s+|ở\s+|trường\s+)?|"
    r"^(?:(?:cũng\s+)?(?:sống\s+tại|sống\s+ở|quê\s+ở|quê\s+tại|ở|tại))\s+|"
    r"^sinh\s+ngày\s+|"
    r"^born\s+(?:on\s+)?|"
    r"^(?:works?|worked|studying|studied|student|alumni|professor)\s+(?:at|in|of)\s+|"
    r"^(?:based\s+in|living\s+in|from)\s+",
    re.IGNORECASE,
)

_BLOCKED_PLATFORM_ALIASES = frozenset({
    "không", "khong", "none", "null", "unknown", "chưa", "chua",
    "linkedin", "facebook", "github", "instagram", "tiktok", "twitter",
    "threads", "zalo", "google", "studocu", "scribd", "youtube",
    "telegram", "mastodon", "codeforces", "atcoder", "orcid", "gmail",
})

_ORG_MAJOR_SPLIT_RE = re.compile(
    r"\s*(?:[-–—,|]\s*)?\b(?:chuyên\s+ngành|ngành)\s+([A-Za-zÀ-ỹ0-9\s,&\-]{2,45})$",
    re.IGNORECASE,
)


def _clean_org_and_extract_major(raw_org: str) -> tuple[list[str], list[str]]:
    """Strip conversational verbs ('đang học', 'Từng học cấp 2'), reject Markdown headers,
    and split trailing ' - Ngành ...' into (clean_orgs, extracted_major_keywords).
    """
    s = (raw_org or "").strip(" ,;.-")
    if not s or any(ch in s for ch in ("#", "[", "]", "*")):
        return [], []
    low_s = s.lower()
    if any(bad in low_s for bad in ("tóm tắt trường", "trường chuẩn hóa", "không hiển thị", "chưa rõ")):
        return [], []

    # Strip conversational prefix if still present
    s = _NL_CLAUSE_PREFIX_STRIP_RE.sub("", s).strip(" ,;.-")
    s = re.sub(
        r"^(?:(?:hiện\s+)?(?:đang|từng|đã)\s+)?(?:theo\s+)?(?:học|làm\s+việc|công\s+tác|tốt\s+nghiệp)(?:\s+cấp\s*[123])?\s+",
        "",
        s,
        flags=re.IGNORECASE,
    ).strip(" ,;.-")

    majors: list[str] = []
    # Extract parenthetical acronyms or sub-notes BEFORE stripping parentheses
    paren_orgs: list[str] = []
    for pm in re.finditer(r"\(([^()]{2,80})\)", s):
        p_txt = pm.group(1).strip()
        if re.match(r"^[A-Z]{2,8}$", p_txt):
            paren_orgs.append(p_txt)
        else:
            # e.g. "(Cựu học sinh THPT chuyên Trần Đại Nghĩa, chuyên Văn)"
            for sub in p_txt.split(","):
                sub_clean = _NL_CLAUSE_PREFIX_STRIP_RE.sub("", sub.strip()).strip()
                if any(k in sub_clean.lower() for k in ("thpt", "thcs", "đại học", "trường")):
                    paren_orgs.append(sub_clean)
                elif sub_clean.lower().startswith("chuyên ") and len(sub_clean) <= 30:
                    majors.append(sub_clean)

    s_no_paren = re.sub(r"\([^)]*\)", "", s).strip(" ,;.-")
    m_maj = _ORG_MAJOR_SPLIT_RE.search(s_no_paren)
    if m_maj:
        maj_val = m_maj.group(1).strip(" ,;.-")
        if maj_val:
            majors.append(f"ngành {maj_val}" if not maj_val.lower().startswith("ngành") else maj_val)
        s_no_paren = s_no_paren[: m_maj.start()].strip(" ,;.-")

    out_orgs: list[str] = []
    for cand in [s_no_paren] + paren_orgs:
        c = _NL_CLAUSE_PREFIX_STRIP_RE.sub("", cand).strip(" ,;.-")
        if 2 <= len(c) <= 55 and not any(ch in c for ch in ("#", "[", "]", ":", ")")):
            out_orgs.append(c)
    return out_orgs, majors


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

    # Long-prose / Key:Value bio / pasted AI-summary pre-extraction
    is_kv_form = raw.count(":") >= 2 and bool(
        re.search(
            r"(?:họ(?:\s+và)?\s+tên|năm\s+sinh|ngày\s+sinh|nghề\s+nghiệp|đơn\s+vị\s+công\s+tác|điện\s+thoại|cựu\s+sinh\s+viên|full\s+name|birth\s+year)\s*:",
            raw,
            re.IGNORECASE,
        )
    )
    is_prose_paste = (
        is_kv_form
        or len(raw) >= 120
        or "•" in raw
        or bool(re.search(r"\b(?:họ(?:\s+và)?\s+tên|giới\s+tính|dựa\s+trên\s+thông\s+tin)\b", raw, re.IGNORECASE))
    )
    if is_prose_paste:
        # Insert line breaks before Key:Value headers so single-line pasted forms split cleanly
        raw_lined = _FORM_KEY_BOUNDARY_RE.sub("\n", raw) if is_kv_form else raw

        m_name = _LABELED_NAME_RE.search(raw_lined)
        if m_name:
            cand_name = re.sub(r"\s+", " ", m_name.group(1)).strip()
            # Guard against trailing single form-header token if pasted without colon
            cand_name = re.sub(r"\s+(?:Năm|Ngày|Giới|Dân|Quốc|Nghề|Điện|Đơn|Địa|Nơi|Quê|Cựu)$", "", cand_name).strip()
            if cand_name and not _is_non_name_label(cand_name):
                target_name = cand_name

        m_dob = _EMBEDDED_DOB_RE.search(raw_lined)
        if m_dob:
            ndob, nyear = _normalize_dob_safe(m_dob.group(1))
            if ndob:
                birth_date = ndob
                birth_year = nyear

        if not birth_year:
            m_by = _KV_BIRTH_YEAR_RE.search(raw_lined)
            if m_by:
                birth_year = int(m_by.group(1))

        # Extract organizations from Key:Value lines (e.g. "Đơn vị công tác: Công ty TNHH X (...)" & "Cựu sinh viên UEH:")
        for m_org in _KV_ORG_LINE_RE.finditer(raw_lined):
            c_orgs, c_majors = _clean_org_and_extract_major(m_org.group(1))
            for org_val in c_orgs:
                if not any(normalize_text(org_val) == normalize_text(x) for x in organizations):
                    organizations.append(org_val)
            for maj_val in c_majors:
                if maj_val not in keywords:
                    keywords.append(maj_val)

        for m_alum in _KV_ALUMNI_ORG_RE.finditer(raw_lined):
            c_orgs, _ = _clean_org_and_extract_major(m_alum.group(1))
            for alum_org in c_orgs:
                if not any(normalize_text(alum_org) == normalize_text(x) for x in organizations):
                    organizations.append(alum_org)

        for m_occ in _KV_OCCUPATION_RE.finditer(raw_lined):
            occ_val = m_occ.group(1).strip(" ,;.-")
            if 2 <= len(occ_val) <= 45 and occ_val not in keywords:
                keywords.append(occ_val)

        raw_low = raw_lined.lower()
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

        # Skip long descriptive sentences (> 65 chars) from being misclassified as org or person name;
        # avoid dumping raw multi-field Key:Value headers (containing ':') into keywords.
        if len(part) > 65:
            if ":" not in part:
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

        # Explicit institutional/corporate nouns checked BEFORE LOC_HINTS so
        # "University of Toronto", "Đại học Hà Nội", "ĐH Đà Nẵng" classify as organizations, not locations!
        # Note: Do NOT match unaccented "truong" against accented Vietnamese family name "Trương ..."!
        strong_org_markers = (
            "đại học", "dai hoc", "trường", "thpt", "thcs", "học viện", "hoc vien",
            "công ty", "cong ty", "tập đoàn", "tap doan", "university", "institute", "college",
            "school", "academy", "polytechnic", "laboratory", "corp", "inc", "ltd", "llc", "gmbh",
        )
        is_unaccented_school_phrase = bool(
            re.search(r"\btruong\s+(?:dh|dai\s+hoc|thpt|thcs|tieu\s+hoc|cao\s+dang|trung\s+cap|quoc\s+te|chuyen)\b", norm)
            and "trương" not in low
        )
        if (
            len(part) <= 55
            and not any(ch in part for ch in (":", ")", "#", "[", "]"))
            and (
                any(m in low or (m != "trường" and m in norm) for m in strong_org_markers)
                or is_unaccented_school_phrase
            )
        ):
            c_orgs, c_majors = _clean_org_and_extract_major(part)
            for org_val in c_orgs:
                if not any(normalize_text(org_val) == normalize_text(x) for x in organizations):
                    organizations.append(org_val)
            for maj_val in c_majors:
                if maj_val not in keywords:
                    keywords.append(maj_val)
            continue

        # Location hints (checked BEFORE uppercase org acronym check so TPHCM, USA, UK map to locations!)
        # Reject noisy prose clauses (> 35 chars or containing ':' / ')') from polluting locations.
        if (
            len(part) <= 35
            and not any(ch in part for ch in (":", ")", "("))
            and any(h in low or h in norm for h in LOC_HINTS)
        ):
            clean_loc = re.sub(
                r"^(?:cũng\s+)?(?:sống\s+)?(?:ở|tại|quê\s+ở|quê\s+tại)\s+",
                "",
                part,
                flags=re.IGNORECASE,
            )
            clean_loc = re.sub(r"\s+(?:luôn|nhé|nha|ạ|nữa|đấy|đó)$", "", clean_loc, flags=re.IGNORECASE).strip(" ,.-")
            clean_loc = clean_loc or part
            if not any(normalize_text(clean_loc) == normalize_text(x) for x in locations):
                locations.append(clean_loc)
            continue

        # Organization / School hints (explicit hints OR uppercase institution/company acronyms like USSH, FTU, UEH, MIT)
        is_org_acronym = (
            bool(re.match(r"^[A-Z]{2,8}(?:-[A-Z]{2,8})?$", part))
            and part.upper() not in non_org_acronyms
        )
        if (
            (len(part) <= 45 and not any(ch in part for ch in (":", ")", "#", "[", "]")) and any(h in low or h in norm for h in ORG_HINTS))
            or is_org_acronym
        ):
            c_orgs, c_majors = _clean_org_and_extract_major(part)
            for org_val in c_orgs:
                if not any(normalize_text(org_val) == normalize_text(x) for x in organizations):
                    organizations.append(org_val)
            for maj_val in c_majors:
                if maj_val not in keywords:
                    keywords.append(maj_val)
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
        elif ":" not in part and ")" not in part:
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
    user_msg_payload: dict[str, Any] = {
        "has_image": bool(image_b64),
        "geo_point": geo_point,
        "has_file": bool(attached_file_text),
    }
    if image_b64 and len(image_b64) <= 600_000:
        user_msg_payload["image_preview_url"] = f"data:{image_mime or 'image/png'};base64,{image_b64}"
    store.add_chat_message(
        workspace_id,
        role="user",
        content=prompt,
        payload=user_msg_payload,
    )

    # Vision OCR / IMINT (Uniforms, Badges, Signage, License Plates) + Local EXIF/GPS Metadata Extraction
    vision_extracted_text = ""
    exif_meta: dict[str, Any] = {}
    if image_b64:
        from app.connectors.multimodal_intake import build_imint_vision_prompt, extract_image_exif_metadata

        exif_meta = extract_image_exif_metadata(image_b64)
        v_prompt = build_imint_vision_prompt(prompt)
        try:
            from app.core.key_pool import IntegrationStore

            v_pool = IntegrationStore(store.db_path)
            active_v_keys = [k for k in v_pool.list_keys("gemini") if k.get("enabled")]
            max_v_attempts = max(1, min(len(active_v_keys), 8))
            tried_v_ids: set[str] = set()
            for v_attempt in range(max_v_attempts):
                v_key = v_pool.acquire_key("gemini")
                if v_key and v_key["id"] in tried_v_ids:
                    break
                if v_key:
                    tried_v_ids.add(v_key["id"])
                v_api_key = v_key["api_key"] if v_key else (settings.gemini_api_key if v_attempt == 0 else "")
                v_model = model_override or (
                    v_key["model"] if (v_key and v_key.get("model")) else settings.gemini_model
                )
                if not v_api_key:
                    break
                try:
                    vision_extracted_text = await GeminiProvider(v_api_key, v_model).analyze_image_and_text(
                        v_prompt, image_b64, mime_type=image_mime, client=client
                    )
                    if vision_extracted_text:
                        break
                except httpx.HTTPStatusError as exc:
                    if v_key:
                        v_pool.report_key_error(v_key["id"], is_rate_limit=(exc.response.status_code == 429))
                    continue
                except Exception:
                    if v_key:
                        v_pool.report_key_error(v_key["id"], is_rate_limit=False)
                    continue
            if not vision_extracted_text and settings.llm_provider == "ollama":
                vision_extracted_text = await OllamaProvider(
                    settings.ollama_base_url, settings.ollama_model
                ).analyze_image_and_text(v_prompt, image_b64, mime_type=image_mime, client=client)
        except Exception:
            vision_extracted_text = ""
        if exif_meta.get("summary_text"):
            vision_extracted_text = (
                f"{vision_extracted_text}\n{exif_meta['summary_text']}".strip()
                if vision_extracted_text
                else str(exif_meta["summary_text"])
            )
        if not geo_point and exif_meta.get("gps_lat") is not None and exif_meta.get("gps_lng") is not None:
            geo_point = {
                "lat": exif_meta["gps_lat"],
                "lng": exif_meta["gps_lng"],
                "label": "EXIF GPS Metadata",
            }

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

    # Hydrate clues discovered from Vision IMINT/OCR or Attached Documents (PDF/XLSX/CSV/vCard)
    # so users can investigate directly from an image or file even without typing text clues!
    _GENERIC_PROMPT_PREFIXES = (
        "phân tích",
        "phan tich",
        "tìm thông tin",
        "tim thong tin",
        "tra cứu",
        "tra cuu",
        "kiểm tra",
        "kiem tra",
        "ai đây",
        "ai day",
        "analyze ",
        "find ",
        "who is",
        "investigate",
    )
    for extra_source_text in (vision_extracted_text, attached_file_text or ""):
        if not extra_source_text or not extra_source_text.strip():
            continue
        extra_parsed = parse_user_prompt(extra_source_text[:3500])
        cur_tname = str(parsed.get("target_name") or "").strip()
        cur_tname_low = cur_tname.lower()
        is_placeholder_target = (
            not cur_tname
            or cur_tname == "Đối tượng chưa rõ tên"
            or len(cur_tname.split()) > 5
            or cur_tname_low.startswith(_GENERIC_PROMPT_PREFIXES)
        )
        ext_tname = str(extra_parsed.get("target_name") or "").strip()
        if (
            is_placeholder_target
            and ext_tname
            and ext_tname != "Đối tượng chưa rõ tên"
            and 1 <= len(ext_tname.split()) <= 5
            and len(re.findall(r"[A-Za-zÀ-ỹ]", ext_tname)) >= 3
            and not any(c.isdigit() for c in ext_tname)
            and not ext_tname.lower().startswith(_GENERIC_PROMPT_PREFIXES)
        ):
            parsed["target_name"] = ext_tname
        if not parsed.get("birth_date") and extra_parsed.get("birth_date"):
            parsed["birth_date"] = extra_parsed["birth_date"]
        if not parsed.get("birth_year") and extra_parsed.get("birth_year"):
            parsed["birth_year"] = extra_parsed["birth_year"]
        for org_val in extra_parsed.get("organizations", []):
            if not any(normalize_text(org_val) == normalize_text(o) for o in parsed["organizations"]):
                parsed["organizations"].append(org_val)
        for loc_val in extra_parsed.get("locations", []):
            if not any(normalize_text(loc_val) == normalize_text(l) for l in parsed["locations"]):
                parsed["locations"].append(loc_val)
        for kw_val in extra_parsed.get("keywords", [])[:4]:
            if kw_val not in parsed["keywords"] and len(kw_val) <= 60 and not any(ch in kw_val for ch in ("#", "[", "]")):
                parsed["keywords"].append(kw_val)
        # Extract social handles labeled in Vision OCR (e.g. "Username LinkedIn / Mạng xã hội: NhuNguyenAnh" or "LinkedIn - `NhuNguyenAnh`")
        for m_vh in re.finditer(
            r"(?:username|user\s*name|handle|nick|linkedin|github|instagram|tiktok)[^:\n]{0,35}:\s*(?:(?:linkedin|facebook|github|instagram|tiktok)\s*[-–:]\s*)?[`'\"]?@?([A-Za-z0-9_.-]{4,35})[`'\"]?\b",
            extra_source_text,
            re.IGNORECASE,
        ):
            vh = m_vh.group(1).strip(" .,-`'")
            if (
                vh
                and not vh.isdigit()
                and vh.lower() not in _BLOCKED_PLATFORM_ALIASES
                and vh not in parsed["aliases"]
            ):
                parsed["aliases"].append(vh)

    # Detect upfront if the user explicitly pivoted to a NEW target person in this workspace
    # (e.g. "Đặng Như Phong sinh năm 1996 là em ruột của Đặng Kiều Diễm") so we don't leak
    # the prior person's dossier anchors (MSSV, DOB, org) onto the new target!
    prior_clues_list = [
        m["payload"].get("parsed_clues")
        for m in prior_messages
        if m.get("role") == "assistant" and isinstance(m.get("payload"), dict) and m["payload"].get("parsed_clues")
    ]
    prior_name_preview = prior_clues_list[-1].get("target_name", "") if prior_clues_list else ""
    parsed_tname_preview = str(parsed.get("target_name") or "").strip()
    first_part_preview = (
        [p.strip() for p in re.split(r"[,;\n]+", prompt.strip()) if p.strip()][0] if prompt.strip() else ""
    )
    pivoted_to_new_person = bool(
        parsed_tname_preview
        and parsed_tname_preview != "Đối tượng chưa rõ tên"
        and prior_name_preview
        and normalize_text(parsed_tname_preview) != normalize_text(prior_name_preview)
        and parsed_tname_preview not in parsed["organizations"]
        and parsed_tname_preview not in parsed["locations"]
        and 2 <= len(parsed_tname_preview.split()) <= 5
        and not any(ch.isdigit() for ch in parsed_tname_preview)
        and not any(
            parsed_tname_preview.lower().startswith(k)
            for k in ("khoa ", "ngành ", "lớp ", "khóa ", "sinh ", "quê ", "sđt", "email", "fb ", "facebook")
        )
        and (
            bool(parsed.get("related_people"))
            or normalize_text(first_part_preview).startswith(normalize_text(parsed_tname_preview))
        )
    )
    if pivoted_to_new_person:
        # Re-decode anchors strictly from the NEW prompt + attachments (excluding old person's dossier_blob)
        new_person_text = "\n".join(
            part for part in (prompt, vision_extracted_text, attached_file_text or "", geo_blob) if part
        ).strip()
        anchors = decode_high_entropy_anchors(new_person_text)
    else:
        # Hydrate Verified Dossier items into active search context (same target person)
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

    # Hydrate public schema metadata decoded from Vietnamese 12-digit CCCD (birth_year, birth_province)
    for c_info in anchors.get("cccds", []):
        if c_info.get("birth_year") and not parsed.get("birth_year"):
            parsed["birth_year"] = int(c_info["birth_year"])
        prov = str(c_info.get("birth_province") or "").strip()
        if prov and not any(normalize_text(prov) == normalize_text(x) for x in parsed["locations"]):
            parsed["locations"].append(prov)

    # Hydrate province from Vietnamese license plate if no location is set yet
    if not parsed["locations"]:
        for lp in anchors.get("license_plates", []):
            prov = str(lp.get("province") or "").strip()
            if prov and not any(normalize_text(prov) == normalize_text(x) for x in parsed["locations"]):
                parsed["locations"].append(prov)

    # Hydrate social handles extracted from Telegram / LinkedIn URLs
    for sid_obj in anchors.get("social_ids", []):
        if sid_obj.get("platform") in ("telegram", "linkedin"):
            handle = str(sid_obj.get("id") or "").strip()
            if handle and handle not in parsed["aliases"]:
                parsed["aliases"].append(handle)

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
        # If the user explicitly pivoted to a NEW target person (e.g., "Đặng Như Phong sinh năm 1996 là em ruột của Đặng Kiều Diễm"),
        # `parsed["target_name"]` is a valid multi-word person name distinct from `prior_name` (and not an org/loc/keyword).
        # Never overwrite a new target person just because `first_part` contains "sinh năm 1996" or mentions `prior_name` as a relative!
        parsed_tname = str(parsed.get("target_name") or "").strip()
        is_explicit_new_person = bool(
            parsed_tname
            and parsed_tname != "Đối tượng chưa rõ tên"
            and prior_name
            and normalize_text(parsed_tname) != normalize_text(prior_name)
            and parsed_tname not in parsed["organizations"]
            and parsed_tname not in parsed["locations"]
            and 2 <= len(parsed_tname.split()) <= 5
            and not any(ch.isdigit() for ch in parsed_tname)
            and not any(
                parsed_tname.lower().startswith(k)
                for k in ("khoa ", "ngành ", "lớp ", "khóa ", "sinh ", "quê ", "sđt", "email", "fb ", "facebook")
            )
            and (
                bool(parsed.get("related_people"))
                or normalize_text(first_part).startswith(normalize_text(parsed_tname))
            )
        )
        is_followup_clue = (
            not is_explicit_new_person
            and (
                parsed_tname == "Đối tượng chưa rõ tên"
                or parsed_tname in parsed["organizations"]
                or parsed_tname in parsed["locations"]
                or prior_mentioned_in_prose
                or any(k in first_low for k in ("khoa", "ngành", "lớp", "khóa", "sinh", "quê", "sđt", "email", "fb", "facebook"))
            )
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
                        s_val = str(val or "").strip()
                        if not s_val:
                            continue
                        if field_name == "aliases":
                            if s_val.isdigit() or s_val.lower() in _BLOCKED_PLATFORM_ALIASES:
                                continue
                            if s_val not in parsed["aliases"]:
                                parsed["aliases"].append(s_val)
                        elif field_name == "organizations":
                            c_orgs, c_majors = _clean_org_and_extract_major(s_val)
                            for co in c_orgs:
                                if not any(normalize_text(co) == normalize_text(x) for x in parsed["organizations"]):
                                    parsed["organizations"].append(co)
                            for cm in c_majors:
                                if cm not in parsed["keywords"]:
                                    parsed["keywords"].append(cm)
                        elif field_name == "locations":
                            if (
                                len(s_val) > 35
                                or any(c in s_val for c in (":", ")", "(", "#", "*"))
                                or not any(h in s_val.lower() or h in normalize_text(s_val) for h in LOC_HINTS)
                            ):
                                continue
                            if not any(normalize_text(s_val) == normalize_text(x) for x in parsed["locations"]):
                                parsed["locations"].append(s_val)
                        elif field_name == "keywords":
                            if any(c in s_val for c in ("#", "[", "]", "*", "`")) or len(s_val) > 60:
                                continue
                            if s_val not in parsed["keywords"]:
                                parsed["keywords"].append(s_val)
                        else:
                            if s_val not in parsed[field_name]:
                                parsed[field_name].append(s_val)
                # Preserve decoded student_ids across turns for the same target (excluding MOET 7-digit major codes)
                prior_sids = (pc.get("anchors") or {}).get("student_ids", [])
                seen_sid_vals = {s["student_id"] for s in anchors.get("student_ids", [])}
                for psid in prior_sids:
                    if (
                        isinstance(psid, dict)
                        and psid.get("student_id")
                        and not is_vn_major_code(psid["student_id"])
                        and psid["student_id"] not in seen_sid_vals
                    ):
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
                c_val_str = str(c.value or "").strip()
                if c.key == "school_or_org":
                    c_orgs, _ = _clean_org_and_extract_major(c_val_str)
                    for co in c_orgs:
                        if not any(normalize_text(co) == normalize_text(x) for x in parsed["organizations"]):
                            parsed["organizations"].append(co)
                elif c.key == "location":
                    if (
                        len(c_val_str) <= 35
                        and any(h in c_val_str.lower() or h in normalize_text(c_val_str) for h in LOC_HINTS)
                        and not any(normalize_text(c_val_str) == normalize_text(x) for x in parsed["locations"])
                    ):
                        parsed["locations"].append(c_val_str)
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

    region = parsed.get("region") or infer_query_region(combined_input_text or prompt, "auto")
    phone_candidates = extract_phone_candidates(combined_input_text or prompt)
    parsed["phone_candidates"] = phone_candidates
    if exif_meta.get("has_exif"):
        parsed["image_exif"] = exif_meta

    from urllib.parse import unquote

    def _norm_u(u: str) -> str:
        return unquote(str(u or "")).strip().rstrip("/").lower()

    confirmed_urls: set[str] = {
        _norm_u(it.get("source_url", ""))
        for it in dossier_items
        if it.get("source_url")
    }
    feedback_rows = store.list_source_feedback(workspace_id)
    rejected_urls: set[str] = set()
    for fb in feedback_rows:
        nu = _norm_u(fb.get("source_url", ""))
        if not nu:
            continue
        if fb.get("verdict") == "REJECTED":
            rejected_urls.add(nu)
        elif fb.get("verdict") == "CONFIRMED":
            confirmed_urls.add(nu)

    previously_shown_unverified_urls: set[str] = set()
    if not pivoted_to_new_person:
        for m in prior_messages:
            if m.get("role") == "assistant" and isinstance(m.get("payload"), dict):
                for s_item in m["payload"].get("discovered_sources") or []:
                    su = _norm_u(s_item.get("url", ""))
                    if su and su not in confirmed_urls and su not in rejected_urls:
                        previously_shown_unverified_urls.add(su)

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
        rejected_urls=rejected_urls,
        confirmed_urls=confirmed_urls,
        previously_shown_unverified_urls=previously_shown_unverified_urls,
    )
