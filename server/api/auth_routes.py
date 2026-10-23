"""People: first-run setup, login sessions (HttpOnly cookie), own password."""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, func, insert, select, update

from .. import db, events
from ..auth import SESSION_COOKIE, Principal, current_principal, optional_principal
from ..config import get_settings
from ..security import SESSION_PREFIX, hash_password, new_token, token_hash, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str
    password: str
    display_name: str = ""


class PasswordIn(BaseModel):
    password: str
    next_password: str


def _user_public(row) -> dict:
    return {"id": row.id, "username": row.username, "display_name": row.display_name or row.username,
            "role": row.role, "disabled": row.disabled, "created_at": row.created_at}


def start_session(conn, response: Response, user_id: str) -> str:
    token = new_token(SESSION_PREFIX)
    hours = get_settings().session_hours
    conn.execute(insert(db.sessions).values(
        id=db.new_id("sess"), user_id=user_id, token_hash=token_hash(token),
        expires_at=db.now() + timedelta(hours=hours), last_seen_at=db.now(),
    ))
    secure = get_settings().public_base.startswith("https://")
    response.set_cookie(SESSION_COOKIE, token, max_age=hours * 3600, httponly=True, samesite="lax",
                        secure=secure, path="/")
    return token


@router.get("/status")
def status(request: Request) -> dict:
    with db.tx() as conn:
        users = conn.execute(select(func.count()).select_from(db.users)).scalar_one()
    principal = optional_principal(request)
    return {
        "setup_needed": users == 0,
        "signed_in": bool(principal),
        "me": {"id": principal.id, "name": principal.name, "role": principal.role, "kind": principal.kind,
               "perms": sorted(principal.perms)} if principal else None,
    }


@router.post("/setup")
def setup(body: LoginIn, response: Response) -> dict:
    """Only while there are no users: create the first admin and sign in."""
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="账号不能为空")
    try:
        hashed = hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with db.tx() as conn:
        conn.execute(db.text("LOCK TABLE users IN EXCLUSIVE MODE"))
        if conn.execute(select(func.count()).select_from(db.users)).scalar_one():
            raise HTTPException(status_code=409, detail="已经有管理员了，请直接登录")
        user_id = db.new_id("user")
        conn.execute(insert(db.users).values(id=user_id, username=username, display_name=body.display_name or username,
                                             role="admin", password_hash=hashed))
        from ..auth import SYSTEM

        events.record(conn, SYSTEM, "user.setup", target_kind="user", target_id=user_id, payload={"username": username})
        start_session(conn, response, user_id)
        row = conn.execute(select(db.users).where(db.users.c.id == user_id)).first()
    return {"user": _user_public(row)}


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    from ..auth import limiter

    client = request.client.host if request.client else "unknown"
    if not limiter.allow(f"login:{client}", 20):
        raise HTTPException(status_code=429, detail="登录尝试太频繁，请一分钟后再试")
    with db.tx() as conn:
        row = conn.execute(select(db.users).where(db.users.c.username == body.username.strip())).first()
        if not row or row.disabled or not verify_password(body.password, row.password_hash):
            raise HTTPException(status_code=401, detail="账号或密码不对")
        start_session(conn, response, row.id)
        principal = Principal(kind="user", id=row.id, name=row.display_name or row.username, role=row.role)
        events.record(conn, principal, "user.login", target_kind="user", target_id=row.id)
    return {"user": _user_public(row)}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        with db.tx() as conn:
            conn.execute(delete(db.sessions).where(db.sessions.c.token_hash == token_hash(token)))
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(current_principal)) -> dict:
    return {"id": principal.id, "kind": principal.kind, "name": principal.name, "role": principal.role,
            "workspace_id": principal.workspace_id, "perms": sorted(principal.perms)}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, principal: Principal = Depends(current_principal)) -> dict:
    if principal.kind != "user":
        raise HTTPException(status_code=403, detail="只有登录的人可以改自己的密码")
    with db.tx() as conn:
        row = conn.execute(select(db.users).where(db.users.c.id == principal.id)).first()
        if not verify_password(body.password, row.password_hash):
            raise HTTPException(status_code=401, detail="当前密码不对")
        try:
            hashed = hash_password(body.next_password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        conn.execute(update(db.users).where(db.users.c.id == principal.id).values(password_hash=hashed))
        current = token_hash(request.cookies.get(SESSION_COOKIE, "") or "")
        conn.execute(delete(db.sessions).where(db.sessions.c.user_id == principal.id, db.sessions.c.token_hash != current))
        events.record(conn, principal, "user.password", target_kind="user", target_id=principal.id)
    return {"ok": True, "message": "密码已更新，其他登录已失效"}
