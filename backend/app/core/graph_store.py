"""Local-first Knowledge Graph persistence (SQLite + FTS5) and traversal (NetworkX)."""

from __future__ import annotations

import json
import math
import re
import sqlite3
from pathlib import Path
from typing import Any, Optional

import networkx as nx

from app.core.bayesian import compute_bayesian_confidence
from app.core.normalizer import normalize_text, string_similarity
from app.core.schemas import (
    Edge,
    EdgeCreate,
    EdgeStatusUpdate,
    FeatureClaim,
    GraphSnapshot,
    Node,
    NodeCreate,
    Workspace,
    WorkspaceCreate,
    new_id,
    utc_now,
)


class GraphStore:
    """Manages isolated investigation workspaces in SQLite with FTS5 and NetworkX analytics."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA busy_timeout = 15000;")
        except sqlite3.OperationalError:
            pass
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    pinned INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS nodes (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    label TEXT NOT NULL,
                    normalized_label TEXT NOT NULL,
                    claims_json TEXT NOT NULL DEFAULT '[]',
                    dynamic_traits_json TEXT NOT NULL DEFAULT '{}',
                    confidence REAL NOT NULL DEFAULT 0.5,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_nodes_ws_norm
                ON nodes (workspace_id, normalized_label);

                CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                    node_id UNINDEXED,
                    workspace_id UNINDEXED,
                    label,
                    normalized_label,
                    claims_text,
                    traits_text
                );

                CREATE TABLE IF NOT EXISTS edges (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    confidence REAL NOT NULL DEFAULT 0.5,
                    status TEXT NOT NULL DEFAULT 'HYPOTHESIS',
                    evidence_quote TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    time_range_json TEXT,
                    discovered_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
                    FOREIGN KEY (source_id) REFERENCES nodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES nodes(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS http_cache (
                    url_hash TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status_code INTEGER NOT NULL,
                    fetched_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS blackboards (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS dossier_items (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'general',
                    field_key TEXT NOT NULL,
                    field_value TEXT NOT NULL,
                    source_url TEXT NOT NULL DEFAULT '',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS source_feedback (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    normalized_url TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    verdict TEXT NOT NULL DEFAULT 'REJECTED',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_source_feedback_ws_norm
                ON source_feedback (workspace_id, normalized_url);
                """
            )
            # Safe additive migration for existing SQLite databases created before `pinned` column
            try:
                conn.execute("ALTER TABLE workspaces ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;")
            except sqlite3.OperationalError:
                pass
            # Deduplicate any historical duplicate edges (same workspace_id, source_id, target_id, relation)
            try:
                conn.execute(
                    """
                    DELETE FROM edges
                    WHERE id NOT IN (
                        SELECT MIN(id)
                        FROM edges
                        GROUP BY workspace_id, source_id, target_id, relation
                    );
                    """
                )
            except sqlite3.OperationalError:
                pass
            # Clean up historical node claims: remove duplicate (key, normalized_value) claims and bystander emails
            try:
                from app.agents.reader import is_email_plausible_for_subject

                node_rows = conn.execute("SELECT id, label, type, claims_json FROM nodes").fetchall()
                for nr in node_rows:
                    raw_list = json.loads(nr["claims_json"] or "[]")
                    if not raw_list:
                        continue
                    cleaned_list: list[dict[str, Any]] = []
                    by_kv: dict[tuple[str, str], int] = {}
                    changed = False
                    for c_dict in raw_list:
                        ckey = str(c_dict.get("key") or "")
                        cval = str(c_dict.get("value") or "")
                        curl = str(c_dict.get("source_url") or "")
                        if (
                            nr["type"] == "Person"
                            and ckey == "email"
                            and curl not in ("user://prompt", "manual://user_verified")
                            and not is_email_plausible_for_subject(cval, str(nr["label"] or ""))
                        ):
                            changed = True
                            continue
                        norm_val = normalize_text(cval) if ckey not in ("stylometry_vector", "temporal_activity_signature") else cval
                        sig = (ckey, norm_val)
                        if sig in by_kv:
                            changed = True
                            idx_existing = by_kv[sig]
                            ex_item = cleaned_list[idx_existing]
                            # Prefer real external URL or manual://user_verified over user://prompt
                            if curl == "manual://user_verified" or (
                                curl and not curl.startswith("user://") and str(ex_item.get("source_url") or "").startswith("user://")
                            ):
                                ex_item["source_url"] = curl
                            ex_item["confidence"] = max(float(ex_item.get("confidence", 0.5)), float(c_dict.get("confidence", 0.5)))
                        else:
                            by_kv[sig] = len(cleaned_list)
                            cleaned_list.append(c_dict)
                    if changed:
                        conn.execute(
                            "UPDATE nodes SET claims_json = ? WHERE id = ?",
                            (json.dumps(cleaned_list), nr["id"]),
                        )
            except Exception:
                pass
        # Sync all existing Dossier items into their workspace's primary Person node so pinned truths override stale scraped claims
        try:
            with self._connect() as conn:
                dos_rows = conn.execute(
                    "SELECT workspace_id, field_key, field_value, source_url FROM dossier_items ORDER BY updated_at ASC"
                ).fetchall()
            for dr in dos_rows:
                self._sync_dossier_item_to_graph(
                    dr["workspace_id"],
                    dr["field_key"],
                    dr["field_value"],
                    dr["source_url"] or "",
                )
        except Exception:
            pass

    # --- Workspaces ---

    def _build_workspace_search_summaries(self, conn: sqlite3.Connection) -> dict[str, str]:
        """Build lightweight per-workspace search summaries (nodes, claims, dossier, recent prompts)."""
        summaries: dict[str, list[str]] = {}
        try:
            for r in conn.execute("SELECT workspace_id, label, claims_json FROM nodes").fetchall():
                ws_id = r["workspace_id"]
                bucket = summaries.setdefault(ws_id, [])
                if r["label"]:
                    bucket.append(str(r["label"]))
                try:
                    for c in json.loads(r["claims_json"] or "[]")[:8]:
                        v = str(c.get("value") or "").strip()
                        if v and len(v) <= 60:
                            bucket.append(v)
                except Exception:
                    pass
            for r in conn.execute("SELECT workspace_id, field_key, field_value FROM dossier_items").fetchall():
                ws_id = r["workspace_id"]
                bucket = summaries.setdefault(ws_id, [])
                fv = str(r["field_value"] or "").strip()
                if fv:
                    bucket.append(fv[:100])
            for r in conn.execute(
                "SELECT workspace_id, substr(content, 1, 160) AS snip FROM chat_messages WHERE role = 'user'"
            ).fetchall():
                ws_id = r["workspace_id"]
                bucket = summaries.setdefault(ws_id, [])
                if r["snip"]:
                    bucket.append(str(r["snip"]))
        except Exception:
            pass
        return {k: " · ".join(dict.fromkeys(v))[:600] for k, v in summaries.items()}

    def create_workspace(self, payload: WorkspaceCreate) -> Workspace:
        ws = Workspace(name=payload.name, description=payload.description)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workspaces (id, name, description, pinned, created_at) VALUES (?, ?, ?, 0, ?)",
                (ws.id, ws.name, ws.description, ws.created_at.isoformat()),
            )
        return ws

    def list_workspaces(self) -> list[Workspace]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    w.id,
                    w.name,
                    w.description,
                    COALESCE(w.pinned, 0) AS pinned,
                    w.created_at,
                    COALESCE(
                        (SELECT MAX(m.created_at) FROM chat_messages m WHERE m.workspace_id = w.id),
                        w.created_at
                    ) AS last_active_at
                FROM workspaces w
                ORDER BY COALESCE(w.pinned, 0) DESC, last_active_at DESC, w.created_at DESC
                """
            ).fetchall()
            summaries = self._build_workspace_search_summaries(conn)
        out: list[Workspace] = []
        for r in rows:
            d = dict(r)
            d["pinned"] = bool(d.get("pinned", 0))
            d["search_summary"] = summaries.get(d["id"], "")
            out.append(Workspace(**d))
        return out

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    w.id,
                    w.name,
                    w.description,
                    COALESCE(w.pinned, 0) AS pinned,
                    w.created_at,
                    COALESCE(
                        (SELECT MAX(m.created_at) FROM chat_messages m WHERE m.workspace_id = w.id),
                        w.created_at
                    ) AS last_active_at
                FROM workspaces w
                WHERE w.id = ?
                """,
                (workspace_id,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["pinned"] = bool(d.get("pinned", 0))
        return Workspace(**d)

    def rename_workspace(self, workspace_id: str, new_name: str) -> Optional[Workspace]:
        clean_name = new_name.strip()
        if not clean_name:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE workspaces SET name = ? WHERE id = ?",
                (clean_name, workspace_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_workspace(workspace_id)

    def pin_workspace(self, workspace_id: str, pinned: bool) -> Optional[Workspace]:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE workspaces SET pinned = ? WHERE id = ?",
                (1 if pinned else 0, workspace_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_workspace(workspace_id)

    def delete_workspace(self, workspace_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM nodes_fts WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM http_cache")
            cur = conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
            return cur.rowcount > 0

    # --- Nodes & FTS5 Indexing ---

    @staticmethod
    def _row_to_node(row: sqlite3.Row) -> Node:
        claims = [FeatureClaim(**c) for c in json.loads(row["claims_json"])]
        traits = json.loads(row["dynamic_traits_json"])
        return Node(
            id=row["id"],
            workspace_id=row["workspace_id"],
            type=row["type"],
            label=row["label"],
            normalized_label=row["normalized_label"],
            claims=claims,
            dynamic_traits=traits,
            confidence=row["confidence"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _sync_fts(conn: sqlite3.Connection, node: Node) -> None:
        claims_text = " ".join(
            f"{c.key} {normalize_text(str(c.value))} {normalize_text(c.evidence_quote)}"
            for c in node.claims
        )
        traits_text = " ".join(
            f"{k} {normalize_text(str(v))}" for k, v in node.dynamic_traits.items()
        )
        conn.execute("DELETE FROM nodes_fts WHERE node_id = ?", (node.id,))
        conn.execute(
            """
            INSERT INTO nodes_fts (
                node_id, workspace_id, label, normalized_label, claims_text, traits_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                node.workspace_id,
                node.label,
                node.normalized_label,
                claims_text,
                traits_text,
            ),
        )

    def upsert_node(self, workspace_id: str, payload: NodeCreate) -> Node:
        """Create a node or merge claims using Bayesian Log-Odds belief updating."""
        norm = normalize_text(payload.label)
        now = utc_now()

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT * FROM nodes WHERE workspace_id = ? AND type = ? AND normalized_label = ?",
                (workspace_id, payload.type, norm),
            ).fetchone()

            if existing:
                node = self._row_to_node(existing)
                by_kv: dict[tuple[str, str], FeatureClaim] = {}
                for ec in node.claims:
                    n_val = (
                        normalize_text(str(ec.value))
                        if ec.key not in ("stylometry_vector", "temporal_activity_signature")
                        else str(ec.value)
                    )
                    by_kv[(ec.key, n_val)] = ec

                new_claims: list[FeatureClaim] = []
                for claim in payload.claims:
                    n_val = (
                        normalize_text(str(claim.value))
                        if claim.key not in ("stylometry_vector", "temporal_activity_signature")
                        else str(claim.value)
                    )
                    sig = (claim.key, n_val)
                    if sig not in by_kv:
                        node.claims.append(claim)
                        new_claims.append(claim)
                        by_kv[sig] = claim
                    else:
                        ex_c = by_kv[sig]
                        if claim.confidence > ex_c.confidence:
                            ex_c.confidence = claim.confidence
                        if claim.source_url == "manual://user_verified" or (
                            claim.source_url
                            and not claim.source_url.startswith("user://")
                            and ex_c.source_url.startswith("user://")
                        ):
                            ex_c.source_url = claim.source_url
                            if claim.evidence_quote:
                                ex_c.evidence_quote = claim.evidence_quote

                node.dynamic_traits.update(payload.dynamic_traits)
                base_prior = max(node.confidence, payload.confidence)
                node.confidence = compute_bayesian_confidence(base_prior, new_claims)
                node.updated_at = now

                conn.execute(
                    """
                    UPDATE nodes
                    SET claims_json = ?, dynamic_traits_json = ?, confidence = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        json.dumps([c.model_dump(mode="json") for c in node.claims]),
                        json.dumps(node.dynamic_traits),
                        node.confidence,
                        node.updated_at.isoformat(),
                        node.id,
                    ),
                )
                self._sync_fts(conn, node)
                return node

            initial_conf = compute_bayesian_confidence(payload.confidence, payload.claims)
            node = Node(
                workspace_id=workspace_id,
                type=payload.type,
                label=payload.label,
                normalized_label=norm,
                claims=payload.claims,
                dynamic_traits=payload.dynamic_traits,
                confidence=initial_conf,
                created_at=now,
                updated_at=now,
            )
            conn.execute(
                """
                INSERT INTO nodes (
                    id, workspace_id, type, label, normalized_label,
                    claims_json, dynamic_traits_json, confidence, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    node.id,
                    node.workspace_id,
                    node.type,
                    node.label,
                    node.normalized_label,
                    json.dumps([c.model_dump(mode="json") for c in node.claims]),
                    json.dumps(node.dynamic_traits),
                    node.confidence,
                    node.created_at.isoformat(),
                    node.updated_at.isoformat(),
                ),
            )
            self._sync_fts(conn, node)
            return node

    def get_node(self, node_id: str) -> Optional[Node]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return self._row_to_node(row) if row else None

    def search_candidates(
        self, workspace_id: str, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Hybrid FTS5 BM25 + Jaro-Winkler/phonetic fuzzy candidate blocking across 8D claims."""
        norm_q = normalize_text(query)
        if not norm_q:
            return []

        tokens = [re.sub(r"\W+", "", t) for t in norm_q.split() if re.sub(r"\W+", "", t)]
        fts_hits: dict[str, float] = {}

        if tokens:
            fts_expr = " OR ".join(f'"{t}"*' for t in tokens)
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT node_id, bm25(nodes_fts) AS rank
                    FROM nodes_fts
                    WHERE workspace_id = ? AND nodes_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (workspace_id, fts_expr, limit * 2),
                ).fetchall()
                for r in rows:
                    # bm25() in SQLite FTS5 is negative (lower = better match)
                    fts_hits[r["node_id"]] = min(1.0, max(0.1, -float(r["rank"]) / 10.0))

        snapshot = self.get_graph(workspace_id)
        if not snapshot:
            return []

        scored: list[dict[str, Any]] = []
        for node in snapshot.nodes:
            sim = string_similarity(query, node.label)
            bm25_bonus = fts_hits.get(node.id, 0.0)
            score = round(min(1.0, max(sim, 0.65 * sim + 0.45 * bm25_bonus)), 4)
            if score >= 0.35 or node.id in fts_hits:
                scored.append({"node": node, "match_score": score})

        scored.sort(key=lambda x: x["match_score"], reverse=True)
        return scored[:limit]

    # --- Edges ---

    @staticmethod
    def _row_to_edge(row: sqlite3.Row) -> Edge:
        time_range = json.loads(row["time_range_json"]) if row["time_range_json"] else None
        return Edge(
            id=row["id"],
            workspace_id=row["workspace_id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation=row["relation"],
            confidence=row["confidence"],
            status=row["status"],
            evidence_quote=row["evidence_quote"],
            source_url=row["source_url"],
            time_range=tuple(time_range) if time_range else None,
            discovered_at=row["discovered_at"],
        )

    def add_edge(self, workspace_id: str, payload: EdgeCreate) -> Edge:
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM edges
                WHERE workspace_id = ? AND source_id = ? AND target_id = ? AND relation = ?
                ORDER BY confidence DESC
                LIMIT 1
                """,
                (workspace_id, payload.source_id, payload.target_id, payload.relation),
            ).fetchone()
            if existing:
                old_edge = self._row_to_edge(existing)
                merged_conf = max(float(old_edge.confidence), float(payload.confidence))
                # Upgrade status if new payload is VERIFIED
                merged_status = (
                    "VERIFIED"
                    if ("VERIFIED" in (old_edge.status, payload.status))
                    else (payload.status or old_edge.status)
                )
                # Prefer real external URL over user://prompt if available
                old_url = str(old_edge.source_url or "")
                new_url = str(payload.source_url or "")
                merged_url = (
                    new_url
                    if (new_url and (not old_url or old_url.startswith("user://")))
                    else (old_url or new_url)
                )
                old_quote = str(old_edge.evidence_quote or "")
                new_quote = str(payload.evidence_quote or "")
                if new_quote and new_quote not in old_quote:
                    merged_quote = f"{old_quote} | {new_quote}".strip(" |")[:500] if old_quote else new_quote[:500]
                else:
                    merged_quote = old_quote or new_quote
                merged_time = payload.time_range or old_edge.time_range
                conn.execute(
                    """
                    UPDATE edges
                    SET confidence = ?, status = ?, evidence_quote = ?, source_url = ?, time_range_json = ?
                    WHERE id = ?
                    """,
                    (
                        merged_conf,
                        merged_status,
                        merged_quote,
                        merged_url,
                        json.dumps(list(merged_time)) if merged_time else None,
                        old_edge.id,
                    ),
                )
                updated_row = conn.execute("SELECT * FROM edges WHERE id = ?", (old_edge.id,)).fetchone()
                return self._row_to_edge(updated_row)

            edge = Edge(workspace_id=workspace_id, **payload.model_dump())
            conn.execute(
                """
                INSERT INTO edges (
                    id, workspace_id, source_id, target_id, relation,
                    confidence, status, evidence_quote, source_url, time_range_json, discovered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    edge.id,
                    edge.workspace_id,
                    edge.source_id,
                    edge.target_id,
                    edge.relation,
                    edge.confidence,
                    edge.status,
                    edge.evidence_quote,
                    edge.source_url,
                    json.dumps(list(edge.time_range)) if edge.time_range else None,
                    edge.discovered_at.isoformat(),
                ),
            )
        return edge

    def update_edge_status(self, edge_id: str, update: EdgeStatusUpdate) -> Optional[Edge]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone()
            if not row:
                return None
            new_conf = update.confidence if update.confidence is not None else row["confidence"]
            conn.execute(
                "UPDATE edges SET status = ?, confidence = ? WHERE id = ?",
                (update.status, new_conf, edge_id),
            )
            updated = conn.execute("SELECT * FROM edges WHERE id = ?", (edge_id,)).fetchone()
        return self._row_to_edge(updated)

    # --- Graph Snapshot & NetworkX Algorithms ---

    def get_graph(self, workspace_id: str) -> Optional[GraphSnapshot]:
        ws = self.get_workspace(workspace_id)
        if not ws:
            return None
        with self._connect() as conn:
            node_rows = conn.execute(
                "SELECT * FROM nodes WHERE workspace_id = ?", (workspace_id,)
            ).fetchall()
            edge_rows = conn.execute(
                "SELECT * FROM edges WHERE workspace_id = ?", (workspace_id,)
            ).fetchall()
        return GraphSnapshot(
            workspace=ws,
            nodes=[self._row_to_node(r) for r in node_rows],
            edges=[self._row_to_edge(r) for r in edge_rows],
        )

    def to_networkx(self, workspace_id: str, include_rejected: bool = False) -> nx.MultiDiGraph:
        """Build an in-memory NetworkX MultiDiGraph for pathfinding and centrality analysis."""
        snapshot = self.get_graph(workspace_id)
        g = nx.MultiDiGraph()
        if not snapshot:
            return g
        for n in snapshot.nodes:
            g.add_node(n.id, label=n.label, type=n.type, confidence=n.confidence)
        for e in snapshot.edges:
            if not include_rejected and e.status == "REJECTED":
                continue
            g.add_edge(
                e.source_id,
                e.target_id,
                id=e.id,
                relation=e.relation,
                confidence=e.confidence,
                status=e.status,
            )
        return g

    def find_paths(
        self, workspace_id: str, source_id: str, target_id: str, max_hops: int = 5
    ) -> list[list[str]]:
        """Find all simple undirected paths up to max_hops between two entities."""
        g = self.to_networkx(workspace_id).to_undirected()
        if source_id not in g or target_id not in g:
            return []
        return list(nx.all_simple_paths(g, source=source_id, target=target_id, cutoff=max_hops))

    def suggest_pivots(self, workspace_id: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Rank nodes by Information Gain potential to guide Planner Agent's next search."""
        snapshot = self.get_graph(workspace_id)
        if not snapshot or not snapshot.nodes:
            return []

        g = self.to_networkx(workspace_id).to_undirected()
        # High-specificity types carry higher intrinsic pivot value
        type_weights = {
            "Alias": 1.35,
            "TechnicalArtifact": 1.40,
            "Person": 1.15,
            "Org": 1.05,
            "Event": 1.00,
            "Location": 0.80,
            "Topic": 0.75,
        }

        recommendations: list[dict[str, Any]] = []
        for node in snapshot.nodes:
            deg = g.degree(node.id) if node.id in g else 0
            # Frontier bonus: high confidence nodes with fewer explored neighbors have more untapped gain
            frontier_factor = 1.0 / math.sqrt(1.0 + deg)
            claim_richness = 1.0 + 0.15 * min(5, len(node.claims))
            t_weight = type_weights.get(node.type, 1.0)

            info_gain = round(node.confidence * t_weight * frontier_factor * claim_richness, 4)
            recommendations.append(
                {
                    "node_id": node.id,
                    "label": node.label,
                    "type": node.type,
                    "confidence": node.confidence,
                    "degree": deg,
                    "information_gain_score": info_gain,
                }
            )

        recommendations.sort(key=lambda r: r["information_gain_score"], reverse=True)
        return recommendations[:top_k]

    # --- Persistent Investigation Blackboards ---

    def save_blackboard(self, blackboard: Any) -> None:
        """Persist an InvestigationBlackboard (MCTS tree, trace, checkpoints) into SQLite."""
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO blackboards (id, workspace_id, data_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    blackboard.id,
                    blackboard.workspace_id,
                    blackboard.model_dump_json(),
                    utc_now().isoformat(),
                ),
            )

    def get_blackboard(self, blackboard_id: str) -> Optional[dict[str, Any]]:
        """Load raw blackboard JSON dict from SQLite."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM blackboards WHERE id = ?", (blackboard_id,)
            ).fetchone()
        return json.loads(row["data_json"]) if row else None

    def list_blackboards(self, workspace_id: str) -> list[dict[str, Any]]:
        """List all persisted investigation blackboards for a workspace."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data_json FROM blackboards WHERE workspace_id = ? ORDER BY updated_at DESC",
                (workspace_id,),
            ).fetchall()
        return [json.loads(r["data_json"]) for r in rows]

    # --- Persistent Chat History & Multi-Turn Context ---

    def add_chat_message(
        self,
        workspace_id: str,
        role: str,
        content: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Persist a user or assistant chat message in SQLite so context survives reloads."""
        msg_id = new_id()
        now_iso = utc_now().isoformat()
        payload_data = payload or {}
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_messages (id, workspace_id, role, content, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    msg_id,
                    workspace_id,
                    role,
                    content,
                    json.dumps(payload_data, ensure_ascii=False),
                    now_iso,
                ),
            )
        return {
            "id": msg_id,
            "workspace_id": workspace_id,
            "role": role,
            "content": content,
            "payload": payload_data,
            "created_at": now_iso,
        }

    def list_chat_messages(self, workspace_id: str) -> list[dict[str, Any]]:
        """Return all persisted chat messages for a workspace in chronological order."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, role, content, payload_json, created_at
                FROM chat_messages
                WHERE workspace_id = ?
                ORDER BY created_at ASC, rowid ASC
                """,
                (workspace_id,),
            ).fetchall()
        return [
            {
                "id": r["id"],
                "workspace_id": r["workspace_id"],
                "role": r["role"],
                "content": r["content"],
                "payload": json.loads(r["payload_json"]) if r["payload_json"] else {},
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    # --- Confirmed Dossier Board (User-Curated Ground Truth fed into Next Searches) ---

    def list_dossier_items(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, category, field_key, field_value, source_url, note, updated_at
                FROM dossier_items
                WHERE workspace_id = ?
                ORDER BY updated_at DESC, rowid DESC
                """,
                (workspace_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    @staticmethod
    def _normalize_dossier_url(url: str) -> str:
        return url.strip().rstrip("/").lower()

    _KNOWN_DOMAIN_ORG_MAP: dict[str, str] = {
        "ntt.edu.vn": "NTTU (ĐH Nguyễn Tất Thành)",
        "ueh.edu.vn": "UEH (ĐH Kinh tế TP.HCM)",
        "uit.edu.vn": "UIT (ĐH Công nghệ Thông tin)",
        "hcmut.edu.vn": "HCMUT (ĐH Bách Khoa TP.HCM)",
        "hcmus.edu.vn": "HCMUS (ĐH Khoa học Tự nhiên TP.HCM)",
        "hcmussh.edu.vn": "USSH (ĐH KHXH&NV TP.HCM)",
        "uel.edu.vn": "UEL (ĐH Kinh tế - Luật)",
        "hust.edu.vn": "HUST (ĐH Bách Khoa Hà Nội)",
        "ftu.edu.vn": "FTU (ĐH Ngoại thương)",
        "neu.edu.vn": "NEU (ĐH Kinh tế Quốc dân)",
        "ptit.edu.vn": "PTIT (Học viện CNBCVT)",
        "fpt.edu.vn": "Đại học FPT",
        "ump.edu.vn": "UMP (ĐH Y Dược TP.HCM)",
        "pnt.edu.vn": "ĐH Y khoa Phạm Ngọc Thạch",
        "sgu.edu.vn": "SGU (ĐH Sài Gòn)",
        "tdtu.edu.vn": "TDTU (ĐH Tôn Đức Thắng)",
        "hutech.edu.vn": "HUTECH (ĐH Công nghệ TP.HCM)",
        "vlu.edu.vn": "VLU (ĐH Văn Lang)",
        "huflit.edu.vn": "HUFLIT (ĐH Ngoại ngữ - Tin học TP.HCM)",
        "iuh.edu.vn": "IUH (ĐH Công nghiệp TP.HCM)",
        "huit.edu.vn": "HUIT (ĐH Công Thương TP.HCM)",
        "ute.udn.vn": "ĐH Sư phạm Kỹ thuật Đà Nẵng",
        "hcmute.edu.vn": "HCMUTE (ĐH Sư phạm Kỹ thuật TP.HCM)",
        "ctu.edu.vn": "CTU (ĐH Cần Thơ)",
    }

    def _sync_dossier_item_to_graph(
        self,
        workspace_id: str,
        field_key: str,
        field_value: str,
        source_url: str = "",
    ) -> None:
        """Immediately reflect a user-pinned or edited Dossier item onto the primary Person node AND create Org/Location edges."""
        try:
            with self._connect() as conn:
                person_row = conn.execute(
                    "SELECT * FROM nodes WHERE workspace_id = ? AND type = 'Person' ORDER BY confidence DESC, updated_at DESC LIMIT 1",
                    (workspace_id,),
                ).fetchone()
            if not person_row:
                return
            person_node = self._row_to_node(person_row)
            fk_low = field_key.strip().lower()
            fv = field_value.strip()
            if not fv:
                return

            mapped_key = ""
            mapped_cat = FeatureCategory.IDENTITY
            if len(fv) <= 160:
                if any(k in fk_low for k in ("email", "thư điện tử", "mail")):
                    mapped_key = "email"
                    mapped_cat = FeatureCategory.TECHNICAL_ARTIFACT
                elif any(k in fk_low for k in ("mssv", "mã sinh viên", "student_id", "cccd", "sbd")):
                    mapped_key = "student_id"
                    mapped_cat = FeatureCategory.IDENTITY
                elif any(k in fk_low for k in ("sđt", "điện thoại", "phone")):
                    mapped_key = "public_phone"
                    mapped_cat = FeatureCategory.TECHNICAL_ARTIFACT
                elif any(k in fk_low for k in ("ngày sinh", "năm sinh", "dob", "birth")):
                    mapped_key = "birth_date"
                    mapped_cat = FeatureCategory.SPATIOTEMPORAL
                elif any(k in fk_low for k in ("trường", "tổ chức", "công ty", "đơn vị", "school", "org")):
                    mapped_key = "school_or_org"
                    mapped_cat = FeatureCategory.EDUCATION_CAREER
                elif any(k in fk_low for k in ("địa chỉ", "địa điểm", "quê", "location")):
                    mapped_key = "location"
                    mapped_cat = FeatureCategory.SPATIOTEMPORAL
                elif any(k in fk_low for k in ("nick", "alias", "username", "tài khoản")):
                    mapped_key = "nickname"
                    mapped_cat = FeatureCategory.IDENTITY

            extracted_claims: list[FeatureClaim] = []
            discovered_orgs: list[str] = []
            discovered_locs: list[str] = []
            eff_url = source_url.strip() or "manual://user_verified"

            if mapped_key:
                extracted_claims.append(
                    FeatureClaim(
                        category=mapped_cat,
                        key=mapped_key,
                        value=fv,
                        confidence=0.99,
                        source_url=eff_url,
                        evidence_quote=f"Hồ sơ đã ghim ({field_key}): {fv}",
                    )
                )
                if mapped_key == "school_or_org":
                    discovered_orgs.append(fv)
                elif mapped_key == "location":
                    discovered_locs.append(fv)
            else:
                # Parse rich pinned source snippet / excerpt (e.g. "Nguồn đã xác nhận": "Fullnttu | PDF — ... 1900006468 19DYK1A Võ Phúc Thiên Kim 28/05/2001 ...")
                from app.agents.reader import is_email_plausible_for_subject

                for em_match in re.findall(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", fv):
                    if is_email_plausible_for_subject(em_match, person_node.label, fv):
                        extracted_claims.append(
                            FeatureClaim(
                                category=FeatureCategory.TECHNICAL_ARTIFACT,
                                key="email",
                                value=em_match.lower(),
                                confidence=0.99,
                                source_url=eff_url,
                                evidence_quote=f"Hồ sơ đã ghim: {em_match}",
                            )
                        )

                # Extract Vietnamese student IDs (7-11 digits, excluding BHYT/social security 10-digit numbers that follow SV479... or 79-010)
                for sid_m in re.finditer(r"\b(\d{8,11})\b", fv):
                    cand_sid = sid_m.group(1)
                    # Skip if preceded by 'SV' (health insurance card number) or identical to a phone starting with 0
                    prefix_2 = fv[max(0, sid_m.start() - 2) : sid_m.start()].upper()
                    if prefix_2 == "SV" or cand_sid.startswith("0"):
                        continue
                    # If 10 digits starting with 79/80 right before SV479<same10digits>, skip BHYT social security code
                    if f"SV479{cand_sid}" in fv or f"SV4{cand_sid}" in fv:
                        continue
                    extracted_claims.append(
                        FeatureClaim(
                            category=FeatureCategory.IDENTITY,
                            key="student_id",
                            value=cand_sid,
                            confidence=0.96,
                            source_url=eff_url,
                            evidence_quote=fv[:160],
                        )
                    )
                    break

                # Extract Vietnamese university class codes (e.g. 19DYK1A, 19ĐYK1A, DH22TIN01, K51...)
                for cls_m in re.finditer(r"\b(\d{2}[A-ZĐ]{2,5}\d[A-Z0-9]{1,3}|(?:DH|CQ|CLC)\d{2}[A-Z]{2,5}\d{1,3})\b", fv):
                    cls_code = cls_m.group(1)
                    extracted_claims.append(
                        FeatureClaim(
                            category=FeatureCategory.EDUCATION_CAREER,
                            key="class_code",
                            value=cls_code,
                            confidence=0.95,
                            source_url=eff_url,
                            evidence_quote=fv[:160],
                        )
                    )
                    break

                # Extract institution from source_url domain (e.g. ctsv.ntt.edu.vn -> NTTU) or title/snippet keywords (Fullnttu, NTTU, UEH, UIT...)
                url_low = eff_url.lower()
                fv_low = fv.lower()
                for dom, canon_org in self._KNOWN_DOMAIN_ORG_MAP.items():
                    if dom in url_low:
                        discovered_orgs.append(canon_org)
                        break
                if not discovered_orgs:
                    if "nttu" in fv_low or "nguyễn tất thành" in fv_low:
                        discovered_orgs.append("NTTU (ĐH Nguyễn Tất Thành)")
                    elif "ueh" in fv_low or "đại học kinh tế tp" in fv_low:
                        discovered_orgs.append("UEH (ĐH Kinh tế TP.HCM)")
                    elif "uit" in fv_low or "công nghệ thông tin" in fv_low:
                        discovered_orgs.append("UIT (ĐH Công nghệ Thông tin)")
                    elif "hcmut" in fv_low or "bách khoa" in fv_low:
                        discovered_orgs.append("HCMUT (ĐH Bách Khoa TP.HCM)")

                for org_name in discovered_orgs:
                    extracted_claims.append(
                        FeatureClaim(
                            category=FeatureCategory.EDUCATION_CAREER,
                            key="school_or_org",
                            value=org_name,
                            confidence=0.96,
                            source_url=eff_url,
                            evidence_quote=fv[:160],
                        )
                    )

            # Create Org and Location nodes + verified Edges in the Knowledge Graph!
            for org_name in discovered_orgs:
                org_node = self.upsert_node(
                    workspace_id,
                    NodeCreate(type="Org", label=org_name, confidence=0.95),
                )
                self.add_edge(
                    workspace_id,
                    EdgeCreate(
                        source_id=person_node.id,
                        target_id=org_node.id,
                        relation="STUDIED_OR_WORKED_AT",
                        confidence=0.95,
                        status="VERIFIED",
                        evidence_quote=fv[:160],
                        source_url=eff_url,
                    ),
                )
            for loc_name in discovered_locs:
                loc_node = self.upsert_node(
                    workspace_id,
                    NodeCreate(type="Location", label=loc_name, confidence=0.92),
                )
                self.add_edge(
                    workspace_id,
                    EdgeCreate(
                        source_id=person_node.id,
                        target_id=loc_node.id,
                        relation="LOCATED_IN",
                        confidence=0.92,
                        status="VERIFIED",
                        evidence_quote=fv[:160],
                        source_url=eff_url,
                    ),
                )

            if not extracted_claims:
                return

            # If user explicitly pinned a single-valued identity key (email, birth_date, student_id, public_phone),
            # replace any unverified web-scraped value on that same key so the entity stays 100% consistent with Dossier!
            single_value_keys = {"email", "birth_date", "student_id", "public_phone"}
            pinned_single_keys = {c.key for c in extracted_claims if c.key in single_value_keys and mapped_key}
            if pinned_single_keys:
                with self._connect() as conn:
                    filtered_existing = [
                        c
                        for c in person_node.claims
                        if not (c.key in pinned_single_keys and c.source_url != "manual://user_verified")
                    ]
                    conn.execute(
                        "UPDATE nodes SET claims_json = ? WHERE id = ?",
                        (json.dumps([c.model_dump(mode="json") for c in filtered_existing]), person_node.id),
                    )

            self.upsert_node(
                workspace_id,
                NodeCreate(
                    type=person_node.type,
                    label=person_node.label,
                    claims=extracted_claims,
                    confidence=max(person_node.confidence, 0.95),
                ),
            )
        except Exception:
            pass

    def delete_node(self, node_id: str) -> bool:
        with self._connect() as conn:
            conn.execute("DELETE FROM nodes_fts WHERE node_id = ?", (node_id,))
            conn.execute("DELETE FROM edges WHERE source_id = ? OR target_id = ?", (node_id, node_id))
            cur = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            return cur.rowcount > 0

    def delete_node_claim(self, node_id: str, claim_key: str, claim_value: str) -> Optional[Node]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
            if not row:
                return None
            node = self._row_to_node(row)
            target_norm = normalize_text(claim_value)
            kept = [
                c
                for c in node.claims
                if not (c.key == claim_key and (str(c.value) == claim_value or normalize_text(str(c.value)) == target_norm))
            ]
            node.claims = kept
            conn.execute(
                "UPDATE nodes SET claims_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps([c.model_dump(mode="json") for c in kept]), utc_now().isoformat(), node.id),
            )
            self._sync_fts(conn, node)
        return node

    def delete_edge(self, edge_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM edges WHERE id = ?", (edge_id,))
            return cur.rowcount > 0

    def add_dossier_item(
        self,
        workspace_id: str,
        field_key: str,
        field_value: str,
        category: str = "general",
        source_url: str = "",
        note: str = "",
    ) -> dict[str, Any]:
        clean_key = field_key.strip()
        clean_val = field_value.strip()
        clean_cat = category.strip() or "general"
        clean_url = source_url.strip()
        clean_note = note.strip()
        norm_url = self._normalize_dossier_url(clean_url)

        # Prevent duplicate entries in the same workspace (by normalized source_url OR exact key+value)
        with self._connect() as conn:
            existing_rows = conn.execute(
                """
                SELECT id, workspace_id, category, field_key, field_value, source_url, note, updated_at
                FROM dossier_items
                WHERE workspace_id = ?
                """,
                (workspace_id,),
            ).fetchall()
            for row in existing_rows:
                row_norm_url = self._normalize_dossier_url(row["source_url"] or "")
                is_external_url = norm_url.startswith(("http://", "https://"))
                same_url = bool(is_external_url and row_norm_url and norm_url == row_norm_url)
                same_kv = (
                    (row["field_key"] or "").strip().lower() == clean_key.lower()
                    and (row["field_value"] or "").strip().lower() == clean_val.lower()
                )
                if same_url or same_kv:
                    existing = dict(row)
                    existing["already_exists"] = True
                    return existing

            item_id = new_id()
            now_iso = utc_now().isoformat()
            conn.execute(
                """
                INSERT INTO dossier_items (
                    id, workspace_id, category, field_key, field_value, source_url, note, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    workspace_id,
                    clean_cat,
                    clean_key,
                    clean_val,
                    clean_url,
                    clean_note,
                    now_iso,
                ),
            )
        self._sync_dossier_item_to_graph(workspace_id, clean_key, clean_val, clean_url)
        return {
            "id": item_id,
            "workspace_id": workspace_id,
            "category": clean_cat,
            "field_key": clean_key,
            "field_value": clean_val,
            "source_url": clean_url,
            "note": clean_note,
            "updated_at": now_iso,
            "already_exists": False,
        }

    def update_dossier_item(
        self,
        item_id: str,
        field_key: Optional[str] = None,
        field_value: Optional[str] = None,
        category: Optional[str] = None,
        source_url: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM dossier_items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                return None
            new_key = field_key.strip() if field_key is not None else row["field_key"]
            new_val = field_value.strip() if field_value is not None else row["field_value"]
            new_cat = category.strip() if category is not None else row["category"]
            new_src = source_url.strip() if source_url is not None else row["source_url"]
            new_note = note.strip() if note is not None else row["note"]
            now_iso = utc_now().isoformat()
            conn.execute(
                """
                UPDATE dossier_items
                SET category = ?, field_key = ?, field_value = ?, source_url = ?, note = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_cat, new_key, new_val, new_src, new_note, now_iso, item_id),
            )
            updated = conn.execute("SELECT * FROM dossier_items WHERE id = ?", (item_id,)).fetchone()
        if updated:
            self._sync_dossier_item_to_graph(
                updated["workspace_id"],
                updated["field_key"],
                updated["field_value"],
                updated["source_url"] or "",
            )
        return dict(updated) if updated else None

    def delete_dossier_item(self, item_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM dossier_items WHERE id = ?", (item_id,))
            return cur.rowcount > 0

    # --- Source Feedback & Permanent URL Veto Memory ---

    def add_source_feedback(
        self,
        workspace_id: str,
        source_url: str,
        verdict: str = "REJECTED",
        title: str = "",
    ) -> dict[str, Any]:
        clean_url = (source_url or "").strip()
        norm_url = self._normalize_dossier_url(clean_url)
        clean_verdict = (verdict or "REJECTED").strip().upper()
        now_iso = utc_now().isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT id FROM source_feedback WHERE workspace_id = ? AND normalized_url = ?",
                (workspace_id, norm_url),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE source_feedback SET verdict = ?, title = ?, created_at = ? WHERE id = ?",
                    (clean_verdict, title.strip(), now_iso, existing["id"]),
                )
                fb_id = existing["id"]
            else:
                fb_id = new_id()
                conn.execute(
                    """
                    INSERT INTO source_feedback (id, workspace_id, source_url, normalized_url, title, verdict, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (fb_id, workspace_id, clean_url, norm_url, title.strip(), clean_verdict, now_iso),
                )
        return {
            "id": fb_id,
            "workspace_id": workspace_id,
            "source_url": clean_url,
            "normalized_url": norm_url,
            "title": title.strip(),
            "verdict": clean_verdict,
            "created_at": now_iso,
        }

    def list_source_feedback(self, workspace_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, workspace_id, source_url, normalized_url, title, verdict, created_at
                FROM source_feedback
                WHERE workspace_id = ?
                ORDER BY created_at DESC
                """,
                (workspace_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_source_feedback(self, workspace_id: str, source_url: str) -> bool:
        norm_url = self._normalize_dossier_url(source_url or "")
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM source_feedback WHERE workspace_id = ? AND normalized_url = ?",
                (workspace_id, norm_url),
            )
            return cur.rowcount > 0
