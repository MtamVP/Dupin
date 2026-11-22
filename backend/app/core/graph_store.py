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
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA busy_timeout = 10000;")
        conn.execute("PRAGMA journal_mode = WAL;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
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
                """
            )

    # --- Workspaces ---

    def create_workspace(self, payload: WorkspaceCreate) -> Workspace:
        ws = Workspace(name=payload.name, description=payload.description)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO workspaces (id, name, description, created_at) VALUES (?, ?, ?, ?)",
                (ws.id, ws.name, ws.description, ws.created_at.isoformat()),
            )
        return ws

    def list_workspaces(self) -> list[Workspace]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, description, created_at FROM workspaces ORDER BY created_at DESC"
            ).fetchall()
        return [Workspace(**dict(r)) for r in rows]

    def get_workspace(self, workspace_id: str) -> Optional[Workspace]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name, description, created_at FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
        return Workspace(**dict(row)) if row else None

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
            row = conn.execute(
                "SELECT id, name, description, created_at FROM workspaces WHERE id = ?",
                (workspace_id,),
            ).fetchone()
        return Workspace(**dict(row)) if row else None

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
                existing_keys = {(c.key, str(c.value), c.source_url) for c in node.claims}
                new_claims: list[FeatureClaim] = []
                for claim in payload.claims:
                    sig = (claim.key, str(claim.value), claim.source_url)
                    if sig not in existing_keys:
                        node.claims.append(claim)
                        new_claims.append(claim)
                        existing_keys.add(sig)

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
        edge = Edge(workspace_id=workspace_id, **payload.model_dump())
        with self._connect() as conn:
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
                same_url = bool(norm_url and row_norm_url and norm_url == row_norm_url)
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
        return dict(updated) if updated else None

    def delete_dossier_item(self, item_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM dossier_items WHERE id = ?", (item_id,))
            return cur.rowcount > 0
