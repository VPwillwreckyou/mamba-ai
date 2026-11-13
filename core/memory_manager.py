from __future__ import annotations

import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)


class MemoryDBError(RuntimeError):
    """Raised when the memory database cannot be opened or initialized.

    Carries a human-readable explanation so startup surfaces a clear cause
    instead of a raw, cryptic ``sqlite3.OperationalError``. This is a *loud*
    failure: memory is user data, so a broken database must never be silently
    disabled or replaced with an empty one.
    """


class MemoryManager:
    """Long-term memory for projects, preferences, workflows, and recurring items.

    Memory is stored in a local SQLite database so it persists across sessions and
    can be searched, edited, and deleted. Memory is treated as user data, not as
    security policy. It must never override the configured permission rules.

    Connection handling is deliberately defensive: the parent directory is
    created on demand, connections carry a generous busy timeout so a transient
    lock from another process is waited out (not crashed on), every connection
    is closed deterministically, and WAL mode degrades safely to the rollback
    journal when the platform forbids it. None of these paths ever delete the
    database file, its WAL/SHM sidecars, or existing rows.
    """

    # Seconds to wait for a busy/locked database before giving up. This turns a
    # momentary lock (e.g. a slow writer) into a wait instead of a crash.
    _CONNECT_TIMEOUT = 30.0
    _BUSY_TIMEOUT_MS = 30000

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._journal_mode = "unknown"
        self._ensure_parent_dir()
        self._ensure_tables()

    # ------------------------------------------------------------ filesystem
    def _ensure_parent_dir(self) -> None:
        """Create the database's parent directory if it is missing.

        Safe to call repeatedly (``exist_ok=True``); never touches the database
        file itself. A filesystem failure here is wrapped in MemoryDBError so
        the startup surface is always a clear, actionable message.
        """
        parent = os.path.dirname(os.path.abspath(self.db_path))
        if not parent:
            return
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as exc:
            raise MemoryDBError(
                f"Cannot create memory database directory {parent!r}: {exc}. "
                f"Check permissions, disk space, and that no component of the "
                f"path is an existing file."
            ) from exc

    # ---------------------------------------------------------- connections
    def _connect(self) -> sqlite3.Connection:
        """Open a tuned connection. Raises MemoryDBError on a genuine failure."""
        self._ensure_parent_dir()
        try:
            conn = sqlite3.connect(self.db_path, timeout=self._CONNECT_TIMEOUT)
        except sqlite3.Error as exc:
            raise MemoryDBError(
                f"Cannot open memory database at {self.db_path!r}: {exc}"
            ) from exc
        conn.row_factory = sqlite3.Row
        # SQLite ignores FOREIGN KEY constraints (including the schema's
        # ON DELETE CASCADE) unless this pragma is enabled on EVERY connection.
        # Without it, deleting a memory leaves its metadata row behind as an
        # orphan. It is a no-op inside a transaction, so set it right after
        # opening, before any statement runs.
        try:
            conn.execute("PRAGMA foreign_keys=ON")
        except sqlite3.Error:
            pass  # Best-effort; explicit cleanup in delete() is the backstop.
        try:
            conn.execute(f"PRAGMA busy_timeout={self._BUSY_TIMEOUT_MS}")
        except sqlite3.Error:
            pass  # busy_timeout is best-effort; not fatal.
        self._configure_journal_mode(conn)
        return conn

    def _configure_journal_mode(self, conn: sqlite3.Connection) -> None:
        """Enable WAL for concurrent reads, degrading safely if unavailable.

        WAL lets readers proceed while a writer holds the lock. On some network
        filesystems, or when another live connection holds an exclusive lock,
        enabling WAL can fail. In that case we *distinguish* a transient lock
        from a genuine I/O error, log a clear diagnostic, and fall back to the
        default rollback journal when it is a real I/O problem. We never delete
        files or wipe data to force WAL.
        """
        try:
            row = conn.execute("PRAGMA journal_mode=WAL").fetchone()
            self._journal_mode = str(row[0]).lower() if row else "unknown"
        except sqlite3.OperationalError as exc:
            message = str(exc).lower()
            if "locked" in message or "busy" in message:
                # Transient contention with another live connection. Not
                # corruption: keep whatever mode is active and let busy_timeout
                # arbitrate writes. Reads continue to work.
                self._journal_mode = "wal-locked"
                logger.warning(
                    "Memory DB WAL deferred: database is locked by another "
                    "connection (%s). Reads still work; writes wait up to %ds.",
                    exc, int(self._CONNECT_TIMEOUT),
                )
            else:
                # Genuine I/O problem (network FS, permissions, disk). WAL is
                # unsupported here; fall back to the default rollback journal,
                # which needs no extra sidecar files and preserves all data.
                logger.warning(
                    "Memory DB WAL unavailable (%s); falling back to the "
                    "default rollback journal. Existing data is preserved.",
                    exc,
                )
                try:
                    conn.execute("PRAGMA journal_mode=DELETE")
                    self._journal_mode = "delete"
                except sqlite3.Error:
                    self._journal_mode = "unset"

    @contextmanager
    def _connection(self):
        """Yield a connection that commits on success, rolls back on error, and
        is *always* closed.

        Note: ``with sqlite3.connect(...)`` only manages the transaction -- it
        never closes the connection. Leaking handles (and their Windows
        shared-memory locks) was a real contributor to lock build-up, so every
        access path funnels through here to guarantee ``close()``.
        """
        conn = self._connect()
        try:
            with conn:  # commit on success, rollback on exception
                yield conn
        finally:
            conn.close()

    def _ensure_tables(self) -> None:
        """Create tables if absent. Never drops or recreates existing ones."""
        try:
            with self._connection() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory (
                        id TEXT PRIMARY KEY,
                        kind TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        tags TEXT NOT NULL,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS memory_metadata (
                        memory_id TEXT PRIMARY KEY,
                        metadata TEXT NOT NULL,
                        FOREIGN KEY (memory_id) REFERENCES memory(id) ON DELETE CASCADE
                    )
                    """
                )
        except sqlite3.Error as exc:
            raise MemoryDBError(
                f"Failed to initialize memory database at {self.db_path!r}: "
                f"{exc}. The database file was left untouched; if the problem "
                f"persists, ensure no other process holds it open."
            ) from exc

    def get(self, memory_id: str) -> dict[str, Any] | None:
        with self._connection() as conn:
            row = conn.execute("SELECT * FROM memory WHERE id=?", (memory_id,)).fetchone()
            if not row:
                return None
            meta = self._get_metadata(conn, memory_id)
            return self._row_to_dict(row, meta)

    def edit(self, memory_id: str, *, title: str | None = None, content: str | None = None, tags: list[str] | None = None, metadata: dict[str, Any] | None = None) -> bool:
        with self._connection() as conn:
            row = conn.execute("SELECT id FROM memory WHERE id=?", (memory_id,)).fetchone()
            if not row:
                return False
            now = _now_epoch()
            updates: list[str] = []
            values: list[Any] = []
            if title is not None:
                updates.append("title=?")
                values.append(title)
            if content is not None:
                updates.append("content=?")
                values.append(content)
            if tags is not None:
                updates.append("tags=?")
                values.append(",".join(tags))
            if updates:
                updates.append("updated_at=?")
                values.append(now)
                values.append(memory_id)
                conn.execute(f"UPDATE memory SET {', '.join(updates)} WHERE id=?", values)
            if metadata is not None:
                conn.execute(
                    "INSERT OR REPLACE INTO memory_metadata (memory_id, metadata) VALUES (?,?)",
                    (memory_id, repr(metadata)),
                )
            return True

    def delete(self, memory_id: str) -> bool:
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM memory WHERE id=?", (memory_id,))
            deleted = cursor.rowcount > 0
            if deleted:
                # Belt-and-suspenders: the schema declares ON DELETE CASCADE and
                # _connect() enables PRAGMA foreign_keys=ON, but we delete the
                # metadata row explicitly too so a memory can never leave an
                # orphan even if foreign-key enforcement is off on a connection.
                conn.execute(
                    "DELETE FROM memory_metadata WHERE memory_id=?", (memory_id,)
                )
            return deleted

    def clear(self) -> None:
        with self._connection() as conn:
            conn.execute("DELETE FROM memory")
            conn.execute("DELETE FROM memory_metadata")

    def search(self, *, kind: str | None = None, query: str | None = None, tags: list[str] | None = None) -> list[dict[str, Any]]:
        """Search memory by kind, free-text query, and/or tags."""
        results: list[dict[str, Any]] = []
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM memory").fetchall()
            for row in rows:
                if kind is not None and row["kind"] != kind:
                    continue
                if query is not None:
                    haystack = f"{row['title']} {row['content']} {row['tags']}"
                    if query.lower() not in haystack.lower():
                        continue
                if tags:
                    row_tags = set(row["tags"].split(",")) if row["tags"] else set()
                    if not set(tags).issubset(row_tags):
                        continue
                meta = self._get_metadata(conn, row["id"])
                results.append(self._row_to_dict(row, meta))
        return results

    def _get_metadata(self, conn: sqlite3.Connection, memory_id: str) -> dict[str, Any]:
        row = conn.execute("SELECT metadata FROM memory_metadata WHERE memory_id=?", (memory_id,)).fetchone()
        if not row:
            return {}
        try:
            return eval(row["metadata"])
        except Exception:
            return {}

    def _row_to_dict(self, row: sqlite3.Row, metadata: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "title": row["title"],
            "content": row["content"],
            "tags": [t for t in row["tags"].split(",") if t],
            "metadata": metadata,
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def _now_epoch() -> float:
    import time

    return time.time()


# Add the remember method to the MemoryManager class
def remember(
    self,
    kind: str,
    title: str,
    content: str,
    *,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    memory_id: str | None = None,
) -> str:
    """Store a memory entry and return its ID."""
    if memory_id is None:
        import uuid

        memory_id = str(uuid.uuid4())
    tags_value = ",".join(tags or [])
    metadata_value = repr(metadata or {})
    now = _now_epoch()
    with self._connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO memory (id, kind, title, content, tags, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (memory_id, kind, title, content, tags_value, now, now),
        )
        conn.execute(
            "INSERT OR REPLACE INTO memory_metadata (memory_id, metadata) VALUES (?,?)",
            (memory_id, metadata_value),
        )
    return memory_id


MemoryManager.remember = remember
