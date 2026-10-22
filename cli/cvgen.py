"""Shallow cvgen operator. Commands come from the server catalog."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"

import httpx
import typer

TERMINAL = {"succeeded", "failed", "unknown"}
HOME = Path(os.environ["CVGEN_AUTH"]) if os.environ.get("CVGEN_AUTH") else Path.home() / ".cvgen" / "auth.json"
app = typer.Typer(help="操作云端视频系统。命令由服务目录提供。", context_settings={"allow_extra_args": True, "ignore_unknown_options": True})


def _auth() -> dict:
    if not HOME.is_file():
        typer.echo("还没有登录。先运行 cvgen login --base 服务地址。", err=True)
        raise typer.Exit(1)
    return json.loads(HOME.read_text(encoding="utf-8"))


def _request(method: str, path: str, body: dict | None = None, files=None, data=None) -> dict:
    saved = _auth()
    kwargs = {"headers": {"Authorization": f"Bearer {saved['token']}"}, "timeout": 120}
    if files is not None:
        kwargs["files"] = files
        kwargs["data"] = data or {}
    elif body is not None:
        kwargs["json"] = body
    response = httpx.request(method, saved["base"].rstrip("/") + path, trust_env=False, **kwargs)
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    if "application/json" in response.headers.get("content-type", ""):
        return response.json()
    return {"status_code": response.status_code, "bytes": len(response.content)}


def _print(data: dict) -> None:
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def login(base: str) -> None:
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
        time.sleep(1)
    typer.echo("等待批准超时。", err=True)
    raise typer.Exit(1)


def _catalog() -> list[dict]:
    return _request("GET", "/api/cli")["commands"]


def _match(argv: list[str], catalog: list[dict]) -> tuple[dict, list[str]]:
    names = {item["name"]: item for item in catalog}
    if len(argv) >= 2 and f"{argv[0]} {argv[1]}" in names:
        return names[f"{argv[0]} {argv[1]}"], argv[2:]
    if argv and argv[0] in names:
        return names[argv[0]], argv[1:]
    typer.echo(f"未知命令 {argv[0] if argv else ''}。运行 cvgen --help。", err=True)
    raise typer.Exit(1)


def _value(spec: dict, tokens: list[str]):
    if spec.get("flag"):
        if spec["flag"] in tokens:
            return tokens[tokens.index(spec["flag"]) + 1]
        return None
    plain = []
    skip = False
    for item in tokens:
        if skip:
            skip = False
            continue
        if str(item).startswith("--"):
            skip = True
            continue
        plain.append(item)
    if spec.get("rest"):
        return plain
    position = int(spec.get("position") or 0)
    return plain[position] if position < len(plain) else None


def _invoke(argv: list[str]) -> None:
    spec, tokens = _match(argv, _catalog())
    if spec.get("file"):
        fields = {}
        file_path = ""
        for arg in spec.get("args") or []:
            value = _value(arg, tokens)
            if value is None:
                continue
            if arg.get("file"):
                file_path = value
            else:
                fields[arg["name"]] = value
        path = Path(file_path)
        _print(_request("POST", spec["path"], files={"file": (path.name, path.read_bytes())}, data=fields))
        return
    if spec.get("binary"):
        saved = _auth()
        response = httpx.get(saved["base"].rstrip("/") + spec["path"].replace("{0}", tokens[0]), headers={"Authorization": f"Bearer {saved['token']}"}, timeout=120, trust_env=False)
        _print({"status_code": response.status_code, "bytes": len(response.content)})
        return
    if spec.get("wait"):
        job_id = _value(spec["args"][0], tokens)
        deadline = time.time() + 120
        while time.time() < deadline:
            shown = _request("GET", spec["path"].replace("{0}", job_id))
            if shown.get("status") in TERMINAL:
                _print(shown)
                return
            time.sleep(0.05)
        typer.echo("等待任务超时。", err=True)
        raise typer.Exit(1)
    path = spec["path"]
    plain = [item for item in tokens if not str(item).startswith("--")]
    for index, token in enumerate(plain):
        path = path.replace("{" + str(index) + "}", token)
    query = []
    body: dict = {}
    detail: dict = {}
    for arg in spec.get("args") or []:
        if arg.get("query"):
            value = _value(arg, tokens)
            if value:
                query.append(f"{arg['query']}={value}")
            continue
        value = arg["const"] if "const" in arg else _value(arg, tokens)
        if value is None:
            continue
        if arg.get("json"):
            value = json.loads(value)
        target = arg.get("body") or arg["name"]
        if target.startswith("detail."):
            detail[target.split(".", 1)[1]] = value
        else:
            body[target] = value
    if detail:
        body["detail"] = detail
    if query:
        path += "?" + "&".join(query)
    _print(_request(spec["method"], path, None if spec["method"] == "GET" else body or {}))


def entry(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["login"]:
        if "--base" not in argv:
            typer.echo("登录必须带 --base 服务地址", err=True)
            raise SystemExit(1)
        login(argv[argv.index("--base") + 1])
        return
    if not argv or argv[0] in {"--help", "-h", "help"}:
        if not HOME.is_file():
            typer.echo("用法：cvgen login --base 服务地址\n先登录。之后的命令由服务目录提供。")
            return
        for item in _catalog():
            typer.echo(item["usage"])
        return
    _invoke(argv)


if __name__ == "__main__":
    entry()
