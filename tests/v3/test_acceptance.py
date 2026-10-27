"""Acceptance sentences driven through the platform HTTP entry points."""

from __future__ import annotations

from sqlalchemy import text

from agent.app import dispatch, comic_team
from cvplatform.comic import backfill_decision
from cvplatform.db import session
from cvplatform.gates import GRID_SENTENCE, validate_prompt


def _segment(**extra):
    row = {
        "number": 1,
        "duration": 10,
        "cast": ["A", "B", "C"],
        "scene": "夜路",
        "action": "滑过",
        "dialogue": "无",
        "end_state": "停住",
    }
    row.update(extra)
    return row


def _words(count: int) -> str:
    return " ".join(["moves"] * count)


def test_command_order_and_inspiration_are_rejected(client):
    order = client.get("/api/commands").json()
    assert order["g1_before_image"] is True
    assert order["g2_before_probe"] is True
    assert order["g3_after_probe"] is True
    assert order["ratio_after_segments"] is True
    assert order["order"].index("提交分段") < order["order"].index("提交同框比例")
    blocked = client.post("/api/runs", json={"version_id": "wf_comic", "inspiration": "一句灵感"})
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "inspiration"


def test_new_episode_reuses_numbers_and_does_not_copy_segments(client):
    created = client.post("/api/runs", json={"version_id": "wf_comic", "script": "第二集剧本"}).json()
    episode = client.get(f"/api/episodes/{created['episode_id']}").json()
    assert episode["segments"] == []
    assert episode["numbers"] == [{"asset_id": "role-a", "kind": "角色", "number": 1}]
    assert created["copied_segments"] == 0
    assert created["reallocated"] is False
    empty = client.post("/api/runs", json={"version_id": "wf_comic", "script": "   "})
    assert empty.status_code == 422
    assert empty.json()["detail"]["code"] == "script"


def test_dialogue_none_blocks_confirm_until_the_line_is_edited(client):
    episode = client.post("/api/episodes").json()["id"]
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(cast=["A"], dialogue="你好")]).json()
    segment_id = saved["items"][0]["id"]
    client.post(f"/api/episodes/{episode}/dialogue", params={"mode": "无"})
    client.post(f"/api/segments/{segment_id}/one-action", params={"checked": True})
    rejected = client.post(f"/api/segments/{segment_id}/confirm")
    assert rejected.status_code == 422
    edited = client.post(f"/api/segments/{segment_id}/edit", json={"dialogue": "无"}, params={"dialogue_mode": "无"})
    assert edited.status_code == 200
    assert edited.json()["confirmed"] is False
    confirmed = client.post(f"/api/segments/{segment_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["confirmed"] is True
    assert confirmed.json()["dialogue"] == "无"


def test_one_action_and_voiceover_slot(client):
    episode = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{episode}/dialogue", params={"mode": "有"})
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(cast=["A"], dialogue="旁白在画外")]).json()
    segment_id = saved["items"][0]["id"]
    client.post(f"/api/segments/{segment_id}/speakers", json=["旁白"])
    missing = client.post(f"/api/segments/{segment_id}/confirm")
    assert missing.json()["detail"]["code"] == "one_action"
    client.post(f"/api/segments/{segment_id}/one-action", params={"checked": True})
    voice = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "voice-narrator", "kind": "音色", "number": 0, "segment_id": segment_id, "product_id": "audio-file"},
    )
    assert voice.status_code == 200
    assert voice.json()["binding"] == {}
    assert client.post(f"/api/segments/{segment_id}/confirm").status_code == 200


def test_ratios_and_audio_binding_go_through_the_api(client):
    episode = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{episode}/segments", json=[_segment()])
    one_pair = client.post(
        f"/api/episodes/{episode}/ratios",
        json=[{"left": "A", "right": "B", "left_ratio": 7, "right_ratio": 7}],
    )
    assert one_pair.status_code == 422
    assert one_pair.json()["detail"]["code"] == "pairs"
    solo = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{solo}/segments", json=[_segment(cast=["A"])])
    assert client.post(f"/api/episodes/{solo}/ratios", json=[]).status_code == 200
    role = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "role-a", "kind": "角色", "number": 1, "segment_id": "seg-a"},
    ).json()
    assert role["binding"]["image"] == "ref_image_1"
    assert role["binding"]["audio"] == "ref_audio_0"
    assert role["binding"]["audio_tag"] == "<Audio 1>"
    switched = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "role-b", "kind": "角色", "number": 1, "segment_id": "seg-a"},
    )
    assert switched.status_code == 422


