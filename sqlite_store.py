from __future__ import annotations

import json
import logging
import math
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from constants import MEMORY_ROOT

LOGGER = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS memories (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL,
    body         TEXT NOT NULL,
    repo         TEXT,
    source_path  TEXT,
    source_kind  TEXT,
    category     TEXT,
    module       TEXT,
    priority     TEXT DEFAULT 'normal',
    fingerprint  TEXT,
    upsert_key   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    token_count  INTEGER,
    tags         TEXT
);

CREATE INDEX IF NOT EXISTS idx_memories_project ON memories(project_id);
CREATE INDEX IF NOT EXISTS idx_memories_repo ON memories(repo);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_fingerprint ON memories(fingerprint);
CREATE INDEX IF NOT EXISTS idx_memories_upsert_key ON memories(upsert_key);
CREATE INDEX IF NOT EXISTS idx_memories_updated_at ON memories(updated_at);

CREATE TABLE IF NOT EXISTS memory_tags (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    tag       TEXT NOT NULL,
    PRIMARY KEY (memory_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_memory_tags_tag ON memory_tags(tag);

CREATE TABLE IF NOT EXISTS access_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id   TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    accessed_at TEXT NOT NULL,
    query_hash  TEXT,
    rank_position INTEGER
);

CREATE INDEX IF NOT EXISTS idx_access_log_memory ON access_log(memory_id);
CREATE INDEX IF NOT EXISTS idx_access_log_accessed ON access_log(accessed_at);

CREATE TABLE IF NOT EXISTS memory_versions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id   TEXT NOT NULL,
    body        TEXT NOT NULL,
    metadata    TEXT NOT NULL,
    version     INTEGER NOT NULL,
    changed_at  TEXT NOT NULL,
    change_source TEXT
);

CREATE INDEX IF NOT EXISTS idx_versions_memory ON memory_versions(memory_id);

CREATE TABLE IF NOT EXISTS entities (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL,
    project_id TEXT NOT NULL,
    UNIQUE(name, kind, project_id)
);

CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(name);
CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);

CREATE TABLE IF NOT EXISTS memory_entities (
    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    confidence REAL DEFAULT 1.0,
    PRIMARY KEY (memory_id, entity_id)
);

CREATE TABLE IF NOT EXISTS relations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id    TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    target_id    TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
    relation     TEXT NOT NULL,
    confidence   REAL DEFAULT 1.0,
    created_at   TEXT NOT NULL,
    created_by   TEXT DEFAULT 'system'
);

CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id);
CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id);
CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(relation);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    body, repo, source_path, category, module, tags,
    content='memories', content_rowid='rowid'
);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_memory_dict(row: tuple, tags: list[str]) -> dict[str, Any]:
    return {
        "id": row[0],
        "project_id": row[1],
        "body": row[2],
        "metadata": {
            "repo": row[3],
            "source_path": row[4],
            "source_kind": row[5],
            "category": row[6],
            "module": row[7],
            "priority": row[8],
            "fingerprint": row[9],
            "upsert_key": row[10],
            "tags": tags,
        },
        "created_at": row[11],
        "updated_at": row[12],
        "token_count": row[13],
    }


