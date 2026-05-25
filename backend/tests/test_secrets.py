"""Tests for hollerbox.secrets.SecretStore."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from hollerbox.secrets import SecretStore, SecretStoreError
from hollerbox.store import init_db, make_engine, make_session_factory


@pytest.fixture()
def session_factory():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    return make_session_factory(engine)


@pytest.fixture()
def store(session_factory, tmp_path: Path) -> SecretStore:
    return SecretStore(session_factory, key_path=tmp_path / "key")


# --------------------------- round-trip ---------------------------

def test_set_then_get_roundtrip(store: SecretStore):
    store.set("OPENAI_API_KEY", "sk-real-value")
    assert store.get("OPENAI_API_KEY") == "sk-real-value"


def test_get_missing_returns_none(store: SecretStore):
    assert store.get("NEVER_SET") is None


def test_has_reflects_set_state(store: SecretStore):
    assert store.has("FOO") is False
    store.set("FOO", "bar")
    assert store.has("FOO") is True


def test_update_overwrites(store: SecretStore):
    store.set("K", "v1")
    store.set("K", "v2")
    assert store.get("K") == "v2"


def test_delete(store: SecretStore):
    store.set("K", "v")
    assert store.delete("K") is True
    assert store.get("K") is None
    assert store.delete("K") is False  # already gone


def test_list_names_sorted(store: SecretStore):
    store.set("BETA", "x")
    store.set("ALPHA", "y")
    store.set("GAMMA", "z")
    assert store.list_names() == ["ALPHA", "BETA", "GAMMA"]


def test_empty_name_rejected(store: SecretStore):
    with pytest.raises(ValueError):
        store.set("", "x")
    with pytest.raises(ValueError):
        store.set("   ", "x")


# --------------------------- key file ---------------------------

def test_key_file_created_with_0600_perms(session_factory, tmp_path: Path):
    key_path = tmp_path / "subdir" / "key"
    _ = SecretStore(session_factory, key_path=key_path)
    assert key_path.exists()
    # Parent dir created
    assert key_path.parent.is_dir()
    # Permission bits: 0600 on POSIX
    if os.name == "posix":
        mode = stat.S_IMODE(key_path.stat().st_mode)
        assert mode == 0o600, oct(mode)


def test_persistent_across_instances(session_factory, tmp_path: Path):
    key_path = tmp_path / "key"
    s1 = SecretStore(session_factory, key_path=key_path)
    s1.set("HELLO", "world")
    s2 = SecretStore(session_factory, key_path=key_path)
    assert s2.get("HELLO") == "world"


def test_wrong_key_raises_clean_error(session_factory, tmp_path: Path):
    # Encrypt with one key.
    key_a = tmp_path / "key_a"
    s1 = SecretStore(session_factory, key_path=key_a)
    s1.set("X", "encrypted-under-a")

    # Now point a fresh SecretStore at a different key file and try to read
    # the row that was encrypted with key_a — should fail loudly.
    key_b = tmp_path / "key_b"
    key_b.write_bytes(Fernet.generate_key())
    s2 = SecretStore(session_factory, key_path=key_b)
    with pytest.raises(SecretStoreError, match="does not match"):
        s2.get("X")


def test_invalid_key_file_rejected(session_factory, tmp_path: Path):
    bad = tmp_path / "bad_key"
    bad.write_bytes(b"not-a-real-fernet-key")
    with pytest.raises(SecretStoreError, match="invalid"):
        SecretStore(session_factory, key_path=bad)


def test_empty_key_file_refused(session_factory, tmp_path: Path):
    empty = tmp_path / "empty_key"
    empty.write_bytes(b"")
    with pytest.raises(SecretStoreError, match="empty"):
        SecretStore(session_factory, key_path=empty)


# --------------------------- load_all ---------------------------

def test_load_all_returns_decrypted_dict(store: SecretStore):
    store.set("A", "alpha")
    store.set("B", "beta")
    loaded = store.load_all()
    assert loaded == {"A": "alpha", "B": "beta"}


def test_load_all_empty(store: SecretStore):
    assert store.load_all() == {}


# --------------------------- encryption integrity ---------------------------

def test_ciphertext_in_db_does_not_contain_plaintext(store: SecretStore, session_factory):
    """The on-disk DB row must NEVER contain the plaintext byte sequence."""
    plaintext = "this-is-very-secret-value-12345"
    store.set("K", plaintext)
    from hollerbox.store import repo, session_scope

    with session_scope(session_factory) as s:
        ct = repo.get_secret_ciphertext(s, "K")
    assert ct is not None
    assert plaintext.encode("utf-8") not in ct
