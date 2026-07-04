"""Persistence layer.

Two stores live side by side under the index dir:

  * manifest.sqlite  — a plain stdlib-sqlite table tracking each note's
    content hash + mtime, used to detect what changed since last run.
    (Plain tables only; no loadable extensions, so it works everywhere.)

  * lancedb/         — the LanceDB vector store holding one row per chunk
    (path, breadcrumb, chunk_index, text, vector).

Keeping change-tracking in sqlite and vectors in LanceDB means each store
does the one thing it's good at, and neither needs a running server.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import lancedb

CHUNK_TABLE = "chunks"


@dataclass
class SearchHit:
    path: str
    breadcrumb: str
    text: str
    score: float


class Store:
    def __init__(self, index_dir: Path):
        index_dir.mkdir(parents=True, exist_ok=True)
        self._db = lancedb.connect(str(index_dir / "lancedb"))
        self._sql = sqlite3.connect(index_dir / "manifest.sqlite")
        self._sql.execute(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                hash TEXT NOT NULL,
                mtime REAL NOT NULL,
                chunk_count INTEGER NOT NULL
            )
            """
        )
        # Small key/value table for index-wide metadata, e.g. which embedding
        # model produced the stored vectors (used to detect an incompatible swap).
        self._sql.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._sql.commit()

    def close(self) -> None:
        self._sql.close()

    # -- metadata ---------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self._sql.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._sql.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._sql.commit()

    def reset_index(self) -> None:
        """Wipe all vectors and change-tracking, forcing a full re-embed.

        Used when the embedding model changes: the old vectors live in a
        different, incompatible space, so they must all be rebuilt.
        """
        if CHUNK_TABLE in self._db.table_names():
            self._db.drop_table(CHUNK_TABLE)
        self._sql.execute("DELETE FROM files")
        self._sql.commit()

    # -- manifest (change detection) -------------------------------------

    def known_hashes(self) -> dict[str, str]:
        """Return {relative_path: hash} for everything indexed so far."""
        rows = self._sql.execute("SELECT path, hash FROM files").fetchall()
        return {path: h for path, h in rows}

    def record_file(self, path: str, file_hash: str, mtime: float, chunk_count: int) -> None:
        self._sql.execute(
            "INSERT INTO files (path, hash, mtime, chunk_count) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(path) DO UPDATE SET hash=excluded.hash, "
            "mtime=excluded.mtime, chunk_count=excluded.chunk_count",
            (path, file_hash, mtime, chunk_count),
        )
        self._sql.commit()

    def forget_file(self, path: str) -> None:
        self._sql.execute("DELETE FROM files WHERE path = ?", (path,))
        self._sql.commit()

    def stats(self) -> tuple[int, int]:
        """(file_count, chunk_count) currently indexed."""
        row = self._sql.execute(
            "SELECT COUNT(*), COALESCE(SUM(chunk_count), 0) FROM files"
        ).fetchone()
        return int(row[0]), int(row[1])

    # -- vectors ----------------------------------------------------------

    def _table(self):
        if CHUNK_TABLE in self._db.table_names():
            return self._db.open_table(CHUNK_TABLE)
        return None

    def delete_chunks(self, path: str) -> None:
        tbl = self._table()
        if tbl is not None:
            tbl.delete(f"path = '{_escape(path)}'")

    def add_chunks(self, rows: list[dict]) -> None:
        """Add chunk rows. Each row: path, breadcrumb, chunk_index, text, vector."""
        if not rows:
            return
        if CHUNK_TABLE in self._db.table_names():
            self._db.open_table(CHUNK_TABLE).add(rows)
        else:
            self._db.create_table(CHUNK_TABLE, data=rows)

    def search(self, query_vector: list[float], top_k: int) -> list[SearchHit]:
        tbl = self._table()
        if tbl is None:
            return []
        results = tbl.search(query_vector).limit(top_k).to_list()
        hits: list[SearchHit] = []
        for r in results:
            # LanceDB returns L2 distance in `_distance`; smaller = closer.
            distance = float(r.get("_distance", 0.0))
            hits.append(
                SearchHit(
                    path=r["path"],
                    breadcrumb=r.get("breadcrumb", ""),
                    text=r["text"],
                    score=1.0 / (1.0 + distance),
                )
            )
        return hits


def _escape(value: str) -> str:
    """Escape single quotes for a LanceDB SQL filter literal."""
    return value.replace("'", "''")
