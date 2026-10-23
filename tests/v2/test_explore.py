"""Exploration through the API: an agent builds a work, generates, checks and edits; people audit."""

from __future__ import annotations

from fastapi.testclient import TestClient

from server.app import app
from server.samples import seed_samples

from .conftest import make_user, run_worker


def _shot(agent, work_id: str, title: str = "背她之前", duration: int = 5) -> str:
    return agent.post(f"/api/works/{work_id}/entities", {"type": "Shot", "data": {
        "title": title, "size": "中景", "angle": "平视", "action": "零号把纱布绕两圈", "duration": duration,
    }})["id"]


def test_agent_builds_and_generates(admin, agent, fresh, mock_providers):
    seed_samples(fresh["workspace_id"])
    work = agent.post("/api/works", {"workspace_id": fresh["workspace_id"], "title": "雪原测试"})
    shot = _shot(agent, work["id"])
    agent.post(f"/api/works/{work['id']}/links", {"name": "styled_as", "source": shot, "target": "asset:style-snow-film@1"})
    agent.post(f"/api/works/{work['id']}/links", {"name": "references", "source": shot, "target": "asset:ref-zero-space@1"})
    duplicate = agent.post(f"/api/works/{work['id']}/links", {"name": "references", "source": shot,
                                                              "target": "asset:ref-zero-space@1"})
    assert duplicate["duplicate"] is True
    agent.request("POST", f"/api/works/{work['id']}/links", json={"name": "styled_as", "source": shot,
                                                                   "target": "asset:place-siberia-snow@1"}, expect=400)
    composed = agent.get(f"/api/entities/{shot}/compose")
    assert composed["can_submit"] and "空镜雪原" in composed["prompt"]

    task = agent.post(f"/api/works/{work['id']}/tasks", {"kind": "video", "input": {"shot_id": shot}})
    assert task["status"] == "ready"
    again = agent.request("POST", f"/api/works/{work['id']}/tasks", json={"kind": "video", "input": {"shot_id": shot}},
                          expect=409)
    assert "未完成" in again.json()["detail"]
    assert run_worker() >= 1
    done = agent.get(f"/api/tasks/{task['id']}")
    assert done["status"] == "succeeded", done
    output = done["output"]
    assert output["clip_id"] and output["url"].startswith("/media/") and output["sheet_url"] and output["last_frame_url"]
    assert output["cost_yuan"] == 2.5

    anonymous = TestClient(app)
    assert anonymous.get(output["url"]).status_code == 200
    assert anonymous.get(f"/media/{output['artifact_id']}").status_code == 401
    assert anonymous.get(output["url"].replace("sig=", "sig=0")).status_code == 401

    agent.request("POST", f"/api/works/{work['id']}/tasks", json={"kind": "video", "input": {"shot_id": shot}}, expect=409)
    regenerated = agent.post(f"/api/works/{work['id']}/tasks", {"kind": "video", "again": True, "input": {"shot_id": shot}})
    assert regenerated["status"] == "ready"

    board = admin.get(f"/api/works/{work['id']}/storyboard")
    assert board["shots"][0]["clips"][0]["artifact"]["url"]
    assert board["shots"][0]["cost_yuan"] == 2.5

    reviewer = make_user(admin, "rev", "reviewer")
    activity = reviewer.get(f"/api/activity?work_id={work['id']}")["items"]
    actions = {item["action"] for item in activity}
    assert {"work.create", "entity.create", "link.create", "task.create"} <= actions
    assert any(item["actor_kind"] == "device" for item in activity)


def test_finished_explore_video_estimates_the_next_queued_one(admin, agent, fresh, mock_providers):
    """A completed 5s explore generate must estimate the next identical queued generate.

    The create path used to store only shot_id. prepare_video then wrote duration
    onto the finished row, so GET /api/queue left the next copy at eta_seconds null.
    """
    seed_samples(fresh["workspace_id"])
    work = agent.post("/api/works", {"workspace_id": fresh["workspace_id"], "title": "历史签名"})
    shot = _shot(agent, work["id"], duration=5)
    agent.post(f"/api/works/{work['id']}/links", {"name": "references", "source": shot, "target": "asset:ref-zero-space@1"})
    first = agent.post(f"/api/works/{work['id']}/tasks", {
        "kind": "video", "provider": "video.default", "input": {"shot_id": shot},
    })
    assert first["status"] == "ready"
    assert first["timeout_seconds"] == 1800
    queued = admin.get(f"/api/tasks/{first['id']}")
    request = queued["input"]["request"]
    assert request["duration"] == 5
    assert request["resolution"] == "768p横"
    assert request["template"] == ""
    assert queued["eta_seconds"] is None
    assert run_worker() >= 1
    done = admin.get(f"/api/tasks/{first['id']}")
    assert done["status"] == "succeeded", done
    assert done["input"]["request"]["duration"] == 5
    second = agent.post(f"/api/works/{work['id']}/tasks", {
        "kind": "video", "provider": "video.default", "again": True, "input": {"shot_id": shot},
    })
    assert second["status"] == "ready"
    overview = admin.get("/api/queue")
    ready = {item["id"]: item for item in overview["ready"]}
    assert ready[second["id"]]["queue_position"] == 1
    assert ready[second["id"]]["eta_seconds"] is not None
    assert ready[second["id"]]["eta_seconds"] != 1800
    assert ready[second["id"]]["eta_seconds"] < 60
    detail = admin.get(f"/api/tasks/{second['id']}")
    assert detail["eta_seconds"] == ready[second["id"]]["eta_seconds"]
    assert detail["input"]["request"]["duration"] == 5


