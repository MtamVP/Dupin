"""Adaptive Divide-and-Conquer & Branch-and-Bound Investigation Tree Engine.

Implements a generalizable, non-mechanical recursive OSINT decision tree:
1. Sufficiency Trigger: Activates only when direct intersection queries yield sparse,
   ambiguous, or incomplete identity dimensions (e.g., partial name, missing DOB/ID).
2. Divide-and-Conquer Decomposition: Splits seed clues into independent atomic facets
   (organization rosters, portal attachments, isolated keyword/location/relation pivots).
3. Recursive Branching (Portal HTML -> Embedded PDF/XLSX -> Row-Level Identity Expansion ->
   Snowball Re-Query): Every discovered candidate spawns a hypothesis branch at depth + 1.
4. Same-Person Consistency Check & Backtracking: Scores every branch against 8D seed
   constraints; prunes conflicting branches (PRUNED_CONFLICT / PRUNED_VETO) and backtracks
   on dead ends (DEAD_END_BACKTRACKED) to explore the next highest-scoring sibling branch.
"""

from __future__ import annotations

import asyncio
import copy
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import httpx

from app.agents.blackboard import InvestigationBlackboard
from app.connectors.document_reader import (
    extract_roster_candidates_from_excerpts,
    fetch_and_inspect_document,
    fetch_page_and_find_attachments,
    is_inspectable_document_url,
    scan_roster_portal_page,
)
from app.connectors.web_search import WebSearchConnector
from app.core.normalizer import normalize_text
from app.pipeline.layer2_gatekeeper import OuterGatekeeper
from app.pipeline.models import InvestigationContext


@dataclass
class BranchNode:
    """Single node in the Divide-and-Conquer / Branch-and-Bound investigation decision tree."""

    branch_id: str
    parent_id: Optional[str]
    depth: int
    hypothesis_type: str  # ROOT | LATERAL_ORG_ROSTER | PORTAL_ATTACHMENT | IDENTITY_SNOWBALL | FACET_ISOLATED
    label: str
    query: str = ""
    status: str = "OPEN"  # OPEN | EXPLORING | CONFIRMED | UNCERTAIN | DEAD_END_BACKTRACKED | PRUNED_CONFLICT | PRUNED_VETO
    score: float = 0.0
    discovered_facts: dict[str, Any] = field(default_factory=dict)
    evidence_urls: list[str] = field(default_factory=list)
    conflict_reason: str = ""
    children_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "hypothesis_type": self.hypothesis_type,
            "label": self.label,
            "query": self.query,
            "status": self.status,
            "score": round(self.score, 2),
            "discovered_facts": self.discovered_facts,
            "evidence_urls": self.evidence_urls[:4],
            "conflict_reason": self.conflict_reason,
            "children_ids": self.children_ids,
        }


