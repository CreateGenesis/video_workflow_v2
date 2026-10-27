"""Episode commands through the platform HTTP entry points."""

from __future__ import annotations

from sqlalchemy import text

from cvplatform.db import session


def _segment(number=1, cast=None, dialogue="无", duration=10):
    return {
        "number": number,
        "duration": duration,
        "cast": cast or ["A"],
        "scene": "夜路",
        "action": "滑过",
        "dialogue": dialogue,
        "end_state": "停住",
    }


def test_new_episode_creates_segment_script_and_does_not_copy(client):
    denied = client.post("/api/runs", json={"version_id": "wf_comic", "inspiration": "一个滑板"})
    assert denied.status_code == 422
    assert denied.json()["detail"]["code"] == "inspiration"
    created = client.post("/api/runs", json={"version_id": "wf_comic", "script": "第一场夜路"}).json()
    assert created["copied"] is False
    assert created["job_id"] is None
    assert created["submitted"] is True
    accepted = client.post(f"/api/episodes/{created['episode_id']}/accept-published").json()
    assert accepted["job_id"].startswith("job_")
    missing = client.get("/api/comic/missing", params={"episode_id": created["episode_id"]}).json()
    assert missing["stopped_at"] == "是否对白"
    assert missing["local_h3"] is False
    saved = client.post(f"/api/episodes/{created['episode_id']}/segments", json=[_segment()]).json()
    assert saved["items"][0]["confirmed"] is False
    confirm = client.post(f"/api/segments/{saved['items'][0]['id']}/confirm")
    assert confirm.status_code == 422


def test_voiceover_and_silent_line(client):
    episode = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{episode}/dialogue", params={"mode": "有"})
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(dialogue="无"), _segment(number=2, dialogue="旁白")]).json()
    silent, spoken = saved["items"]
    client.post(f"/api/segments/{silent['id']}/one-action", params={"checked": True})
    confirmed = client.post(f"/api/segments/{silent['id']}/confirm")
    assert confirmed.status_code == 200
    client.post(f"/api/segments/{spoken['id']}/one-action", params={"checked": True})
    missing_speaker = client.post(f"/api/segments/{spoken['id']}/confirm")
    assert missing_speaker.status_code == 422
    client.post(f"/api/segments/{spoken['id']}/speakers", json=["旁白"])
    assert client.post(f"/api/segments/{spoken['id']}/confirm").status_code == 200


def test_slot_number_stays_and_graph_has_kind(client):
    episode = client.post("/api/episodes").json()["id"]
    first = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "role-a", "kind": "角色", "number": 1, "segment_id": "seg"},
    ).json()
    assert first["binding"]["audio"] == "ref_audio_0"
    second = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "role-a", "kind": "角色", "number": 2, "segment_id": "seg"},
    )
    assert second.status_code == 422
    graph = client.get("/api/segments/seg/graph").json()
    assert graph["items"][0]["kind"] == "角色"


def test_product_search_and_promote_boundary(client):
    with session() as db:
        db.execute(
            text(
                """
                INSERT INTO products (id, workspace_id, kind, status, prompt, title, accepted, created_at)
                VALUES ('p1', 'ws', 'image', 'succeeded', 'red can skateboard', 'red', 1, 't')
                """
            )
        )
        db.execute(
            text(
                """
                INSERT INTO products (id, workspace_id, kind, status, prompt, title, accepted, created_at)
                VALUES ('p2', 'ws', 'image', 'succeeded', 'draft frame', 'frame', 0, 't')
                """
            )
        )
    with session() as db:
        db.execute(
            text(
                """
                INSERT INTO products (id, workspace_id, kind, status, prompt, title, accepted, created_at)
                VALUES ('p-failed', 'ws', 'video', 'failed', 'failed skateboard take', 'failed', 0, 't')
                """
            )
        )
    found = client.get("/api/products", params={"q": "skateboard"}).json()
    assert [item["id"] for item in found["items"]] == ["p1"]
    with session() as db:
        db.execute(
            text(
                """
                INSERT INTO jobs (id, workspace_id, type, input, output, status, attempt, max_attempts, created_at)
                VALUES ('job-draft', 'ws', 'extract_reference', '{}', :output, 'succeeded', 1, 3, 't')
                """
            ),
            {"output": '{"draft":"模型起草的短句"}'},
        )
        db.execute(text("UPDATE products SET origin_job_id = 'job-draft' WHERE id = 'p1'"))
    promoted = client.post("/api/products/p1/promote", json={"kind": "三视图", "lock_text": "人提交的最终原文"}).json()
    stored = client.get(f"/api/assets/{promoted['asset_id']}/lock").json()
    assert stored["lock_text"] == "人提交的最终原文"
    assert "模型起草" not in stored["lock_text"]
    blocked = client.post("/api/products/p1/promote", json={"kind": "首帧", "lock_text": "x"})
    assert blocked.status_code == 422
    unaccepted = client.post("/api/products/p2/promote", json={"kind": "道具", "lock_text": "纱布"})
    assert unaccepted.status_code == 422


