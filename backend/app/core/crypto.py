"""Local-first Fernet encryption-at-rest for API keys stored in SQLite.

Generates a machine-local key file alongside the SQLite database (`.stalker_key`)
and transparently decrypts both newly encrypted (`enc::...`) and legacy plaintext rows.
"""

from __future__ import annotations

import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ENC_PREFIX = "enc::"


class SecretBox:
    """Symmetric Fernet vault scoped to a local Stalker++ data directory."""

    def __init__(self, db_path: str | Path) -> None:
        db = Path(db_path)
        self.key_file = db.parent / ".stalker_key"
        self._fernet = Fernet(self._load_or_create_key())

    def _load_or_create_key(self) -> bytes:
        env_key = os.environ.get("STALKER_MASTER_KEY", "").strip()
        if env_key:
            return env_key.encode("utf-8")
        self.key_file.parent.mkdir(parents=True, exist_ok=True)
        if self.key_file.exists():
            raw = self.key_file.read_bytes().strip()
            if raw:
                return raw
        key = Fernet.generate_key()
        self.key_file.write_bytes(key)
        try:
            os.chmod(self.key_file, 0o600)
        except OSError:
            pass
        return key

    def encrypt(self, plaintext: str) -> str:
        clean = plaintext.strip()
        if not clean:
            return ""
        if clean.startswith(ENC_PREFIX):
            return clean
        token = self._fernet.encrypt(clean.encode("utf-8")).decode("utf-8")
        return f"{ENC_PREFIX}{token}"

    def decrypt(self, stored: str) -> str:
        raw = (stored or "").strip()
        if not raw:
            return ""
        if not raw.startswith(ENC_PREFIX):
            # Backwards compatibility for pre-encryption plaintext keys
            return raw
        token = raw[len(ENC_PREFIX) :]
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken:
            return ""

    @staticmethod
    def is_encrypted(stored: str) -> bool:
        return (stored or "").startswith(ENC_PREFIX)
