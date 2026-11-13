"""Regression tests for core.memory_manager.MemoryManager.

Covers the connection-safety guarantees that matter at startup: parent-dir
creation, WAL setup with a safe fallback, deterministic connection close,
write/read-back, persistence across reopen, multi-connection correctness, and
clear diagnostics on operational errors. All tests use an isolated temp DB;
the real data/memory.db is never touched.
"""
from __future__ import annotations

import pytest

from core.memory_manager import MemoryDBError, MemoryManager


def test_parent_directory_created_when_missing(tmp_path):
    db = tmp_path / "nested" / "deeper" / "memory.db"
    MemoryManager(str(db))
    assert db.parent.is_dir()
    assert db.exists()


def test_new_database_initializes_tables(tmp_path):
    db = tmp_path / "memory.db"
    mm = MemoryManager(str(db))
    with mm._connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert {"memory", "memory_metadata"} <= tables


def test_write_commits_and_reads_back(tmp_path):
    mm = MemoryManager(str(tmp_path / "memory.db"))
    mid = mm.remember("test", "greeting", "hello world",
                      tags=["a", "b"], metadata={"src": "unit"})
    got = mm.get(mid)
    assert got is not None
    assert got["content"] == "hello world"
    assert got["tags"] == ["a", "b"]
    assert mm.search(query="hello")[0]["id"] == mid


def test_records_and_schema_persist_across_reopen(tmp_path):
    db = tmp_path / "memory.db"
    mm = MemoryManager(str(db))
    mid = mm.remember("fact", "persisted", "still here")
    mm2 = MemoryManager(str(db))  # reopen same file
    assert mm2.get(mid) is not None
    with mm2._connection() as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
    assert {"memory", "memory_metadata"} <= tables


def test_journal_mode_reported(tmp_path):
    mm = MemoryManager(str(tmp_path / "memory.db"))
    assert mm._journal_mode in ("wal", "delete", "unset", "wal-locked")


def test_repeated_connect_close_no_error(tmp_path):
    mm = MemoryManager(str(tmp_path / "memory.db"))
    for _ in range(50):
        with mm._connection() as conn:
            conn.execute("SELECT COUNT(*) FROM memory").fetchone()


def test_multiple_connections_behave_correctly(tmp_path):
    mm = MemoryManager(str(tmp_path / "memory.db"))
    mm.remember("seed", "seed", "body")
    c1 = mm._connect()
    c2 = mm._connect()
    try:
        c1.execute("BEGIN IMMEDIATE")
        c1.execute(
            "INSERT INTO memory (id,kind,title,content,tags,created_at,updated_at) "
            "VALUES ('concurrent','t','title','body','',0,0)"
        )
        c2.execute("SELECT COUNT(*) FROM memory").fetchone()  # reader not blocked
        c1.execute("COMMIT")
    finally:
        c1.close()
        c2.close()
    assert mm.search(query="title") != []


def test_operational_error_raises_memorydberror(tmp_path):
    # A path whose parent component is a FILE cannot be created -> clear error.
    blocker = tmp_path / "afile"
    blocker.write_text("x", encoding="utf-8")
    bad = blocker / "sub" / "memory.db"
    with pytest.raises(MemoryDBError):
        MemoryManager(str(bad))


def test_open_failure_is_reported_not_silenced(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise MemoryDBError("simulated open failure")

    monkeypatch.setattr(MemoryManager, "_ensure_tables", boom)
    with pytest.raises(MemoryDBError):
        MemoryManager(str(tmp_path / "memory.db"))
