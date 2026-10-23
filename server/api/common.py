"""Shared helpers for routers: error mapping, JSON shaping, signed media URLs inside outputs."""

from __future__ import annotations

from decimal import Decimal

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .. import artifacts
from ..assets import AssetError
from ..graph import GraphError, NotFound
from ..security import media_url


def install_error_handlers(app) -> None:
    from ..workflows.runner import RunError
    from ..workflows.template import TemplateError

    async def bad_request(_request: Request, exc: Exception):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    async def not_found(_request: Request, exc: Exception):
        return JSONResponse(status_code=404, content={"detail": str(exc).strip("'\"")})

    for error in (GraphError, AssetError, TemplateError, RunError):
        app.add_exception_handler(error, bad_request)
    app.add_exception_handler(NotFound, not_found)


def with_urls(value):
    """Add *_url next to every artifact id inside task outputs, so clients never build media paths."""
    if isinstance(value, list):
        return [with_urls(item) for item in value]
    if not isinstance(value, dict):
        return value
    out = {}
    for key, item in value.items():
        out[key] = with_urls(item)
        if isinstance(item, str) and (key == "artifact_id" or key.endswith("_artifact_id")) and item:
            out[key[: -len("artifact_id")] + "url" if key != "artifact_id" else "url"] = media_url(item)
    return out


def number(value):
    return float(value) if isinstance(value, Decimal) else value


def task_public(task: dict, *, full: bool = False) -> dict:
    output = task.get("output") or {}
    error = task.get("error") or {}
    data = {
        "id": task["id"], "kind": task["kind"], "status": task["status"], "pool": task["pool"],
        "run_id": task.get("run_id"), "work_id": task.get("work_id"), "node_id": task.get("node_id"),
        "item": task.get("item_key"), "item_index": task.get("item_index"), "provider": task.get("provider_instance"),
        "priority": task.get("priority"), "attempts": task.get("attempts"), "max_attempts": task.get("max_attempts"),
        "progress": task.get("progress"), "progress_message": output.get("progress_message", ""),
        "attention": task.get("attention") or "", "error": error.get("message") if error else None,
        "cancel_requested": task.get("cancel_requested"), "superseded_by": task.get("superseded_by"),
        "created_at": task.get("created_at"), "started_at": task.get("started_at"),
        "submitted_at": task.get("submitted_at"), "finished_at": task.get("finished_at"),
        "created_by": f"{task.get('created_by_kind')}:{task.get('created_by_id')}",
        "cost_yuan": output.get("cost_yuan"),
        "timeout_seconds": task.get("timeout_seconds"),
    }
    summary_keys = ("artifact_id", "clip_id", "entity_id", "sheet_artifact_id", "last_frame_artifact_id", "passed",
                    "problems", "prompt", "warnings", "duration", "candidates", "attached", "decision", "export",
                    "observation_id", "draft", "entities", "flagged", "rerun", "note", "by", "references", "shot_id",
                    "shot_title", "resolution", "selections", "last_decision", "redo", "artifacts", "result")
    shown = output if full else {key: output[key] for key in summary_keys if key in output}
    data["output"] = with_urls(shown)
    if full:
        data["input"] = task.get("input")
        data["provider_ref"] = {k: v for k, v in (task.get("provider_ref") or {}).items() if not k.startswith("_")}
        data["error_detail"] = error
    return data


def artifact_public(conn, artifact_id: str | None) -> dict | None:
    return artifacts.public(artifacts.get(conn, artifact_id)) if artifact_id else None


def entity_public(conn, entity: dict) -> dict:
    return {
        "id": entity["id"], "work_id": entity["work_id"], "type": entity["type"], "data": entity["data"],
        "ord": entity.get("ord"), "position": entity.get("position"),
        "artifact": artifact_public(conn, entity.get("artifact_id")),
        "created_by": entity.get("created_by"), "created_at": entity.get("created_at"),
        "updated_at": entity.get("updated_at"),
    }


def require_found(value, message: str = "没有找到"):
    if not value:
        raise HTTPException(status_code=404, detail=message)
    return value
