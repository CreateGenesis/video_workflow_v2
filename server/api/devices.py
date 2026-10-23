"""Device flow for the agent CLI.

1. cvgen calls POST /api/device/start and gets a short user code plus a secret only it knows.
2. A signed-in person opens /approve/<code> and approves; the device then belongs to that person.
3. cvgen polls POST /api/device/poll with the secret and receives its token exactly once.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import insert, select, update

from .. import db, events
from ..auth import Principal, current_principal, limiter, need
from ..security import DEVICE_PREFIX, new_token, new_user_code, normalize_user_code, token_hash

router = APIRouter(tags=["devices"])
CODE_TTL = timedelta(minutes=10)


class StartIn(BaseModel):
    name: str = ""
    client_version: str = ""


class PollIn(BaseModel):
    device_id: str
    poll_secret: str


class BudgetIn(BaseModel):
    daily_budget_yuan: float | None = None
    name: str | None = None


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _public(row) -> dict:
    data = {key: value for key, value in dict(row._mapping).items()
            if key not in {"poll_secret_hash", "token_hash"}}
    data["online"] = bool(row.last_seen_at and db.now() - row.last_seen_at < timedelta(minutes=2))
    return data


@router.post("/api/device/start")
def start(body: StartIn, request: Request) -> dict:
    if not limiter.allow(f"device-start:{_client(request)}", 10):
        raise HTTPException(status_code=429, detail="申请太频繁，请稍后再试")
    secret = new_token("cvp_")
    with db.tx() as conn:
        for _ in range(5):
            code = new_user_code()
            if not conn.execute(select(db.devices.c.id).where(db.devices.c.user_code == code)).first():
                break
        device_id = db.new_id("dev")
        conn.execute(insert(db.devices).values(
            id=device_id, name=body.name.strip()[:60], status="pending", user_code=code,
            poll_secret_hash=token_hash(secret), client_version=body.client_version[:40],
            expires_at=db.now() + CODE_TTL,
        ))
    return {"device_id": device_id, "user_code": code, "poll_secret": secret, "approve_path": f"/approve/{code}",
            "expires_in": int(CODE_TTL.total_seconds()), "interval": 3}


@router.post("/api/device/poll")
def poll(body: PollIn, request: Request) -> dict:
    if not limiter.allow(f"device-poll:{_client(request)}", 120):
        raise HTTPException(status_code=429, detail="轮询太频繁")
    with db.tx() as conn:
        row = conn.execute(select(db.devices).where(db.devices.c.id == body.device_id).with_for_update()).first()
        if not row or row.poll_secret_hash != token_hash(body.poll_secret):
            raise HTTPException(status_code=404, detail="没有这个申请")
        if row.status == "pending" and row.expires_at < db.now():
            conn.execute(update(db.devices).where(db.devices.c.id == row.id).values(status="expired"))
            return {"status": "expired"}
        if row.status != "approved":
            return {"status": row.status}
        if row.token_claimed:
            return {"status": "claimed"}
        token = new_token(DEVICE_PREFIX)
        conn.execute(update(db.devices).where(db.devices.c.id == row.id).values(
            token_hash=token_hash(token), token_claimed=True, last_seen_at=db.now(),
        ))
        return {"status": "approved", "token": token}


@router.get("/api/devices/code/{user_code}")
def lookup(user_code: str, principal: Principal = Depends(need("devices:approve"))) -> dict:
    code = normalize_user_code(user_code)
    with db.tx() as conn:
        row = conn.execute(select(db.devices).where(db.devices.c.user_code == code)).first()
    if not row:
        raise HTTPException(status_code=404, detail="没有这个设备码")
    if row.status == "pending" and row.expires_at < db.now():
        raise HTTPException(status_code=410, detail="设备码已过期，请在终端重新运行 cvgen login")
    return _public(row)


@router.post("/api/devices/code/{user_code}/approve")
def approve(user_code: str, principal: Principal = Depends(need("devices:approve"))) -> dict:
    if principal.kind != "user":
        raise HTTPException(status_code=403, detail="只有登录的人可以批准设备")
    code = normalize_user_code(user_code)
    with db.tx() as conn:
        row = conn.execute(select(db.devices).where(db.devices.c.user_code == code).with_for_update()).first()
        if not row:
            raise HTTPException(status_code=404, detail="没有这个设备码")
        if row.status != "pending":
            raise HTTPException(status_code=409, detail=f"这个设备码已经是 {row.status} 状态")
        if row.expires_at < db.now():
            raise HTTPException(status_code=410, detail="设备码已过期，请在终端重新运行 cvgen login")
        conn.execute(update(db.devices).where(db.devices.c.id == row.id).values(
            status="approved", user_id=principal.id, approved_at=db.now(),
        ))
        events.record(conn, principal, "device.approve", target_kind="device", target_id=row.id,
                      payload={"name": row.name, "code": code})
        row = conn.execute(select(db.devices).where(db.devices.c.id == row.id)).first()
    return _public(row)


@router.get("/api/devices")
def list_devices(principal: Principal = Depends(current_principal)) -> dict:
    with db.tx() as conn:
        query = select(db.devices, db.users.c.username).outerjoin(db.users, db.users.c.id == db.devices.c.user_id)
        query = query.where(db.devices.c.status.in_(("approved", "revoked")))
        if not principal.can("devices:manage"):
            if principal.kind != "user":
                raise HTTPException(status_code=403, detail="没有权限")
            query = query.where(db.devices.c.user_id == principal.id)
        rows = conn.execute(query.order_by(db.devices.c.approved_at.desc())).all()
    return {"items": [_public(row) for row in rows]}


def _owned(conn, device_id: str, principal: Principal):
    row = conn.execute(select(db.devices).where(db.devices.c.id == device_id)).first()
    if not row:
        raise HTTPException(status_code=404, detail="没有这台设备")
    if row.user_id != principal.id and not principal.can("devices:manage"):
        raise HTTPException(status_code=403, detail="只能管理自己的设备")
    return row


@router.post("/api/devices/{device_id}/revoke")
def revoke(device_id: str, principal: Principal = Depends(current_principal)) -> dict:
    with db.tx() as conn:
        _owned(conn, device_id, principal)
        conn.execute(update(db.devices).where(db.devices.c.id == device_id).values(status="revoked", token_hash=None))
        events.record(conn, principal, "device.revoke", target_kind="device", target_id=device_id)
    return {"ok": True}


@router.patch("/api/devices/{device_id}")
def update_device(device_id: str, body: BudgetIn, principal: Principal = Depends(current_principal)) -> dict:
    with db.tx() as conn:
        _owned(conn, device_id, principal)
        values = {}
        if "daily_budget_yuan" in body.model_fields_set:
            if not principal.can("devices:manage"):
                raise HTTPException(status_code=403, detail="设备预算由审计员或管理员设置")
            values["daily_budget_yuan"] = body.daily_budget_yuan
        if body.name:
            values["name"] = body.name[:60]
        if values:
            conn.execute(update(db.devices).where(db.devices.c.id == device_id).values(**values))
            events.record(conn, principal, "device.update", target_kind="device", target_id=device_id, payload=values)
        row = conn.execute(select(db.devices).where(db.devices.c.id == device_id)).first()
    return _public(row)
