"""Administration: users, API keys, settings, provider instances, pools, workspaces."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import insert, select, update

from .. import db, events
from ..auth import ROLES, Principal, current_principal, need
from ..providers import adapter_for
from ..providers import instances as provider_lib
from ..security import API_KEY_PREFIX, encrypt_secret, hash_password, new_token, new_webhook_secret, token_hash

router = APIRouter(prefix="/api/admin", tags=["admin"])

SETTINGS_DEFAULTS = {
    "ffmpeg_passthrough": False,
    "approval_threshold_yuan": 20,
}


class UserIn(BaseModel):
    username: str
    password: str = ""
    display_name: str = ""
    role: str = "producer"
    disabled: bool | None = None


class KeyIn(BaseModel):
    name: str
    workspace_id: str
    scopes: list[str] = Field(default_factory=lambda: ["runs:write", "runs:read"])
    rate_per_minute: int = 60
    monthly_budget_yuan: float | None = None


class ProviderIn(BaseModel):
    name: str
    kind: str | None = None
    protocol: str | None = None
    group_name: str | None = None
    base_url: str | None = None
    secret: str | None = None
    clear_secret: bool = False
    model: str | None = None
    pool: str | None = None
    capabilities: dict | None = None
    retry_safe: bool | None = None
    max_attempts: int | None = None
    timeout_seconds: int | None = None
    pricing: dict | None = None
    options: dict | None = None
    enabled: bool | None = None


class PoolIn(BaseModel):
    concurrency: int | None = None
    rate_per_minute: int | None = None
    paused: bool | None = None
    note: str | None = None


class WorkspaceIn(BaseModel):
    name: str


def _user(row) -> dict:
    return {"id": row.id, "username": row.username, "display_name": row.display_name or row.username,
            "role": row.role, "disabled": row.disabled, "created_at": row.created_at}


@router.get("/users")
def list_users(principal: Principal = Depends(need("admin"))) -> dict:
    with db.tx() as conn:
        rows = conn.execute(select(db.users).order_by(db.users.c.created_at)).all()
    return {"items": [_user(row) for row in rows]}


@router.post("/users")
def create_user(body: UserIn, principal: Principal = Depends(need("admin"))) -> dict:
    if body.role not in ROLES:
        raise HTTPException(status_code=400, detail=f"角色只能是 {'、'.join(ROLES)}")
    try:
        hashed = hash_password(body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with db.tx() as conn:
        if conn.execute(select(db.users.c.id).where(db.users.c.username == body.username.strip())).first():
            raise HTTPException(status_code=409, detail="账号已存在")
        user_id = db.new_id("user")
        conn.execute(insert(db.users).values(id=user_id, username=body.username.strip(), role=body.role,
                                             display_name=body.display_name or body.username.strip(), password_hash=hashed))
        events.record(conn, principal, "user.create", target_kind="user", target_id=user_id,
                      payload={"username": body.username, "role": body.role})
        row = conn.execute(select(db.users).where(db.users.c.id == user_id)).first()
    return _user(row)


@router.patch("/users/{user_id}")
def update_user(user_id: str, body: UserIn, principal: Principal = Depends(need("admin"))) -> dict:
    values = {}
    if body.role:
        if body.role not in ROLES:
            raise HTTPException(status_code=400, detail=f"角色只能是 {'、'.join(ROLES)}")
        values["role"] = body.role
    if body.display_name:
        values["display_name"] = body.display_name
    if body.disabled is not None:
        values["disabled"] = body.disabled
    if body.password:
        try:
            values["password_hash"] = hash_password(body.password)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    with db.tx() as conn:
        row = conn.execute(select(db.users).where(db.users.c.id == user_id)).first()
        if not row:
            raise HTTPException(status_code=404, detail="没有这个账号")
        if user_id == principal.id and (values.get("role", "admin") != "admin" or values.get("disabled")):
            raise HTTPException(status_code=400, detail="不能降低或停用自己的管理员账号")
        if values:
            conn.execute(update(db.users).where(db.users.c.id == user_id).values(**values))
        if values.get("disabled") or "password_hash" in values:
            conn.execute(db.sessions.delete().where(db.sessions.c.user_id == user_id))
        events.record(conn, principal, "user.update", target_kind="user", target_id=user_id,
                      payload={key: value for key, value in values.items() if key != "password_hash"}
                      | {"password_reset": "password_hash" in values})
        row = conn.execute(select(db.users).where(db.users.c.id == user_id)).first()
    return _user(row)


@router.get("/keys")
def list_keys(principal: Principal = Depends(need("admin"))) -> dict:
    with db.tx() as conn:
        rows = conn.execute(select(db.api_keys).order_by(db.api_keys.c.created_at.desc())).mappings().all()
    return {"items": [{key: value for key, value in row.items() if key not in {"key_hash", "webhook_secret_enc"}}
                      for row in rows]}


@router.post("/keys")
def create_key(body: KeyIn, principal: Principal = Depends(need("admin"))) -> dict:
    allowed = {"runs:write", "runs:read", "assets:write"}
    if not body.scopes or set(body.scopes) - allowed:
        raise HTTPException(status_code=400, detail=f"权限范围只能从 {', '.join(sorted(allowed))} 里选")
    token = new_token(API_KEY_PREFIX)
    webhook_secret = new_webhook_secret()
    with db.tx() as conn:
        if not conn.execute(select(db.workspaces.c.id).where(db.workspaces.c.id == body.workspace_id)).first():
            raise HTTPException(status_code=404, detail="没有这个工作区")
        key_id = db.new_id("key")
        conn.execute(insert(db.api_keys).values(
            id=key_id, name=body.name, owner_user_id=principal.user_id, workspace_id=body.workspace_id,
            scopes=body.scopes, prefix=token[:12], key_hash=token_hash(token), rate_per_minute=body.rate_per_minute,
            webhook_secret_enc=encrypt_secret(webhook_secret),
            monthly_budget_yuan=body.monthly_budget_yuan,
        ))
        events.record(conn, principal, "apikey.create", workspace_id=body.workspace_id, target_kind="apikey",
                      target_id=key_id, payload={"name": body.name, "scopes": body.scopes})
    return {"id": key_id, "key": token, "prefix": token[:12], "webhook_secret": webhook_secret,
            "message": "密钥和回调签名密钥只显示这一次，请立即保存"}


@router.post("/keys/{key_id}/revoke")
def revoke_key(key_id: str, principal: Principal = Depends(need("admin"))) -> dict:
    with db.tx() as conn:
        done = conn.execute(update(db.api_keys).where(db.api_keys.c.id == key_id, db.api_keys.c.revoked_at.is_(None))
                            .values(revoked_at=db.now())).rowcount
        if not done:
            raise HTTPException(status_code=404, detail="没有这个密钥或已经吊销")
        events.record(conn, principal, "apikey.revoke", target_kind="apikey", target_id=key_id)
    return {"ok": True}


@router.get("/webhook-secret")
def webhook_secret(rotate: bool = False, principal: Principal = Depends(need("admin"))) -> dict:
    """Secret that signs callbacks of runs started in the web console (API-key runs use the key's own secret)."""
    from ..engine.webhooks import global_secret

    with db.tx() as conn:
        secret = global_secret(conn, rotate=rotate)
        if rotate:
            events.record(conn, principal, "webhook.rotate", target_kind="settings", target_id="webhook_secret")
    return {"webhook_secret": secret}


class SamplesIn(BaseModel):
    workspace_id: str


@router.post("/samples")
def load_samples(body: SamplesIn, principal: Principal = Depends(need("admin"))) -> dict:
    """Load the example assets and workflows (as drafts) into a workspace. Safe to repeat."""
    from ..samples import seed_samples

    with db.tx() as conn:
        if not conn.execute(select(db.workspaces.c.id).where(db.workspaces.c.id == body.workspace_id)).first():
            raise HTTPException(status_code=404, detail="没有这个工作区")
    result = seed_samples(body.workspace_id, publish=False)
    with db.tx() as conn:
        events.record(conn, principal, "samples.load", workspace_id=body.workspace_id, target_kind="workspace",
                      target_id=body.workspace_id, payload={"workflows": list(result["workflows"])})
    return result


@router.get("/settings")
def get_settings_view(principal: Principal = Depends(current_principal)) -> dict:
    with db.tx() as conn:
        return {key: db.get_setting(conn, key, default) for key, default in SETTINGS_DEFAULTS.items()}


@router.patch("/settings")
def patch_settings(body: dict, principal: Principal = Depends(need("admin"))) -> dict:
    unknown = set(body) - set(SETTINGS_DEFAULTS)
    if unknown:
        raise HTTPException(status_code=400, detail=f"没有这些设置：{', '.join(sorted(unknown))}")
    with db.tx() as conn:
        for key, value in body.items():
            db.set_setting(conn, key, value)
        events.record(conn, principal, "settings.update", target_kind="settings", payload=body)
        return {key: db.get_setting(conn, key, default) for key, default in SETTINGS_DEFAULTS.items()}


@router.get("/providers")
def list_providers(principal: Principal = Depends(need("queue:read"))) -> dict:
    with db.tx() as conn:
        rows = provider_lib.list_instances(conn)
        return {"items": [provider_lib.public(row) for row in rows]}


@router.post("/providers")
def save_provider(body: ProviderIn, principal: Principal = Depends(need("admin"))) -> dict:
    fields = body.model_dump(exclude={"name", "secret", "clear_secret"}, exclude_none=True)
    with db.tx() as conn:
        try:
            return provider_lib.save(conn, principal, body.name, fields, secret=body.secret, clear_secret=body.clear_secret)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/providers/{name}")
def delete_provider(name: str, principal: Principal = Depends(need("admin"))) -> dict:
    with db.tx() as conn:
        provider_lib.remove(conn, principal, name)
    return {"ok": True}


def _instance(name: str):
    with db.tx() as conn:
        row = provider_lib.get_row(conn, name)
        if not row:
            raise HTTPException(status_code=404, detail="没有这个供应商实例")
        return provider_lib.to_instance(row)


@router.post("/providers/{name}/probe")
def probe_provider(name: str, principal: Principal = Depends(need("admin"))) -> dict:
    instance = _instance(name)
    try:
        result = adapter_for(instance).probe()
    except Exception as exc:
        result = {"reachable": False, "message": f"探测没有完成：{exc}"}
    with db.tx() as conn:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == name)
                     .values(health={**result, "checked_at": db.now().isoformat()}))
    return result


