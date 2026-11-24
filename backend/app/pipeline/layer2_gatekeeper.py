"""Layer 2 (Outer Sanitization & Noise Shield): Gatekeeper, Temporal Veto & Relevance Scoring.

All external web/mirror/registry candidates from Layer 3 MUST pass through this outer filter layer
BEFORE entering Layer 4 (the Deep Core Knowledge Graph & MCTS engine).

Defenses implemented at the perimeter:
1. URL Hygiene & Deduplication (percent-decoded canonical URL, junk category & e-commerce reject, title cap).
2. Negative Constraint Instant Veto (user/Reflexion-learned exclusions).
3. Temporal Seniority & High-School/University Grade-Age Impossibility Veto (eliminates wrong-generation homonyms).
4. Cross-Clue Target Relevance Scoring (full name, alias, shortened-name+org, exact-DOB+partial-name/org).
5. High-Entropy Student ID Academic Context Gate (rejects foreign auto-parts/SKU/vessel false matches).
6. Transparent Rejection Telemetry (`rejected_by_reason`) so every blocked candidate is auditable.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote

from app.connectors.mirror_pivots import is_junk_category_url
from app.core.anchor_decoder import is_vn_major_code
from app.core.normalizer import normalize_org_or_location, normalize_text
from app.pipeline.models import GateDecision, GatekeeperTelemetry, InvestigationContext

ORG_EN_ALIASES: dict[str, tuple[str, ...]] = {
    "ussh": ("social sciences and humanities", "hcmussh", "nhan van"),
    "uit": ("university of information technology", "cong nghe thong tin"),
    "ueh": ("university of economics ho chi minh", "kinh te tp hcm", "kinh te thanh pho"),
    "ump": ("university of medicine and pharmacy", "y duoc"),
    "hcmut": ("ho chi minh city university of technology", "bach khoa"),
    "hcmus": ("university of science", "khoa hoc tu nhien"),
    "hust": ("hanoi university of science and technology", "bach khoa ha noi"),
}

VN_COMMON_SURNAMES: tuple[str, ...] = (
    "nguyen",
    "tran",
    "le",
    "pham",
    "hoang",
    "huynh",
    "phan",
    "vu",
    "vo",
    "dang",
    "bui",
    "do",
    "ho",
    "ngo",
    "duong",
    "ly",
    "dinh",
    "doan",
    "truong",
    "to",
    "mai",
    "luong",
    "ta",
    "cao",
)

SENIOR_MARKERS: tuple[str, ...] = (
    "pgs.ts",
    "pgs ts",
    "phó giáo sư",
    "gs.ts",
    "bs.ck2",
    "bs.ckii",
    "bs ck2",
    "bác sĩ chuyên khoa 2",
    "chi ủy viên",
    "trưởng đơn vị",
    "phó chủ tịch",
    "giám đốc bệnh viện",
    "thạc sĩ",
    "ths ",
    "ths.",
    "tiến sĩ",
    "master of engineering",
    "master of science",
    "master of arts",
    "m.eng",
    "m.sc",
    "chuyên gia",
    "/chuyen-gia/",
    "giảng viên",
    "học thầy",
    "thầy ",
)


def _evaluate_relevance_detailed(
    text: str,
    url: str,
    parsed: dict[str, Any],
) -> GateDecision:
    """Core Layer 2 decision logic returning accepted flag, cross-clue score, labels, and reject_reason."""
    combined = normalize_text(f"{text} {url}")
    target_norm = normalize_text(parsed["target_name"])
    target_joined = target_norm.replace(" ", "")

    # 1. Negative keyword instant veto
    for neg in parsed.get("negative_keywords", []):
        neg_n = normalize_text(neg)
        if neg_n and neg_n in combined:
            return GateDecision(accepted=False, reject_reason="negative_veto")

    # 2. Temporal Seniority & High-School/University Grade-Age Veto
    exact_dob_hit = False
    if parsed.get("birth_date"):
        dob_parts = str(parsed["birth_date"]).split("/")
        if len(dob_parts) == 3 and all(p.isdigit() for p in dob_parts):
            d, m, y = dob_parts
            exact_dob_forms = {f"{d}/{m}/{y}", f"{int(d)}/{int(m)}/{y}", f"{d}-{m}-{y}", f"{d}.{m}.{y}", f"{y}-{m}-{d}"}
            exact_dob_hit = any(f in text or f in url for f in exact_dob_forms)

    byear = parsed.get("birth_year")
    low_raw = f"{text} {url}".lower()

    # High-entropy phone match (computed early so true phone hits are never falsely vetoed by temporal heuristics)
    phone_hit = False
    phone_cands = parsed.get("phone_candidates") or []
    if phone_cands:
        raw_digits_all = re.sub(r"\D+", "", f"{text} {url}")
        for raw_ph in phone_cands:
            ph_digits = re.sub(r"\D+", "", str(raw_ph or ""))
            if ph_digits.startswith("84") and len(ph_digits) == 11:
                ph_digits = "0" + ph_digits[2:]
            core_ph = ph_digits.lstrip("0")
            if len(core_ph) >= 8 and (ph_digits in raw_digits_all or core_ph in raw_digits_all):
                phone_hit = True
                break

    if byear and int(byear) >= 2002 and not exact_dob_hit and not phone_hit:
        if any(mk in low_raw for mk in SENIOR_MARKERS) or re.search(r"tốt nghiệp.{0,40}19[6789]\d", low_raw):
            return GateDecision(accepted=False, reject_reason="temporal_seniority_veto")

        title_url_years = [int(y) for y in re.findall(r"\b(199\d|20[0-2]\d)\b", f"{text[:140]} {url}")]
        if title_url_years:
            max_event_year = max(title_url_years)
            has_highschool_grade = bool(re.search(r"\b(?:(?:lớp|lop)\s*1[012]|1[012][a-z]\d)\b", low_raw))
            has_uni_status = bool(
                re.search(r"\b(?:sinh viên|sinh vien|cử nhân|cu nhan|tốt nghiệp đại học|tot nghiep dai hoc|graduate)\b", low_raw)
            )
            if has_highschool_grade and max_event_year < int(byear) + 14:
                return GateDecision(accepted=False, reject_reason="temporal_grade_age_veto")
            if has_uni_status and max_event_year < int(byear) + 17:
                return GateDecision(accepted=False, reject_reason="temporal_grade_age_veto")

    # Reverse-direction Temporal Veto: when target is an older cohort (birth_year <= 1990),
    # reject unmistakable child/elementary worksheets or recent 2020-2029 freshman MSSV records
    # (never blocks if parent/teacher context, exact DOB, or phone hit is present).
    if byear and int(byear) <= 1990 and not exact_dob_hit and not phone_hit:
        has_adult_role_ctx = any(
            k in low_raw
            for k in ("giáo viên", "giảng viên", "phụ huynh", "mẹ của", "cha của", "bố của", "parent", "teacher", "chủ nhiệm")
        )
        if not has_adult_role_ctx:
            is_child_worksheet = bool(
                re.search(
                    r"\b(?:starter\s*[1-4]|movers|flyers|thiếu\s+nhi|tiểu\s+học|học\s+sinh\s+lớp\s*[1-5])\b",
                    low_raw,
                )
            )
            is_recent_freshman_mssv = bool(
                re.search(
                    r"(?:mssv|mã\s+số\s+sinh\s+viên)\s*[:\-]?\s*(?:312[0-9]{8}|2[0-6]52\d{4}|202[0-9]\d{4,6})\b",
                    low_raw,
                )
            )
            if is_child_worksheet or is_recent_freshman_mssv:
                return GateDecision(accepted=False, reject_reason="temporal_younger_cohort_veto")

    # 3. Match target's full name / alias / phone-digits / shortened-name+org / exact-DOB+partial-name-or-org
    matched: list[str] = []
    name_hit = bool(target_norm and (target_norm in combined or (len(target_joined) >= 6 and target_joined in combined)))

    # Guard against Vietnamese historical figure + conjunction collision ("Nguyễn Ánh như các tài liệu xưa... Tây Sơn")
    if name_hit and target_norm.endswith(" nhu") and not phone_hit and not exact_dob_hit:
        if any(h in low_raw for h in ("tây sơn", "gia long", "chúa nguyễn", "đại việt", "triều nguyễn", "sử liệu")) and re.search(
            r"\bnguyễn\s+ánh\s+như\b", low_raw
        ):
            name_hit = False
    if not name_hit and target_joined.isdigit() and len(target_joined) >= 9:
        raw_digits = re.sub(r"\D+", "", f"{text} {url}")
        core_phone = target_joined.lstrip("0")
        if target_joined in raw_digits or (len(core_phone) >= 8 and core_phone in raw_digits):
            name_hit = True
    # High-entropy anchor exact match (MST, SBD, ORCID, CCCD, License Plate, Crypto Wallet)
    anchors_dict = parsed.get("anchors") or {}
    if not name_hit and anchors_dict:
        raw_blob_low = f"{text} {url}".lower()
        anchor_exact_tokens: list[str] = []
        anchor_exact_tokens.extend(str(x) for x in anchors_dict.get("tax_ids", []))
        anchor_exact_tokens.extend(str(x) for x in anchors_dict.get("exam_ids", []))
        anchor_exact_tokens.extend(str(x) for x in anchors_dict.get("orcid_ids", []))
        anchor_exact_tokens.extend(str(x.get("cccd", "")) for x in anchors_dict.get("cccds", []))
        anchor_exact_tokens.extend(str(x.get("plate", "")) for x in anchors_dict.get("license_plates", []))
        anchor_exact_tokens.extend(str(x) for x in anchors_dict.get("crypto_wallets", []))
        if any(tok and len(tok) >= 6 and tok.lower() in raw_blob_low for tok in anchor_exact_tokens):
            name_hit = True
    alias_hit = any(normalize_text(a) in combined for a in parsed.get("aliases", []) if len(a) >= 3)

    matched_orgs: list[str] = []
    for org in parsed.get("organizations", []):
        org_n = normalize_text(org)
        org_exp = normalize_org_or_location(org)
        org_tokens = [
            t
            for t in org_n.split()
            if t
            not in (
                "truong", "thpt", "thcs", "dh", "dai", "hoc", "chuyen",
                "tp", "tphcm", "thanh", "pho", "ho", "chi", "minh",
                "ha", "noi", "da", "nang", "can", "tho", "quoc", "gia",
            )
        ]
        short_sig = " ".join(org_tokens[-2:]) if len(org_tokens) >= 2 else org_n
        extra_sigs = ORG_EN_ALIASES.get(org_n, ())
        if (
            org_n in combined
            or (org_exp and org_exp != org_n and org_exp in combined)
            or (len(short_sig) >= 3 and short_sig in combined)
            or any(sig in combined for sig in extra_sigs)
        ):
            matched_orgs.append(org)

    # Check related people co-occurrence (e.g., parent/spouse/sibling from natural-language relational prompt)
    matched_related: list[str] = []
    for rp in parsed.get("related_people", []):
        rp_name = str(rp.get("name") or "").strip()
        rp_norm = normalize_text(rp_name)
        if rp_norm and rp_norm in combined:
            matched_related.append(rp_name)

    short_name_with_org_hit = False
    name_parts = target_norm.split()
    if not name_hit and (matched_orgs or matched_related) and len(name_parts) >= 3:
        surname = name_parts[0]
        given_two = " ".join(name_parts[-2:])
        given_one = name_parts[-1]
        if re.search(rf"\b{re.escape(surname)}\b", combined) and (
            (len(name_parts) >= 4 and given_two in combined)
            or (len(name_parts) == 3 and re.search(rf"\b{re.escape(given_one)}\b", combined))
        ):
            short_name_with_org_hit = True
        elif matched_related and len(name_parts) >= 2 and given_two in combined:
            short_name_with_org_hit = True

    has_doc_or_edu_ctx = (
        ".edu." in url.lower()
        or ".pdf" in url.lower()
        or any(k in low_raw for k in ("danh sách", "thí sinh", "sinh viên", "trúng tuyển", "chứng chỉ", "khen thưởng"))
    )
    has_partial_name_or_org = bool(matched_orgs) or bool(matched_related) or (
        len(name_parts) >= 2 and bool(re.search(rf"\b{re.escape(name_parts[-1])}\b", combined))
    )
    # If the user specifically asked about "Target [relation] RelatedPerson" and a public page profiles RelatedPerson
    # alongside family/bio context, keep it as a lower-priority relational pivot candidate!
    related_family_pivot = bool(matched_related) and any(
        fk in low_raw for fk in ("con ", "gia đình", "vợ", "chồng", "cha", "mẹ", "bố", "family", "son", "daughter", "wife", "husband", "chủ tịch", "giám đốc", "hội đồng", "báo cáo", "cổ đông")
    )

    if (
        not name_hit
        and not phone_hit
        and not alias_hit
        and not short_name_with_org_hit
        and not related_family_pivot
        and not (exact_dob_hit and has_doc_or_edu_ctx and has_partial_name_or_org)
    ):
        return GateDecision(accepted=False, reject_reason="no_target_match")

    # Prefix-surname & suffix-given-name & Vietnamese tone/diacritic mismatch checks:
    # 1. Prefix surname: "Nguyễn Lê Ngọc Bích" when target is "Lê Ngọc Bích"
    # 2. Suffix given name: "Nguyễn Anh Như Huỳnh" or "NGUYỄN ÁNH NHƯ NGỌC" when target is 3-word "Nguyễn Anh Như"
    # 3. Diacritic mismatch: "Nguyễn Ánh Như" when target has explicit Vietnamese accents "Nguyễn Anh Như"
    prefix_surname_mismatch = False
    suffix_name_mismatch = False
    diacritic_name_mismatch = False
    if name_hit and len(name_parts) >= 3 and not phone_hit and not exact_dob_hit:
        name_matches = list(re.finditer(rf"\b{re.escape(target_norm)}\b", combined))
        if name_matches:
            all_prefixed = True
            for nm in name_matches:
                before = combined[: nm.start()].rstrip()
                prev_word = before.split()[-1] if before else ""
                if prev_word not in VN_COMMON_SURNAMES:
                    all_prefixed = False
                    break
            if all_prefixed:
                prefix_surname_mismatch = True

        # Check if followed by an extra capitalized Vietnamese/proper name token in raw text
        # (e.g. "Huỳnh Nguyễn Thuận Thiên", "Huỳnh Nguyễn Thuận Thắng", "Nguyễn Văn A Heo")
        # excluding non-name metadata words that normally follow a name in roster tables ("Nam", "Nữ", "Kinh", "Lớp", "Sinh"...).
        _NON_NAME_FOLLOWERS = frozenset({
            "nam", "nu", "kinh", "hoa", "khmer", "tay", "thai", "muong", "nung", "cham", "ede",
            "lop", "khoa", "nganh", "truong", "thpt", "thcs", "dh", "dai", "hoc", "sinh", "ngay",
            "tphcm", "hcm", "tp", "tinh", "quan", "huyen", "phuong", "xa", "dat", "khong", "gioi",
            "kha", "trung", "binh", "xuat", "sac", "toan", "phan", "ban", "and", "or", "is", "at",
            "in", "on", "the", "of", "for", "with", "from", "by", "to", "pdf", "doc", "docx", "xlsx",
        })
        raw_tname = str(parsed.get("target_name") or "").strip()
        if raw_tname and len(name_parts) >= 3:
            norm_text_KeepCase = re.sub(
                r"\s+",
                " ",
                "".join(
                    c
                    for c in __import__("unicodedata").normalize("NFD", text)
                    if __import__("unicodedata").category(c) != "Mn"
                )
                .replace("đ", "d")
                .replace("Đ", "D"),
            )
            # Match `<target_name> <CapitalizedWord>` (NOT separated by punctuation like '.' or ',')
            ext_name_re = re.compile(
                rf"(?i)\b{'\\s+'.join(re.escape(w) for w in name_parts)}[ \t]+(?-i:([A-Z][a-z]{{1,12}}))\b"
            )
            ext_matches = list(ext_name_re.finditer(norm_text_KeepCase))
            plain_matches = list(
                re.finditer(rf"(?i)\b{'\\s+'.join(re.escape(w) for w in name_parts)}\b", norm_text_KeepCase)
            )
            if ext_matches and plain_matches:
                # Only flag suffix mismatch if EVERY occurrence of target_name is followed by an extra capitalized name word
                extra_follower_hits = [
                    m for m in ext_matches if m.group(1).lower() not in _NON_NAME_FOLLOWERS
                ]
                if extra_follower_hits and len(extra_follower_hits) >= len(plain_matches):
                    suffix_name_mismatch = True

        # Check Vietnamese diacritic mismatch when both target_name and candidate text use Vietnamese accents
        raw_tname_low = re.sub(r"\s+", " ", raw_tname.lower())
        if any(ord(c) > 127 for c in raw_tname_low) and any(ord(c) > 127 for c in text):
            text_low_clean = re.sub(r"\s+", " ", text.lower())
            if raw_tname_low not in text_low_clean and target_norm not in text_low_clean:
                diacritic_name_mismatch = True

    # Direct Neighbor DOB Conflict Veto:
    # When target's birth_year is known (e.g. 2007) and every occurrence of <target_name> in a roster snippet
    # is immediately followed (within 25 chars) by a plausible birth date DD/MM/YYYY with a DIFFERENT year
    # (e.g. "NGUYỄN VIỆT KHUÊ 01/04/2005" or "Nguyễn Việt Khuê 20/08/1997"), reject as wrong homonym.
    if name_hit and byear and not exact_dob_hit and not phone_hit and len(name_parts) >= 2:
        norm_for_dob = re.sub(
            r"\s+",
            " ",
            "".join(
                c
                for c in __import__("unicodedata").normalize("NFD", text)
                if __import__("unicodedata").category(c) != "Mn"
            )
            .replace("đ", "d")
            .replace("Đ", "D")
            .lower(),
        )
        dob_name_re = re.compile(rf"\b{'\\s+'.join(re.escape(w) for w in name_parts)}\b")
        dob_matches = list(dob_name_re.finditer(norm_for_dob))
        if dob_matches:
            found_neighbor_years: list[int] = []
            for dm in dob_matches:
                tail = norm_for_dob[dm.end() : dm.end() + 28]
                m_dt = re.search(r"\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]((?:19|20)\d{2})\b", tail)
                if m_dt:
                    yr = int(m_dt.group(1))
                    if 1950 <= yr <= 2018:
                        found_neighbor_years.append(yr)
            if found_neighbor_years and all(yr != byear for yr in found_neighbor_years):
                return GateDecision(accepted=False, reject_reason="dob_mismatch_veto")

    if name_hit:
        matched.append(f"Tên: {parsed['target_name']}")
    elif short_name_with_org_hit:
        matched.append(f"Tên rút gọn + Ngữ cảnh: {parsed['target_name']}")
    if phone_hit:
        matched.append("Khớp SĐT")
    if alias_hit:
        matched.append("Alias")
    for mr in matched_related:
        matched.append(f"Liên quan: {mr}")

    # 4. Secondary clue intersection & high-entropy exact DOB / phone / relational co-occurrence boost
    matched.extend(matched_orgs)
    for loc in parsed.get("locations", []):
        if normalize_text(loc) in combined:
            matched.append(loc)

    bonus = 0
    if phone_hit:
        bonus += 5
    if matched_related and (name_hit or short_name_with_org_hit):
        bonus += 4  # Both target AND related person co-occur on the same public document!
    if exact_dob_hit:
        matched.append(parsed["birth_date"])
        bonus += 5
    elif parsed.get("birth_year") and str(parsed["birth_year"]) in f"{text} {url}":
        matched.append(str(parsed["birth_year"]))

    for kw in parsed.get("keywords", []):
        if normalize_text(kw) in combined:
            matched.append(kw)

    # 5. Official Student/Candidate Roster Row Recognition:
    # When a public document/Studocu/Scribd snippet contains "<TARGET_NAME> <DD/MM/YYYY> [Nam/Nữ] <7-12 digit MSSV>",
    # boost it heavily (+4) so authentic roster tables always outrank essays or random mentions.
    if (
        name_hit
        and not prefix_surname_mismatch
        and not suffix_name_mismatch
        and not diacritic_name_mismatch
    ):
        norm_no_acc = (
            "".join(
                c
                for c in __import__("unicodedata").normalize("NFD", text)
                if __import__("unicodedata").category(c) != "Mn"
            )
            .replace("đ", "d")
            .replace("Đ", "D")
            .lower()
        )
        roster_row_re = re.compile(
            rf"\b{'\\s+'.join(re.escape(w) for w in name_parts)}\s+"
            r"(\d{1,2}/\d{1,2}/(?:19|20)\d{2})\s+(?:nam|nu\s+)?(\d{7,12})\b"
        )
        m_row = roster_row_re.search(norm_no_acc)
        if m_row:
            row_dob, row_sid = m_row.group(1), m_row.group(2)
            if not byear or row_dob.endswith(str(byear)):
                bonus += 4
                matched.append(f"Dòng danh sách: {row_dob} · MSSV {row_sid}")

    if prefix_surname_mismatch:
        bonus -= 2
    if suffix_name_mismatch:
        # Hard reject when every occurrence is a different longer name ("Huỳnh Nguyễn Thuận Thiên", "Nguyễn Văn A Heo")
        # and there is no exact DOB/phone anchor corroborating the target!
        if not exact_dob_hit and not phone_hit:
            return GateDecision(accepted=False, reject_reason="suffix_name_mismatch")
        bonus -= 3
    if diacritic_name_mismatch:
        bonus -= 2

    final_score = max(0, len(matched) + bonus)
    if prefix_surname_mismatch:
        matched.append("Nghi khác họ đệm")
    if suffix_name_mismatch:
        matched.append("Nghi thừa tên chính")
    if diacritic_name_mismatch:
        matched.append("Khác dấu tên")

    return GateDecision(accepted=True, score=final_score, matched_clues=matched)


def score_source_relevance(
    text: str,
    url: str,
    parsed: dict[str, Any],
) -> tuple[bool, int, list[str]]:
    """Backwards-compatible strict Target-Relevance Gate returning `(is_relevant, score, matched_clues)`."""
    decision = _evaluate_relevance_detailed(text, url, parsed)
    return decision.accepted, decision.score, decision.matched_clues


class OuterGatekeeper:
    """Stateful Layer 2 Perimeter Filter guarding Layer 4 (Deep Core) from all external noise."""

    def __init__(self, ctx: InvestigationContext) -> None:
        self.ctx = ctx
        self.seen_urls: set[str] = set()
        self.ranked_sources: list[dict[str, Any]] = []
        self.relevant_docs: list[dict[str, str]] = []
        self.telemetry = GatekeeperTelemetry()

    def _record_reject(self, reason: str) -> None:
        self.telemetry.rejected_count += 1
        self.telemetry.rejected_by_reason[reason] = self.telemetry.rejected_by_reason.get(reason, 0) + 1

    def evaluate_candidate(
        self,
        title: str,
        url: str,
        snippet: str,
        *,
        force_keep: bool = False,
        consensus_score: int = 0,
        mirror_boost_label: str = "",
    ) -> bool:
        """Filter, score, and admit (or reject with audit reason) a candidate from Layer 3."""
        norm_seen_key = unquote(url or "").strip().rstrip("/").lower()
        if not url or norm_seen_key in self.seen_urls:
            return False

        self.telemetry.total_inspected += 1

        # 1. Hard Permanent Veto: User explicitly marked this source URL as "Không hữu ích / Sai mục tiêu"
        if norm_seen_key in self.ctx.rejected_urls:
            self._record_reject("user_rejected_source")
            return False

        # Outer URL hygiene & junk domain reject
        if is_junk_category_url(url) or len(title) > 180:
            self._record_reject("junk_url")
            return False

        decision = _evaluate_relevance_detailed(f"{title} {snippet}", url, self.ctx.parsed)
        is_rel = decision.accepted
        score = decision.score
        matched = list(decision.matched_clues)
        reject_reason = decision.reject_reason

        # 2. Progressive Unverified Rotation: If this source was already displayed in a previous turn
        # and the user did NOT confirm/pin it into the Verified Dossier, rotate out ONLY low/ambiguous hits
        # to make room for fresh deeper hits.
        # NEVER rotate out sources that strongly corroborate the user's input clues (e.g. exact DOB/phone/
        # org+name match with score >= 4, or deep-inspected `force_keep=True` official rosters), even if the
        # user forgot to click "Lưu Hồ sơ"!
        is_strong_input_corroboration = bool(
            force_keep
            or (is_rel and score >= 4 and "Nghi thừa tên chính" not in matched and "Khác dấu tên" not in matched)
        )
        if (
            not is_strong_input_corroboration
            and norm_seen_key in self.ctx.previously_shown_unverified_urls
            and norm_seen_key not in self.ctx.confirmed_urls
        ):
            self._record_reject("unverified_rotated_out")
            return False

        if consensus_score >= 3 and is_rel:
            score += 1
            if "Đồng thuận SearXNG+ddgs" not in matched:
                matched.append("Đồng thuận SearXNG+ddgs")

        # High-entropy exact Student ID check gated by academic/VN context
        haystack_low = f"{title} {snippet} {url}".lower()
        has_academic_or_vn_context = (
            is_rel
            or ".edu." in url.lower()
            or ".vn/" in url.lower()
            or url.lower().endswith(".vn")
            or any(
                kw in haystack_low
                for kw in (
                    "sinh viên", "sinh vien", "mssv", "danh sách", "danh sach",
                    "quyết định", "quyet dinh", "đại học", "dai hoc",
                    "khóa ", "khoa ", "ngành", "nganh", "chuẩn đầu ra", "chuan dau ra",
                    "ielts", "đhcq", "dhcq",
                )
            )
            or any(org.lower() in haystack_low for org in self.ctx.parsed.get("organizations", []) if len(org) >= 3)
        )
        for sid_info in self.ctx.anchors.get("student_ids", []):
            sid_val = str(sid_info.get("student_id") or "").strip()
            if not sid_val or is_vn_major_code(sid_val):
                continue
            if sid_val in f"{title} {snippet} {url}" and has_academic_or_vn_context:
                score += 4
                is_rel = True
                if f"MSSV: {sid_val}" not in matched:
                    matched.append(f"MSSV: {sid_val}")

        if mirror_boost_label and force_keep and has_academic_or_vn_context:
            score = max(score, 3)
            is_rel = True
            if mirror_boost_label not in matched:
                matched.append(mirror_boost_label)

        if not is_rel and not force_keep:
            self._record_reject(reject_reason or "no_target_match")
            return False

        self.seen_urls.add(norm_seen_key)
        self.telemetry.accepted_count += 1
        self.ranked_sources.append(
            {
                "title": title or url,
                "url": url,
                "snippet": snippet[:280],
                "match_score": score,
                "matched_clues": matched,
            }
        )
        # Only feed documents that directly mention the target (or target ID/DOB) into ReaderAgent
        # so a parent/related-person bio (e.g., father born 1975) never pollutes the target's own 8D claims!
        mentions_target_directly = any(
            lbl.startswith(("Tên:", "Tên rút gọn", "Alias", "MSSV:", "Khớp chỉ mục MSSV"))
            for lbl in matched
        ) or (self.ctx.parsed.get("birth_date") and self.ctx.parsed["birth_date"] in matched)
        if score >= 1 and (mentions_target_directly or not self.ctx.parsed.get("related_people")):
            self.relevant_docs.append({"text": f"{title}. {snippet}", "source_url": url})
        return True

    def finalize_and_prune(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        """Sort accepted candidates by descending cross-clue score and prune 0-score clutter."""
        self.ranked_sources.sort(key=lambda s: s["match_score"], reverse=True)
        if any(s["match_score"] >= 2 for s in self.ranked_sources):
            pruned = [s for s in self.ranked_sources if s["match_score"] >= 1]
            dropped = len(self.ranked_sources) - len(pruned)
            if dropped > 0:
                self.telemetry.rejected_count += dropped
                self.telemetry.rejected_by_reason["low_score_pruned"] = (
                    self.telemetry.rejected_by_reason.get("low_score_pruned", 0) + dropped
                )
                self.telemetry.accepted_count = len(pruned)
            self.ranked_sources = pruned
        return self.ranked_sources, self.relevant_docs
