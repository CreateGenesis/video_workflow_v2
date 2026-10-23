"""Queue mechanics: slots, ordering, leases, resume without resubmission, parking, retries, cancel."""

from __future__ import annotations

import time
from datetime import timedelta

import pytest
from sqlalchemy import insert, select, update

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


def _music(work: dict, pool: str = "local", priority: int = 0, sort_key: str = "", kind: str = "music", **kwargs) -> dict:
    with db.tx() as conn:
        payload = kwargs.pop("input", {"prompt": "测试"})
        provider = kwargs.pop("provider_instance", "music.default")
        return task_q.create(conn, SYSTEM, workspace_id=work["workspace_id"], kind=kind, pool=pool,
                             input=payload, work_id=work["work_id"], provider_instance=provider,
                             priority=priority, sort_key=sort_key, **kwargs)


def _claim(pools=None):
    with db.tx() as conn:
        return task_q.claim(conn, "w1", pools)


def _finish(task: dict, *, seconds: int, provider: str, template: str, resolution: str, duration: int,
           via: str = "flat") -> None:
    """Record a succeeded task whose wall time and signature the ETA query can read.

    `via` is `flat` for exploration input, `request` for the fields prepare_video writes
    after composing a shot, or `node` for a workflow node spec.
    """
    if via == "request":
        payload = {"request": {"template": template, "resolution": resolution, "duration": duration}}
    elif via == "node":
        payload = {"node": {"template": template, "resolution": resolution, "duration_seconds": duration}}
    else:
        payload = {"template": template, "resolution": resolution, "duration": duration, "prompt": "历史"}
    with db.tx() as conn:
        conn.execute(update(db.tasks).where(db.tasks.c.id == task["id"]).values(
            status="succeeded",
            provider_instance=provider,
            input=payload,
            started_at=db.now() - timedelta(seconds=seconds),
            finished_at=db.now(),
        ))


def test_queue_overview_reports_pool_eta(admin, work):
    """§6.5: estimated completion is queue position × historical duration of the same group.

    A ready 5-second video with no matching history must not be labeled with its 1800s timeout.
    Two prior runs of the same provider, template, resolution and duration (10s and 20s) make
    the average 15s, so the first queued task is 15s and the second is 30s.
    """
    with db.tx() as conn:
        instances.set_pool(conn, SYSTEM, "local", concurrency=1)
    same = {"provider": "video.default", "template": "asset:comfy-wan@1", "resolution": "768p横", "duration": 5}
    other = {"provider": "video.other", "template": "asset:comfy-wan@1", "resolution": "768p横", "duration": 5}
    for seconds in (10, 20):
        done = _music(work, pool="local", provider_instance=same["provider"])
        _finish(done, seconds=seconds, **same)
    # A different provider must not leak into the group average.
    foreign = _music(work, pool="local", provider_instance=other["provider"])
    _finish(foreign, seconds=600, **other)
    first = _music(work, pool="local", sort_key="a", timeout_seconds=1800, provider_instance=same["provider"],
                   input={"template": same["template"], "resolution": same["resolution"], "duration": 5, "prompt": "排队"})
    second = _music(work, pool="local", sort_key="b", timeout_seconds=1800, provider_instance=same["provider"],
                    input={"template": same["template"], "resolution": same["resolution"], "duration": 5, "prompt": "排队"})
    unknown = _music(work, pool="local", sort_key="c", timeout_seconds=1800, provider_instance="video.fresh",
                     input={"template": same["template"], "resolution": same["resolution"], "duration": 5, "prompt": "无历史"})
    overview = admin.get("/api/queue")
    pools = {pool["name"]: pool for pool in overview["pools"]}
    local = pools["local"]
    assert local["busy"] == 0
    assert local["ready"] == 3
    # Position 2 × 15s average. The 1800s timeout is not the estimate.
    assert local["eta_seconds"] == 30
    ready = {task["id"]: task for task in overview["ready"]}
    assert ready[first["id"]]["queue_position"] == 1
    assert ready[first["id"]]["eta_seconds"] == 15
    assert ready[second["id"]]["queue_position"] == 2
    assert ready[second["id"]]["eta_seconds"] == 30
    assert ready[unknown["id"]]["eta_seconds"] is None
    assert ready[unknown["id"]]["timeout_seconds"] == 1800
    # Shipped queue rows use position × same-group average. 1800 // concurrency is not an estimate.
    assert ready[first["id"]]["eta_seconds"] == 1 * 15
    assert ready[second["id"]]["eta_seconds"] == 2 * 15
    assert ready[first["id"]]["eta_seconds"] != 1800
    assert ready[second["id"]]["eta_seconds"] != 1800
    detail = admin.get(f"/api/tasks/{first['id']}")
    assert detail["eta_seconds"] == 15
    assert detail["queue_position"] == 1
    claimed = _claim(["local"])
    assert claimed["id"] == first["id"]
    after = admin.get("/api/queue")
    after_local = next(pool for pool in after["pools"] if pool["name"] == "local")
    assert after_local["busy"] == 1
    assert after_local["ready"] == 2
    # The remaining matched task is now position 1, so the pool wait drops to 15s.
    assert after_local["eta_seconds"] == 15
    assert any(task["id"] == claimed["id"] for task in after["active"])
    # Two slots run the first two positions in one wave. A 5s video is not labeled 30 分钟.
    with db.tx() as conn:
        instances.set_pool(conn, SYSTEM, "local", concurrency=2)
    parallel = admin.get("/api/queue")
    parallel_local = next(pool for pool in parallel["pools"] if pool["name"] == "local")
    assert parallel_local["eta_seconds"] == 15
    parallel_ready = {task["id"]: task for task in parallel["ready"]}
    assert parallel_ready[second["id"]]["eta_seconds"] == 15


