"""Queue mechanics: slots, ordering, leases, resume without resubmission, parking, retries, cancel."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from server import db
from server.auth import SYSTEM
from server.engine import tasks as task_q
from server.engine.executor import execute
from server.providers import instances, mock
from server.providers.base import SubmissionUnknown

from .conftest import run_worker


@pytest.fixture()
def work(fresh, mock_providers):
    from server import graph

    with db.tx() as conn:
        work = graph.create_work(conn, SYSTEM, fresh["workspace_id"], "引擎")
    return {"workspace_id": fresh["workspace_id"], "work_id": work["id"]}


def _music(work: dict, pool: str = "local", priority: int = 0, sort_key: str = "", **kwargs) -> dict:
    with db.tx() as conn:
        return task_q.create(conn, SYSTEM, workspace_id=work["workspace_id"], kind="music", pool=pool,
                             input={"prompt": "测试"}, work_id=work["work_id"], provider_instance="music.default",
                             priority=priority, sort_key=sort_key, **kwargs)


def _claim(pools=None):
    with db.tx() as conn:
        return task_q.claim(conn, "w1", pools)


def test_slots_cap_concurrency_and_priority_orders(work):
    with db.tx() as conn:
        instances.set_pool(conn, SYSTEM, "local", concurrency=1)
    low = _music(work, sort_key="b")
    high = _music(work, priority=5, sort_key="c")
    first_sorted = _music(work, sort_key="a")
    claimed = _claim(["local"])
    assert claimed["id"] == high["id"] and claimed["slot"] == 0
    assert _claim(["local"]) is None
    execute(claimed, "w1")
    assert _claim(["local"])["id"] == first_sorted["id"]
    assert low["status"] == "ready"


def test_paused_pool_is_not_claimed(work):
    with db.tx() as conn:
        instances.set_pool(conn, SYSTEM, "local", paused=True)
    _music(work)
    assert _claim() is None
    with db.tx() as conn:
        instances.set_pool(conn, SYSTEM, "local", paused=False)
    assert _claim() is not None


def test_expired_lease_is_recovered(work):
    task = _music(work)
    claimed = _claim()
    with db.tx() as conn:
        conn.execute(update(db.tasks).where(db.tasks.c.id == claimed["id"]).values(
            lease_expires_at=db.now() - timedelta(seconds=5)))
        result = task_q.janitor(conn)
        assert result["requeued"] == 1
        row = task_q.get(conn, task["id"])
        assert row["status"] == "ready"
        assert conn.execute(select(db.pool_slots.c.task_id).where(db.pool_slots.c.task_id == task["id"])).first() is None


def _reference(conn, work: dict) -> str:
    import subprocess
    import tempfile
    from pathlib import Path

    from server import artifacts, graph

    path = Path(tempfile.mkdtemp()) / "ref.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=64x64", "-frames:v", "1",
                    str(path)], check=True)
    artifact = artifacts.store_file(conn, work["workspace_id"], path, prefix="test")
    return graph.add_entity(conn, SYSTEM, work["work_id"], "Reference", {"title": "空间", "role": "空间"},
                            artifact_id=artifact["id"])["id"]


def _video_task(work: dict, provider: str) -> dict:
    from server import graph

    with db.tx() as conn:
        shot = graph.add_entity(conn, SYSTEM, work["work_id"], "Shot", {"title": "s", "size": "中景", "angle": "平视",
                                                                       "action": "走", "duration": 5})
        graph.add_link(conn, SYSTEM, work["work_id"], "references", shot["id"], _reference(conn, work))
        return task_q.create(conn, SYSTEM, workspace_id=work["workspace_id"], kind="video",
                             pool=instances.get_row(conn, provider).pool, input={"shot_id": shot["id"], "allow_warnings": True},
                             work_id=work["work_id"], provider_instance=provider, retry_safe=provider != "video.autodl-h3")


def test_submitted_task_resumes_without_resubmitting(work):
    task = _video_task(work, "video.default")
    claimed = _claim()
    ref = {"mock_id": task["id"], "started": time.time() - 100, "duration": 5, "resolution": "768p横",
           "_instance": "video.default"}
    with db.tx() as conn:
        task_q.set_status(conn, claimed["id"], "submitted", provider_ref=ref, submitted_at=db.now(),
                          lease_expires_at=db.now() - timedelta(seconds=1))
    mock.reset()
    assert run_worker() == 1
    with db.tx() as conn:
        row = task_q.get(conn, task["id"])
    assert row["status"] == "succeeded", row["error"]
    assert mock._SUBMISSIONS == {}
    assert row["output"]["artifact_id"]


def test_crash_while_submitting_to_paid_provider_parks(work):
    task = _video_task(work, "video.autodl-h3")
    claimed = _claim()
    with db.tx() as conn:
        task_q.set_status(conn, claimed["id"], "submitting", lease_expires_at=db.now() - timedelta(seconds=1))
        assert task_q.janitor(conn)["parked"] == 1
        row = task_q.get(conn, task["id"])
    assert row["status"] == "needs_attention" and "不知道上游是否已受理" in row["attention"]
    with db.tx() as conn, pytest.raises(ValueError):
        task_q.resolve_attention(conn, SYSTEM, task["id"], "requery")
    with db.tx() as conn:
        task_q.resolve_attention(conn, SYSTEM, task["id"], "resubmit")
    run_worker()
    with db.tx() as conn:
        assert task_q.get(conn, task["id"])["status"] == "succeeded"


def test_submission_unknown_parks_paid_and_retries_safe(work, monkeypatch):
    def unsure(self, request, ctx):
        raise SubmissionUnknown("网络断了")

    monkeypatch.setattr(mock.MockAdapter, "submit", unsure)
    paid = _video_task(work, "video.autodl-h3")
    safe = _video_task(work, "video.default")
    with db.tx() as conn:
        conn.execute(update(db.tasks).where(db.tasks.c.id == safe["id"]).values(max_attempts=2, backoff_seconds=3600))
    run_worker()
    with db.tx() as conn:
        assert task_q.get(conn, paid["id"])["status"] == "needs_attention"
        retried = task_q.get(conn, safe["id"])
    assert retried["status"] == "ready" and retried["attempts"] == 1 and retried["ready_at"] > db.now()


def test_retry_then_success(work):
    with db.tx() as conn:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == "music.default")
                     .values(options={"fail_times": 1}))
    task = _music(work, max_attempts=3, backoff_seconds=0)
    run_worker()
    with db.tx() as conn:
        row = task_q.get(conn, task["id"])
    assert row["status"] == "succeeded" and row["attempts"] == 2


def test_cancel_while_rendering(work):
    with db.tx() as conn:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == "video.default")
                     .values(options={"delay_seconds": 30}))
    task = _video_task(work, "video.default")
    claimed = _claim()
    import threading

    thread = threading.Thread(target=execute, args=(claimed, "w1"))
    thread.start()
    for _ in range(50):
        with db.tx() as conn:
            if task_q.get(conn, task["id"])["status"] == "submitted":
                task_q.request_cancel(conn, SYSTEM, task["id"])
                break
        time.sleep(0.1)
    thread.join(timeout=20)
    with db.tx() as conn:
        row = task_q.get(conn, task["id"])
        free = conn.execute(select(db.pool_slots.c.task_id).where(db.pool_slots.c.task_id == task["id"])).first()
    assert row["status"] == "canceled" and free is None


def test_queue_order_follows_runs(admin, fresh, mock_providers):
    """GPU pool of one: the earlier run's video starts first (run_first)."""
    from server.samples import ZERO_FIXTURE, seed_samples

    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["zero-snow"]["workflow_id"]
    admin.post(f"/api/workflows/{workflow_id}/versions/1/publish")
    with db.tx() as conn:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == "llm.default")
                     .values(options={"replies": {"adapt": ZERO_FIXTURE}}))
    first = admin.post("/api/runs", {"workflow_id": workflow_id, "inputs": {"passage": "一"}})
    second = admin.post("/api/runs", {"workflow_id": workflow_id, "inputs": {"passage": "二"}})
    run_worker()
    with db.tx() as conn:
        started = {row.run_id: row.started_at for row in conn.execute(
            select(db.tasks.c.run_id, db.tasks.c.started_at).where(db.tasks.c.kind == "video"))}
    assert started[first["id"]] < started[second["id"]]
