"""Published workflows run end to end on mock providers: gates, retries, reruns, budgets, batches."""

from __future__ import annotations

import io
import json
from pathlib import Path

from sqlalchemy import select, update

from server import db
from server.samples import ZERO_FIXTURE, seed_samples

from .conftest import make_user, run_worker

GOLDEN = json.loads((Path(__file__).parents[1] / "golden" / "zero_shot_768p.json").read_text(encoding="utf-8"))


def _publish(admin, workflow_id: str, version: int = 1) -> dict:
    admin.post(f"/api/workflows/{workflow_id}/versions/{version}/validate")
    return admin.post(f"/api/workflows/{workflow_id}/versions/{version}/publish")


def _upload(api, workspace_id: str, label: str = "产品正面") -> str:
    import subprocess
    import tempfile

    path = Path(tempfile.mkdtemp()) / "product.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=320x240", "-frames:v", "1",
                    str(path)], check=True)
    response = api.request("POST", "/api/uploads", data={"workspace_id": workspace_id, "label": label},
                           files={"file": ("product.png", io.BytesIO(path.read_bytes()), "image/png")})
    return response.json()["id"]


def _set_llm_reply(node_id: str, reply: dict) -> None:
    with db.tx() as conn:
        conn.execute(update(db.provider_instances).where(db.provider_instances.c.name == "llm.default")
                     .values(options={"replies": {node_id: reply}}))


