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
    if byear and int(byear) >= 2002 and not exact_dob_hit:
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

    # 3. Match target's full name / alias / shortened-name+org / exact-DOB+partial-name-or-org
    matched: list[str] = []
    name_hit = bool(target_norm and (target_norm in combined or (len(target_joined) >= 6 and target_joined in combined)))
    alias_hit = any(normalize_text(a) in combined for a in parsed.get("aliases", []) if len(a) >= 3)

    matched_orgs: list[str] = []
    for org in parsed.get("organizations", []):
        org_n = normalize_text(org)
        org_exp = normalize_org_or_location(org)
        org_tokens = [t for t in org_n.split() if t not in ("truong", "thpt", "thcs", "dh", "dai", "hoc")]
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
        and not alias_hit
        and not short_name_with_org_hit
        and not related_family_pivot
        and not (exact_dob_hit and has_doc_or_edu_ctx and has_partial_name_or_org)
    ):
        return GateDecision(accepted=False, reject_reason="no_target_match")

    if name_hit:
        matched.append(f"Tên: {parsed['target_name']}")
    elif short_name_with_org_hit:
        matched.append(f"Tên rút gọn + Ngữ cảnh: {parsed['target_name']}")
    if alias_hit:
        matched.append("Alias")
    for mr in matched_related:
        matched.append(f"Liên quan: {mr}")

    # 4. Secondary clue intersection & high-entropy exact DOB / relational co-occurrence boost
    matched.extend(matched_orgs)
    for loc in parsed.get("locations", []):
        if normalize_text(loc) in combined:
            matched.append(loc)

    bonus = 0
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

    return GateDecision(accepted=True, score=len(matched) + bonus, matched_clues=matched)


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

        # Outer URL hygiene & junk domain reject
        if is_junk_category_url(url) or len(title) > 180:
            self._record_reject("junk_url")
            return False

        decision = _evaluate_relevance_detailed(f"{title} {snippet}", url, self.ctx.parsed)
        is_rel = decision.accepted
        score = decision.score
        matched = list(decision.matched_clues)
        reject_reason = decision.reject_reason

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
            if sid_info["student_id"] in f"{title} {snippet} {url}" and has_academic_or_vn_context:
                score += 4
                is_rel = True
                if f"MSSV: {sid_info['student_id']}" not in matched:
                    matched.append(f"MSSV: {sid_info['student_id']}")

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