def test_boot_does_not_register_comfy(client):
    boot = client.get("/api/boot").json()
    assert "video.comfy-gpu1" not in boot["providers"]
    assert boot["comfy"] == []
    with session() as db:
        db.execute(
            text(
                """
                INSERT INTO workflow_versions (id, name, protocol, pinned_json, published)
                VALUES ('old', 'comfy-wan', 'comfyui', '{}', 1)
                """
            )
        )
    rerun = client.post("/api/runs", json={"version_id": "old", "script": "剧本"})
    assert rerun.status_code == 422
    assert "已移除" in rerun.json()["detail"]["message"]


def test_probe_and_mcp_and_benchmark(client):
    from cvplatform.probes import judge_benchmark, probe_h3, probe_image, probe_text

    def transport(method, url, payload, token):
        assert not token.lower().startswith("bearer ")
        if "images" in url:
            assert payload["response_format"] == "b64_json"
            return {"data": [{"b64_json": "aGVsbG8="}]}
        if "workflows" in url:
            assert method == "GET"
            return {"input_rules": {"enums": {"resolution": ["480p"], "mode": ["高速", "高质"]}}}
        return {"choices": [{"message": {"content": "hi there"}}]}

    assert probe_text("http://example", "raw", transport=transport)["reply"] == "hi there"
    assert probe_image("http://example", "raw", transport=transport)["ok"] is True
    h3 = probe_h3("http://example", "raw-token", "minimax_h3_803", transport=transport)
    assert h3["paid"] is False
    assert h3["auth"] == "raw-token"
    assert judge_benchmark("extract_reference", "lock", visual=False) == "不适用"
    assert judge_benchmark("segment_script", [{"number": 1, "duration": 5, "cast": [], "scene": "a", "action": "b", "dialogue": "无", "end_state": "c"}], visual=True) == "passed"
    account = client.post("/api/accounts/verify", json={"fields": {"token": ""}, "example": "ghp_example"}).json()
    assert account["status"] == "失败"
    mcp = client.post(
        "/api/mcp/verify",
        json={"name": "资料检索", "address": "http://127.0.0.1:3333/mcp", "example": "http://127.0.0.1:3333/mcp", "tools": ["search"]},
    ).json()
    assert mcp["status"] == "可用"
    assert mcp["tools"] == ["search"]
    assert mcp["card"]["status"] == "可用"
    assert mcp["card"]["example"] == "http://127.0.0.1:3333/mcp"
    listed = client.get("/api/mcp/cards").json()
    assert listed["items"][0]["address"] == "http://127.0.0.1:3333/mcp"
    failed = client.post("/api/mcp/verify", json={"name": "资料检索", "address": "", "example": "http://127.0.0.1:3333/mcp"}).json()
    assert failed["status"] == "失败"
    assert client.get("/api/mcp/cards").json()["items"][0]["status"] == "失败"
    blocked = client.get("/api/segment-script/allowed", params={"needs_external": True, "mcp_status": "未验证"}).json()
    assert blocked["allowed"] is False
    free = client.get("/api/segment-script/allowed", params={"needs_external": False}).json()
    assert free["allowed"] is True
