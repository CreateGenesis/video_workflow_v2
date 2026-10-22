"""The command catalog. The binary reads this; it does not keep its own command table."""

from __future__ import annotations


def commands() -> list[dict]:
    return [
        {"name": "ontology", "usage": "cvgen ontology", "method": "GET", "path": "/api/ontology", "args": []},
        {"name": "entity add", "usage": "cvgen entity add <类型> <JSON>", "method": "POST", "path": "/api/entity", "args": [
            {"name": "type", "position": 0, "file": False},
            {"name": "data", "position": 1, "file": False, "json": True},
        ]},
        {"name": "entity get", "usage": "cvgen entity get <实体>", "method": "GET", "path": "/api/entity/{0}", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "entity query", "usage": "cvgen entity query [类型]", "method": "GET", "path": "/api/entities", "args": [{"name": "type", "position": 0, "file": False, "optional": True, "query": "type"}]},
        {"name": "link", "usage": "cvgen link <关系> <来源> <目标> [说明]", "method": "POST", "path": "/api/link", "args": [
            {"name": "name", "position": 0, "file": False},
            {"name": "source_id", "position": 1, "file": False},
            {"name": "target_id", "position": 2, "file": False},
            {"name": "note", "position": 3, "file": False, "optional": True},
        ]},
        {"name": "derive", "usage": "cvgen derive <来源> <目标> [说明]", "method": "POST", "path": "/api/derive", "args": [
            {"name": "source_id", "position": 0, "file": False},
            {"name": "target_id", "position": 1, "file": False},
            {"name": "note", "position": 2, "file": False, "optional": True},
        ]},
        {"name": "shot compose", "usage": "cvgen shot compose <镜头> [分辨率]", "method": "GET", "path": "/api/shot/{0}/compose", "args": [
            {"name": "shot", "position": 0, "file": False},
            {"name": "resolution", "position": 1, "file": False, "optional": True, "query": "resolution"},
        ]},
        {"name": "story", "usage": "cvgen story", "method": "POST", "path": "/api/stories/zero", "args": []},
        {"name": "generate", "usage": "cvgen generate <镜头> [分辨率]", "method": "POST", "path": "/api/generate", "args": [
            {"name": "shot_id", "position": 0, "file": False},
            {"name": "resolution", "position": 1, "file": False, "optional": True},
        ]},
        {"name": "tts", "usage": "cvgen tts <台词>", "method": "POST", "path": "/api/tts", "args": [{"name": "target_id", "position": 0, "file": False}]},
        {"name": "pull", "usage": "cvgen pull <地址> [角色]", "method": "POST", "path": "/api/pull", "args": [
            {"name": "url", "position": 0, "file": False, "body": "detail.url"},
            {"name": "role", "position": 1, "file": False, "optional": True, "body": "detail.role"},
        ]},
        {"name": "inspect", "usage": "cvgen inspect <成片>", "method": "POST", "path": "/api/inspect", "args": [{"name": "target_id", "position": 0, "file": False}]},
        {"name": "reverse", "usage": "cvgen reverse <实体>", "method": "POST", "path": "/api/reverse", "args": [{"name": "target_id", "position": 0, "file": False}]},
        {"name": "learn", "usage": "cvgen learn <地址>", "method": "POST", "path": "/api/learn", "args": [
            {"name": "url", "position": 0, "file": False, "body": "detail.url"},
            {"name": "role", "const": "风格", "body": "detail.role"},
        ]},
        {"name": "style extract", "usage": "cvgen style extract <成片>", "method": "POST", "path": "/api/style", "args": [{"name": "target_id", "position": 0, "file": False}]},
        {"name": "reference upload", "usage": "cvgen reference upload <文件> --role <用途>", "method": "POST", "path": "/api/reference", "file": True, "args": [
            {"name": "file", "position": 0, "file": True},
            {"name": "role", "flag": "--role", "file": False},
            {"name": "title", "flag": "--title", "file": False, "optional": True},
        ]},
        {"name": "reference frame", "usage": "cvgen reference frame <成片> [--at first|last] [--role 用途]", "method": "POST", "path": "/api/frame", "args": [
            {"name": "target_id", "position": 0, "file": False},
            {"name": "at", "flag": "--at", "file": False, "optional": True, "body": "detail.at"},
            {"name": "role", "flag": "--role", "file": False, "optional": True, "body": "detail.role"},
        ]},
        {"name": "preview", "usage": "cvgen preview <实体>", "method": "GET", "path": "/api/preview/{0}", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "media upload", "usage": "cvgen media upload <文件> --kind image|video|audio", "method": "POST", "path": "/api/media", "file": True, "args": [
            {"name": "file", "position": 0, "file": True},
            {"name": "kind", "flag": "--kind", "file": False},
            {"name": "title", "flag": "--title", "file": False, "optional": True},
            {"name": "role", "flag": "--role", "file": False, "optional": True},
        ]},
        {"name": "media get", "usage": "cvgen media get <对象键>", "method": "GET", "path": "/media/{0}", "binary": True, "args": [{"name": "key", "position": 0, "file": False}]},
        {"name": "media", "usage": "cvgen media <对象键>", "method": "GET", "path": "/media/{0}", "binary": True, "args": [{"name": "key", "position": 0, "file": False}]},
        {"name": "image", "usage": "cvgen image <镜头> [--role 用途]", "method": "POST", "path": "/api/image", "args": [
            {"name": "target_id", "position": 0, "file": False},
            {"name": "role", "flag": "--role", "file": False, "optional": True, "body": "detail.role"},
        ]},
        {"name": "music", "usage": "cvgen music <文本>", "method": "POST", "path": "/api/music", "args": [{"name": "text", "position": 0, "file": False, "body": "detail.text"}]},
        {"name": "check", "usage": "cvgen check <成片>", "method": "POST", "path": "/api/check", "args": [{"name": "target_id", "position": 0, "file": False}]},
        {"name": "probe", "usage": "cvgen probe [video|image|music]", "method": "POST", "path": "/api/provider/probe", "reader": True, "args": [{"name": "capability", "position": 0, "file": False, "optional": True}]},
        {"name": "model list", "usage": "cvgen model list [--capability video|image|music]", "method": "POST", "path": "/api/provider/models", "reader": True, "args": [{"name": "capability", "flag": "--capability", "file": False, "optional": True}]},
        {"name": "model use", "usage": "cvgen model use <模型> [--capability video|image|music]", "method": "POST", "path": "/api/provider/model", "reader": True, "args": [
            {"name": "source", "position": 0, "file": False},
            {"name": "capability", "flag": "--capability", "file": False, "optional": True},
        ]},
        {"name": "ffmpeg", "usage": "cvgen ffmpeg -- <参数>...", "method": "POST", "path": "/api/ffmpeg", "args": [{"name": "args", "position": 0, "file": False, "rest": True, "body": "detail.args"}]},
        {"name": "edit join", "usage": "cvgen edit join <成片>...", "method": "POST", "path": "/api/edit", "args": [{"name": "clips", "position": 0, "file": False, "rest": True, "body": "detail.clips"}, {"name": "fade", "flag": "--fade", "file": False, "optional": True, "body": "detail.fade"}, {"name": "op", "const": "join", "body": "detail.op"}]},
        {"name": "edit export", "usage": "cvgen edit export <剪辑>", "method": "POST", "path": "/api/edit", "args": [{"name": "target_id", "position": 0, "file": False}, {"name": "op", "const": "export", "body": "detail.op"}]},
        {"name": "edit mix", "usage": "cvgen edit mix <剪辑>", "method": "POST", "path": "/api/edit", "args": [{"name": "target_id", "position": 0, "file": False}, {"name": "op", "const": "mix", "body": "detail.op"}]},
        {"name": "edit subtitle", "usage": "cvgen edit subtitle <剪辑>", "method": "POST", "path": "/api/edit", "args": [{"name": "target_id", "position": 0, "file": False}, {"name": "op", "const": "subtitle", "body": "detail.op"}]},
        {"name": "job show", "usage": "cvgen job show <任务>", "method": "GET", "path": "/api/job/{0}", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "job wait", "usage": "cvgen job wait <任务>", "method": "GET", "path": "/api/job/{0}", "wait": True, "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "skill list", "usage": "cvgen skill list", "method": "GET", "path": "/api/skills", "args": []},
        {"name": "skill show", "usage": "cvgen skill show <名称>", "method": "GET", "path": "/api/skills/{0}", "args": [{"name": "name", "position": 0, "file": False}]},
        {"name": "canvas", "usage": "cvgen canvas", "method": "GET", "path": "/api/work/current", "args": []},
        {"name": "batch show", "usage": "cvgen batch show <作品>", "method": "GET", "path": "/api/batch/{0}", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "workspace list", "usage": "cvgen workspace list", "method": "GET", "path": "/api/workspaces", "args": []},
        {"name": "workspace add", "usage": "cvgen workspace add <名称>", "method": "POST", "path": "/api/workspaces", "args": [{"name": "title", "position": 0, "file": False}]},
        {"name": "workspace rename", "usage": "cvgen workspace rename <工作区> <名称>", "method": "POST", "path": "/api/workspaces/{0}/rename", "args": [
            {"name": "id", "position": 0, "file": False},
            {"name": "title", "position": 1, "file": False},
        ]},
        {"name": "workspace use", "usage": "cvgen workspace use <工作区>", "method": "POST", "path": "/api/workspaces/use", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "work list", "usage": "cvgen work list", "method": "GET", "path": "/api/works", "args": []},
        {"name": "work", "usage": "cvgen work <名称> [类型] [简介]", "method": "POST", "path": "/api/works", "args": [
            {"name": "title", "position": 0, "file": False},
            {"name": "kind", "position": 1, "file": False, "optional": True},
            {"name": "brief", "position": 2, "file": False, "optional": True},
        ]},
        {"name": "work add", "usage": "cvgen work add <名称> [类型] [简介]", "method": "POST", "path": "/api/works", "args": [
            {"name": "title", "position": 0, "file": False},
            {"name": "kind", "position": 1, "file": False, "optional": True},
            {"name": "brief", "position": 2, "file": False, "optional": True},
        ]},
        {"name": "work use", "usage": "cvgen work use <作品>", "method": "POST", "path": "/api/works/use", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "retry", "usage": "cvgen retry <任务>", "method": "POST", "path": "/api/jobs/{0}/retry", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "prompt show", "usage": "cvgen prompt show <镜头>", "method": "GET", "path": "/api/shots/{0}/prompt", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "prompt save", "usage": "cvgen prompt save <镜头> <文本>", "method": "POST", "path": "/api/shots/{0}/prompt", "args": [
            {"name": "id", "position": 0, "file": False},
            {"name": "text", "position": 1, "file": False},
        ]},
        {"name": "prompt restore", "usage": "cvgen prompt restore <镜头> <序号>", "method": "POST", "path": "/api/shots/{0}/prompt/restore", "args": [
            {"name": "id", "position": 0, "file": False},
            {"name": "index", "position": 1, "file": False},
        ]},
        {"name": "redraw", "usage": "cvgen redraw <参考>", "method": "POST", "path": "/api/images/{0}/redraw", "args": [{"name": "id", "position": 0, "file": False}]},
        {"name": "layout save", "usage": "cvgen layout save <JSON>", "method": "POST", "path": "/api/layout", "args": [{"name": "positions", "position": 0, "file": False, "json": True}]},
        {"name": "layout tidy", "usage": "cvgen layout tidy", "method": "POST", "path": "/api/layout/tidy", "args": []},
    ]


def find(name: str) -> dict | None:
    for item in commands():
        if item["name"] == name:
            return item
    return None