@router.get("/providers/{name}/models")
def provider_models(name: str, principal: Principal = Depends(need("admin"))) -> dict:
    instance = _instance(name)
    try:
        return {"items": adapter_for(instance).list_models()}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/pools")
def list_pools(principal: Principal = Depends(need("queue:read"))) -> dict:
    with db.tx() as conn:
        return {"items": provider_lib.pools_overview(conn)}


@router.patch("/pools/{name}")
def update_pool(name: str, body: PoolIn, principal: Principal = Depends(need("queue:manage"))) -> dict:
    with db.tx() as conn:
        try:
            return provider_lib.set_pool(conn, principal, name, **body.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


workspaces_router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


@workspaces_router.get("")
def list_workspaces(principal: Principal = Depends(current_principal)) -> dict:
    with db.tx() as conn:
        query = select(db.workspaces).order_by(db.workspaces.c.created_at)
        if principal.workspace_id:
            query = query.where(db.workspaces.c.id == principal.workspace_id)
        return {"items": [dict(row) for row in conn.execute(query).mappings()]}


@workspaces_router.post("")
def create_workspace(body: WorkspaceIn, principal: Principal = Depends(need("admin"))) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="工作区名称不能为空")
    with db.tx() as conn:
        if conn.execute(select(db.workspaces.c.id).where(db.workspaces.c.name == name)).first():
            raise HTTPException(status_code=409, detail="已经有同名工作区")
        workspace_id = db.new_id("ws")
        conn.execute(insert(db.workspaces).values(id=workspace_id, name=name, created_by=f"{principal.kind}:{principal.id}"))
        events.record(conn, principal, "workspace.create", workspace_id=workspace_id, target_kind="workspace",
                      target_id=workspace_id, payload={"name": name})
        return dict(conn.execute(select(db.workspaces).where(db.workspaces.c.id == workspace_id)).mappings().one())


@workspaces_router.patch("/{workspace_id}")
def rename_workspace(workspace_id: str, body: WorkspaceIn, principal: Principal = Depends(need("admin"))) -> dict:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="工作区名称不能为空")
    with db.tx() as conn:
        if conn.execute(select(db.workspaces.c.id).where(db.workspaces.c.name == name, db.workspaces.c.id != workspace_id)).first():
            raise HTTPException(status_code=409, detail="已经有同名工作区")
        done = conn.execute(update(db.workspaces).where(db.workspaces.c.id == workspace_id).values(name=name)).rowcount
        if not done:
            raise HTTPException(status_code=404, detail="没有这个工作区")
        events.record(conn, principal, "workspace.rename", workspace_id=workspace_id, target_kind="workspace",
                      target_id=workspace_id, payload={"name": name})
        return dict(conn.execute(select(db.workspaces).where(db.workspaces.c.id == workspace_id)).mappings().one())
