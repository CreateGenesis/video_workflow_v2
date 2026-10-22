"""Compose a shot from linked entities. This does not generate video.

`graph` is anything with get(node_id) and linked(source_id, relation) returning nodes shaped like
{"id", "type", "data", "artifact_id"} — the database graph, or an in-memory graph during dry runs.
"""

from __future__ import annotations

from .ontology import RESOLUTIONS, ROLES

HEADINGS = ("【参考素材说明】", "【核心创意】", "【画面过程描述】", "【整体要求补充】")


def _alignment(first_at: int | None, last_at: int | None, duration: int) -> str:
    """Put the keyframe sentence first so image-to-video does not drift."""
    end = f"{duration:.2f}"
    if first_at and last_at:
        return f"参考图怎样对齐成片：参考图 {first_at} 对齐 0.00 秒；参考图 {last_at} 对齐 {end} 秒。"
    if first_at:
        return f"对于目标成片，在 0.00 秒，参考图 {first_at} 被完整采用。"
    if last_at:
        return f"参考图怎样对齐成片：参考图 {last_at} 对齐 {end} 秒。"
    return ""


def lint(prompt: str, shot: dict, refs: list[dict]) -> list[str]:
    warnings = []
    action = shot["data"].get("action", "")
    if "定格" in prompt and not any(word in prompt for word in ("不是", "没有", "禁止", "不要")):
        warnings.append("定格被写成正面要求")
    if "顺滑" not in prompt:
        warnings.append("没有写顺滑")
    if action.count("。") > 2:
        warnings.append("一个正向段里可能塞了多个主动作")
    if shot["data"].get("size") == "特写" and not any(ref["data"].get("role") == "细节" for ref in refs):
        warnings.append("细节镜头没有专用参考图")
    if "不要露出" in prompt and "脸" in prompt and not any(word in prompt for word in ("兜帽", "背对", "转向墙", "面朝墙")):
        warnings.append("藏脸只有否定句")
    return warnings


def compose(graph, shot_id: str, resolution: str = "768p横", extra_refs: list[dict] | None = None) -> dict:
    """extra_refs are appended after linked references (for example the previous shot's last frame)."""
    shot = graph.get(shot_id)
    if shot["type"] != "Shot":
        raise ValueError("只能组合镜头")
    if resolution not in RESOLUTIONS:
        raise ValueError("分辨率不在这个工作流的档位里")
    places = graph.linked(shot_id, "located_in")
    details = graph.linked(shot_id, "holds")
    styles = graph.linked(shot_id, "styled_as")
    cameras = graph.linked(shot_id, "shot_with")
    beats = graph.linked(shot_id, "contrasts_with")
    refs = graph.linked(shot_id, "references") + list(extra_refs or [])
    warnings = []
    if len(cameras) > 1:
        warnings.append("一条镜头连了多种运镜")
    camera = cameras[0]["data"] if cameras else {"move": "固定镜头", "amplitude": "", "speed": ""}
    style = styles[0]["data"] if styles else {}
    place = places[0]["data"] if places else {}
    versions = shot["data"].get("prompt_versions") or []
    if isinstance(versions, list) and versions and versions[-1].get("text"):
        shot = {**shot, "data": {**shot["data"], "action": versions[-1]["text"]}}
    duration = int(shot["data"].get("duration") or 5)
    if not 1 <= duration <= 15:
        raise ValueError("时长必须是 1 到 15 秒")

    ref_lines = []
    first_at = None
    last_at = None
    for index, ref in enumerate(refs, 1):
        role = ref["data"].get("role", "")
        if role not in ROLES:
            warnings.append(f"参考 {index} 的用途不在原型里")
        take = ref["data"].get("take") or "只采用画面中指定的部分"
        ignore = ref["data"].get("ignore") or "不采用其余内容"
        extra = "动作从下文重新开始。" if role == "空间" else ""
        if role == "首帧":
            first_at = index
            extra = "这张图是 0.00 秒的首帧。"
        elif role == "尾帧":
            last_at = index
            extra = f"这张图对齐 {duration:.2f} 秒。"
        label = ref["data"].get("title", role)
        ref_lines.append(f"参考图 {index}：{label}。只采用{take}。不采用{ignore}。{extra}")
    if not ref_lines:
        ref_lines.append("无参考素材（纯文字生成视频）")
        warnings.append("这个工作流没有参考图就不能提交")
    alignment = _alignment(first_at, last_at, duration)
    if alignment:
        ref_lines.insert(0, alignment)

    detail_text = "、".join(item["data"].get("title", "") for item in details)
    beat = beats[0]["data"].get("curve", "") if beats else ""
    move = camera.get("move", "固定镜头")
    motion = "、".join(part for part in (move, camera.get("amplitude"), camera.get("speed")) if part)
    paragraphs = shot["data"].get("paragraphs") or [{
        "size": shot["data"].get("size", "中景"),
        "angle": shot["data"].get("angle", "平视"),
        "motion": motion,
        "action": shot["data"].get("action", ""),
        "details": shot["data"].get("details", ""),
        "reverse": shot["data"].get("reverse") or "不要丢掉主动作，不要新增人物。",
    }]
    if len(paragraphs) > 4:
        warnings.append("15 秒里正向段超过 4 段，细节会被挤掉")
    shot_lines = []
    for index, paragraph in enumerate(paragraphs, 1):
        action = paragraph.get("action", "")
        extra = paragraph.get("details") or ""
        shot_lines.append(
            f"正向：镜头{index}，{paragraph.get('size', '中景')}，{paragraph.get('angle', '平视')}，{paragraph.get('motion', motion)}：{action}。{extra}"
        )
        shot_lines.append(f"反向：{paragraph.get('reverse') or '不要丢掉主动作，不要新增人物。'}")
    if any(item.get("size") == "特写" for item in paragraphs) and not any(ref["data"].get("role") == "细节" for ref in refs):
        warnings.append("细节镜头没有专用参考图")
    prompt = "\n".join([
        "【参考素材说明】",
        "\n".join(ref_lines),
        "",
        "【核心创意】",
        f"{duration} 秒，{resolution}。{style.get('medium', '按锁定风格')}。{place.get('title', '地点未写')}。这一段演：{shot['data'].get('action')}。基调：{beat or '按相连情绪'}。",
        "",
        "【画面过程描述】",
        "\n".join(shot_lines),
        "",
        "【整体要求补充】",
        f"▍风格（贯穿全片）{style.get('medium', '')} {style.get('grade', '')} 24 帧顺滑。",
        f"▍场景与方向（贯穿全片）{place.get('facts', '')}",
        f"▍细节（贯穿全片）{detail_text}",
        f"▍禁止项（贯穿全片）{style.get('ban', '禁止字幕、水印和可读文字。')}",
        f"▍声音（贯穿全片）{shot['data'].get('sound') or '只保留动作发出的声音。'}",
        "非叙事性音乐：N/A",
    ])
    if shot["data"].get("dialogue"):
        warnings.append("台词在镜头字段里。H3 提示词不生成旁白，对白只留在这一镜的主动作中")
    warnings.extend(lint(prompt, shot, refs))
    return {
        "shot_id": shot_id,
        "prompt": prompt,
        "duration": duration,
        "resolution": resolution,
        "references": [
            {
                "id": ref["id"],
                "role": ref["data"].get("role"),
                "artifact_id": ref.get("artifact_id"),
                "title": ref["data"].get("title"),
            }
            for ref in refs
        ],
        "warnings": warnings,
        "can_submit": bool(refs) and not any("不能提交" in item for item in warnings),
    }
