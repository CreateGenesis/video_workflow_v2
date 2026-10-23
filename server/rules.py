"""Pure checks shared by executors."""

from __future__ import annotations

RESOLUTION_SIZE = {
    "480p横": (854, 480),
    "480p竖": (480, 854),
    "768p横": (1366, 768),
    "768p竖": (768, 1366),
    "480p(1:1)": (480, 480),
    "768p(1:1)": (768, 768),
}


def shell_forbidden(args: list[str]) -> bool:
    tokens = (";", "|", "`", "\n", "$(", "&&")
    return any(any(token in arg for token in tokens) for arg in args)


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
