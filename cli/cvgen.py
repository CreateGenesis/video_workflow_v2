"""cvgen is an operator. It starts hosted work and reads results."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import httpx
import typer

TERMINAL = {"succeeded", "failed", "unknown"}

app = typer.Typer(help="操作云端视频系统。执行由服务完成。")
entity_app = typer.Typer(help="读写实体")
app.add_typer(entity_app, name="entity")
job_app = typer.Typer(help="读取托管任务")
app.add_typer(job_app, name="job")
skill_app = typer.Typer(help="读取技能正文")
app.add_typer(skill_app, name="skill")
edit_app = typer.Typer(help="让服务剪辑")
app.add_typer(edit_app, name="edit")
reference_app = typer.Typer(help="上传本机参考文件")
app.add_typer(reference_app, name="reference")
style_app = typer.Typer(help="从成片提取风格")
app.add_typer(style_app, name="style")
batch_app = typer.Typer(help="查看作品里的镜头")
app.add_typer(batch_app, name="batch")
shot_app = typer.Typer(help="组合镜头")
app.add_typer(shot_app, name="shot")


HOME = Path(os.environ["CVGEN_AUTH"]) if os.environ.get("CVGEN_AUTH") else Path.home() / ".cvgen" / "auth.json"


def _auth() -> dict:
    if not HOME.is_file():
        typer.echo("还没有登录。先运行 cvgen login。", err=True)
        raise typer.Exit(1)
    return json.loads(HOME.read_text(encoding="utf-8"))


def _request(method: str, path: str, body: dict | None = None, files=None, data=None) -> dict:
    saved = _auth()
    base = saved["base"]
    token = saved["token"]
    kwargs = {"headers": {"Authorization": f"Bearer {token}"}, "timeout": 120}
    if files is not None:
        kwargs["files"] = files
        kwargs["data"] = data or {}
    else:
        kwargs["json"] = body
    url = base.rstrip("/") + path
    response = httpx.request(method, url, trust_env=False, **kwargs)
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    if "application/json" in response.headers.get("content-type", ""):
        return response.json()
    return {"status_code": response.status_code, "bytes": len(response.content)}


def _print(data: dict) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@app.command()
def login(base: str = typer.Option("http://127.0.0.1:8080", help="云端地址")) -> None:
    started = httpx.post(base.rstrip("/") + "/api/device/start", timeout=30, trust_env=False).json()
    typer.echo(f"设备码 {started['code']}")
    typer.echo(f"在网页批准：{started['approve_url']}")
    for _ in range(60):
        polled = httpx.get(base.rstrip("/") + f"/api/device/{started['code']}", timeout=30, trust_env=False).json()
        if polled.get("status") == "approved":
            HOME.parent.mkdir(parents=True, exist_ok=True)
            HOME.write_text(json.dumps({"base": base, "token": polled["token"]}), encoding="utf-8")
            HOME.chmod(0o600)
            typer.echo("已授权。凭证只保存在本机。")
            return
        time.sleep(2)
    typer.echo("等待批准超时。", err=True)
    raise typer.Exit(1)


@app.command("ontology")
def ontology_show() -> None:
    _print(_request("GET", "/api/ontology"))


@entity_app.command("add")
def entity_add(type_name: str, data: str) -> None:
    _print(_request("POST", "/api/entity", {"type": type_name, "data": json.loads(data)}))


@entity_app.command("get")
def entity_get(entity_id: str) -> None:
    _print(_request("GET", f"/api/entity/{entity_id}"))


@entity_app.command("query")
def entity_query(type_name: str = "") -> None:
    path = "/api/entities" + (f"?type={type_name}" if type_name else "")
    _print(_request("GET", path))


@app.command()
def link(name: str, source_id: str, target_id: str, note: str = "") -> None:
    _print(_request("POST", "/api/link", {"name": name, "source_id": source_id, "target_id": target_id, "note": note}))


@app.command()
def derive(source_id: str, target_id: str, note: str = "") -> None:
    _print(_request("POST", "/api/derive", {"name": "derived_from", "source_id": source_id, "target_id": target_id, "note": note}))


@shot_app.command("compose")
def shot_compose(shot_id: str, resolution: str = "768p横") -> None:
    _print(_request("GET", f"/api/shot/{shot_id}/compose?resolution={resolution}"))


@app.command("story")
def story_zero() -> None:
    _print(_request("POST", "/api/stories/zero"))


@app.command()
def generate(shot_id: str, resolution: str = "768p横", force: bool = False) -> None:
    _print(_request("POST", "/api/generate", {"shot_id": shot_id, "resolution": resolution, "force": force}))


@app.command()
def tts(line_id: str) -> None:
    _print(_request("POST", "/api/tts", {"target_id": line_id}))


@app.command()
def pull(url: str, role: str = "风格") -> None:
    _print(_request("POST", "/api/pull", {"detail": {"url": url, "role": role}}))


@app.command()
def inspect(entity_id: str) -> None:
    _print(_request("POST", "/api/inspect", {"target_id": entity_id}))


@app.command()
def reverse(entity_id: str) -> None:
    _print(_request("POST", "/api/reverse", {"target_id": entity_id}))


@app.command()
def learn(url: str) -> None:
    _print(_request("POST", "/api/learn", {"detail": {"url": url, "role": "风格"}}))


@style_app.command("extract")
def style_extract(entity_id: str) -> None:
    _print(_request("POST", "/api/style", {"target_id": entity_id}))


@reference_app.command("frame")
def reference_frame(
    clip_id: str,
    at: str = typer.Option("last", help="first 或 last"),
    role: str = typer.Option("空间", help="首帧、尾帧或空间"),
) -> None:
    _print(_request("POST", "/api/frame", {"target_id": clip_id, "detail": {"at": at, "role": role}}))


@reference_app.command("upload")
def reference_upload(
    path: str,
    role: str = typer.Option(..., help="身份、空间、细节、风格、分镜、音色或情感"),
    title: str = "",
    take: str = "",
    ignore: str = "",
) -> None:
    file_path = Path(path)
    if not file_path.is_file():
        typer.echo("参考文件不存在。", err=True)
        raise typer.Exit(1)
    with file_path.open("rb") as handle:
        _print(_request(
            "POST",
            "/api/reference",
            files={"file": (file_path.name, handle, "application/octet-stream")},
            data={"role": role, "title": title or file_path.stem, "take": take, "ignore": ignore},
        ))


@app.command()
def preview(entity_id: str) -> None:
    _print(_request("GET", f"/api/preview/{entity_id}"))


@app.command()
def ffmpeg(args: list[str]) -> None:
    _print(_request("POST", "/api/ffmpeg", {"detail": {"args": args}}))


@edit_app.command("join")
def edit_join(clips: list[str], fade: float = 2) -> None:
    _print(_request("POST", "/api/edit", {"detail": {"op": "join", "clips": clips, "fade": fade}}))


@edit_app.command("export")
def edit_export(edit_id: str) -> None:
    _print(_request("POST", "/api/edit", {"target_id": edit_id, "detail": {"op": "export"}}))


@edit_app.command("mix")
def edit_mix(edit_id: str) -> None:
    _print(_request("POST", "/api/edit", {"target_id": edit_id, "detail": {"op": "mix"}}))


@edit_app.command("subtitle")
def edit_subtitle(edit_id: str) -> None:
    _print(_request("POST", "/api/edit", {"target_id": edit_id, "detail": {"op": "subtitle"}}))


@job_app.command("show")
def job_show(job_id: str) -> None:
    _print(_request("GET", f"/api/job/{job_id}"))


@job_app.command("wait")
def job_wait(job_id: str, timeout: float = 120) -> None:
    deadline = time.time() + timeout
    shown = _request("GET", f"/api/job/{job_id}")
    while shown.get("status") not in TERMINAL:
        if time.time() > deadline:
            typer.echo("任务还没结束。", err=True)
            raise typer.Exit(1)
        time.sleep(0.4)
        shown = _request("GET", f"/api/job/{job_id}")
    _print(shown)


@skill_app.command("list")
def skill_list() -> None:
    _print(_request("GET", "/api/skills"))


@skill_app.command("show")
def skill_show(name: str) -> None:
    _print(_request("GET", f"/api/skills/{name}"))


@app.command()
def canvas() -> None:
    _print(_request("GET", "/api/canvas"))


@batch_app.command("show")
def batch_show(work_id: str) -> None:
    _print(_request("GET", f"/api/batch/{work_id}"))


@app.command("media", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def media_entry(ctx: typer.Context, target: str = typer.Argument("")) -> None:
    tokens = [item for item in [target, *ctx.args] if item]
    if not tokens:
        typer.echo("用法：cvgen media upload <文件> --kind image|video|audio，或 cvgen media get <对象键>。", err=True)
        raise typer.Exit(1)
    if tokens[0] == "upload":
        _media_upload(tokens[1:])
        return
    if tokens[0] == "get":
        if len(tokens) < 2:
            typer.echo("缺少对象键。", err=True)
            raise typer.Exit(1)
        _media_get(tokens[1])
        return
    _media_get(tokens[0])


def _media_upload(tokens: list[str]) -> None:
    path = ""
    kind = ""
    title = ""
    role = "细节"
    index = 0
    while index < len(tokens):
        item = tokens[index]
        if item == "--kind":
            kind = tokens[index + 1]
            index += 2
        elif item == "--title":
            title = tokens[index + 1]
            index += 2
        elif item == "--role":
            role = tokens[index + 1]
            index += 2
        else:
            path = item
            index += 1
    file_path = Path(path)
    if not file_path.is_file():
        typer.echo("文件不存在。", err=True)
        raise typer.Exit(1)
    if kind not in {"image", "video", "audio"}:
        typer.echo("文件种类只能是 image、video 或 audio。", err=True)
        raise typer.Exit(1)
    with file_path.open("rb") as handle:
        _print(_request(
            "POST",
            "/api/media",
            files={"file": (file_path.name, handle, "application/octet-stream")},
            data={"kind": kind, "title": title or file_path.stem, "role": role},
        ))


def _media_get(object_key: str) -> None:
    saved = _auth()
    response = httpx.get(
        saved["base"].rstrip("/") + "/media/" + object_key.lstrip("/"),
        headers={"Authorization": f"Bearer {saved['token']}"},
        timeout=60,
        trust_env=False,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps({"object_key": object_key, "bytes": len(response.content)}, ensure_ascii=False))


@app.command()
def image(shot_id: str, role: str = "细节") -> None:
    _print(_request("POST", "/api/image", {"target_id": shot_id, "detail": {"role": role}}))


@app.command()
def music(text: str) -> None:
    _print(_request("POST", "/api/music", {"detail": {"text": text}}))


@app.command()
def check(clip_id: str) -> None:
    _print(_request("POST", "/api/check", {"target_id": clip_id}))


@app.command()
def work(
    title: str,
    kind: str = typer.Argument("短片"),
    brief: str = typer.Argument(""),
) -> None:
    _print(_request("POST", "/api/entity", {"type": "Work", "data": {"title": title, "kind": kind, "brief": brief}}))


if __name__ == "__main__":
    app()