def test_compose_warning_blocks_until_forced(agent, fresh, mock_providers):
    seed_samples(fresh["workspace_id"])
    work = agent.post("/api/works", {"workspace_id": fresh["workspace_id"], "title": "警告"})
    shot = _shot(agent, work["id"])
    task = agent.post(f"/api/works/{work['id']}/tasks", {"kind": "video", "input": {"shot_id": shot}})
    run_worker()
    failed = agent.get(f"/api/tasks/{task['id']}")
    assert failed["status"] == "failed" and "不能提交" in failed["error"]
    assert failed["attempts"] == 1


def test_image_then_edit_and_check(agent, fresh, mock_providers):
    seed_samples(fresh["workspace_id"])
    work = agent.post("/api/works", {"workspace_id": fresh["workspace_id"], "title": "剪辑"})
    shots = [_shot(agent, work["id"], f"镜头{index}") for index in range(2)]
    for shot in shots:
        agent.post(f"/api/works/{work['id']}/tasks", {"kind": "image", "input": {"shot_id": shot, "role": "首帧"}})
    run_worker()
    for shot in shots:
        entity = agent.get(f"/api/entities/{shot}")
        assert any(link["name"] == "references" for link in entity["links"])
        agent.post(f"/api/works/{work['id']}/tasks", {"kind": "video", "input": {"shot_id": shot}})
    run_worker()
    clips = [task["output"]["clip_id"] for task in agent.get(f"/api/tasks?work_id={work['id']}&status=succeeded")["items"]
             if task["kind"] == "video"]
    assert len(clips) == 2
    check = agent.post(f"/api/works/{work['id']}/tasks", {"kind": "check", "input": {"clip_id": clips[0]}})
    edit = agent.post(f"/api/works/{work['id']}/tasks", {"kind": "edit", "input": {
        "clips": clips, "fade": 0.5, "music": "asset:music-bright-bed@1", "export": "768p横", "title": "测试成片"}})
    run_worker()
    checked = agent.get(f"/api/tasks/{check['id']}")["output"]
    assert checked["passed"] is True, checked
    edited = agent.get(f"/api/tasks/{edit['id']}")
    assert edited["status"] == "succeeded", edited["error"]
    assert 9.5 < edited["output"]["duration"] < 10.5


def test_approval_threshold_parks_agent_tasks(admin, agent, fresh, mock_providers):
    admin.patch("/api/admin/settings", {"approval_threshold_yuan": 1})
    seed_samples(fresh["workspace_id"])
    work = agent.post("/api/works", {"workspace_id": fresh["workspace_id"], "title": "审批"})
    shot = _shot(agent, work["id"])
    agent.post(f"/api/works/{work['id']}/links", {"name": "references", "source": shot, "target": "asset:ref-zero-space@1"})
    task = agent.post(f"/api/works/{work['id']}/tasks", {"kind": "video", "input": {"shot_id": shot}})
    assert task["status"] == "needs_attention" and "审批阈值" in task["attention"]
    assert run_worker() == 0
    producer = make_user(admin, "pro", "producer")
    producer.request("POST", f"/api/tasks/{task['id']}/resolve", json={"action": "approve"}, expect=403)
    reviewer = make_user(admin, "rev", "reviewer")
    reviewer.post(f"/api/tasks/{task['id']}/resolve", {"action": "approve"})
    run_worker()
    assert agent.get(f"/api/tasks/{task['id']}")["status"] == "succeeded"


def test_cancel_ready_task(agent, fresh, mock_providers):
    seed_samples(fresh["workspace_id"])
    work = agent.post("/api/works", {"workspace_id": fresh["workspace_id"], "title": "取消"})
    task = agent.post(f"/api/works/{work['id']}/tasks", {"kind": "music", "input": {"prompt": "轻快"}})
    canceled = agent.post(f"/api/tasks/{task['id']}/cancel")
    assert canceled["status"] == "canceled"
    assert run_worker() == 0
    retried = agent.post(f"/api/tasks/{task['id']}/retry")
    run_worker()
    assert agent.get(f"/api/tasks/{retried['id']}")["status"] == "succeeded"
