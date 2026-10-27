"""Comic-drama gates. Pure rules used by the platform API. Do not reimplement these in callers."""

from __future__ import annotations

import itertools
import math
import re
from typing import Any

SEVEN = ("number", "duration", "cast", "scene", "action", "dialogue", "end_state")
PROBE_FIELDS = ("resolution", "mode", "duration")
GRID_SENTENCE = "The grid lines and labels of the reference board do not appear in the picture."
MANDATORY_NEGATIVE = "no burned-in text, no subtitles, no watermark"
LEASE_SECONDS = 600
PROMOTABLE = {"三视图", "九宫格", "道具", "音色"}
NOT_PROMOTABLE = {"首帧", "同框比例图", "末帧"}
NONE_OK = {"是否对白", "调色", "字幕", "铺乐", "响度"}
NONE_FORBIDDEN = {"画幅", "段时长", "模式"}


class GateError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def adsorb(requested_seconds: float) -> dict[str, Any]:
    """k is the smallest integer such that 17k+5 is not less than requested_seconds * 24."""
    if requested_seconds <= 0:
        raise GateError("duration", "时长必须大于 0")
    target = requested_seconds * 24
    k = 0
    while 17 * k + 5 < target:
        k += 1
    frames = 17 * k + 5
    return {"k": k, "frames": frames, "actual_seconds": frames / 24}


def save_segment_row(row: dict[str, Any]) -> dict[str, Any]:
    """Save checks only the original seven columns and forces confirmed false."""
    missing = [name for name in SEVEN if name not in row or row[name] in (None, "")]
    if missing:
        raise GateError("missing_columns", "缺列: " + ",".join(missing))
    duration = float(row["duration"])
    if duration > 15 or duration <= 0:
        raise GateError("duration", "段时长必须在 15 秒以内")
    dialogue_mode = row.get("dialogue_mode")
    if dialogue_mode == "无" and row["dialogue"] != "无":
        raise GateError("dialogue_mismatch", "是否对白为无而台词不是无")
    saved = {name: row[name] for name in SEVEN}
    saved["duration"] = duration
    saved["frames"] = adsorb(duration)["frames"]
    saved["confirmed"] = False
    return saved


def speakers_required(dialogue_mode: str | None, dialogue: str) -> bool:
    return dialogue_mode == "有" and dialogue != "无"


def confirm_segment(segment: dict[str, Any], episode: dict[str, Any]) -> dict[str, Any]:
    if not episode.get("dialogue_confirmed"):
        raise GateError("dialogue_unconfirmed", "是否对白未确认")
    mode = episode.get("dialogue_mode")
    dialogue = segment.get("dialogue", "")
    if mode == "无" and dialogue != "无":
        raise GateError("dialogue_mismatch", "是否对白为无而台词不是无")
    if speakers_required(mode, dialogue):
        speakers = segment.get("speakers") or []
        if not speakers:
            raise GateError("speakers", "有台词却没有说话角色")
    if dialogue == "无" and not speakers_required(mode, dialogue):
        pass
    if not segment.get("one_action_checked"):
        raise GateError("one_action", "未勾只有一个动作")
    updated = dict(segment)
    updated["confirmed"] = True
    for name in SEVEN:
        updated[name] = segment[name]
    return updated


def recheck_dialogue_change(segments: list[dict[str, Any]], new_mode: str) -> list[dict[str, Any]]:
    """Changing 是否对白 to 有 or 无 rechecks every segment."""
    out = []
    for segment in segments:
        item = dict(segment)
        dialogue = item.get("dialogue", "")
        failed = False
        if new_mode == "无" and dialogue != "无":
            failed = True
        if new_mode == "有" and dialogue != "无" and not item.get("speakers"):
            failed = True
        if failed:
            item["confirmed"] = False
            item["g1"] = "pending"
        out.append(item)
    return out


