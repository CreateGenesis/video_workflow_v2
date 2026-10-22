"""Who is calling, and what they may do.

Three kinds of callers:
- people use the web console with an HttpOnly session cookie;
- an agent's cvgen CLI uses a device token that belongs to the person who approved it;
- other services use API keys bound to one workspace.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update

from . import db
from .security import API_KEY_PREFIX, DEVICE_PREFIX, SESSION_PREFIX, token_hash

SESSION_COOKIE = "cvgen_session"
CSRF_HEADER = "x-cvgen-csrf"
ROLES = ("producer", "reviewer", "admin")

_PRODUCER = {
    "works:read", "assets:read", "workflows:read", "runs:read", "runs:create", "queue:read",
    "uploads:write", "devices:approve", "gates:decide:producer", "costs:read",
}
_REVIEWER = _PRODUCER | {
    "activity:read", "notes:read", "notes:write", "workflows:draft", "workflows:publish",
    "assets:write", "gates:decide:reviewer", "devices:manage",
}
_ADMIN = _REVIEWER | {
    "admin", "queue:manage", "tasks:resolve", "works:write", "tasks:create", "gates:decide:admin",
}
_AGENT = {
    "works:read", "works:write", "tasks:create", "assets:read", "assets:write", "workflows:read",
    "workflows:draft", "runs:create:trial", "runs:read", "queue:read", "uploads:write", "notes:read",
    "costs:read",
}
_SCOPES = {
    "runs:write": {"runs:create", "uploads:write", "workflows:read"},
    "runs:read": {"runs:read", "workflows:read"},
    "assets:write": {"uploads:write"},
}
ROLE_PERMS = {"producer": _PRODUCER, "reviewer": _REVIEWER, "admin": _ADMIN, "agent": _AGENT}


@dataclass
class Principal:
    kind: str
    id: str
    name: str
    role: str
    user_id: str | None = None
    workspace_id: str | None = None
    scopes: tuple[str, ...] = ()
    via_cookie: bool = False
    perms: set[str] = field(default_factory=set)

    def can(self, perm: str) -> bool:
        return perm in self.perms

    def require(self, perm: str) -> None:
        if not self.can(perm):
            raise HTTPException(status_code=403, detail=f"没有权限：{perm}")

    def check_workspace(self, workspace_id: str | None) -> None:
        if self.workspace_id and workspace_id and self.workspace_id != workspace_id:
            raise HTTPException(status_code=403, detail="API 密钥不能访问这个工作区")

    @property
    def actor(self) -> tuple[str, str]:
        return self.kind, self.id


SYSTEM = Principal(kind="system", id="system", name="系统", role="admin", perms=set(_ADMIN))


def worker_principal(worker_id: str) -> Principal:
    return Principal(kind="worker", id=worker_id, name=worker_id, role="admin", perms=set(_ADMIN))


def _perms_for(role: str, scopes: tuple[str, ...] = ()) -> set[str]:
    if role == "service":
        found: set[str] = set()
        for scope in scopes:
            found |= _SCOPES.get(scope, set())
        return found
    return set(ROLE_PERMS.get(role, set()))


class _RateLimiter:
    """Per-process sliding window. Good enough for one API instance; documented as such."""

    def __init__(self) -> None:
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        if limit <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > window:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True


limiter = _RateLimiter()


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return ""


def resolve_token(token: str, via_cookie: bool = False) -> Principal | None:
    if not token:
        return None
    hashed = token_hash(token)
    with db.tx() as conn:
        if token.startswith(SESSION_PREFIX):
            row = conn.execute(
                select(db.sessions, db.users.c.username, db.users.c.display_name, db.users.c.role, db.users.c.disabled)
                .join(db.users, db.users.c.id == db.sessions.c.user_id)
                .where(db.sessions.c.token_hash == hashed)
            ).first()
            if not row or row.disabled or row.expires_at < db.now():
                return None
            if not row.last_seen_at or db.now() - row.last_seen_at > timedelta(minutes=1):
                conn.execute(update(db.sessions).where(db.sessions.c.id == row.id).values(last_seen_at=db.now()))
            return Principal(
                kind="user", id=row.user_id, name=row.display_name or row.username, role=row.role,
                user_id=row.user_id, via_cookie=via_cookie, perms=_perms_for(row.role),
            )
        if token.startswith(DEVICE_PREFIX):
            row = conn.execute(select(db.devices).where(db.devices.c.token_hash == hashed)).first()
            if not row or row.status != "approved":
                return None
            if not row.last_seen_at or db.now() - row.last_seen_at > timedelta(seconds=30):
                conn.execute(update(db.devices).where(db.devices.c.id == row.id).values(last_seen_at=db.now()))
            return Principal(
                kind="device", id=row.id, name=row.name or row.user_code, role="agent",
                user_id=row.user_id, perms=_perms_for("agent"),
            )
        if token.startswith(API_KEY_PREFIX):
            row = conn.execute(select(db.api_keys).where(db.api_keys.c.key_hash == hashed)).first()
            if not row or row.revoked_at:
                return None
            if not limiter.allow(f"key:{row.id}", row.rate_per_minute):
                raise HTTPException(status_code=429, detail="API 密钥请求过于频繁")
            if not row.last_used_at or db.now() - row.last_used_at > timedelta(minutes=1):
                conn.execute(update(db.api_keys).where(db.api_keys.c.id == row.id).values(last_used_at=db.now()))
            scopes = tuple(row.scopes or [])
            return Principal(
                kind="apikey", id=row.id, name=row.name, role="service", user_id=row.owner_user_id,
                workspace_id=row.workspace_id, scopes=scopes, perms=_perms_for("service", scopes),
            )
    return None


def optional_principal(request: Request) -> Principal | None:
    token = _bearer(request)
    via_cookie = False
    if not token:
        token = request.cookies.get(SESSION_COOKIE, "")
        via_cookie = bool(token)
    principal = resolve_token(token, via_cookie=via_cookie)
    if principal and via_cookie and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get(CSRF_HEADER) != "1":
            raise HTTPException(status_code=403, detail="缺少 X-CVGEN-CSRF 请求头")
    return principal


def current_principal(request: Request) -> Principal:
    principal = optional_principal(request)
    if not principal:
        raise HTTPException(status_code=401, detail="未登录或凭证已失效，请重新登录（cvgen login）")
    return principal


def need(perm: str):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        principal.require(perm)
        return principal

    return dependency
