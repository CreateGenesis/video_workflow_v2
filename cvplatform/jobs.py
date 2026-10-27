"""Jobs protocol. Claim is one conditional update. Agent writes only lease and output columns."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from cvplatform.gates import LEASE_SECONDS, GateError

SECRET_KEYS = {"token", "api_key", "secret", "password", "authorization", "cookie"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _loads(value: str | None) -> Any:
    if not value:
        return None
    return json.loads(value)


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _row(session: Session, job_id: str) -> dict[str, Any] | None:
    found = session.execute(text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id}).mappings().first()
    return dict(found) if found else None


def contains_secret(payload: Any) -> bool:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in SECRET_KEYS or contains_secret(value):
                return True
    if isinstance(payload, list):
        return any(contains_secret(item) for item in payload)
    return False


def enqueue(session: Session, *, workspace_id: str, job_type: str, payload: dict[str, Any], max_attempts: int = 3) -> dict[str, Any]:
    if job_type not in {"extract_reference", "segment_script", "write_prompt"}:
        raise GateError("job_type", "jobs 只承担三类文本任务")
    if contains_secret(payload):
        raise GateError("secret", "密钥不进 jobs.input")
    job_id = "job_" + uuid.uuid4().hex[:12]
    session.execute(
        text(
            """
            INSERT INTO jobs (id, workspace_id, type, input, status, attempt, max_attempts, created_at)
            VALUES (:id, :workspace_id, :type, :input, 'queued', 0, :max_attempts, :created_at)
            """
        ),
        {
            "id": job_id,
            "workspace_id": workspace_id,
            "type": job_type,
            "input": _dumps(payload),
            "max_attempts": max_attempts,
            "created_at": _iso(_now()),
        },
    )
    return _row(session, job_id) or {}


def claim(session: Session, owner: str, *, credential: str, now: datetime | None = None) -> dict[str, Any] | None:
    """Single-row conditional update. No updated row means do not call the model."""
    now = now or _now()
    candidate = session.execute(
        text(
            """
            SELECT id FROM jobs
            WHERE attempt < max_attempts
              AND (
                status = 'queued'
                OR (status = 'leased' AND lease_expires_at < :now)
              )
            ORDER BY created_at
            LIMIT 1
            """
        ),
        {"now": _iso(now)},
    ).first()
    if candidate is None:
        return None
    expires = now + timedelta(seconds=LEASE_SECONDS)
    updated = session.execute(
        text(
            """
            UPDATE jobs
            SET status = 'leased', lease_owner = :owner, lease_expires_at = :expires, attempt = attempt + 1
            WHERE id = :id
              AND attempt < max_attempts
              AND (
                status = 'queued'
                OR (status = 'leased' AND lease_expires_at < :now)
              )
            """
        ),
        {"id": candidate[0], "owner": owner, "expires": _iso(expires), "now": _iso(now)},
    )
    if updated.rowcount != 1:
        return None
    row = _row(session, candidate[0]) or {}
    return {
        "job": row,
        "credential": credential,
        "credential_expires_at": _iso(expires),
        "lease_expires_at": _iso(expires),
    }


def complete(session: Session, job_id: str, owner: str, output: dict[str, Any] | None, error: str | None, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    row = _row(session, job_id)
    if row is None:
        raise GateError("missing", "任务不存在")
    expires = _parse(row["lease_expires_at"])
    if row["lease_owner"] != owner or row["status"] != "leased" or expires is None or expires <= now:
        raise GateError("lease", "过期或越权的回写不改变该行")
    if output is not None and contains_secret(output):
        raise GateError("secret", "回写结果里出现密钥字段")
    status = "failed" if error else "succeeded"
    session.execute(
        text(
            """
            UPDATE jobs
            SET output = :output, error = :error, status = :status
            WHERE id = :id AND status = 'leased' AND lease_owner = :owner AND lease_expires_at > :now
            """
        ),
        {
            "id": job_id,
            "owner": owner,
            "now": _iso(now),
            "output": _dumps(output) if output is not None else None,
            "error": error,
            "status": status,
        },
    )
    return _row(session, job_id) or row


def reject_agent_insert(role: str) -> None:
    """The agent role has no INSERT on business tables. Platform commands pass."""
    if role == "agent":
        raise GateError("forbidden", "agent 不能插入业务行")


def agent_insert_business(session: Session, role: str = "agent") -> None:
    """Kept for the dedicated ban route. It uses the same sentence as every business insert."""
    reject_agent_insert(role)
    session.execute(text("INSERT INTO products (id, workspace_id, kind, status, prompt) VALUES ('agent-row', 'ws', 'image', 'succeeded', 'agent')"))


def inspect(session: Session, *, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or _now()
    rows = session.execute(
        text("SELECT * FROM jobs WHERE status = 'leased' AND lease_expires_at < :now"),
        {"now": _iso(now)},
    ).mappings().all()
    changed = []
    for row in rows:
        if row["attempt"] < row["max_attempts"]:
            session.execute(
                text("UPDATE jobs SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL WHERE id = :id"),
                {"id": row["id"]},
            )
        else:
            session.execute(
                text("UPDATE jobs SET status = 'failed', error = 'lease_expired' WHERE id = :id"),
                {"id": row["id"]},
            )
        changed.append(_row(session, row["id"]) or {})
    return changed


def accept_write_prompt(session: Session, job_id: str, *, valid: bool, now: datetime | None = None) -> dict[str, Any]:
    """Prompt product and accepted_at are written in the same transaction, or neither is."""
    now = now or _now()
    row = _row(session, job_id)
    if row is None or row["status"] != "succeeded" or row["type"] != "write_prompt":
        raise GateError("accept", "只能接受已回传的 write_prompt")
    if not valid:
        session.execute(
            text("UPDATE jobs SET status = 'failed', error = :error, accepted_at = NULL WHERE id = :id"),
            {"id": job_id, "error": "prompt_invalid"},
        )
        return {"job": _row(session, job_id), "product": None}
    product_id = "prod_" + uuid.uuid4().hex[:12]
    output = _loads(row["output"]) or {}
    session.execute(
        text(
            """
            INSERT INTO products (
              id, workspace_id, kind, status, prompt, title, origin_job_id, created_at
            ) VALUES (
              :id, :workspace_id, 'text', 'succeeded', :prompt, :title, :origin_job_id, :created_at
            )
            """
        ),
        {
            "id": product_id,
            "workspace_id": row["workspace_id"],
            "prompt": output.get("prompt", ""),
            "title": (output.get("prompt") or "提示词")[:40],
            "origin_job_id": job_id,
            "created_at": _iso(now),
        },
    )
    session.execute(
        text("UPDATE jobs SET accepted_at = :accepted_at WHERE id = :id"),
        {"id": job_id, "accepted_at": _iso(now)},
    )
    product = session.execute(text("SELECT * FROM products WHERE id = :id"), {"id": product_id}).mappings().first()
    return {"job": _row(session, job_id), "product": dict(product) if product else None}