def should_activate_divide_and_conquer(
    ctx: InvestigationContext,
    gatekeeper: OuterGatekeeper,
) -> tuple[bool, str]:
    """Adaptively decide whether to trigger Divide-and-Conquer & recursive branching.

    Avoids mechanical execution: skips when direct search already yielded strong,
    multi-source corroborated evidence with full identity dimensions.
    """
    parsed = ctx.parsed
    target_name = str(parsed.get("target_name") or "").strip()
    name_words = [w for w in target_name.split() if w]
    is_partial_name = len(name_words) <= 2 and not target_name.isdigit()
    has_orgs = bool(parsed.get("organizations"))
    has_facets = has_orgs or bool(parsed.get("locations")) or bool(parsed.get("keywords")) or bool(parsed.get("related_people"))

    if not has_facets and not is_partial_name:
        return False, "insufficient_facets"

    strong_hits = [s for s in gatekeeper.ranked_sources if int(s.get("match_score", 0)) >= 3]
    total_hits = len(gatekeeper.ranked_sources)

    if total_hits == 0:
        return True, "zero_direct_hits_divide_and_conquer"
    if is_partial_name and has_orgs and not parsed.get("birth_date"):
        return True, "partial_name_missing_identity_dimensions"
    # Activate Divide-and-Conquer when fewer than 3 strong hits exist and a specified school/org
    # (e.g. "THCS Nguyễn Gia Thiều") has zero direct hits among collected sources!
    if has_orgs and len(strong_hits) < 3:
        orgs_list = [str(o).strip() for o in (parsed.get("organizations") or []) if str(o).strip()]
        for org_item in orgs_list[:3]:
            org_tokens = [
                t
                for t in normalize_text(org_item).split()
                if len(t) >= 2 and t not in ("truong", "thpt", "thcs", "dai", "hoc", "dh", "tp", "hcm")
            ]
            sig = " ".join(org_tokens[-2:]) if len(org_tokens) >= 2 else normalize_text(org_item)
            if sig and not any(
                sig in normalize_text(f"{s.get('title', '')} {s.get('snippet', '')} {s.get('url', '')}")
                for s in gatekeeper.ranked_sources
            ):
                return True, f"missing_direct_hit_for_org:{org_item}"
    if len(strong_hits) < 2 and (has_orgs or bool(parsed.get("related_people"))):
        return True, "sparse_high_confidence_evidence"
    return False, "direct_evidence_sufficient"


def verify_same_person_consistency(
    seed_parsed: dict[str, Any],
    candidate_facts: dict[str, Any],
) -> tuple[bool, float, str]:
    """Verify whether a newly discovered candidate branch is consistent with the seed target.

    Returns (is_consistent, score_delta, conflict_reason).
    """
    seed_name = normalize_text(str(seed_parsed.get("target_name") or ""))
    cand_name = normalize_text(str(candidate_facts.get("full_name") or ""))
    row_text = normalize_text(str(candidate_facts.get("row_line") or ""))
    blob = f"{cand_name} {row_text}"

    # 1. Negative keyword veto
    for neg in seed_parsed.get("negative_keywords", []):
        neg_n = normalize_text(neg)
        if neg_n and neg_n in blob:
            return False, -10.0, f"Vi phạm ràng buộc loại trừ (-{neg})"

    # 2. Name compatibility check
    score = 1.0
    if seed_name and cand_name:
        if seed_name == cand_name:
            score += 2.0
        elif seed_name in cand_name:
            # Partial name expanded to full name (e.g., "Ngọc Diệp" -> "Nguyễn Thị Ngọc Diệp")
            score += 2.5
        else:
            seed_tokens = [t for t in seed_name.split() if len(t) >= 2]
            if seed_tokens and not all(t in cand_name for t in seed_tokens[-2:]):
                return False, -5.0, "Họ tên ứng viên không chứa phần tên mục tiêu"

    # 3. Birth Date / Birth Year consistency check
    seed_dob = str(seed_parsed.get("birth_date") or "").strip()
    cand_dob = str(candidate_facts.get("birth_date") or "").strip()
    if seed_dob and cand_dob:
        if seed_dob == cand_dob:
            score += 4.0
        else:
            return False, -8.0, f"Mâu thuẫn ngày sinh ({cand_dob} != {seed_dob})"

    seed_year = seed_parsed.get("birth_year")
    cand_year = candidate_facts.get("birth_year")
    if seed_year and cand_year:
        diff = abs(int(seed_year) - int(cand_year))
        if diff == 0:
            score += 2.0
        elif diff > 2:
            return False, -8.0, f"Lệch năm sinh quá lớn ({cand_year} vs {seed_year})"
    elif cand_dob:
        # Newly discovered exact DOB raises information entropy significantly
        score += 1.5

    if candidate_facts.get("class_code"):
        score += 0.8
    if candidate_facts.get("student_id"):
        score += 1.5

    return True, score, ""


