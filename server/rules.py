"""Pure rules for hosted execution. Tests drive these functions."""

from __future__ import annotations

BLOCKING = {"queued", "running", "unknown", "succeeded"}
STATUS_RANK = {"已成片": 0, "排队": 1, "提交不明": 2, "失败": 3, "未生成": 4}


def can_generate(existing: list[dict]) -> tuple[bool, str]:
    blocking = [job for job in existing if job.get("status") in BLOCKING]
    if blocking:
        return False, "这个镜头已有未完成或已成功的生成，不能再次提交"
    return True, ""


def shot_status(jobs: list[dict]) -> str:
    related = [job for job in jobs if job.get("kind") == "generate"]
    if any(job.get("status") == "succeeded" for job in related):
        return "已成片"
    if any(job.get("status") in {"queued", "running"} for job in related):
        return "排队"
    if any(job.get("status") == "unknown" for job in related):
        return "提交不明"
    if any(job.get("status") == "failed" for job in related):
        return "失败"
    return "未生成"


def passthrough_allowed(setting: str) -> bool:
    return setting == "1"


def shell_forbidden(args: list[str]) -> bool:
    tokens = (";", "|", "`", "\n", "$(", "&&")
    return any(any(token in arg for token in tokens) for arg in args)


def provider_outcome(state: dict) -> str:
    status = str(state.get("status") or "").lower()
    if state.get("video_url") or status in {"success", "succeeded", "completed"}:
        return "ready"
    if status in {"failed", "error", "canceled", "cancelled"}:
        return "failed"
    if status in {"queued", "running", ""}:
        return "pending"
    return "unknown"
