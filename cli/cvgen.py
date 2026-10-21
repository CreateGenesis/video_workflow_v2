"""cvgen is an operator. It starts hosted work and reads results."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
import typer

app = typer.Typer(help="操作云端视频系统。执行由服务完成。")
entity_app = typer.Typer(help="读写实体")
app.add_typer(entity_app, name="entity")
job_app = typer.Typer(help="读取托管任务")
app.add_typer(job_app, name="job")
skill_app = typer.Typer(help="读取技能正文")
app.add_typer(skill_app, name="skill")
edit_app = typer.Typer(help="让服务剪辑")
app.add_typer(edit_app, name="edit")
shot_app = typer.Typer(help="组合镜头")
app.add_typer(shot_app, name="shot")

HOME = Path.home() / ".cvgen" / "auth.json"


def _auth() -> dict:
    if not HOME.is_file():
        typer.echo("还没有登录。先运行 cvgen login。", err=True)
        raise typer.Exit(1)
    return json.loads(HOME.read_text(encoding="utf-8"))


def _request(method: str, path: str, body: dict | None = None) -> dict:
    saved = _auth()
    base = saved["base"]
    token = saved["token"]
    response = httpx.request(
        method,
        base.rstrip("/") + path,
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=60,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    return response.json()


def _print(data: dict) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


@app.command()
def login(base: str = typer.Option("http://127.0.0.1:8080", help="云端地址")) -> None:
    started = httpx.post(base.rstrip("/") + "/api/device/start", timeout=30).json()
    typer.echo(f"设备码 {started['code']}")
    typer.echo(f"在网页批准：{started['approve_url']}")
    for _ in range(60):
        polled = httpx.get(base.rstrip("/") + f"/api/device/{started['code']}", timeout=30).json()
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


@app.command("style")
def style_extract(entity_id: str) -> None:
    _print(_request("POST", "/api/style", {"target_id": entity_id}))


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


@job_app.command("show")
def job_show(job_id: str) -> None:
    _print(_request("GET", f"/api/job/{job_id}"))


@skill_app.command("list")
def skill_list() -> None:
    _print(_request("GET", "/api/skills"))


@skill_app.command("show")
def skill_show(name: str) -> None:
    _print(_request("GET", f"/api/skills/{name}"))


@app.command()
def canvas() -> None:
    _print(_request("GET", "/api/canvas"))


@app.command("batch")
def batch_show(work_id: str) -> None:
    _print(_request("GET", f"/api/batch/{work_id}"))


@app.command()
def work(title: str, kind: str = "短片", brief: str = "") -> None:
    _print(_request("POST", "/api/entity", {"type": "Work", "data": {"title": title, "kind": kind, "brief": brief}}))


if __name__ == "__main__":
    app()