def decompose_clues_to_lateral_queries(ctx: InvestigationContext) -> list[dict[str, str]]:
    """Divide seed clues into independent lateral subproblems (organizations, facets, rosters)."""
    parsed = ctx.parsed
    orgs = parsed.get("organizations") or []
    locs = parsed.get("locations") or []
    kws = parsed.get("keywords") or []
    name = str(parsed.get("target_name") or "").strip()
    byear = parsed.get("birth_year")
    region = ctx.region

    sub_queries: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(htype: str, label: str, query: str) -> None:
        q = re.sub(r"\s+", " ", query).strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            sub_queries.append({"hypothesis_type": htype, "label": label, "query": q})

    # 1. Organization Lateral Roster / Directory Subproblems (Divide by Organization!)
    for org in orgs[:3]:
        org_clean = org.strip()
        org_low = org_clean.lower()
        is_middleschool = any(k in org_low for k in ("thcs", "cấp 2", "trung học cơ sở"))
        is_highschool = (not is_middleschool) and any(
            k in org_low for k in ("thpt", "cấp 3", "trung học phổ thông", "high school")
        )
        if region == "vn":
            if is_middleschool:
                # Middle school (grades 6-9): general academic year span around birth_year + 13 (e.g., 2007 -> 2020-2021)
                if byear:
                    y_start = int(byear) + 13
                    yr_span = f"{y_start}-{y_start + 1}"
                else:
                    yr_span = ""
                _add(
                    "LATERAL_ORG_ROSTER",
                    f"Danh sách lớp {org_clean}",
                    f'"{org_clean}" danh sách lớp {yr_span}'.strip(),
                )
            elif is_highschool:
                # High school (grades 10-12): grade 12 is roughly birth_year + 17 (e.g., 2007 -> 2024-2025)
                yr_hint = f"{int(byear) + 17}" if byear else ""
                _add(
                    "LATERAL_ORG_ROSTER",
                    f"Danh sách học sinh {org_clean}",
                    f'"{org_clean}" danh sách học sinh {yr_hint}'.strip(),
                )
            else:
                _add(
                    "LATERAL_ORG_ROSTER",
                    f"Danh sách thành viên / nhân sự {org_clean}",
                    f'"{org_clean}" danh sách',
                )
        else:
            _add(
                "LATERAL_ORG_ROSTER",
                f"Public directory / roster of {org_clean}",
                f'"{org_clean}" directory OR roster OR members',
            )

    # 2. Facet-Isolated Subproblems (Name + single high-value keyword or location when joint query failed)
    for kw in kws[:1]:
        kw_clean = kw.strip()
        if name and kw_clean and len(kw_clean) <= 35:
            _add("FACET_ISOLATED", f"Tách nhánh từ khóa: {kw_clean}", f'"{name}" {kw_clean}')
    for loc in locs[:1]:
        loc_clean = loc.strip()
        if name and loc_clean and not orgs:
            _add("FACET_ISOLATED", f"Tách nhánh địa điểm: {loc_clean}", f'"{name}" "{loc_clean}"')

    return sub_queries[:3]


