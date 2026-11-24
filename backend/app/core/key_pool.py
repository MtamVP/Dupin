"""SQLite-backed Multi-Key Rotation Pool (n8n-style Round-Robin + 429 Cooldown) & Local Host Config."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.core.crypto import SecretBox
from app.core.schemas import new_id, utc_now

ProviderType = Literal["gemini", "openai", "serper", "tavily", "github"]


class APIKeyCreate(BaseModel):
    """Payload to register a named API key into the rotation pool."""

    name: str = Field(..., min_length=1, max_length=80)
    provider: ProviderType
    api_key: str = Field(..., min_length=4)
    model: str = ""
    enabled: bool = True


class LocalHostConfig(BaseModel):
    """Persistent configuration for local-first AI & search hosts (Ollama, SearXNG)."""

    active_mode: Literal["auto", "gemini_pool", "ollama_local", "openai_pool", "metasearch_only"] = "auto"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    searxng_url: str = ""


def mask_secret(secret: str) -> str:
    """Safely mask an API key for UI display (never expose raw keys)."""
    s = secret.strip()
    if len(s) <= 8:
        return "****"
    return f"{s[:4]}...{s[-4:]}"


class IntegrationStore:
    """Manages rotating API key pools and local host settings in SQLite."""

    _initialized_dbs: set[str] = set()

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._vault = SecretBox(self.db_path)
        db_key = str(self.db_path.resolve())
        if db_key not in self._initialized_dbs:
            self._init_schema()
            self._initialized_dbs.add(db_key)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 15000;")
        except sqlite3.OperationalError:
            pass
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    api_key TEXT NOT NULL,
                    model TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    error_count INTEGER NOT NULL DEFAULT 0,
                    last_used_ts REAL NOT NULL DEFAULT 0,
                    cooldown_until REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS local_host_config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    config_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

    # --- Local Host Config (Ollama + SearXNG) ---

    def get_local_config(self) -> LocalHostConfig:
        with self._connect() as conn:
            row = conn.execute("SELECT config_json FROM local_host_config WHERE id = 1").fetchone()
        if not row:
            return LocalHostConfig()
        return LocalHostConfig(**json.loads(row["config_json"]))

    def save_local_config(self, cfg: LocalHostConfig) -> LocalHostConfig:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO local_host_config (id, config_json, updated_at)
                VALUES (1, ?, ?)
                """,
                (cfg.model_dump_json(), utc_now().isoformat()),
            )
        return cfg

    # --- Multi-Key Rotation Pool ---

    def add_key(self, payload: APIKeyCreate) -> dict[str, Any]:
        key_id = new_id()
        now_iso = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO api_keys (
                    id, name, provider, api_key, model, enabled,
                    usage_count, error_count, last_used_ts, cooldown_until, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, ?)
                """,
                (
                    key_id,
                    payload.name.strip(),
                    payload.provider,
                    self._vault.encrypt(payload.api_key.strip()),
                    payload.model.strip(),
                    1 if payload.enabled else 0,
                    now_iso,
                ),
            )
        return self.get_masked_key(key_id) or {}

    def get_masked_key(self, key_id: str) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        return self._row_to_masked(row) if row else None

    def _row_to_masked(self, row: sqlite3.Row) -> dict[str, Any]:
        now_ts = time.time()
        in_cooldown = float(row["cooldown_until"]) > now_ts
        status = "DISABLED" if not row["enabled"] else ("COOLDOWN" if in_cooldown else "ACTIVE")
        raw_plain = self._vault.decrypt(row["api_key"])
        return {
            "id": row["id"],
            "name": row["name"],
            "provider": row["provider"],
            "masked_key": mask_secret(raw_plain),
            "encrypted": SecretBox.is_encrypted(row["api_key"]),
            "model": row["model"],
            "enabled": bool(row["enabled"]),
            "usage_count": int(row["usage_count"]),
            "error_count": int(row["error_count"]),
            "status": status,
            "cooldown_remaining_sec": max(0, int(float(row["cooldown_until"]) - now_ts)),
            "created_at": row["created_at"],
        }

    def list_keys(self, provider: Optional[str] = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if provider:
                rows = conn.execute(
                    "SELECT * FROM api_keys WHERE provider = ? ORDER BY created_at ASC",
                    (provider,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM api_keys ORDER BY provider ASC, created_at ASC"
                ).fetchall()
        return [self._row_to_masked(r) for r in rows]

    def toggle_key(self, key_id: str, enabled: bool) -> Optional[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE api_keys SET enabled = ?, cooldown_until = 0 WHERE id = ?",
                (1 if enabled else 0, key_id),
            )
            if cur.rowcount == 0:
                return None
        return self.get_masked_key(key_id)

    def delete_key(self, key_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
            return cur.rowcount > 0

    def acquire_key(self, provider: str) -> Optional[dict[str, Any]]:
        """Select the next healthy API key for `provider` using Round-Robin (least-recently-used).

        Automatically skips disabled keys and keys currently in 429 rate-limit cooldown.
        """
        now_ts = time.time()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM api_keys
                WHERE provider = ? AND enabled = 1 AND cooldown_until <= ?
                ORDER BY last_used_ts ASC, usage_count ASC
                LIMIT 1
                """,
                (provider, now_ts),
            ).fetchone()
            if not row:
                return None
            try:
                conn.execute(
                    "UPDATE api_keys SET usage_count = usage_count + 1, last_used_ts = ? WHERE id = ?",
                    (now_ts, row["id"]),
                )
            except sqlite3.OperationalError:
                pass
            return {
                "id": row["id"],
                "name": row["name"],
                "provider": row["provider"],
                "api_key": self._vault.decrypt(row["api_key"]),
                "model": row["model"],
            }

    def report_key_error(
        self, key_id: str, is_rate_limit: bool = False, cooldown_sec: float = 60.0
    ) -> None:
        """Increment error counter and place key into temporary cooldown on HTTP 429 / quota errors."""
        cooldown_until = (time.time() + cooldown_sec) if is_rate_limit else 0.0
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE api_keys
                SET error_count = error_count + 1,
                    cooldown_until = CASE WHEN ? > cooldown_until THEN ? ELSE cooldown_until END
                WHERE id = ?
                """,
                (cooldown_until, cooldown_until, key_id),
            )
