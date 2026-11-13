"""Unit tests for MemoryManager connection safety and data preservation.

Uses only temporary databases for destructive/isolated scenarios; the real
data/memory.db is opened read-only in exactly one test to prove existing
records survive a normal connect.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.memory_manager import MemoryDBError, MemoryManager


def test_parent_dir_created_when_missing(tmp_path):
    nested = tmp_path / "a" / "b" / "c" / "memory.db"
    mm = MemoryManager(str(nested))
    assert nested.parent.is_dir()
    assert nested.exists()
    # A write/read round-trips through the freshly created path.
    mid = mm.remember("fact", "t", "c")
    assert mm.get(mid)["content"] == "c"


def test_new_db_initializes_and_journal_mode_works(tmp_path):
    db = tmp_path / "fresh.db"
    mm = MemoryManager(str(db))
    # WAL is the preferred mode on a normal local filesystem.
    assert mm._journal_mode in {"wal", "delete", "unset", "wal-locked"}
    # Tables exist and are empty to start.
    assert mm.search() == []


def test_existing_records_survive_reopen(tmp_path):
    db = tmp_path / "persist.db"
    mm = MemoryManager(str(db))
    ids = [mm.remember("conversation", f"title{i}", f"content{i}") for i in range(3)]
    del mm  # simulate a fresh process
    mm2 = MemoryManager(str(db))
    assert len(mm2.search()) == 3
    assert {r["title"] for r in mm2.search()} == {"title0", "title1", "title2"}
    assert all(mm2.get(i) is not None for i in ids)


def test_init_does_not_erase_existing_memories(tmp_path):
    db = tmp_path / "keep.db"
    mm = MemoryManager(str(db))
    mm.remember("fact", "important", "do not lose me")
    # Re-initialize the same path several times.
    for _ in range(3):
        MemoryManager(str(db))
    assert len(MemoryManager(str(db)).search(kind="fact")) == 1


def test_repeated_connections_and_close(tmp_path):
    db = tmp_path / "repeat.db"
    mm = MemoryManager(str(db))
    for i in range(20):
        mm.remember("conversation", f"t{i}", f"c{i}")
    # Each _connection() must close its handle; no leak means many opens work.
    assert len(mm.search()) == 20


def test_multiple_connections_concurrently(tmp_path):
    db = tmp_path / "multi.db"
    a = MemoryManager(str(db))
    b = MemoryManager(str(db))
    a.remember("fact", "from_a", "x")
    b.remember("fact", "from_b", "y")
    # Both managers see both rows (WAL allows concurrent readers).
    assert len(a.search()) == 2
    assert len(b.search()) == 2


def test_write_committed_and_read_back(tmp_path):
    db = tmp_path / "commit.db"
    mm = MemoryManager(str(db))
    mid = mm.remember("preference", "color", "blue", tags=["ui"], metadata={"k": "v"})
    row = mm.get(mid)
    assert row["content"] == "blue"
    assert row["tags"] == ["ui"]
    assert row["metadata"] == {"k": "v"}
    # edit + delete round-trip
    assert mm.edit(mid, content="green") is True
    assert mm.get(mid)["content"] == "green"
    assert mm.delete(mid) is True
    assert mm.get(mid) is None


def test_operational_error_raises_memorydberror(tmp_path, monkeypatch):
    """A genuine open failure must surface as MemoryDBError, not crash raw."""
    db = tmp_path / "boom.db"
    mm = MemoryManager(str(db))

    def _boom(*a, **k):
        raise sqlite3.OperationalError("unable to open database file")

    monkeypatch.setattr(sqlite3, "connect", _boom)
    with pytest.raises(MemoryDBError):
        MemoryManager(str(db))


def test_real_db_opens_without_losing_records():
    """Open the REAL database read-only and confirm records are intact.

    This never writes, so it cannot alter user data. It is skipped if the
    database has not been created yet.
    """
    real = ROOT / "data" / "memory.db"
    if not real.exists():
        pytest.skip("real memory.db not present")
    uri = f"file:{real.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        count = conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        assert count >= 1
    finally:
        conn.close()


def test_delete_removes_metadata_no_orphans(tmp_path):
    """Deleting a memory must also remove its metadata row (no orphans).

    Regression guard: the schema declares ON DELETE CASCADE, but SQLite only
    enforces foreign keys when PRAGMA foreign_keys=ON is set per-connection.
    A prior bug left orphaned memory_metadata rows behind on delete().
    """
    db = tmp_path / "orphan_guard.db"
    mm = MemoryManager(str(db))
    mid = mm.remember("fact", "temp", "to be deleted", metadata={"x": 1})
    other = mm.remember("fact", "keep", "stays", metadata={"y": 2})

    orphans_before = _orphan_count(db)
    assert orphans_before == 0

    assert mm.delete(mid) is True

    orphans_after = _orphan_count(db)
    assert orphans_after == 0
    # The kept memory and its metadata are untouched.
    assert mm.get(other) is not None
    with sqlite3.connect(db) as conn:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM memory_metadata WHERE memory_id=?", (other,)
        ).fetchone()[0]
    assert remaining == 1


def _orphan_count(db_path) -> int:
    """Count memory_metadata rows whose memory_id has no matching memory."""
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM memory_metadata "
            "WHERE memory_id NOT IN (SELECT id FROM memory)"
        ).fetchone()[0]
    finally:
        conn.close()