def test_unaccepted_last_frame_cannot_enter_a_slot_and_graph_reads_slots(client):
    episode = client.post("/api/episodes").json()["id"]
    blocked = client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "末帧", "number": 0, "segment_id": "seg-b", "accepted": False},
    )
    assert blocked.status_code == 422
    assert blocked.json()["detail"]["code"] == "accept"
    refused = client.post("/api/products/missing/promote", json={"kind": "末帧", "lock_text": "x"})
    assert refused.status_code == 422
    entity = client.post("/api/works/work_1/entities")
    assert entity.status_code == 422
    assert entity.json()["detail"]["code"] == "reference"


def test_probe_rejects_empty_first_frame_wrong_audio_and_missing_seed(client):
    episode = client.post("/api/episodes").json()["id"]
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(cast=["A"])]).json()
    segment_id = saved["items"][0]["id"]
    with session() as db:
        db.execute(text("UPDATE segments SET prompt = 'old', prompt_accepted = 0 WHERE id = :id"), {"id": segment_id})
    no_seed = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": ""},
    )
    assert no_seed.status_code == 422
    assert no_seed.json()["detail"]["code"] == "seed"
    with session() as db:
        db.execute(text("UPDATE segments SET prompt = NULL, prompt_accepted = 0 WHERE id = :id"), {"id": segment_id})
    empty = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9"},
    )
    assert empty.json()["detail"]["code"] == "slot"
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    )
    opened = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9"},
    ).json()
    assert opened["spec"] == {"resolution": "480p", "mode": "高速", "duration": 2}
    assert opened["segment_duration"] == 10
    assert opened["aspect_reference"] == "480p"
    wrong_audio = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 2, "seed": "9", "audio_binding": "ref_audio_1"},
    )
    assert wrong_audio.json()["detail"]["code"] == "audio"


def test_formal_submit_uses_only_the_latest_probe_check(client):
    episode = client.post("/api/episodes").json()["id"]
    client.post(f"/api/episodes/{episode}/dialogue", params={"mode": "无"})
    with session() as db:
        db.execute(
            text("UPDATE episodes SET aspect = '1088x1920', mode = '高质', aspect_confirmed = 1, mode_confirmed = 1 WHERE id = :id"),
            {"id": episode},
        )
    saved = client.post(f"/api/episodes/{episode}/segments", json=[_segment(cast=["A"], dialogue="无")]).json()
    segment_id = saved["items"][0]["id"]
    client.post(
        f"/api/episodes/{episode}/slots",
        json={"asset_id": "frame", "kind": "首帧", "number": 0, "segment_id": segment_id, "product_id": "frame-file"},
    )
    first = client.post(
        f"/api/segments/{segment_id}/probe",
        params={"resolution": "480p", "mode": "高速", "duration": 5, "seed": "7"},
    ).json()
    client.post(f"/api/probe-results/{first['result_id']}/check")
    second = client.post(f"/api/segments/{segment_id}/reprobe").json()
    assert second["copied"] == {"resolution": "480p", "mode": "高速", "duration": 5.0}
    assert second["includes_seed"] is False
    assert second["includes_check"] is False
    with session() as db:
        db.execute(text("UPDATE segments SET prompt = 'accepted prompt', prompt_accepted = 1 WHERE id = :id"), {"id": segment_id})
    stale = client.post(f"/api/segments/{segment_id}/formal")
    assert stale.status_code == 422
    assert stale.json()["detail"]["code"] == "g3"
    client.post(f"/api/probe-results/{second['result_id']}/check")
    body = client.post(f"/api/segments/{segment_id}/formal").json()
    assert body["duration"] == 10
    assert body["resolution"] == "1088x1920"
    assert body["mode"] == "高质"
    assert body["seed"] == "7"
    assert body["read_probe_fields"] is False
    assert body["prompt"] == "accepted prompt"


def test_mark_failed_and_image_version_follow_the_table(client):
    failed = client.get("/api/rerun", params={"change": "failed"}).json()
    assert failed["invalidate"] == ["g3", "g4"]
    unchanged = client.get("/api/rerun", params={"change": "unchanged"}).json()
    assert unchanged["keeps_g3"] is False
    image = client.get("/api/rerun", params={"change": "image_version"}).json()
    assert "g2" in image["invalidate"]
    voice = client.get("/api/rerun", params={"change": "seed_or_voice_version"}).json()
    assert "g2" in voice["keep"]
    duration = client.get("/api/rerun", params={"change": "duration"}).json()
    assert "g2" in duration["invalidate"]
    end_state = client.get("/api/rerun", params={"change": "end_state", "has_next": True}).json()
    assert end_state["next"] == "rewrite_probe_then_render_last_frame"
    blocked = client.post("/api/segments/seg-next/next-probe", params={"last_frame_slotted": False})
    assert blocked.json()["detail"]["code"] == "last_frame"
    assert client.post("/api/segments/seg-next/next-probe", params={"last_frame_slotted": True}).json()["allowed"] is True
    last = client.get("/api/rerun", params={"change": "end_state", "has_next": False}).json()
    assert "next_prompt" not in last["invalidate"]


