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


RESOLUTIONS = ("480p横", "480p竖", "768p横", "768p竖", "480p(1:1)", "768p(1:1)")
RESOLUTION_SIZE = {
    "480p横": (854, 480),
    "480p竖": (480, 854),
    "768p横": (1366, 768),
    "768p竖": (768, 1366),
    "480p(1:1)": (480, 480),
    "768p(1:1)": (768, 768),
}


def check_spec(duration: float, width: int | None, height: int | None, resolution: str = "") -> list[str]:
    """A stored clip is usable only inside 1–15s and an existing tier."""
    problems = []
    if duration < 1 or duration > 15:
        problems.append("时长不在 1 到 15 秒")
    named = RESOLUTION_SIZE.get(resolution)
    if named and width and height:
        if (width, height) != named:
            problems.append("分辨率和声明档位不一致")
    elif width and height:
        if (width, height) not in RESOLUTION_SIZE.values():
            problems.append("分辨率不在现有档位")
    else:
        problems.append("分辨率没有测到")
    return problems


def provider_outcome(state: dict) -> str:
    status = str(state.get("status") or "").lower()
    if state.get("video_url") or status in {"success", "succeeded", "completed"}:
        return "ready"
    if status in {"failed", "error", "canceled", "cancelled"}:
        return "failed"
    if status in {"queued", "running", ""}:
        return "pending"
    return "unknown"