def test_run_eta_uses_position_times_history(admin, fresh, mock_providers):
    """GET /api/runs/{id} reports the longest ready-task wait, not the sum of timeouts.

    A published workflow materializes the video node. History of the same provider,
    template, resolution and duration (9s and 21s, average 15s) makes the queued clip
    15 seconds. The node's 3600s timeout must not appear as the estimate. A second
    ready task with a different template stays unestimated and does not inflate the run.
    """
    from server import graph
    from server.samples import ZERO_FIXTURE, seed_samples

    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["zero-snow"]["workflow_id"]
    admin.post(f"/api/workflows/{workflow_id}/versions/1/publish")
    with db.tx() as conn:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == "llm.default")
                     .values(options={"replies": {"adapt": ZERO_FIXTURE}}))
        instances.set_pool(conn, SYSTEM, "autodl-h3", concurrency=1, paused=True)
    # zero-snow's video node stores resolution on the node and leaves template empty.
    # Duration comes from the shot the executor composes (the fixture is 15s).
    template = ""
    resolution = "768p横"
    duration = 15
    with db.tx() as conn:
        history_work = graph.create_work(conn, SYSTEM, fresh["workspace_id"], "历史耗时")
    history_scope = {"workspace_id": fresh["workspace_id"], "work_id": history_work["id"]}
    for seconds, via in ((9, "request"), (21, "node")):
        done = _music(history_scope, kind="video", pool="autodl-h3", provider_instance="video.autodl-h3")
        _finish(done, seconds=seconds, provider="video.autodl-h3", template=template,
                resolution=resolution, duration=duration, via=via)
    run = admin.post("/api/runs", {"workflow_id": workflow_id, "inputs": {"passage": "雪原上他替她包好脚"}})
    run_worker(limit=8)
    with db.tx() as conn:
        instances.set_pool(conn, SYSTEM, "autodl-h3", paused=False)
    detail = admin.get(f"/api/runs/{run['id']}")
    clip = next(node for node in detail["nodes"] if node["id"] == "clip")["tasks"][0]
    assert clip["status"] == "ready", clip
    assert clip["timeout_seconds"] == 3600
    assert clip["pool"] == "autodl-h3"
    with db.tx() as conn:
        stored = dict(conn.execute(select(db.tasks).where(db.tasks.c.id == clip["id"])).mappings().one())
        from server.engine.eta import historical_average, signature

        assert signature(stored) == ("video.autodl-h3", template, resolution, str(duration)), stored.get("input")
        average = historical_average(conn, stored)
        assert average is not None and round(average) == 15, signature(stored)
    # The page reads this field. Position 1 × 15s average. 3600 is the deadline, not the ETA.
    assert detail["progress"]["ready"] >= 1
    assert detail["progress"]["eta_seconds"] == 15
    assert detail["progress"]["eta_seconds"] != 3600
    task = admin.get(f"/api/tasks/{clip['id']}")
    assert task["queue_position"] == 1
    assert task["eta_seconds"] == 15
    assert task["timeout_seconds"] == 3600
    # A queued sibling with another template must not turn the run estimate into a timeout sum.
    sibling = _music(history_scope, pool="autodl-h3", provider_instance="video.autodl-h3", sort_key="z",
                     timeout_seconds=3600,
                     input={"node": {"template": "asset:other@1", "resolution": resolution, "duration_seconds": duration}})
    with db.tx() as conn:
        conn.execute(update(db.tasks).where(db.tasks.c.id == sibling["id"]).values(run_id=run["id"], node_id="other"))
    again = admin.get(f"/api/runs/{run['id']}")
    assert again["progress"]["eta_seconds"] == 15
    unmatched = admin.get(f"/api/tasks/{sibling['id']}")
    assert unmatched["eta_seconds"] is None
    assert unmatched["timeout_seconds"] == 3600


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


