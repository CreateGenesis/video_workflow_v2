"""Sample library assets and the two example workflows from docs/design/examples.

The snowfield sample reproduces the v1 demo (server/stories.py in v1): compiling it with its fixture
must give exactly the prompt the v1 composer produced (tests/golden/zero_shot_768p.json).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy import select

from . import artifacts, assets, db
from .auth import SYSTEM
from .config import ROOT

EXAMPLES = ROOT / "docs" / "design" / "examples"
REFERENCES = ROOT / "assets" / "references"

NOVEL_ADAPT = """你把小说片段改编成一条 15 秒的动画或实拍镜头（一次生成）。

做法：
1. 先找这段真正在演什么，以及情绪曲线；不要把小说句子逐句画出来。
2. 把原文换成动画手法：传闻变成会动的画面，声音和停顿也算手法。
3. 一条镜头最多四拍（paragraphs），每拍只有一个主动作，最多两个细节。
4. 每拍写清景别、角度、一种运动或“固定镜头”。台词用中文引号写在那一拍的 action 里，只写一次。
5. reverse 写这一拍最可能偷的懒，例如“不要让人物站起来走路”。
6. 不写时间码。动作要顺滑；“定格”只能作为禁止项出现，不能当正面要求。
7. 场景、风格、运镜和参考图已经锁定，不要在文字里另起新的地点或人物。

只输出符合 schema 的 JSON。"""

AD_SCRIPT = """你为一个产品写 15 秒广告的分镜：三镜，每镜 5 秒左右，每镜只有一个主动作。

要求：
- 只用给出的已核对卖点，不编数据、不编奖项。
- 第一镜建立产品外形，第二镜展示一个卖点的使用动作，第三镜收在产品和标识上。
- 每镜写清景别、角度和主动作；details 最多两个细节；reverse 写这一镜最可能偷的懒。
- 不写时间码，不写字幕和可读文字。动作顺滑，不要定格。