def required_pairs(segments: list[dict[str, Any]]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for segment in segments:
        cast = list(segment.get("cast") or [])
        for left, right in itertools.combinations(sorted(set(cast)), 2):
            pairs.add((left, right))
    return pairs


def check_ratios(segments: list[dict[str, Any]], submitted: list[dict[str, Any]]) -> None:
    if not segments:
        raise GateError("no_segments", "对数没有来源")
    needed = required_pairs(segments)
    got = {(item["left"], item["right"]) for item in submitted}
    if got != needed:
        raise GateError("pairs", "必填的是出场角色的全部组合")
    for item in submitted:
        if "left_ratio" not in item or "right_ratio" not in item:
            raise GateError("numbers", "只勾选通过")
        left = float(item["left_ratio"])
        right = float(item["right_ratio"])
        if left <= 0 or right <= 0:
            raise GateError("numbers", "比例必须是正数")
        delta = abs(left - right) / max(left, right)
        if delta > 0.10:
            raise GateError("ratio", "任一对差值大于 10%")


def assign_number(existing: list[dict[str, Any]], asset_id: str, kind: str, number: int | None) -> int:
    """Number is assigned the first time the asset enters a slot and stays fixed."""
    for row in existing:
        if row["asset_id"] == asset_id:
            if row["kind"] != kind:
                raise GateError("number", "同一资产不能占两个编号")
            if number is not None and number != row["number"]:
                raise GateError("number", "同一编号不能换资产")
            return row["number"]
    if number is None:
        raise GateError("number", "编号在该资产第一次入槽时分配")
    for row in existing:
        if row["number"] == number and row["kind"] == kind and row["asset_id"] != asset_id:
            raise GateError("number", "同一编号不能换资产")
    return number


def character_slots(index: int) -> dict[str, str]:
    """Character index starts at 1. Image is ref_image_k, audio is ref_audio_{k-1}."""
    if index < 1:
        raise GateError("number", "角色序号从 1 起")
    return {
        "image": f"ref_image_{index}",
        "audio": f"ref_audio_{index - 1}",
        "audio_tag": f"<Audio {index}>",
        "picture_tag": f"<Picture {index + 1}>",
        "subject_tag": f"<Subject {index}>",
    }


def picture_tag(ref_index: int) -> str:
    return f"<Picture {ref_index + 1}>"


def subject_lines(slots: list[dict[str, Any]]) -> list[str]:
    """Empty slots occupy a number but emit no Subject line. Filled slots keep their number."""
    lines = []
    for slot in slots:
        if slot.get("kind") not in {"角色", "场景", "道具"}:
            continue
        if slot.get("empty") or not slot.get("lock_text"):
            continue
        number = int(slot["number"])
        lines.append(f"<Subject {number}>: {slot['lock_text']}")
    return lines


def validate_prompt(full_text: str, slots: list[dict[str, Any]], sections: dict[str, str], formal_duration: float) -> list[str]:
    errors: list[str] = []
    if "subject_definitions" in (sections.get("summary", "") + sections.get("detailed_description", "") + sections.get("overall_soundscape", "")):
        errors.append("second_lock_block")
    for slot in slots:
        if slot.get("kind") not in {"角色", "场景", "道具"} or slot.get("empty"):
            continue
        expected = f"<Subject {int(slot['number'])}>: {slot['lock_text']}"
        if expected not in full_text:
            errors.append("lock_mismatch")
        if slot["kind"] == "角色":
            audio = character_slots(int(slot["number"]))["audio"]
            wrong = f"ref_audio_{int(slot['number'])}"
            if wrong in full_text and audio not in full_text:
                errors.append("audio_slot")
    for slot in slots:
        if slot.get("empty") and slot.get("kind") in {"角色", "场景", "道具"}:
            forbidden = f"<Subject {int(slot['number'])}>"
            if forbidden in full_text:
                errors.append("empty_subject")
    if "<Picture 1>" in sections.get("summary", "") and "ref_image_0" not in full_text:
        errors.append("picture_1")
    if re.search(r"<Subject \d+>:", sections.get("summary", "") + sections.get("detailed_description", "")):
        if any(line.split(":", 1)[0] in sections.get("summary", "") for line in subject_lines(slots)):
            errors.append("subject_in_sections")
    scene_slots = [slot for slot in slots if slot.get("kind") == "场景" and not slot.get("empty")]
    if scene_slots and GRID_SENTENCE not in full_text:
        errors.append("grid_sentence")
    detailed = sections.get("detailed_description", "")
    detailed = re.sub(r"<d>.*?</d>", " ", detailed, flags=re.S)
    words = re.findall(r"[A-Za-z0-9']+", detailed)
    if not (350 <= len(words) <= 500):
        errors.append("word_count")
    cap = adsorb(formal_duration)["actual_seconds"]
    times = [float(item) for item in re.findall(r"\b(\d+\.\d{3})\b", sections.get("detailed_description", ""))]
    if times != sorted(times) or (times and times[-1] > cap + 1e-9):
        errors.append("timecode")
    return errors


def formal_submit_body(segment: dict[str, Any], slots: list[dict[str, Any]]) -> dict[str, Any]:
    """Formal submit reads the segment spec, never the saved probe fields."""
    if not segment.get("prompt_accepted"):
        raise GateError("prompt", "没有已验收提示词")
    if not segment.get("seed"):
        raise GateError("seed", "没有 seed")
    latest = segment.get("latest_probe") or {}
    if latest.get("g3") != "passed":
        raise GateError("g3", "第 7 步只认最近一次探针结果上的勾选")
    body = {
        "prompt": segment["prompt"],
        "duration": segment["duration"],
        "resolution": segment["aspect"],
        "mode": segment["mode"],
        "seed": segment["seed"],
        "ref_image_0": _slot_file(slots, "首帧", 0),
    }
    for slot in slots:
        if slot.get("empty") or slot.get("kind") == "首帧":
            continue
        if slot["kind"] in {"角色", "场景", "道具"}:
            body[f"ref_image_{int(slot['number'])}"] = slot.get("file")
        if slot["kind"] == "音色":
            body[f"ref_audio_{int(slot['number'])}"] = slot.get("file")
        if slot["kind"] == "角色" and slot.get("audio_file"):
            body[f"ref_audio_{int(slot['number']) - 1}"] = slot["audio_file"]
    return body


def _slot_file(slots: list[dict[str, Any]], kind: str, number: int) -> str:
    for slot in slots:
        if slot.get("kind") == kind and int(slot.get("number") or 0) == number and not slot.get("empty"):
            return slot.get("file") or ""
    raise GateError("slot", "ref_image_0 为空不能探针")


def probe_spec(resolution: str, mode: str, duration: float, rules: dict[str, Any]) -> dict[str, Any]:
    enums = rules.get("enums") or {}
    resolutions = enums.get("resolution") or []
    modes = enums.get("mode") or []
    if resolutions and resolution not in resolutions:
        raise GateError("enum", "分辨率枚举对不上: " + ",".join(resolutions))
    if modes and mode not in modes:
        raise GateError("enum", "模式枚举对不上: " + ",".join(modes))
    if not (1 <= duration <= 5):
        raise GateError("probe_duration", "探针时长由人在 1 到 5 秒内确认")
    return {"resolution": resolution, "mode": mode, "duration": duration}


def copy_probe_fields(saved: dict[str, Any] | None) -> dict[str, Any]:
    if not saved or any(name not in saved for name in PROBE_FIELDS):
        raise GateError("probe_fields", "没有保存的分辨率、模式和时长")
    return {name: saved[name] for name in PROBE_FIELDS}


def rerun(change: str, *, has_next: bool = False) -> dict[str, Any]:
    """Invalidation lives only in this table. Callers must not invent a second list."""
    table: dict[str, dict[str, Any]] = {
        "unchanged": {
            "invalidate": [],
            "keeps_g3": False,
            "next": "copy_probe_fields_new_result",
        },
        "image_version": {
            "invalidate": ["first_frame", "prompt", "g2", "g3", "g4"],
            "next": "regen_accept_slot_g2_rewrite_probe",
        },
        "first_frame": {
            "invalidate": ["prompt", "g2", "g3", "g4"],
            "next": "accept_slot_g2_rewrite_probe",
        },
        "cast_or_scene": {
            "invalidate": ["first_frame", "prompt", "g2", "g3", "g4", "ratios"],
            "next": "recalc_ratios_regen_accept_slot_g2_rewrite_probe",
        },
        "action": {
            "invalidate": ["prompt", "g2", "g3", "g4"],
            "next": "review_first_frame_then_rewrite_or_regen",
        },
        "dialogue": {
            "invalidate": ["prompt", "g3", "g4"],
            "keep": ["g2"],
            "next": "rewrite_probe",
        },
        "duration": {
            "invalidate": ["prompt", "g2", "g3", "g4"],
            "next": "review_first_frame_new_duration",
        },
        "end_state": {
            "invalidate": ["prompt", "g3", "g4"] + (["next_prompt", "next_g2", "next_g3", "next_g4"] if has_next else []),
            "next": "rewrite_probe_then_render_last_frame",
        },
        "audio_slots": {
            "invalidate": ["prompt", "g3", "g4"],
            "keep": ["g2"],
            "next": "rewrite_probe",
        },
        "seed_or_voice_version": {
            "invalidate": ["prompt", "g3", "g4"],
            "keep": ["g2"],
            "next": "rewrite_probe",
        },
    }
    if change not in table:
        raise GateError("rerun", "作废以表为准")
    return table[change]


def mark_failed() -> dict[str, Any]:
    return {"invalidate": ["g3", "g4"], "next": "new_probe_before_formal"}


def concat_ready(segments: list[dict[str, Any]], episode: dict[str, Any]) -> dict[str, Any]:
    if any(segment.get("g4") != "passed" for segment in segments):
        raise GateError("g4", "每段 G4 都通过后才拼接")
    for name, confirmed in (
        ("color_grade", "color_confirmed"),
        ("subtitles", "subtitles_confirmed"),
        ("music", "music_confirmed"),
        ("loudness", "loudness_confirmed"),
    ):
        if not episode.get(confirmed):
            raise GateError("concat_input", f"{name} 未确认")
    requested = sum(float(segment["duration"]) for segment in segments)
    episode_duration = float(episode["episode_duration"])
    if not math.isclose(requested, episode_duration, abs_tol=1e-6):
        raise GateError("episode_duration", "各段请求时长之和必须等于单集时长")
    width, height = episode.get("segment_size", (1088, 1920))
    target = episode.get("aspect")
    if (width, height) == (1088, 1920) and target in {"1080x1920", "1088x1920"}:
        scale = target
    elif (width, height) == _parse_aspect(target):
        scale = target
    else:
        raise GateError("scale", "其他尺寸停住")
    return {"scale": scale, "duration": requested}


def _parse_aspect(value: str | None) -> tuple[int, int]:
    if not value or "x" not in value:
        return (0, 0)
    width, height = value.lower().split("x", 1)
    return int(width), int(height)


def promote_allowed(kind: str) -> bool:
    if kind in NOT_PROMOTABLE:
        return False
    return kind in PROMOTABLE


def used_keep(task_input: bool, clip_chain: bool, asset_link: bool, promoted: bool) -> bool:
    return promoted or task_input or clip_chain or asset_link


def h3_auth_header(token: str) -> str:
    if token.lower().startswith("bearer "):
        raise GateError("auth", "鉴权固定为裸 token")
    return token


def english_outside_d(text: str) -> str:
    return re.sub(r"<d>.*?</d>", " ", text, flags=re.S)
