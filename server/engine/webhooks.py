"""Deliver run callbacks. Signed with HMAC-SHA256 over "<timestamp>.<body>"; retried with backoff."""

from __future__ import annotations

import json
import time
from datetime import timedelta

import httpx
from sqlalchemy import text, update

from .. import db
from ..security import webhook_signature

MAX_ATTEMPTS = 8


def deliver_due(limit: int = 10) -> int:
    delivered = 0
    with db.tx() as conn:
        rows = conn.execute(text("""
            SELECT * FROM webhook_deliveries
            WHERE status = 'pending' AND next_attempt_at <= now()
            ORDER BY id LIMIT :limit FOR UPDATE SKIP LOCKED
        """), {"limit": limit}).mappings().all()
        for row in rows:
            body = json.dumps(row["payload"], ensure_ascii=False).encode("utf-8")
            stamp = int(time.time())
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "cvgen-webhook",
                "X-CVGEN-Event": row["event"],
                "X-CVGEN-Timestamp": str(stamp),
                "X-CVGEN-Signature": f"sha256={webhook_signature(body, stamp)}",
            }
            error = ""
            try:
                response = httpx.post(row["url"], content=body, headers=headers, timeout=10, trust_env=False)
                ok = 200 <= response.status_code < 300
                if not ok:
                    error = f"HTTP {response.status_code}"
            except httpx.HTTPError as exc:
                ok, error = False, str(exc)[:300]
            attempts = row["attempts"] + 1
            if ok:
                values = {"status": "delivered", "attempts": attempts, "last_error": ""}
                delivered += 1
            elif attempts >= MAX_ATTEMPTS:
                values = {"status": "failed", "attempts": attempts, "last_error": error}
            else:
                values = {"attempts": attempts, "last_error": error,
                          "next_attempt_at": db.now() + timedelta(seconds=min(3600, 15 * 2 ** attempts))}
            conn.execute(update(db.webhook_deliveries).where(db.webhook_deliveries.c.id == row["id"]).values(**values))
    return delivered