class MetadataStore:
    def __init__(self, project_id: str, db_dir: str | None = None) -> None:
        self.project_id = project_id
        root = Path(MEMORY_ROOT).expanduser()
        base = root / project_id if db_dir is None else Path(db_dir).expanduser()
        base.mkdir(parents=True, exist_ok=True)
        self._db_path = base / "metadata.db"
        self._local = threading.local()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self._db_path))
            self._local.conn.execute("PRAGMA journal_mode=WAL")
            self._local.conn.execute("PRAGMA foreign_keys=ON")
        return self._local.conn

    def _init_schema(self) -> None:
        conn = self._get_conn()
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None

    def upsert_memory(
        self,
        memory_id: str,
        body: str,
        metadata: dict[str, Any],
        *,
        created_at: str | None = None,
    ) -> None:
        now = _utc_now()
        created = created_at or now
        token_count = int(math.ceil(len(body) / 4.0))
        tags = metadata.get("tags") or []
        tags_str = " ".join(str(t) for t in tags) if tags else ""

        conn = self._get_conn()
        cur = conn.execute(
            "SELECT rowid FROM memories WHERE id = ?",
            (memory_id,),
        )
        existing = cur.fetchone()
        if existing:
            conn.execute(
                "DELETE FROM memories_fts WHERE rowid = ?",
                (existing[0],),
            )

        conn.execute(
            """
            INSERT OR REPLACE INTO memories (
                id, project_id, body, repo, source_path, source_kind,
                category, module, priority, fingerprint, upsert_key,
                created_at, updated_at, token_count, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                metadata.get("project_id") or self.project_id,
                body,
                metadata.get("repo"),
                metadata.get("source_path"),
                metadata.get("source_kind"),
                metadata.get("category"),
                metadata.get("module"),
                metadata.get("priority", "normal"),
                metadata.get("fingerprint"),
                metadata.get("upsert_key"),
                created,
                now,
                token_count,
                tags_str,
            ),
        )

        cur = conn.execute("SELECT rowid FROM memories WHERE id = ?", (memory_id,))
        rowid = cur.fetchone()[0]
        conn.execute(
            """
            INSERT INTO memories_fts(rowid, body, repo, source_path, category, module, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rowid,
                body,
                metadata.get("repo") or "",
                metadata.get("source_path") or "",
                metadata.get("category") or "",
                metadata.get("module") or "",
                tags_str,
            ),
        )

        conn.execute("DELETE FROM memory_tags WHERE memory_id = ?", (memory_id,))
        if tags:
            conn.executemany(
                "INSERT INTO memory_tags (memory_id, tag) VALUES (?, ?)",
                [(memory_id, t) for t in tags],
            )
        conn.commit()

    def delete_memory(self, memory_id: str) -> None:
        conn = self._get_conn()
        cur = conn.execute("SELECT rowid FROM memories WHERE id = ?", (memory_id,))
        row = cur.fetchone()
        if row:
            conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (row[0],))
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT id, project_id, body, repo, source_path, source_kind,
                   category, module, priority, fingerprint, upsert_key,
                   created_at, updated_at, token_count
            FROM memories WHERE id = ?
            """,
            (memory_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur = conn.execute(
            "SELECT tag FROM memory_tags WHERE memory_id = ? ORDER BY tag",
            (memory_id,),
        )
        tags = [r[0] for r in cur.fetchall()]
        return _row_to_memory_dict(row, tags)

    def list_memories(
        self,
        *,
        repo: str | None = None,
        category: str | None = None,
        tag: str | None = None,
        path_prefix: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = ["project_id = ?"]
        params: list[Any] = [self.project_id]
        if repo is not None:
            conditions.append("repo = ?")
            params.append(repo)
        if category is not None:
            conditions.append("category = ?")
            params.append(category)
        if tag is not None:
            conditions.append(
                "id IN (SELECT memory_id FROM memory_tags WHERE tag = ?)"
            )
            params.append(tag)
        if path_prefix is not None:
            conditions.append("source_path LIKE ?")
            params.append(f"{path_prefix}%")

        where = " AND ".join(conditions)
        valid_sort = {"updated_at", "created_at", "category", "repo"}
        col = sort_by if sort_by in valid_sort else "updated_at"
        order = "DESC" if sort_order.lower() == "desc" else "ASC"

        conn = self._get_conn()
        count_cur = conn.execute(
            f"SELECT COUNT(*) FROM memories WHERE {where}",
            params,
        )
        total = count_cur.fetchone()[0]

        list_params = params + [limit, offset]
        cur = conn.execute(
            f"""
            SELECT id, project_id, body, repo, source_path, source_kind,
                   category, module, priority, fingerprint, upsert_key,
                   created_at, updated_at, token_count
            FROM memories WHERE {where}
            ORDER BY {col} {order}
            LIMIT ? OFFSET ?
            """,
            list_params,
        )
        rows = cur.fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            mid = row[0]
            tag_cur = conn.execute(
                "SELECT tag FROM memory_tags WHERE memory_id = ? ORDER BY tag",
                (mid,),
            )
            tags = [r[0] for r in tag_cur.fetchall()]
            items.append(_row_to_memory_dict(row, tags))
        return items, total

    def find_by_upsert_key(self, upsert_key: str) -> list[str]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT id FROM memories WHERE project_id = ? AND upsert_key = ?",
            (self.project_id, upsert_key),
        )
        return [r[0] for r in cur.fetchall()]

    def find_by_fingerprint(self, fingerprint: str) -> list[str]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT id FROM memories WHERE project_id = ? AND fingerprint = ?",
            (self.project_id, fingerprint),
        )
        return [r[0] for r in cur.fetchall()]

    def log_access(
        self,
        memory_id: str,
        query_hash: str | None = None,
        rank_position: int | None = None,
    ) -> None:
        now = _utc_now()
        self._get_conn().execute(
            """
            INSERT INTO access_log (memory_id, accessed_at, query_hash, rank_position)
            VALUES (?, ?, ?, ?)
            """,
            (memory_id, now, query_hash, rank_position),
        )
        self._get_conn().commit()

    def access_count(self, memory_id: str, days: int = 30) -> int:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=days)
        ).isoformat()
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT COUNT(*) FROM access_log
            WHERE memory_id = ? AND accessed_at >= ?
            """,
            (memory_id, cutoff),
        )
        return cur.fetchone()[0]

    def bulk_log_access(
        self,
        entries: list[tuple[str, str | None, int | None]],
    ) -> None:
        now = _utc_now()
        rows = [(mid, now, qh, rp) for mid, qh, rp in entries]
        self._get_conn().executemany(
            """
            INSERT INTO access_log (memory_id, accessed_at, query_hash, rank_position)
            VALUES (?, ?, ?, ?)
            """,
            rows,
        )
        self._get_conn().commit()

    def fts_search(self, query: str, limit: int = 50) -> list[tuple[str, float]]:
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT m.id, bm25(memories_fts) AS rank
            FROM memories_fts
            JOIN memories m ON m.rowid = memories_fts.rowid
            WHERE memories_fts MATCH ? AND m.project_id = ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, self.project_id, limit),
        )
        return [(r[0], float(r[1])) for r in cur.fetchall()]

    def save_version(
        self,
        memory_id: str,
        body: str,
        metadata_json: str,
        change_source: str = "update",
    ) -> None:
        now = _utc_now()
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM memory_versions WHERE memory_id = ?",
            (memory_id,),
        )
        version = cur.fetchone()[0] + 1
        conn.execute(
            """
            INSERT INTO memory_versions (memory_id, body, metadata, version, changed_at, change_source)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (memory_id, body, metadata_json, version, now, change_source),
        )
        conn.commit()

    def get_versions(self, memory_id: str) -> list[dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT id, memory_id, body, metadata, version, changed_at, change_source
            FROM memory_versions WHERE memory_id = ?
            ORDER BY version DESC
            """,
            (memory_id,),
        )
        return [
            {
                "id": r[0],
                "memory_id": r[1],
                "body": r[2],
                "metadata": r[3],
                "version": r[4],
                "changed_at": r[5],
                "change_source": r[6],
            }
            for r in cur.fetchall()
        ]

    def upsert_entity(self, name: str, kind: str, project_id: str) -> int:
        conn = self._get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO entities (name, kind, project_id) VALUES (?, ?, ?)",
            (name, kind, project_id),
        )
        cur = conn.execute(
            "SELECT id FROM entities WHERE name = ? AND kind = ? AND project_id = ?",
            (name, kind, project_id),
        )
        conn.commit()
        return cur.fetchone()[0]

    def link_memory_entity(
        self,
        memory_id: str,
        entity_id: int,
        confidence: float = 1.0,
    ) -> None:
        self._get_conn().execute(
            """
            INSERT OR REPLACE INTO memory_entities (memory_id, entity_id, confidence)
            VALUES (?, ?, ?)
            """,
            (memory_id, entity_id, confidence),
        )
        self._get_conn().commit()

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation: str,
        confidence: float = 1.0,
        created_by: str = "system",
    ) -> None:
        now = _utc_now()
        self._get_conn().execute(
            """
            INSERT INTO relations (source_id, target_id, relation, confidence, created_at, created_by)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (source_id, target_id, relation, confidence, now, created_by),
        )
        self._get_conn().commit()

    def get_related(
        self,
        memory_id: str,
        max_hops: int = 1,
        relation_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        conn = self._get_conn()
        visited: set[str] = {memory_id}
        frontier: list[tuple[str, int, list[str]]] = [(memory_id, 0, [])]
        results: list[dict[str, Any]] = []

        while frontier:
            current, hop, path = frontier.pop(0)
            if hop >= max_hops:
                continue

            rel_filter = ""
            params: list[Any] = [current]
            if relation_types:
                placeholders = ",".join("?" * len(relation_types))
                rel_filter = f" AND relation IN ({placeholders})"
                params.extend(relation_types)

            cur = conn.execute(
                f"""
                SELECT target_id, relation FROM relations
                WHERE source_id = ?{rel_filter}
                """,
                params,
            )
            for target_id, rel in cur.fetchall():
                if target_id in visited:
                    continue
                visited.add(target_id)
                new_path = path + [rel]
                mem = self.get_memory(target_id)
                if mem:
                    results.append(
                        {
                            "memory": mem,
                            "path": new_path,
                            "hops": hop + 1,
                        }
                    )
                frontier.append((target_id, hop + 1, new_path))

            cur = conn.execute(
                f"""
                SELECT source_id, relation FROM relations
                WHERE target_id = ?{rel_filter}
                """,
                params,
            )
            for source_id, rel in cur.fetchall():
                if source_id in visited:
                    continue
                visited.add(source_id)
                new_path = path + [rel]
                mem = self.get_memory(source_id)
                if mem:
                    results.append(
                        {
                            "memory": mem,
                            "path": new_path,
                            "hops": hop + 1,
                        }
                    )
                frontier.append((source_id, hop + 1, new_path))

        return results

    def get_entities_for_memory(self, memory_id: str) -> list[dict[str, Any]]:
        conn = self._get_conn()
        cur = conn.execute(
            """
            SELECT e.id, e.name, e.kind, me.confidence
            FROM entities e
            JOIN memory_entities me ON me.entity_id = e.id
            WHERE me.memory_id = ?
            """,
            (memory_id,),
        )
        return [
            {"id": r[0], "name": r[1], "kind": r[2], "confidence": r[3]}
            for r in cur.fetchall()
        ]

    def find_memories_by_entity(
        self,
        entity_name: str,
        entity_kind: str | None = None,
    ) -> list[str]:
        conn = self._get_conn()
        if entity_kind is not None:
            cur = conn.execute(
                """
                SELECT me.memory_id FROM memory_entities me
                JOIN entities e ON e.id = me.entity_id
                WHERE e.name = ? AND e.kind = ? AND e.project_id = ?
                """,
                (entity_name, entity_kind, self.project_id),
            )
        else:
            cur = conn.execute(
                """
                SELECT me.memory_id FROM memory_entities me
                JOIN entities e ON e.id = me.entity_id
                WHERE e.name = ? AND e.project_id = ?
                """,
                (entity_name, self.project_id),
            )
        return [r[0] for r in cur.fetchall()]

    def get_stats(self) -> dict[str, Any]:
        conn = self._get_conn()
        cur = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(token_count), 0) FROM memories WHERE project_id = ?",
            (self.project_id,),
        )
        total, tokens = cur.fetchone()

        cur = conn.execute(
            "SELECT MIN(created_at), MAX(updated_at) FROM memories WHERE project_id = ?",
            (self.project_id,),
        )
        row = cur.fetchone()
        oldest, newest = row[0], row[1]

        cur = conn.execute(
            """
            SELECT fingerprint, COUNT(*) FROM memories
            WHERE project_id = ? AND fingerprint IS NOT NULL
            GROUP BY fingerprint HAVING COUNT(*) > 1
            """,
            (self.project_id,),
        )
        dup_fp = sum(c - 1 for _, c in cur.fetchall())

        cur = conn.execute(
            "SELECT category, COUNT(*) FROM memories WHERE project_id = ? GROUP BY category",
            (self.project_id,),
        )
        by_category = dict(cur.fetchall())

        cur = conn.execute(
            "SELECT repo, COUNT(*) FROM memories WHERE project_id = ? GROUP BY repo",
            (self.project_id,),
        )
        by_repo = dict(cur.fetchall())

        cur = conn.execute(
            "SELECT source_kind, COUNT(*) FROM memories WHERE project_id = ? GROUP BY source_kind",
            (self.project_id,),
        )
        by_source_kind = dict(cur.fetchall())

        cur = conn.execute(
            "SELECT priority, COUNT(*) FROM memories WHERE project_id = ? GROUP BY priority",
            (self.project_id,),
        )
        by_priority = dict(cur.fetchall())

        return {
            "total_count": total,
            "estimated_tokens": tokens,
            "oldest_created_at": oldest,
            "newest_updated_at": newest,
            "duplicate_fingerprint_count": dup_fp,
            "by_category": by_category,
            "by_repo": by_repo,
            "by_source_kind": by_source_kind,
            "by_priority": by_priority,
        }

    def migrate_from_items(self, items: list[Any], project_id: str) -> None:
        now = _utc_now()
        mem_rows: list[tuple] = []
        tag_rows: list[tuple[str, str]] = []
        fts_data_by_id: dict[str, tuple] = {}

        for item in items:
            mid = item.id
            if not mid:
                continue
            body = item.memory
            md = item.metadata.as_dict()
            created = md.get("updated_at") or now
            token_count = int(math.ceil(len(body) / 4.0))
            tags = md.get("tags") or []
            tags_str = " ".join(str(t) for t in tags) if tags else ""

            mem_rows.append(
                (
                    mid,
                    md.get("project_id") or project_id,
                    body,
                    md.get("repo"),
                    md.get("source_path"),
                    md.get("source_kind"),
                    md.get("category"),
                    md.get("module"),
                    md.get("priority", "normal"),
                    md.get("fingerprint"),
                    md.get("upsert_key"),
                    created,
                    now,
                    token_count,
                    tags_str,
                )
            )
            for t in tags:
                tag_rows.append((mid, t))
            fts_data_by_id[mid] = (
                body,
                md.get("repo") or "",
                md.get("source_path") or "",
                md.get("category") or "",
                md.get("module") or "",
                tags_str,
            )

        if not mem_rows:
            return

        conn = self._get_conn()
        ids = [r[0] for r in mem_rows]
        cur = conn.execute(
            f"SELECT id, rowid FROM memories WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
        for row in cur.fetchall():
            conn.execute("DELETE FROM memories_fts WHERE rowid = ?", (row[1],))

        placeholders = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM memory_tags WHERE memory_id IN ({placeholders})", ids)

        conn.executemany(
            """
            INSERT OR REPLACE INTO memories (
                id, project_id, body, repo, source_path, source_kind,
                category, module, priority, fingerprint, upsert_key,
                created_at, updated_at, token_count, tags
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            mem_rows,
        )

        cur = conn.execute(
            f"SELECT id, rowid FROM memories WHERE id IN ({','.join('?' * len(ids))})",
            ids,
        )
        id_to_rowid = {row[0]: row[1] for row in cur.fetchall()}
        for mid in ids:
            if mid in id_to_rowid and mid in fts_data_by_id:
                rowid = id_to_rowid[mid]
                fd = fts_data_by_id[mid]
                conn.execute(
                    """
                    INSERT INTO memories_fts(rowid, body, repo, source_path, category, module, tags)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (rowid, fd[0], fd[1], fd[2], fd[3], fd[4], fd[5]),
                )

        if tag_rows:
            conn.executemany(
                "INSERT INTO memory_tags (memory_id, tag) VALUES (?, ?)",
                tag_rows,
            )
        conn.commit()
