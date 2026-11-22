"""Planner Agent: LATS/MCTS Hypothesis Tree Search with Backtracking & Reflexion Reformulation."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Optional

import httpx

from app.agents.blackboard import HumanCheckpoint, InvestigationBlackboard, MCTSNode
from app.agents.critic import CriticVerifierAgent
from app.agents.playbooks import PlaybookRegistry
from app.agents.reader import ReaderAgent
from app.agents.resolver import EntityResolutionAgent
from app.config import settings
from app.connectors.github_api import GitHubPublicConnector
from app.connectors.web_fetcher import PublicWebFetcher
from app.connectors.web_search import DorkRequest, WebSearchConnector, generate_smart_dorks
from app.core.fingerprints import extract_handle_fingerprint
from app.core.graph_store import GraphStore
from app.core.llm_provider import build_llm_provider
from app.core.normalizer import normalize_text, strip_vietnamese_accents
from app.core.schemas import EdgeCreate, Node, NodeCreate

STOPWORDS_VN_EN: frozenset[str] = frozenset(
    {
        "va",
        "cua",
        "la",
        "tai",
        "trong",
        "cho",
        "voi",
        "nhung",
        "cac",
        "mot",
        "nguoi",
        "nam",
        "the",
        "and",
        "for",
        "with",
        "from",
        "this",
        "that",
        "profile",
        "view",
        "page",
    }
)


def reflexion_extract_distractor_terms(
    noisy_texts: list[str],
    target_name: str,
    known_positive_terms: list[str],
    top_k: int = 2,
) -> list[str]:
    """Identify high-frequency distractor terms from noisy/off-target results (Reflexion Loop).

    When a search returns many results about a different person sharing the same name,
    extracts the dominant recurring non-target tokens so the next query excludes them (-"term").
    """
    excluded_tokens = set(normalize_text(target_name).split()) | STOPWORDS_VN_EN
    for pos in known_positive_terms:
        excluded_tokens.update(normalize_text(pos).split())

    counts: Counter[str] = Counter()
    for txt in noisy_texts:
        tokens = normalize_text(txt).split()
        for tok in tokens:
            if len(tok) >= 4 and not tok.isdigit() and tok not in excluded_tokens:
                counts[tok] += 1

    return [term for term, freq in counts.most_common(top_k) if freq >= 2]


class PlannerAgent:
    """Orchestrates hypothesis generation, MCTS UCB1 selection, backtracking, and Reflexion."""

    def __init__(
        self,
        store: GraphStore,
        playbook_registry: Optional[PlaybookRegistry] = None,
        use_llm: bool = False,
    ) -> None:
        self.store = store
        self.playbooks = playbook_registry or PlaybookRegistry()
        llm = build_llm_provider(settings) if use_llm else None
        self.reader = ReaderAgent(llm=llm)
        self.critic = CriticVerifierAgent()
        self.resolver = EntityResolutionAgent()

    def initialize_blackboard(
        self,
        workspace_id: str,
        target_name: str,
        playbook_id: str = "vietnam_student_alumni",
        aliases: Optional[list[str]] = None,
        organizations: Optional[list[str]] = None,
        locations: Optional[list[str]] = None,
        keywords: Optional[list[str]] = None,
        negative_keywords: Optional[list[str]] = None,
    ) -> InvestigationBlackboard:
        """Seed an InvestigationBlackboard with Playbook-guided & Dork-synthesized root hypotheses."""
        aliases = aliases or []
        organizations = organizations or []
        locations = locations or []
        keywords = keywords or []
        negative_keywords = negative_keywords or []

        bb = InvestigationBlackboard(
            workspace_id=workspace_id,
            target_name=target_name,
            playbook_id=playbook_id,
            seed_context={
                "aliases": aliases,
                "organizations": organizations,
                "locations": locations,
                "keywords": keywords,
            },
            negative_keywords=list(negative_keywords),
        )

        pb = self.playbooks.get_playbook(playbook_id)
        bb.log("PlannerAgent", "INIT_PLAYBOOK", f"Loaded playbook '{pb.title}'")

        # 1. Generate tactical queries from the selected Playbook
        no_accent = strip_vietnamese_accents(target_name)
        primary_org = organizations[0] if organizations else ""
        primary_alias = aliases[0] if aliases else target_name
        handle_fp = extract_handle_fingerprint(primary_alias)
        core_handle = handle_fp.get("core_alpha") or primary_alias

        for step in pb.steps:
            if "{organization}" in step.query_template and not primary_org:
                continue
            q = step.query_template.format(
                name=target_name,
                name_no_accent=no_accent,
                organization=primary_org,
                alias_or_name=primary_alias,
                core_handle=core_handle,
            )
            if bb.negative_keywords:
                neg_str = " ".join(f'-"{n}"' for n in bb.negative_keywords)
                q = f"{q} {neg_str}".strip()
            bb.add_hypothesis(
                query=q,
                strategy=f"playbook:{step.strategy_tag}",
                prior_score=min(0.95, 0.65 + step.priority_bonus),
                depth=0,
            )

        # 2. Supplement with Smart Boolean Dorks
        dorks = generate_smart_dorks(
            DorkRequest(
                full_name=target_name,
                aliases=aliases,
                organizations=organizations,
                locations=locations,
                keywords=keywords,
                negative_keywords=bb.negative_keywords,
            )
        )
        for d in dorks:
            bb.add_hypothesis(
                query=d["query"],
                strategy=d["strategy"],
                prior_score=0.70,
                depth=0,
            )

        bb.log(
            "PlannerAgent",
            "SEED_HYPOTHESES",
            f"Initialized {len(bb.tree)} MCTS root hypotheses for '{target_name}'",
        )
        return bb

    def select_next_hypothesis(self, bb: InvestigationBlackboard) -> Optional[MCTSNode]:
        """Select the OPEN hypothesis with the highest UCB1 score."""
        open_nodes = [n for n in bb.tree.values() if n.status == "OPEN"]
        if not open_nodes:
            return None

        total_visits = sum(n.visits for n in bb.tree.values()) + 1
        open_nodes.sort(
            key=lambda n: n.ucb1_score(
                parent_visits= (
                    bb.tree[n.parent_id].visits
                    if (n.parent_id and n.parent_id in bb.tree)
                    else total_visits
                )
            ),
            reverse=True,
        )
        chosen = open_nodes[0]
        bb.visited_queries.add(chosen.query.lower())
        bb.log(
            "PlannerAgent",
            "MCTS_SELECT",
            f"Selected hypothesis [{chosen.strategy}] '{chosen.query}' (depth={chosen.depth})",
        )
        return chosen

    async def collect_live_for_hypothesis(
        self,
        bb: InvestigationBlackboard,
        h_node: MCTSNode,
        max_pages: int = 2,
        client: Optional[httpx.AsyncClient] = None,
    ) -> list[dict[str, str]]:
        """Automatically query public web search, GitHub API, and public webpages for an MCTS node."""
        collected: list[dict[str, str]] = []
        search_conn = WebSearchConnector(self.store.db_path, timeout=settings.http_timeout_seconds)
        fetcher = PublicWebFetcher(self.store.db_path, timeout=settings.http_timeout_seconds)

        bb.log("CollectorAgent", "LIVE_SEARCH", f"Querying public search for: {h_node.query}")
        try:
            search_doc = await search_conn.collect(h_node.query, client=client)
            results = search_doc.metadata.get("results", [])
            for r in results[:5]:
                snippet_text = f"{r.get('title', '')}. {r.get('snippet', '')}".strip()
                if snippet_text:
                    collected.append({"text": snippet_text, "source_url": r.get("url", search_doc.url)})

            # Fetch top public webpages for deeper context
            fetched_count = 0
            for url in search_doc.outbound_links:
                if fetched_count >= max_pages:
                    break
                if not url.startswith(("http://", "https://")):
                    continue
                try:
                    page_doc = await fetcher.collect(url, client=client)
                    if not page_doc.is_soft_404 and page_doc.content:
                        collected.append({"text": page_doc.content[:3000], "source_url": page_doc.url})
                        fetched_count += 1
                except Exception:
                    continue
        except Exception as exc:
            bb.log("CollectorAgent", "SEARCH_WARNING", f"Public search request failed: {exc}")

        # If aliases exist in seed_context and query relates to dev/github, also check GitHub API
        aliases = bb.seed_context.get("aliases", [])
        if aliases and ("github" in h_node.query.lower() or h_node.depth == 0):
            gh = GitHubPublicConnector(self.store.db_path, timeout=settings.http_timeout_seconds)
            for alias in aliases[:1]:
                try:
                    gh_doc = await gh.collect(alias, client=client)
                    if not gh_doc.is_soft_404:
                        summary = f"{gh_doc.title}. {gh_doc.content}. " + " ".join(
                            c.evidence_quote for c in gh_doc.claims
                        )
                        collected.append({"text": summary, "source_url": gh_doc.url})
                except Exception:
                    continue

        bb.log(
            "CollectorAgent",
            "LIVE_COLLECTED",
            f"Collected {len(collected)} public text artifacts for '{h_node.query}'",
        )
        return collected

    async def evaluate_and_expand(
        self,
        bb: InvestigationBlackboard,
        hypothesis_id: str,
        collected_texts: list[dict[str, str]],
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """Process collected texts for a hypothesis, update MCTS rewards, backtrack or expand child leads.

        `collected_texts` is a list of `{"text": ..., "source_url": ...}` items.
        """
        if hypothesis_id not in bb.tree:
            raise ValueError(f"Unknown hypothesis_id: {hypothesis_id}")
        h_node = bb.tree[hypothesis_id]

        target_node = self.store.upsert_node(
            bb.workspace_id,
            NodeCreate(type="Person", label=bb.target_name, confidence=0.6),
        )

        total_new_claims = 0
        total_verified_edges = 0
        noisy_snippets: list[str] = []
        spawned_children: list[MCTSNode] = []

        for item in collected_texts:
            raw_text = item.get("text", "")
            src_url = item.get("source_url", "manual://mcts-step")
            if not raw_text.strip():
                continue

            extraction = await self.reader.extract(
                text=raw_text, subject_label=bb.target_name, source_url=src_url
            )
            verified_claims, audited_triples = self.critic.audit_extraction(extraction, raw_text)

            # Evaluate candidate in memory first so noisy/vetoed documents NEVER pollute SQLite!
            candidate_in_memory = Node(
                workspace_id=bb.workspace_id,
                type="Alias",
                label=f"{bb.target_name} ({src_url[-16:]})",
                claims=verified_claims,
                confidence=0.5,
            )
            resolution = self.resolver.compare_nodes(target_node, candidate_in_memory)

            if resolution.decision == "DIFFERENT_ENTITY" and resolution.conflicting_reasons:
                noisy_snippets.append(raw_text)
                bb.log(
                    "EntityResolutionAgent",
                    "VETO_NOISE",
                    f"Rejected off-target document {src_url}: {'; '.join(resolution.conflicting_reasons)}",
                    reward=0.0,
                )
                continue

            if resolution.decision == "POSSIBLE_MATCH" and resolution.conflicting_reasons:
                # Persist ambiguous candidate node & link via POSSIBLE_SAME_ENTITY edge for human review
                persisted_cand = self.store.upsert_node(
                    bb.workspace_id,
                    NodeCreate(
                        type="Alias",
                        label=candidate_in_memory.label,
                        claims=verified_claims,
                        confidence=resolution.overall_probability,
                    ),
                )
                self.store.add_edge(
                    bb.workspace_id,
                    EdgeCreate(
                        source_id=target_node.id,
                        target_id=persisted_cand.id,
                        relation="POSSIBLE_SAME_ENTITY",
                        confidence=resolution.overall_probability,
                        status="HYPOTHESIS",
                        evidence_quote="; ".join(resolution.supporting_reasons) or raw_text[:120],
                        source_url=src_url,
                    ),
                )
                cp = HumanCheckpoint(
                    question=(
                        f"Phát hiện hồ sơ mơ hồ tại {src_url} (xác suất khớp {resolution.overall_probability:.2f}). "
                        "Bạn có muốn gộp vào mục tiêu chính không?"
                    ),
                    candidates=[
                        {
                            "candidate_node_id": persisted_cand.id,
                            "source_url": src_url,
                            "supporting": resolution.supporting_reasons,
                            "conflicting": resolution.conflicting_reasons,
                        }
                    ],
                )
                bb.checkpoints.append(cp)
                bb.log(
                    "PlannerAgent",
                    "HUMAN_CHECKPOINT",
                    f"Paused branch for human verification on {src_url}",
                )

            # Merge verified claims into target_node
            if verified_claims:
                target_node = self.store.upsert_node(
                    bb.workspace_id,
                    NodeCreate(
                        type="Person",
                        label=bb.target_name,
                        claims=verified_claims,
                        confidence=0.7,
                    ),
                )
                total_new_claims += len(verified_claims)

            # Commit verified/hypothesis edges and spawn child pivot hypotheses
            for triple, status in audited_triples:
                if status == "REJECTED":
                    continue
                obj_node = self.store.upsert_node(
                    bb.workspace_id,
                    NodeCreate(
                        type=triple.object_type,
                        label=triple.object_label,
                        confidence=triple.confidence,
                    ),
                )
                self.store.add_edge(
                    bb.workspace_id,
                    EdgeCreate(
                        source_id=target_node.id,
                        target_id=obj_node.id,
                        relation=triple.relation,
                        confidence=triple.confidence,
                        status=status,  # type: ignore[arg-type]
                        evidence_quote=triple.evidence_quote,
                        source_url=triple.source_url,
                    ),
                )
                total_verified_edges += 1

                # Expand MCTS tree with high-value discovered pivot if within max_depth
                if h_node.depth < max_depth:
                    pivot_q = f'"{bb.target_name}" "{triple.object_label}"'
                    if bb.negative_keywords:
                        neg_str = " ".join(f'-"{n}"' for n in bb.negative_keywords)
                        pivot_q = f"{pivot_q} {neg_str}"
                    child = bb.add_hypothesis(
                        query=pivot_q,
                        strategy=f"pivot:{triple.relation.lower()}",
                        prior_score=min(0.95, triple.confidence + 0.1),
                        parent_id=h_node.id,
                        depth=h_node.depth + 1,
                    )
                    if child:
                        spawned_children.append(child)

        # Compute information gain reward for this MCTS rollout
        reward = round(min(1.0, 0.20 * total_new_claims + 0.25 * total_verified_edges), 4)
        bb.backpropagate(h_node.id, reward)

        # If dead-end / noisy, trigger Reflexion Loop to learn negative filters & reformulate!
        reflexion_new_negatives: list[str] = []
        if reward < 0.15 and noisy_snippets and h_node.depth < max_depth:
            known_pos = (
                bb.seed_context.get("organizations", [])
                + bb.seed_context.get("locations", [])
                + bb.seed_context.get("keywords", [])
            )
            distractors = reflexion_extract_distractor_terms(
                noisy_snippets, bb.target_name, known_pos
            )
            for d_term in distractors:
                if d_term not in bb.negative_keywords:
                    bb.negative_keywords.append(d_term)
                    reflexion_new_negatives.append(d_term)

            if reflexion_new_negatives:
                neg_append = " ".join(f'-"{t}"' for t in reflexion_new_negatives)
                reformed_q = f"{h_node.query} {neg_append}".strip()
                child = bb.add_hypothesis(
                    query=reformed_q,
                    strategy="reflexion:noise_filtered",
                    prior_score=min(0.90, h_node.prior_score + 0.1),
                    parent_id=h_node.id,
                    depth=h_node.depth + 1,
                )
                if child:
                    spawned_children.append(child)
                bb.log(
                    "PlannerAgent",
                    "REFLEXION_REFORMULATE",
                    f"Backtracked from dead-end & learned negative filters {reflexion_new_negatives} -> '{reformed_q}'",
                    reward=reward,
                )
        else:
            bb.log(
                "PlannerAgent",
                "MCTS_BACKPROP",
                f"Node '{h_node.query}' status={h_node.status}, reward={reward}, spawned={len(spawned_children)}",
                reward=reward,
            )

        return {
            "evaluated_hypothesis": h_node.model_dump(mode="json"),
            "reward": reward,
            "spawned_hypotheses": [c.model_dump(mode="json") for c in spawned_children],
            "learned_negative_keywords": reflexion_new_negatives,
            "open_checkpoints": [cp.model_dump(mode="json") for cp in bb.checkpoints if not cp.resolved],
        }