def test_zero_snow_runs_and_sends_the_v1_prompt(admin, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["zero-snow"]["workflow_id"]
    _publish(admin, workflow_id)
    _set_llm_reply("adapt", ZERO_FIXTURE)
    producer = make_user(admin, "pro", "producer")
    run = producer.post("/api/runs", {"workflow_id": workflow_id, "inputs": {"passage": "雪原上他替她包好脚"}})
    assert run["status"] == "running"
    run_worker()
    detail = producer.get(f"/api/runs/{run['id']}")
    assert detail["status"] == "succeeded", detail.get("error")
    video = next(node for node in detail["nodes"] if node["id"] == "clip")["tasks"][0]
    assert video["output"]["prompt"] == GOLDEN["prompt"]
    assert detail["outputs"]["video"][0]["url"]
    assert detail["cost_actual"] > 0
    with db.tx() as conn:
        llm_task = conn.execute(select(db.tasks).where(db.tasks.c.run_id == run["id"], db.tasks.c.kind == "llm")).mappings().one()
    assert llm_task["output"]["attempts"] == 1 and "shot" in llm_task["output"]["entities"]


def test_product_ad_gate_selection_and_final_cut(admin, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["product-ad"]["workflow_id"]
    _publish(admin, workflow_id)
    reviewer = make_user(admin, "rev", "reviewer")
    producer = make_user(admin, "pro", "producer")
    image = _upload(producer, fresh["workspace_id"])
    inputs = {"product": "暖杯", "facts": ["三秒加热", "可机洗"], "inspiration": "冬天早晨", "product_images": [image]}
    run = producer.post("/api/runs", {"workflow_id": workflow_id, "inputs": inputs})
    run_worker()
    detail = producer.get(f"/api/runs/{run['id']}")
    assert detail["status"] == "waiting", detail.get("error")
    gate = next(node for node in detail["nodes"] if node["id"] == "review")["tasks"][0]
    assert gate["status"] == "waiting"
    keyframes = next(node for node in detail["nodes"] if node["id"] == "keyframes")["tasks"]
    assert len(keyframes) == 2 and all(len(task["output"]["candidates"]) == 2 for task in keyframes)
    clips = next(node for node in detail["nodes"] if node["id"] == "clips")["tasks"]
    assert all(task["status"] == "blocked" for task in clips)

    producer.request("POST", f"/api/gates/{gate['id']}", json={"decision": "approve"}, expect=403)
    second_candidate = keyframes[0]["output"]["candidates"][1]["entity_id"]
    reviewer.post(f"/api/gates/{gate['id']}", {"decision": "approve", "note": "第一镜用第二张",
                                               "selections": {keyframes[0]["item"]: second_candidate}})
    run_worker()
    detail = producer.get(f"/api/runs/{run['id']}")
    assert detail["status"] == "succeeded", detail.get("error")
    first_clip = next(node for node in detail["nodes"] if node["id"] == "clips")["tasks"][0]
    assert first_clip["output"]["references"][-1].endswith("候选 2")
    final = detail["outputs"]["video"][0]
    assert final["url"]
    with db.tx() as conn:
        final_artifact = conn.execute(select(db.artifacts).where(db.artifacts.c.id == final["artifact_id"])).mappings().one()
    assert (final_artifact["width"], final_artifact["height"]) == (1366, 768)
    assert 9.5 < final_artifact["duration"] < 10.5


def test_gate_redo_reruns_only_the_rejected_item(admin, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["product-ad"]["workflow_id"]
    _publish(admin, workflow_id)
    image = _upload(admin, fresh["workspace_id"])
    run = admin.post("/api/runs", {"workflow_id": workflow_id, "inputs": {
        "product": "暖杯", "facts": ["三秒加热"], "inspiration": "冬天", "product_images": [image]}})
    run_worker()
    detail = admin.get(f"/api/runs/{run['id']}")
    gate = next(node for node in detail["nodes"] if node["id"] == "review")["tasks"][0]
    admin.post(f"/api/gates/{gate['id']}", {"decision": "reject", "note": "第二镜重抽", "redo": ["001"]})
    with db.tx() as conn:
        image_tasks = conn.execute(select(db.tasks).where(db.tasks.c.run_id == run["id"], db.tasks.c.node_id == "keyframes")).mappings().all()
    assert len(image_tasks) == 3
    run_worker()
    detail = admin.get(f"/api/runs/{run['id']}")
    gate = next(node for node in detail["nodes"] if node["id"] == "review")["tasks"][0]
    assert gate["status"] == "waiting"
    admin.post(f"/api/gates/{gate['id']}", {"decision": "approve"})
    run_worker()
    assert admin.get(f"/api/runs/{run['id']}")["status"] == "succeeded"


def _set_budget(workflow_id: str, yuan: float) -> None:
    with db.tx() as conn:
        version = conn.execute(select(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id)).mappings().one()
        conn.execute(update(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id)
                     .values(spec={**version["spec"], "budget": {"max_yuan": yuan}}))


def test_rerun_one_shot_after_success(admin, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["zero-snow"]["workflow_id"]
    _set_budget(workflow_id, 100)
    _publish(admin, workflow_id)
    _set_llm_reply("adapt", ZERO_FIXTURE)
    run = admin.post("/api/runs", {"workflow_id": workflow_id, "inputs": {"passage": "原文"}})
    run_worker()
    first = admin.get(f"/api/runs/{run['id']}")
    old_video = first["outputs"]["video"][0]["artifact_id"]
    result = admin.post(f"/api/runs/{run['id']}/rerun", {"node": "clip", "item": "000"})
    assert len(result["created"]) == 3
    run_worker()
    second = admin.get(f"/api/runs/{run['id']}")
    assert second["status"] == "succeeded"
    assert second["outputs"]["video"][0]["artifact_id"] != old_video


def test_budget_pause_and_resume(admin, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["zero-snow"]["workflow_id"]
    with db.tx() as conn:
        version = conn.execute(select(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id)).mappings().one()
        spec = {**version["spec"], "budget": {"max_yuan": 1}}
        conn.execute(update(db.workflow_versions).where(db.workflow_versions.c.workflow_id == workflow_id)
                     .values(spec=spec, fixtures={}))
    _publish(admin, workflow_id)
    _set_llm_reply("adapt", ZERO_FIXTURE)
    run = admin.post("/api/runs", {"workflow_id": workflow_id, "inputs": {"passage": "原文"}})
    run_worker()
    paused = admin.get(f"/api/runs/{run['id']}")
    assert paused["status"] == "paused" and paused["cost_actual"] > 1
    admin.post(f"/api/runs/{run['id']}/resume")
    run_worker()
    assert admin.get(f"/api/runs/{run['id']}")["status"] in {"succeeded", "paused"}


def test_dry_runs_and_trial_by_agent(admin, agent, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["zero-snow"]["workflow_id"]
    compiled = agent.post(f"/api/workflows/{workflow_id}/versions/1/dry-run", {"inputs": {"passage": "原文"}})
    assert compiled["prompts"][0]["prompt"] == GOLDEN["prompt"]
    _set_llm_reply("adapt", ZERO_FIXTURE)
    llm_level = agent.post(f"/api/workflows/{workflow_id}/versions/1/dry-run", {"inputs": {"passage": "原文"}, "level": "llm"})
    run_worker()
    run = agent.get(f"/api/runs/{llm_level['run_id']}")
    assert run["status"] == "succeeded"
    assert run["outputs"]["compiled"]["prompts"][0]["prompt"] == GOLDEN["prompt"]
    assert all(node["kind"] == "llm" or not node["tasks"] for node in run["nodes"])
    agent.request("POST", f"/api/workflows/{workflow_id}/versions/1/publish", expect=403)
    trial = agent.post(f"/api/workflows/{workflow_id}/versions/1/trial", {"inputs": {"passage": "原文"}})
    run_worker()
    assert agent.get(f"/api/runs/{trial['id']}")["status"] == "succeeded"
    agent.request("POST", "/api/runs", json={"workflow_id": workflow_id, "inputs": {"passage": "x"}}, expect=403)


def test_llm_repair_loop(admin, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["zero-snow"]["workflow_id"]
    _publish(admin, workflow_id)
    bad = json.loads(json.dumps(ZERO_FIXTURE))
    bad["shot"]["action"] = "他跪下。他包扎。他抬头。他背起她"
    _set_llm_reply("adapt", bad)
    run = admin.post("/api/runs", {"workflow_id": workflow_id, "inputs": {"passage": "原文"}})
    run_worker()
    detail = admin.get(f"/api/runs/{run['id']}")
    assert detail["status"] == "waiting"
    llm = next(node for node in detail["nodes"] if node["id"] == "adapt")["tasks"][0]
    assert llm["status"] == "needs_attention" and "多个主动作" in llm["attention"]
    with db.tx() as conn:
        output = conn.execute(select(db.tasks.c.output).where(db.tasks.c.id == llm["id"])).scalar()
    assert output["attempts"] == 3 and len(output["transcript"]) == 7


def test_batch_runs_and_input_validation(admin, fresh, mock_providers):
    seeded = seed_samples(fresh["workspace_id"])
    workflow_id = seeded["workflows"]["zero-snow"]["workflow_id"]
    _publish(admin, workflow_id)
    _set_llm_reply("adapt", ZERO_FIXTURE)
    admin.request("POST", "/api/batches", json={"workflow_id": workflow_id, "inputs": [{"passage": "a"}, {}]}, expect=400)
    batch = admin.post("/api/batches", {"workflow_id": workflow_id, "inputs": [{"passage": "a"}, {"passage": "b"}]})
    assert len(batch["runs"]) == 2
    run_worker()
    runs = admin.get(f"/api/runs?batch_id={batch['batch_id']}")["items"]
    assert {run["status"] for run in runs} == {"succeeded"}
