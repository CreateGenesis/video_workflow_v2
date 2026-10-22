"""Saved provider settings override env. Keys stay on the server."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

CAPABILITIES = ("video", "image", "music")
FIELDS = ("base", "key", "model")
ENV = {
    "video": ("AUTODL_API_BASE", "AUTODL_API_TOKEN", "H3_WORKFLOW_ID"),
    "image": ("CVGEN_IMAGE_BASE", "CVGEN_IMAGE_KEY", "CVGEN_IMAGE_WORKFLOW"),
    "music": ("CVGEN_MUSIC_BASE", "CVGEN_MUSIC_KEY", "CVGEN_MUSIC_WORKFLOW"),
}
VIDEO_DEFAULTS = ("https://www.autodl.art", "", "minimax_h3_zm_u24")
PROBE_TIMEOUT = 8
PROBE_SLOW_MS = 6000
FETCH_TIMEOUT = 15
COMPAT_SUFFIXES = (
    "/api/claudecode",
    "/api/anthropic",
    "/apps/anthropic",
    "/api/coding",
    "/claudecode",
    "/anthropic",
    "/step_plan",
    "/coding",
    "/claude",
)


def mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return "••••"
    return "••••" + secret[-4:]


def _file_env() -> dict[str, str]:
    path = Path(__file__).resolve().parents[1] / ".env"
    if not path.is_file():
        return {}
    values = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env_value(name: str, file_env: dict[str, str]) -> str:
    return os.environ.get(name) or file_env.get(name) or ""


def resolve(store, capability: str) -> dict[str, str]:
    """Return base, key, and the selected model. A saved value wins over env."""
    if capability not in CAPABILITIES:
        raise ValueError("没有这个能力")
    file_env = _file_env()
    names = ENV[capability]
    defaults = VIDEO_DEFAULTS if capability == "video" else ("", "", "")
    resolved = {}
    for field, env_name, default in zip(FIELDS, names, defaults):
        saved = store.setting(f"provider:{capability}:{field}", "")
        if field == "model" and not saved:
            saved = store.setting(f"provider:{capability}:workflow", "")
        resolved[field] = saved or _env_value(env_name, file_env) or default
    resolved["source"] = "saved" if any(
        store.setting(f"provider:{capability}:{field}", "") or store.setting(f"provider:{capability}:workflow", "")
        for field in FIELDS
    ) else "env"
    resolved["workflow"] = resolved["model"]
    return resolved


def configured(store, capability: str) -> bool:
    item = resolve(store, capability)
    return bool(item["base"] and item["key"] and item["model"])


def public_view(store) -> list[dict]:
    rows = []
    for capability in CAPABILITIES:
        item = resolve(store, capability)
        rows.append({
            "capability": capability,
            "configured": bool(item["base"] and item["key"] and item["model"]),
            "base": item["base"],
            "model": item["model"],
            "key": mask(item["key"]),
        })
    return rows


def save(store, capability: str, base: str, key: str) -> None:
    if capability not in CAPABILITIES:
        raise ValueError("没有这个能力")
    if not base.strip():
        raise ValueError("地址不能为空")
    current = store.setting(f"provider:{capability}:key", "")
    secret = key.strip() or current
    if not secret and not _env_value(ENV[capability][1], _file_env()):
        raise ValueError("访问密钥不能为空")
    store.set_setting(f"provider:{capability}:base", base.strip().rstrip("/"))
    if secret:
        store.set_setting(f"provider:{capability}:key", secret)


def select_model(store, capability: str, model: str) -> None:
    if capability not in CAPABILITIES:
        raise ValueError("没有这个能力")
    chosen = model.strip()
    if not chosen:
        raise ValueError("没有选择模型")
    store.set_setting(f"provider:{capability}:model", chosen)


def _open(url: str, token: str = "", timeout: int = PROBE_TIMEOUT, method: str = "GET"):
    headers = {"Accept": "application/json", "User-Agent": "cvgen"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, method=method, headers=headers)
    started = time.perf_counter()
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
        return response.status, response.read(), int((time.perf_counter() - started) * 1000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), int((time.perf_counter() - started) * 1000)


def probe(store, capability: str) -> dict:
    """Reachability only. Any HTTP response counts; this does not submit a job."""
    if capability not in CAPABILITIES:
        raise ValueError("没有这个能力")
    item = resolve(store, capability)
    if not item["base"]:
        return {"reachable": False, "latency_ms": 0, "slow": False, "message": "无法连通", "status": 0}
    last_error = "无法连通"
    for attempt in range(2):
        try:
            status, _body, latency = _open(item["base"], timeout=PROBE_TIMEOUT, method="GET")
            slow = latency > PROBE_SLOW_MS
            message = f"连通但较慢（{latency} ms）" if slow else f"连通正常（{latency} ms）"
            return {"reachable": True, "latency_ms": latency, "slow": slow, "message": message, "status": status}
        except Exception as exc:
            last_error = "无法连通"
            timed_out = isinstance(exc, (TimeoutError, urllib.error.URLError)) and "timed out" in str(exc).lower()
            if not timed_out or attempt == 1:
                break
    return {"reachable": False, "latency_ms": 0, "slow": False, "message": last_error, "status": 0}


def _version_segment(base: str) -> bool:
    last = base.rstrip("/").rsplit("/", 1)[-1]
    return bool(re.fullmatch(r"v\d+", last))


def model_urls(base: str) -> list[str]:
    trimmed = base.strip().rstrip("/")
    if not trimmed:
        return []
    if _version_segment(trimmed):
        urls = [f"{trimmed}/models"]
        if not trimmed.endswith("/v1"):
            urls.append(f"{trimmed}/v1/models")
    else:
        urls = [f"{trimmed}/v1/models"]
    for suffix in COMPAT_SUFFIXES:
        if trimmed.endswith(suffix):
            root = trimmed[: -len(suffix)].rstrip("/")
            if "://" in root:
                urls.append(f"{root}/v1/models")
                urls.append(f"{root}/models")
            break
    seen = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


def _model_ids(payload: dict) -> list[str]:
    found = []
    data = payload.get("data")
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("id"):
                found.append(str(item["id"]))
    models = payload.get("models")
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            slug = item.get("slug") or item.get("id")
            if slug:
                found.append(str(slug))
    return sorted(set(found))


def fetch_models(store, capability: str) -> dict:
    if capability not in CAPABILITIES:
        raise ValueError("没有这个能力")
    item = resolve(store, capability)
    if not item["base"] or not item["key"]:
        raise RuntimeError("先填写地址和访问密钥")
    unsupported = False
    for url in model_urls(item["base"]):
        try:
            status, raw, _latency = _open(url, item["key"], timeout=FETCH_TIMEOUT)
        except Exception as exc:
            raise RuntimeError("模型列表没有返回") from exc
        if status in {401, 403}:
            raise RuntimeError("密钥不正确")
        if status in {404, 405}:
            unsupported = True
            continue
        if status >= 400:
            raise RuntimeError("模型列表没有返回")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("模型列表没有返回") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("模型列表没有返回")
        return {"items": [{"id": model_id} for model_id in _model_ids(payload)]}
    if unsupported:
        raise RuntimeError("这个地址不支持模型列表")
    raise RuntimeError("模型列表没有返回")