只输出符合 schema 的 JSON。"""

SHOT_LIST_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "广告分镜（大模型输出）",
    "type": "object",
    "required": ["shots"],
    "additionalProperties": False,
    "properties": {
        "shots": {
            "type": "array", "minItems": 2, "maxItems": 4,
            "items": {
                "type": "object",
                "required": ["title", "size", "angle", "action", "details", "duration", "sound", "reverse"],
                "additionalProperties": False,
                "properties": {
                    "title": {"type": "string", "maxLength": 20},
                    "size": {"type": "string"},
                    "angle": {"type": "string"},
                    "action": {"type": "string", "description": "一个主动作"},
                    "details": {"type": ["string", "null"]},
                    "duration": {"type": "integer", "minimum": 3, "maximum": 8},
                    "sound": {"type": ["string", "null"]},
                    "reverse": {"type": "string"},
                },
            },
        },
    },
}

ZERO_FIXTURE = {"shot": {
    "title": "背她之前", "size": "特写", "angle": "平视", "action": "零号用纱布包好，再抬头说要背她", "duration": 15,
    "sound": "风声、雪粉、纱布细响",
    "paragraphs": [
        {"size": "大远景", "angle": "平视", "motion": "缓慢横移",
         "action": "蓝色黄昏的雪原上，雷娜塔坐在倒伏白桦上，零号单膝跪在她面前，两个身影小得像黑点",
         "details": None, "reverse": "不要让人物站起来走路，不要出现其他人物。"},
        {"size": "特写", "angle": "平视", "motion": "固定镜头",
         "action": "零号的双手在画面中央，把白纱布绕两圈，纱布边缘压住前一圈",
         "details": "只看见旧军大衣袖口和纱布，不看见脚面", "reverse": "不要拍脚部特写，不要出现血迹。"},
        {"size": "中近景", "angle": "略俯", "motion": "固定镜头",
         "action": "零号抬起头，眉头皱起又松开，撇嘴说：“女人就是嫩点，没办法咯，我背你吧。”嘴里呼出白气",
         "details": None, "reverse": "这句只由零号说，雷娜塔不动嘴，零号不笑。"},
    ],
    "beat": {"title": "嫌弃里的照料", "curve": "寒冷疲惫翻成粗声里的温柔", "turn": "抬眼时眉头松开"},
}}


def _media(conn, workspace_id: str, path: Path, label: str) -> str:
    return artifacts.store_file(conn, workspace_id, path, prefix="assets", label=label)["id"]


def _sine(seconds: int) -> Path:
    path = Path(tempfile.mkdtemp()) / "bed.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
                    str(path)], check=True)
    return path


def _ensure(conn, workspace_id: str, name: str, kind: str, data: dict, media=None) -> None:
    """Create the asset once. `media` is a (path factory, label) pair uploaded only when needed."""
    if assets.get_asset(conn, workspace_id, name):
        return
    artifact_id = _media(conn, workspace_id, media[0](), media[1]) if media else None
    assets.create_or_version(conn, SYSTEM, workspace_id, name, kind, data, artifact_id=artifact_id, note="示例素材")


def seed_samples(workspace_id: str | None = None, publish: bool = False) -> dict:
    from .api.workflows import _new_version, _validate

    with db.tx() as conn:
        if not workspace_id:
            workspace_id = conn.execute(select(db.workspaces.c.id).order_by(db.workspaces.c.created_at).limit(1)).scalar()
        if not workspace_id:
            raise SystemExit("还没有工作区，先启动一次服务或 python -m server.manage migrate")
        _ensure(conn, workspace_id, "style-snow-film", "Style", {
            "title": "雪原电影", "medium": "真人实拍电影质感，35mm 颗粒，浅景深",
            "grade": "蓝色黄昏，侧逆光，冷蓝雪白，地平线暗橙", "ban": "禁止定格、字幕、血迹、脚部特写和新增人物。"})
        _ensure(conn, workspace_id, "place-siberia-snow", "Place", {
            "title": "西伯利亚雪原", "facts": "稀疏白桦，倒伏白桦在左，积雪没过小腿，风从画面右侧吹来，地平线有一线暗橙"})
        _ensure(conn, workspace_id, "detail-gauze-roll", "Detail", {
            "title": "白纱布卷", "measure": "绕两圈，后一圈压住前一圈", "material": "白棉纱"})
        _ensure(conn, workspace_id, "camera-one-move", "Camera", {"title": "一段一镜", "move": "固定镜头", "amplitude": "小", "speed": "慢"})
        _ensure(conn, workspace_id, "ref-zero-space", "Reference", {
            "title": "空镜雪原", "role": "空间", "take": "雪原、白桦和蓝色黄昏", "ignore": "人物和动作"},
                media=(lambda: REFERENCES / "zero-space.png", "空镜雪原"))
        _ensure(conn, workspace_id, "ref-zero-gauze", "Reference", {
            "title": "纱布卷", "role": "细节", "take": "白纱布的卷法和棉纱纹理", "ignore": "背景和人物"},
                media=(lambda: REFERENCES / "zero-gauze.png", "纱布卷"))
        _ensure(conn, workspace_id, "prompt-novel-adapt", "prompt", {"text": NOVEL_ADAPT})
        four_beat = json.loads((EXAMPLES / "schema-four-beat-shot.output.json").read_text(encoding="utf-8"))
        _ensure(conn, workspace_id, "schema-four-beat-shot", "schema", {"schema": four_beat})
        _ensure(conn, workspace_id, "style-brand-clean", "Style", {
            "title": "干净产品光", "medium": "真人实拍商业广告质感，微距与中景结合", "grade": "柔和顶光，浅灰背景，高光干净",
            "ban": "禁止定格、字幕、水印和可读文字。"})
        _ensure(conn, workspace_id, "camera-slow-push", "Camera", {"title": "缓推", "move": "缓慢推近", "amplitude": "小", "speed": "慢"})
        _ensure(conn, workspace_id, "prompt-ad-script", "prompt", {"text": AD_SCRIPT})
        _ensure(conn, workspace_id, "schema-shot-list", "schema", {"schema": SHOT_LIST_SCHEMA})
        _ensure(conn, workspace_id, "comfy-wan-i2v", "comfy_template", {
            "graph": {"6": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}},
                      "12": {"class_type": "LoadImage", "inputs": {"image": ""}},
                      "3": {"class_type": "KSampler", "inputs": {"seed": 0}},
                      "20": {"class_type": "WanImageToVideo", "inputs": {"length": 81, "width": 1366, "height": 768}},
                      "9": {"class_type": "SaveVideo", "inputs": {}}},
            "bindings": {"prompt": "6.inputs.text", "image": "12.inputs.image", "seed": "3.inputs.seed",
                         "length": "20.inputs.length", "width": "20.inputs.width", "height": "20.inputs.height"},
            "outputs": ["9"], "requires": {"nodes": ["WanImageToVideo"]}, "options": {"fps": 16, "expected_seconds": 600},
        })
        _ensure(conn, workspace_id, "music-bright-bed", "media", {"title": "明亮配乐底"},
                media=(lambda: _sine(15), "明亮配乐底"))
        created = {}
        fixtures = {"zero-snow": {"adapt": ZERO_FIXTURE}}
        for example in ("zero-snow", "product-ad"):
            spec = json.loads((EXAMPLES / f"{example}.workflow.json").read_text(encoding="utf-8"))
            existing = conn.execute(select(db.workflows.c.id).where(
                db.workflows.c.workspace_id == workspace_id, db.workflows.c.name == spec["name"])).scalar()
            if existing:
                created[example] = {"workflow_id": existing, "skipped": True}
                continue
            workflow_id = db.new_id("wf")
            conn.execute(db.workflows.insert().values(id=workflow_id, workspace_id=workspace_id, name=spec["name"],
                                                      created_by="system"))
            version = _new_version(conn, SYSTEM, workflow_id, workspace_id, spec, "示例工作流", None)
            if example in fixtures:
                conn.execute(db.workflow_versions.update().where(
                    db.workflow_versions.c.workflow_id == workflow_id, db.workflow_versions.c.version == 1,
                ).values(fixtures=fixtures[example]))
            if publish and not _validate(conn, workspace_id, spec)["errors"]:
                conn.execute(db.workflow_versions.update().where(
                    db.workflow_versions.c.workflow_id == workflow_id, db.workflow_versions.c.version == 1,
                ).values(status="published", published_by="示例", published_at=db.now()))
            created[example] = {"workflow_id": workflow_id, "errors": version["validation"]["errors"]}
    return {"workspace_id": workspace_id, "workflows": created}