class InvestigationTree:
    """Best-First Branch-and-Bound Investigation Tree with Backtracking and Identity Expansion."""

    def __init__(self, root_label: str, seed_facts: dict[str, Any]) -> None:
        self.nodes: dict[str, BranchNode] = {}
        self._counter = 0
        self.root_id = self.add_branch(
            parent_id=None,
            depth=0,
            hypothesis_type="ROOT",
            label=root_label,
            status="EXPLORING",
            score=1.0,
            discovered_facts=seed_facts,
        ).branch_id
        self.activated: bool = False
        self.activation_reason: str = ""
        self.confirmed_expansions: list[dict[str, Any]] = []
        self.backtracked_count: int = 0
        self.pruned_count: int = 0

    def add_branch(
        self,
        *,
        parent_id: Optional[str],
        depth: int,
        hypothesis_type: str,
        label: str,
        query: str = "",
        status: str = "OPEN",
        score: float = 0.0,
        discovered_facts: Optional[dict[str, Any]] = None,
        evidence_urls: Optional[list[str]] = None,
        conflict_reason: str = "",
    ) -> BranchNode:
        self._counter += 1
        bid = f"B{self._counter}"
        node = BranchNode(
            branch_id=bid,
            parent_id=parent_id,
            depth=depth,
            hypothesis_type=hypothesis_type,
            label=label,
            query=query,
            status=status,
            score=score,
            discovered_facts=dict(discovered_facts or {}),
            evidence_urls=list(evidence_urls or []),
            conflict_reason=conflict_reason,
        )
        self.nodes[bid] = node
        if parent_id and parent_id in self.nodes:
            self.nodes[parent_id].children_ids.append(bid)
        return node

    def to_dict(self) -> dict[str, Any]:
        ordered = [self.nodes[k].to_dict() for k in self.nodes]
        return {
            "activated": self.activated,
            "activation_reason": self.activation_reason,
            "total_branches": len(ordered),
            "confirmed_expansions": self.confirmed_expansions[:5],
            "backtracked_count": self.backtracked_count,
            "pruned_count": self.pruned_count,
            "nodes": ordered,
        }

    async def run_recursive_search(
        self,
        *,
        ctx: InvestigationContext,
        gatekeeper: OuterGatekeeper,
        ws_conn: WebSearchConnector,
        bb: InvestigationBlackboard,
        client: Optional[httpx.AsyncClient] = None,
        max_depth: int = 3,
        max_attachments_per_branch: int = 3,
        max_snowball_branches: int = 2,
        search_fn: Optional[Callable[[str, int], Any]] = None,
    ) -> dict[str, Any]:
        """Execute Divide-and-Conquer -> Attachment Crawl -> Recursive Snowball -> Backtrack."""
        should_run, reason = should_activate_divide_and_conquer(ctx, gatekeeper)
        self.activation_reason = reason
        if not should_run:
            self.nodes[self.root_id].status = "CONFIRMED"
            return self.to_dict()

        self.activated = True
        parsed = ctx.parsed
        target_name = str(parsed.get("target_name") or "").strip()
        orgs = list(parsed.get("organizations") or [])
        region = ctx.region

        bb.log(
            "PlannerAgent",
            "DIVIDE_CONQUER_START",
            f"Kích hoạt cây quyết định Chia-để-trị ({reason}) -> tách nhánh độc lập & quét đính kèm công khai",
        )

        async def _do_search(q: str, max_res: int = 10) -> list[dict[str, Any]]:
            if search_fn is not None:
                return await search_fn(q, max_res)
            doc = await ws_conn.collect(q, client=client, max_results=max_res, region=region)
            return list(doc.metadata.get("results", []))

        # Step 1 (Depth 1): Decompose seed clues into lateral/facet branches
        sub_queries = decompose_clues_to_lateral_queries(ctx)
        depth1_branches: list[BranchNode] = []
        for sq in sub_queries:
            br = self.add_branch(
                parent_id=self.root_id,
                depth=1,
                hypothesis_type=sq["hypothesis_type"],
                label=sq["label"],
                query=sq["query"],
                status="EXPLORING",
                score=1.0,
            )
            depth1_branches.append(br)

        # Priority queue of candidate identity-expansion branches (Depth 2 -> Depth 3 Snowball)
        snowball_queue: list[BranchNode] = []
        scanned_doc_urls: set[str] = set()

        for br in depth1_branches:
            try:
                hits = await _do_search(br.query, 8)
            except Exception:
                hits = []

            if not hits:
                br.status = "DEAD_END_BACKTRACKED"
                self.backtracked_count += 1
                bb.log("PlannerAgent", "BRANCH_BACKTRACK", f"[{br.branch_id}] Ngõ cụt ({br.label}) -> Quay lui nhánh kế")
                continue

            br.evidence_urls = [str(h.get("url", "")) for h in hits[:4] if h.get("url")]

            # Evaluate direct text matches first
            direct_kept = 0
            portal_urls_to_crawl: list[str] = []
            for h in hits[:6]:
                h_url = str(h.get("url", ""))
                h_title = str(h.get("title", ""))
                h_snip = str(h.get("snippet", ""))
                if not h_url:
                    continue
                if gatekeeper.evaluate_candidate(h_title, h_url, h_snip, consensus_score=int(h.get("consensus_score", 1))):
                    direct_kept += 1

                # Collect portal / roster HTML pages or direct PDF/XLSX links for attachment crawling
                low_combo = f"{h_title} {h_snip} {h_url}".lower()
                if is_inspectable_document_url(h_url) or any(
                    kw in low_combo for kw in ("danh sách", "danh-sach", "roster", "directory", "học sinh", "sinh viên", ".edu.")
                ):
                    portal_urls_to_crawl.append(h_url)

            # Step 2 (Depth 2): Crawl portal HTML pages for:
            #   (a) Inline HTML roster tables
            #   (b) Embedded PDF/XLSX/Google Drive attachments
            #   (c) Embedded class-roster slide images (`12a10.png`...) via parallel Gemini Vision OCR
            branch_found_candidates = 0
            attachment_urls: list[str] = []
            portal_terms = [t for t in (target_name, str(parsed.get("birth_date") or "")) if len(t) >= 3]
            for p_url in portal_urls_to_crawl[:3]:
                if len(attachment_urls) >= max_attachments_per_branch:
                    break
                if is_inspectable_document_url(p_url):
                    if p_url not in scanned_doc_urls:
                        attachment_urls.append(p_url)
                else:
                    portal_scan = await scan_roster_portal_page(
                        p_url,
                        target_terms=portal_terms or [target_name],
                        birth_year=parsed.get("birth_year"),
                        db_path=ws_conn.db_path,
                        timeout=10.0,
                        max_ocr_images=22,
                        client=client,
                    )
                    # (a) Inline HTML table hit (e.g. THCS Nguyen Gia Thieu HTML student table)
                    for hex_item in portal_scan.get("html_excerpts") or []:
                        bb.log(
                            "DocumentReader",
                            "PORTAL_HTML_ROSTER_HIT",
                            f"[{br.branch_id}] Đọc bảng HTML trực tiếp tại {p_url[:90]} -> khớp '{target_name}'",
                        )
                        gatekeeper.evaluate_candidate(
                            portal_scan.get("title") or br.label,
                            p_url,
                            hex_item.get("line", ""),
                            force_keep=True,
                            consensus_score=3,
                            mirror_boost_label="Khớp trực tiếp trong bảng danh sách HTML",
                        )
                        branch_found_candidates += 1

                    # (c) Embedded class-roster image Vision OCR hit (e.g. THPT Nguyen Thuong Hien 12a10.png)
                    for ocr_item in portal_scan.get("ocr_excerpts") or []:
                        bb.log(
                            "DocumentReader",
                            "PORTAL_IMAGE_OCR_HIT",
                            f"[{br.branch_id}] Quét Vision OCR {portal_scan.get('scanned_image_count', 0)} ảnh danh sách tại {p_url[:80]} -> {ocr_item.get('line', '')[:120]}",
                        )
                        gatekeeper.evaluate_candidate(
                            portal_scan.get("title") or br.label,
                            p_url,
                            ocr_item.get("line", ""),
                            force_keep=True,
                            consensus_score=4,
                            mirror_boost_label="Vision OCR ảnh danh sách lớp",
                        )
                        branch_found_candidates += 1

                    for e_url in portal_scan.get("attachments") or []:
                        if e_url not in scanned_doc_urls and e_url not in attachment_urls:
                            attachment_urls.append(e_url)
                            if len(attachment_urls) >= max_attachments_per_branch:
                                break

            for att_url in attachment_urls[:max_attachments_per_branch]:
                scanned_doc_urls.add(att_url)
                search_terms = [t for t in [target_name] if len(t) >= 3]
                doc_res = await fetch_and_inspect_document(att_url, search_terms, timeout=10.0, client=client)
                if not doc_res.get("ok") or not doc_res.get("excerpts"):
                    continue

                excerpts = doc_res["excerpts"]
                bb.log(
                    "DocumentReader",
                    "PORTAL_ATTACHMENT_HIT",
                    f"[{br.branch_id}] Đọc sâu tệp đính kèm {att_url[:90]} -> khớp {len(excerpts)} dòng cho '{target_name}'",
                )

                # Keep the matched attachment as a verified public source!
                gatekeeper.evaluate_candidate(
                    f"Danh sách công khai ({doc_res.get('header_hint') or br.label})",
                    att_url,
                    excerpts[0].get("line", ""),
                    force_keep=True,
                    consensus_score=3,
                    mirror_boost_label="Khớp trực tiếp trong tệp danh sách tổ chức",
                )

                # Expand partial name / table rows into Candidate Hypothesis Branches
                candidates = extract_roster_candidates_from_excerpts(excerpts, target_name)
                for cand in candidates[:4]:
                    ok_same, c_score, conflict = verify_same_person_consistency(parsed, cand)
                    cand_label = cand["full_name"]
                    if cand.get("birth_date"):
                        cand_label += f" ({cand['birth_date']})"
                    if cand.get("class_code"):
                        cand_label += f" · {cand['class_code']}"

                    if not ok_same:
                        self.add_branch(
                            parent_id=br.branch_id,
                            depth=min(2, max_depth),
                            hypothesis_type="IDENTITY_SNOWBALL",
                            label=cand_label,
                            status="PRUNED_VETO" if "loại trừ" in conflict else "PRUNED_CONFLICT",
                            score=c_score,
                            discovered_facts=cand,
                            evidence_urls=[att_url],
                            conflict_reason=conflict,
                        )
                        self.pruned_count += 1
                        bb.log("CriticAgent", "BRANCH_PRUNE", f"Cắt tỉa nhánh '{cand_label}': {conflict}")
                        continue

                    child_br = self.add_branch(
                        parent_id=br.branch_id,
                        depth=min(2, max_depth),
                        hypothesis_type="IDENTITY_SNOWBALL",
                        label=cand_label,
                        status="UNCERTAIN",
                        score=c_score,
                        discovered_facts=cand,
                        evidence_urls=[att_url],
                    )
                    snowball_queue.append(child_br)
                    branch_found_candidates += 1

            if branch_found_candidates > 0 or direct_kept > 0:
                br.status = "CONFIRMED"
                br.score += 1.5 * branch_found_candidates + 0.5 * direct_kept
            else:
                br.status = "DEAD_END_BACKTRACKED"
                self.backtracked_count += 1
                bb.log("PlannerAgent", "BRANCH_BACKTRACK", f"[{br.branch_id}] Không thấy khớp trong '{br.label}' -> Quay lui")

        # Step 3 (Depth 3 — Best-First Recursive Snowball Expansion & Backtracking)
        snowball_queue.sort(key=lambda b: b.score, reverse=True)
        expanded_count = 0

        for cand_br in snowball_queue:
            if expanded_count >= max_snowball_branches:
                break
            expanded_count += 1
            facts = cand_br.discovered_facts
            full_name = str(facts.get("full_name") or target_name).strip()
            dob = str(facts.get("birth_date") or "").strip()
            cls_code = str(facts.get("class_code") or "").strip()

            # Build augmented parsed context so Layer 2 evaluates Snowball hits against the expanded identity!
            aug_parsed = copy.deepcopy(parsed)
            aug_parsed["target_name"] = full_name
            if dob:
                aug_parsed["birth_date"] = dob
            if facts.get("birth_year"):
                aug_parsed["birth_year"] = int(facts["birth_year"])
            if cls_code and cls_code not in aug_parsed["keywords"]:
                aug_parsed["keywords"].append(cls_code)

            snowball_queries: list[str] = []
            if dob:
                # Pair expanded full name + exact DOB (+ other orgs if user gave >= 2 orgs)
                secondary_org = orgs[1] if len(orgs) >= 2 else (orgs[0] if orgs else "")
                if secondary_org:
                    snowball_queries.append(f'"{full_name}" {dob} {secondary_org}')
                snowball_queries.append(f'"{full_name}" {dob}')
            elif cls_code and orgs:
                snowball_queries.append(f'"{full_name}" {cls_code} {orgs[0]}')
            else:
                snowball_queries.append(f'"{full_name}" {orgs[0] if orgs else ""}'.strip())

            cand_br.query = snowball_queries[0]
            cand_br.status = "EXPLORING"
            bb.log(
                "CollectorAgent",
                "SNOWBALL_EXPAND",
                f"[{cand_br.branch_id}] Đệ quy Quả cầu tuyết (depth={cand_br.depth}): {cand_br.query}",
            )

            corroborating_hits = 0
            orig_parsed = gatekeeper.ctx.parsed
            try:
                # Temporarily validate snowball results against the branch's expanded identity
                gatekeeper.ctx.parsed = aug_parsed
                for sq in snowball_queries[:2]:
                    try:
                        s_hits = await _do_search(sq, 8)
                    except Exception:
                        s_hits = []
                    for sh in s_hits:
                        sh_url = str(sh.get("url", ""))
                        if not sh_url:
                            continue
                        if gatekeeper.evaluate_candidate(
                            str(sh.get("title", "")),
                            sh_url,
                            str(sh.get("snippet", "")),
                            consensus_score=int(sh.get("consensus_score", 2)),
                            mirror_boost_label=f"Nhánh đệ quy {cand_br.branch_id} ({full_name})",
                        ):
                            corroborating_hits += 1
                            if sh_url not in cand_br.evidence_urls:
                                cand_br.evidence_urls.append(sh_url)
            finally:
                gatekeeper.ctx.parsed = orig_parsed

            if corroborating_hits > 0:
                cand_br.status = "CONFIRMED"
                cand_br.score += min(4.0, corroborating_hits * 1.2)
                self.confirmed_expansions.append(
                    {
                        "branch_id": cand_br.branch_id,
                        "full_name": full_name,
                        "birth_date": dob,
                        "class_code": cls_code,
                        "score": round(cand_br.score, 2),
                        "corroborating_hits": corroborating_hits,
                    }
                )
                bb.log(
                    "EntityResolutionAgent",
                    "BRANCH_CONFIRMED",
                    f"[{cand_br.branch_id}] Xác nhận nhánh '{cand_br.label}' với {corroborating_hits} nguồn đối chiếu mới (score={cand_br.score:.1f})",
                )
            else:
                # Keep as UNCERTAIN (still backed by roster row) if roster row matched, else DEAD_END_BACKTRACKED
                if cand_br.evidence_urls:
                    cand_br.status = "UNCERTAIN"
                else:
                    cand_br.status = "DEAD_END_BACKTRACKED"
                    self.backtracked_count += 1
                bb.log(
                    "PlannerAgent",
                    "BRANCH_BACKTRACK",
                    f"[{cand_br.branch_id}] Chưa có nguồn đối chiếu thêm cho '{cand_br.label}' -> giữ trạng thái {cand_br.status} & quay lui",
                )

        # Back-propagate winning expansion into ctx.parsed ONLY when there is a single clear high-confidence winner
        if len(self.confirmed_expansions) == 1:
            win = self.confirmed_expansions[0]
            if win["full_name"] and len(win["full_name"].split()) > len(target_name.split()):
                ctx.parsed["expanded_full_name"] = win["full_name"]
            if win["birth_date"] and not ctx.parsed.get("birth_date"):
                ctx.parsed["birth_date"] = win["birth_date"]
            if win["class_code"] and win["class_code"] not in ctx.parsed["keywords"]:
                ctx.parsed["keywords"].append(win["class_code"])

        self.nodes[self.root_id].status = "CONFIRMED" if self.confirmed_expansions else "UNCERTAIN"
        return self.to_dict()
