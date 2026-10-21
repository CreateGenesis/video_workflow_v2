"""SQLite state. Media bytes stay in object storage."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                object_key TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS links (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                target_id TEXT,
                status TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS devices (
                code TEXT PRIMARY KEY,
                token TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        self.conn.commit()
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(devices)").fetchall()}
        if "seen_at" not in columns:
            self.conn.execute("ALTER TABLE devices ADD COLUMN seen_at TEXT")
            self.conn.commit()

    def add_entity(self, type_name: str, data: dict, object_key: str | None = None) -> dict:
        item = {
            "id": new_id(type_name.lower()),
            "type": type_name,
            "data": data,
            "object_key": object_key,
            "created_at": now(),
        }
        with _LOCK:
            self.conn.execute(
                "INSERT INTO entities VALUES (?,?,?,?,?)",
                (item["id"], type_name, json.dumps(data, ensure_ascii=False), object_key, item["created_at"]),
            )
            self.conn.commit()
        return item

    def update_entity(self, entity_id: str, data: dict | None = None, object_key: str | None = None) -> dict:
        current = self.get_entity(entity_id)
        if data is not None:
            current["data"] = data
        if object_key is not None:
            current["object_key"] = object_key
        with _LOCK:
            self.conn.execute(
                "UPDATE entities SET data=?, object_key=? WHERE id=?",
                (json.dumps(current["data"], ensure_ascii=False), current["object_key"], entity_id),
            )
            self.conn.commit()
        return current

    def get_entity(self, entity_id: str) -> dict:
        row = self.conn.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone()
        if not row:
            raise KeyError(entity_id)
        return self._entity(row)

    def list_entities(self, type_name: str | None = None) -> list[dict]:
        if type_name:
            rows = self.conn.execute("SELECT * FROM entities WHERE type=? ORDER BY created_at", (type_name,)).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM entities ORDER BY created_at").fetchall()
        return [self._entity(row) for row in rows]

    def _entity(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "type": row["type"],
            "data": json.loads(row["data"]),
            "object_key": row["object_key"],
            "created_at": row["created_at"],
        }

    def add_link(self, name: str, source_id: str, target_id: str, note: str = "") -> dict:
        item = {
            "id": new_id("link"),
            "name": name,
            "source_id": source_id,
            "target_id": target_id,
            "note": note,
            "created_at": now(),
        }
        with _LOCK:
            self.conn.execute(
                "INSERT INTO links VALUES (?,?,?,?,?,?)",
                (item["id"], name, source_id, target_id, note, item["created_at"]),
            )
            self.conn.commit()
        return item

    def links(self, source_id: str | None = None, name: str | None = None) -> list[dict]:
        query = "SELECT * FROM links WHERE 1=1"
        args: list[str] = []
        if source_id:
            query += " AND source_id=?"
            args.append(source_id)
        if name:
            query += " AND name=?"
            args.append(name)
        rows = self.conn.execute(query, args).fetchall()
        return [dict(row) for row in rows]

    def all_links(self) -> list[dict]:
        return [dict(row) for row in self.conn.execute("SELECT * FROM links ORDER BY created_at").fetchall()]

    def add_job(self, kind: str, target_id: str | None, status: str, detail: dict) -> dict:
        item = {
            "id": new_id("job"),
            "kind": kind,
            "target_id": target_id,
            "status": status,
            "detail": detail,
            "created_at": now(),
            "updated_at": now(),
        }
        with _LOCK:
            self.conn.execute(
                "INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                (item["id"], kind, target_id, status, json.dumps(detail, ensure_ascii=False), item["created_at"], item["updated_at"]),
            )
            self.conn.commit()
        return item

    def update_job(self, job_id: str, status: str, detail: dict | None = None) -> dict:
        current = self.get_job(job_id)
        if detail is not None:
            current["detail"] = detail
        current["status"] = status
        current["updated_at"] = now()
        with _LOCK:
            self.conn.execute(
                "UPDATE jobs SET status=?, detail=?, updated_at=? WHERE id=?",
                (status, json.dumps(current["detail"], ensure_ascii=False), current["updated_at"], job_id),
            )
            self.conn.commit()
        return current

    def get_job(self, job_id: str) -> dict:
        with _LOCK:
            row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return self._job(row)

    def list_jobs(self) -> list[dict]:
        return [self._job(row) for row in self.conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()]

    def claim_generate(self, target_id: str, detail: dict) -> dict:
        from .rules import can_generate

        with _LOCK:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                rows = self.conn.execute(
                    "SELECT * FROM jobs WHERE target_id=? AND kind=?",
                    (target_id, "generate"),
                ).fetchall()
                allowed, reason = can_generate([self._job(row) for row in rows])
                if not allowed:
                    self.conn.rollback()
                    raise RuntimeError(reason)
                item = {
                    "id": new_id("job"),
                    "kind": "generate",
                    "target_id": target_id,
                    "status": "queued",
                    "detail": detail,
                    "created_at": now(),
                    "updated_at": now(),
                }
                self.conn.execute(
                    "INSERT INTO jobs VALUES (?,?,?,?,?,?,?)",
                    (item["id"], "generate", target_id, "queued", json.dumps(detail, ensure_ascii=False), item["created_at"], item["updated_at"]),
                )
                self.conn.commit()
            except RuntimeError:
                raise
            except Exception:
                self.conn.rollback()
                raise
        return item

    def jobs_for(self, target_id: str, kind: str | None = None) -> list[dict]:
        if kind:
            rows = self.conn.execute(
                "SELECT * FROM jobs WHERE target_id=? AND kind=? ORDER BY created_at DESC",
                (target_id, kind),
            ).fetchall()
        else:
            rows = self.conn.execute("SELECT * FROM jobs WHERE target_id=? ORDER BY created_at DESC", (target_id,)).fetchall()
        return [self._job(row) for row in rows]

    def _job(self, row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "kind": row["kind"],
            "target_id": row["target_id"],
            "status": row["status"],
            "detail": json.loads(row["detail"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def device(self, code: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM devices WHERE code=?", (code,)).fetchone()
        return dict(row) if row else None

    def device_by_token(self, token: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM devices WHERE token=?", (token,)).fetchone()
        return dict(row) if row else None

    def save_device(self, code: str, status: str, token: str | None = None, seen_at: str | None = None) -> None:
        with _LOCK:
            self.conn.execute(
                """
                INSERT INTO devices (code, token, status, created_at, seen_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(code) DO UPDATE SET
                    token=excluded.token,
                    status=excluded.status,
                    seen_at=COALESCE(excluded.seen_at, devices.seen_at)
                """,
                (code, token, status, now(), seen_at),
            )
            self.conn.commit()

    def touch_device(self, code: str) -> None:
        with _LOCK:
            self.conn.execute("UPDATE devices SET seen_at=? WHERE code=?", (now(), code))
            self.conn.commit()

    def list_devices(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM devices ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def revoke_device(self, code: str) -> None:
        with _LOCK:
            self.conn.execute(
                "UPDATE devices SET status='revoked', token=NULL, seen_at=NULL WHERE code=?",
                (code,),
            )
            self.conn.commit()

    def setting(self, key: str, default: str = "") -> str:
        with _LOCK:
            row = self.conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with _LOCK:
            self.conn.execute(
                "INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self.conn.commit()

    def record(self, command: str, payload: dict) -> None:
        with _LOCK:
            self.conn.execute(
                "INSERT INTO activity (command, payload, created_at) VALUES (?,?,?)",
                (command, json.dumps(payload, ensure_ascii=False), now()),
            )
            self.conn.commit()

    def recent(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM activity ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            {"command": row["command"], "payload": json.loads(row["payload"]), "created_at": row["created_at"]}
            for row in rows
        ]