def test_prompt_validation_sentences(client):
    slots = [
        {"kind": "角色", "number": 1, "empty": False, "lock_text": "红罐"},
        {"kind": "角色", "number": 2, "empty": True, "lock_text": ""},
        {"kind": "场景", "number": 3, "empty": False, "lock_text": "夜路"},
    ]
    sections = {
        "summary": "A night street with <Picture 1> from ref_image_0.",
        "detailed_description": _words(360) + " 0.000 9.000 <d>你好</d>",
        "overall_soundscape": "wind",
    }
    full = "<Subject 1>: 红罐\n<Picture 4> <Subject 3>: 夜路\n" + sections["summary"] + sections["detailed_description"] + " " + GRID_SENTENCE
    ok = client.post("/api/prompts/validate", json={"full_text": full, "slots": slots, "sections": sections, "duration": 10}).json()
    assert ok["ok"] is True
    assert "<Subject 2>" not in "\n".join(ok["lines"])
    picture = full.replace("<Picture 1>", "<Picture 2>")
    bad_picture = client.post("/api/prompts/validate", json={"full_text": picture, "slots": slots, "sections": {**sections, "summary": "ref_image_0 as <Picture 2>"}, "duration": 10}).json()
    assert bad_picture["ok"] is False
    missing_grid = client.post(
        "/api/prompts/validate",
        json={"full_text": full.replace(GRID_SENTENCE, ""), "slots": slots, "sections": sections, "duration": 10},
    ).json()
    assert "grid_sentence" in missing_grid["errors"]
    short = dict(sections)
    short["detailed_description"] = _words(200)
    short_result = client.post("/api/prompts/validate", json={"full_text": full, "slots": slots, "sections": short, "duration": 10}).json()
    assert "word_count" in short_result["errors"]
    doubled = dict(sections)
    doubled["summary"] = sections["summary"] + " subject_definitions"
    doubled_result = client.post("/api/prompts/validate", json={"full_text": full, "slots": slots, "sections": doubled, "duration": 10}).json()
    assert "second_lock_block" in doubled_result["errors"]
    errors = validate_prompt(full, slots, sections, 10)
    assert errors == []


def test_concat_price_g1_and_backfill(client):
    missing_price = client.post("/api/estimate", params={"kind": "video", "quantity": 10})
    assert missing_price.status_code == 422
    concat = client.post("/api/estimate", params={"kind": "concat", "quantity": 1}).json()
    assert concat["amount"] == 0
    blocked = client.post("/api/first-frame/allowed", json={"g1": "pending", "speakers": ["A"], "voices": ["A"]})
    assert blocked.json()["detail"]["code"] == "g1"
    no_voice = client.post("/api/first-frame/allowed", json={"g1": "passed", "speakers": ["旁白"], "voices": []})
    assert no_voice.json()["detail"]["code"] == "voice"
    assert client.post("/api/first-frame/allowed", json={"g1": "passed", "speakers": ["旁白"], "voices": ["旁白"]}).json()["allowed"] is True
    assert client.get("/api/segments/seg-1/g4", params={"number": 1}).json()["checks_seam"] is False
    assert client.get("/api/segments/seg-2/g4", params={"number": 2}).json()["checks_seam"] is True
    early = client.post("/api/backfill/export", params={"process_stopped": False})
    assert early.json()["detail"]["code"] == "backfill"
    assert client.post("/api/backfill/export", params={"process_stopped": True}).json()["allowed"] is True
    assert backfill_decision(task_input=False, clip_chain=False, asset_link=False, promoted=True) == "keep"
    assert backfill_decision(task_input=False, clip_chain=False, asset_link=False, promoted=False) == "soft_delete"


def test_probe_errors_and_lead_routing(client):
    from cvplatform.probes import judge_benchmark, probe_h3, probe_image, probe_text

    def boom(method, url, payload, token):
        raise RuntimeError("upstream refused raw token")

    failed = probe_text("http://example", "raw", transport=boom)
    assert failed["sent"]["messages"][0]["content"] == "hi"
    assert "upstream refused" in failed["error"]

    def image_url(method, url, payload, token):
        return {"data": [{"url": "http://unreachable"}]}

    assert probe_image("http://example", "raw", transport=image_url)["ok"] is False
    try:
        probe_h3("http://example", "Bearer secret", "minimax_h3_803", transport=boom)
    except Exception as exc:  # noqa: BLE001
        assert "裸 token" in str(exc)
    team = comic_team()
    assert dispatch(team, "write_prompt") == "prompt-only"
    assert dispatch(team, "segment_script") == "segment-only"
    assert judge_benchmark("write_prompt", {"summary": "a", "detailed_description": "b", "overall_soundscape": "c"}, visual=True) == "passed"
    assert judge_benchmark("write_prompt", {"summary": "subject_definitions"}, visual=True) == "failed"
