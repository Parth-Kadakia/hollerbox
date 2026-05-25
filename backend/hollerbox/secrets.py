"""Encrypted-at-rest secret store.

The master key lives at `~/.hollerbox/key` (0600 perms; the data dir is
0700). Secrets are encrypted with Fernet (AES-128-CBC + HMAC) and stored
as `secrets.value_encrypted` rows in the SQLite db (§8 schema).

Operationally the rules from the brief (§10):
- API responses never include the plaintext (CLI `secret list` shows
  names only; future API exposes `{"set": true}` etc.).
- The Runner snapshots `step_runs.resolved_input` via
  `ctx.resolve_redacted(...)` so persisted records never include a
  resolved `${secrets.*}` value — the in-memory `secrets` dict is the
  only place real values exist during a run.
"""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session, sessionmaker

from hollerbox.store import repo, session_scope

DEFAULT_DATA_DIR = Path("~/.hollerbox").expanduser()
DEFAULT_KEY_FILE = DEFAULT_DATA_DIR / "key"


class SecretStoreError(Exception):
    """Raised on key-file / decryption problems the user can act on."""


class SecretStore:
    """Encrypted secret store backed by SQLite + a local key file."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        key_path: Path | None = None,
    ) -> None:
        self._sf = session_factory
        self._key_path = (key_path or DEFAULT_KEY_FILE).expanduser()
        self._fernet = self._load_or_create_fernet()

    # --------------------------- key handling ---------------------------

    def _load_or_create_fernet(self) -> Fernet:
        if self._key_path.exists():
            key = self._key_path.read_bytes().strip()
            if not key:
                raise SecretStoreError(
                    f"key file at {self._key_path} is empty — refusing to overwrite. "
                    "Delete it manually if you intend to start fresh."
                )
            try:
                return Fernet(key)
            except (ValueError, TypeError) as exc:
                raise SecretStoreError(
                    f"key file at {self._key_path} is invalid: {exc}"
                ) from exc

        # First run — generate and persist a new key. The chmod calls are
        # best-effort: POSIX permissions don't apply on every filesystem
        # (Windows, certain mounted volumes) and we'd rather still create
        # the key there than refuse outright.
        self._key_path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self._key_path.parent, 0o700)
        key = Fernet.generate_key()
        self._key_path.write_bytes(key)
        with contextlib.suppress(OSError):
            os.chmod(self._key_path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        return Fernet(key)

    # --------------------------- public API ---------------------------

    def set(self, name: str, value: str) -> None:
        if not name or not name.strip():
            raise ValueError("secret name must be non-empty")
        ciphertext = self._fernet.encrypt(value.encode("utf-8"))
        with session_scope(self._sf) as s:
            repo.upsert_secret(s, name=name, ciphertext=ciphertext)

    def get(self, name: str) -> str | None:
        with session_scope(self._sf) as s:
            ciphertext = repo.get_secret_ciphertext(s, name)
        if ciphertext is None:
            return None
        return self._decrypt(ciphertext, name=name)

    def has(self, name: str) -> bool:
        with session_scope(self._sf) as s:
            return repo.get_secret_ciphertext(s, name) is not None

    def list_names(self) -> list[str]:
        with session_scope(self._sf) as s:
            return repo.list_secret_names(s)

    def delete(self, name: str) -> bool:
        with session_scope(self._sf) as s:
            return repo.delete_secret(s, name)

    def load_all(self) -> dict[str, str]:
        """Decrypt every stored secret into an in-memory dict.

        Used by the Runner at execute/resume time so `${secrets.*}`
        references inside workflow YAML resolve transparently.
        """
        with session_scope(self._sf) as s:
            rows = repo.list_secrets_with_ciphertext(s)
        return {name: self._decrypt(ct, name=name) for name, ct in rows}

    # --------------------------- internals ---------------------------

    def _decrypt(self, ciphertext: bytes, *, name: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken as exc:
            raise SecretStoreError(
                f"failed to decrypt secret {name!r} — the key at "
                f"{self._key_path} likely does not match the one that "
                "encrypted this value."
            ) from exc