def test_pool_concurrency_above_64_is_rejected(admin, work):
    """The editor and the server share the same 0–64 limit. A rejected save must not look applied."""
    before = admin.get("/api/admin/pools")
    previous = next(pool for pool in before["items"] if pool["name"] == "local")["concurrency"]
    rejected = admin.request("PATCH", "/api/admin/pools/local", expect=400, json={"concurrency": 65})
    assert "64" in rejected.json()["detail"]
    kept = admin.get("/api/admin/pools")
    local = next(pool for pool in kept["items"] if pool["name"] == "local")
    assert local["concurrency"] == previous
    accepted = admin.patch("/api/admin/pools/local", {"concurrency": 4, "note": "上限内"})
    assert accepted["concurrency"] == 4


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


def test_parallel_workers_finish_runs_without_internal_errors(admin, fresh, mock_providers):
    """Several workers finishing tasks of the same runs at once: no deadlock, nothing double-run."""
    import threading

    from server.engine.worker import Worker
    from server.samples import ZERO_FIXTURE, seed_samples
    from tests.v2.test_workflow_runs import _upload

    seeded = seed_samples(fresh["workspace_id"])
    zero = seeded["workflows"]["zero-snow"]["workflow_id"]
    product = seeded["workflows"]["product-ad"]["workflow_id"]
    for workflow_id in (zero, product):
        admin.post(f"/api/workflows/{workflow_id}/versions/1/publish")
    with db.tx() as conn:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == "llm.default")
                     .values(options={"replies": {"adapt": ZERO_FIXTURE}}))
        instances.set_pool(conn, SYSTEM, "gpu", concurrency=2)
    image = _upload(admin, fresh["workspace_id"])
    runs = [admin.post("/api/runs", {"workflow_id": zero, "inputs": {"passage": str(index)}})["id"] for index in range(2)]
    runs += [admin.post("/api/runs", {"workflow_id": product, "auto_gates": True, "inputs": {
        "product": "杯", "facts": ["保温"], "inspiration": "冬", "product_images": [image]}})["id"] for _ in range(2)]
    threads = [threading.Thread(target=Worker(f"w{index}").run_until_idle) for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)
    run_worker()
    with db.tx() as conn:
        statuses = {row.id: row.status for row in conn.execute(select(db.runs.c.id, db.runs.c.status))}
        errors = [row.error for row in conn.execute(select(db.tasks.c.error)) if row.error]
        attempts = [row.attempts for row in conn.execute(select(db.tasks.c.attempts).where(db.tasks.c.kind == "video"))]
    assert set(statuses.values()) == {"succeeded"}, statuses
    assert errors == []
    assert set(attempts) == {1}
