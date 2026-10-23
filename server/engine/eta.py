"""Estimated completion from queue position and historical duration.

§6.5: 预计完成时间 = 当前队列位置 × 历史平均耗时.
History is grouped by (provider instance, template, resolution, duration).
A missing group has no estimate. The task timeout is a deadline, not a duration.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

from . import tasks as task_q

HISTORY_LIMIT = 20


def signature(task: dict) -> tuple:
    """Stable group key: provider instance, template, resolution, duration.

    A queued workflow task stores the node spec under input.node. The executor
    writes the request it actually submitted under input.request (template asset
    ref, resolution, duration). History matches either shape, so a finished run
    estimates the next queued copy of the same node. The task timeout is not a
    member of this key.
    """
    payload = task.get("input") or {}
    node = payload.get("node") if isinstance(payload.get("node"), dict) else {}
    request = payload.get("request") if isinstance(payload.get("request"), dict) else {}
    template = request.get("template") or node.get("template") or payload.get("template") or ""
    resolution = request.get("resolution") or node.get("resolution") or payload.get("resolution") or ""
    duration = request.get("duration")
    if duration is None:
        duration = node.get("duration_seconds")
    if duration is None:
        duration = node.get("duration")
    if duration is None:
        duration = payload.get("duration")
    return (
        task.get("provider_instance") or "",
        str(template or ""),
        str(resolution or ""),
        "" if duration in (None, "") else str(duration),
    )


def _elapsed_seconds(row) -> float | None:
    started = row["started_at"]
    finished = row["finished_at"]
    if not started or not finished:
        return None
    seconds = (finished - started).total_seconds()
    if seconds <= 0:
        return None
    return seconds


def historical_average(conn: Connection, task: dict, cache: dict | None = None) -> float | None:
    """Mean wall time of recent succeeded tasks in the same signature group (memoized per request in `cache`)."""
    key = (signature(task), task.get("kind") or "", task.get("pool") or "")
    if cache is not None and key in cache:
        return cache[key]
    value = _historical_average(conn, task)
    if cache is not None:
        cache[key] = value
    return value


def _historical_average(conn: Connection, task: dict) -> float | None:
    provider, template, resolution, duration = signature(task)
    rows = conn.execute(text("""
        SELECT started_at, finished_at, input
        FROM tasks
        WHERE status = 'succeeded'
          AND started_at IS NOT NULL
          AND finished_at IS NOT NULL
          AND finished_at > started_at
          AND coalesce(provider_instance, '') = :provider
          AND kind = :kind
          AND pool = :pool
        ORDER BY finished_at DESC
        LIMIT 200
    """), {
        "provider": provider,
        "kind": task.get("kind") or "",
        "pool": task.get("pool") or "",
    }).mappings().all()
    samples = []
    for row in rows:
        if signature({"provider_instance": provider, "input": row["input"] or {}}) != (provider, template, resolution, duration):
            continue
        elapsed = _elapsed_seconds(row)
        if elapsed is None:
            continue
        samples.append(elapsed)
        if len(samples) >= HISTORY_LIMIT:
            break
    if not samples:
        return None
    return sum(samples) / len(samples)


def _concurrency(conn: Connection, pool: str) -> int:
    value = conn.execute(text("SELECT concurrency FROM pools WHERE name = :pool"), {"pool": pool}).scalar()
    return max(int(value or 1), 1)


def waves_ahead(position: int, concurrency: int) -> int:
    """How many historical durations a task at this 1-based position still waits.

    One slot runs one task at a time, so position 1 waits one duration and
    position 2 waits two. Extra slots run those positions together: with two
    slots, positions 1 and 2 both wait one duration.
    """
    slots = max(int(concurrency or 1), 1)
    return ((max(int(position), 1) - 1) // slots) + 1


def task_eta_seconds(conn: Connection, task: dict, cache: dict | None = None) -> int | None:
    """Queue waves × historical average. None when the task is not queued or has no history.

    §6.5 states position × historical duration. A pool with one slot is exactly
    that. Extra slots divide the position into parallel waves so two free slots
    do not serialize the first two queued tasks.
    """
    position = task_q.queue_position(conn, task)
    if not position:
        return None
    average = historical_average(conn, task, cache)
    if average is None:
        return None
    waves = waves_ahead(position, _concurrency(conn, task.get("pool") or ""))
    return max(1, int(round(waves * average)))


def pool_eta_seconds(conn: Connection, pool: str, cache: dict | None = None) -> int | None:
    """Wait until the current ready queue of this pool is expected to clear.

    Each ready task waits (position × group average). The pool estimate is the
    longest of those waits, which is when the last queued task should start
    plus one historical duration. Tasks with no history do not invent a number.
    """
    rows = conn.execute(text("""
        SELECT * FROM tasks
        WHERE pool = :pool AND status = 'ready'
    """), {"pool": pool}).mappings().all()
    if not rows:
        return 0
    waits = []
    for row in rows:
        eta = task_eta_seconds(conn, dict(row), cache)
        if eta is not None:
            waits.append(eta)
    if not waits:
        return None
    return max(waits)


def run_eta_seconds(conn: Connection, tasks: list[dict], cache: dict | None = None) -> int | None:
    """Longest estimated wait among this run's ready tasks. None if none have history."""
    waits = []
    for task in tasks:
        if task.get("status") != "ready":
            continue
        eta = task_eta_seconds(conn, task, cache if cache is not None else {})
        if eta is not None:
            waits.append(eta)
    if not waits:
        return None
    return max(waits)
