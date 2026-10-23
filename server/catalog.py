"""Command catalog served to the cvgen CLI (GET /api/cli). The CLI executes these generically.

Each argument says where its value comes from and where it goes:
- source: positional (position, variadic), flag (--name), or context (work / workspace, kept locally by
  `cvgen work use` / `cvgen workspace use`);
- type: string, int, float, bool (flag without value), json (inline JSON, @file, or - for stdin), list
  (comma-separated, or the rest of the positionals when variadic);
- in: path ({name} in the path), query, body, or input (body["input"][name]).
Commands marked local are implemented in the client (login, wait loops, downloads, uploads).
"""

from __future__ import annotations

SCHEMA_VERSION = 2
MIN_CLIENT = "0.2.0"


def pos(name: str, position: int, *, into: str = "body", type: str = "string", required: bool = True,
        variadic: bool = False, help: str = "") -> dict:
    return {"name": name, "source": "positional", "position": position, "in": into, "type": type,
            "required": required, "variadic": variadic, "help": help}


def flag(name: str, flag_name: str, *, into: str = "body", type: str = "string", required: bool = False,
         default=None, help: str = "") -> dict:
    spec = {"name": name, "source": "flag", "flag": flag_name, "in": into, "type": type, "required": required, "help": help}
    if default is not None:
        spec["default"] = default
    return spec


def ctx(name: str, context: str, *, into: str = "path") -> dict:
    return {"name": name, "source": "context", "context": context, "in": into, "type": "string", "required": True}


def cmd(name: str, usage: str, summary: str, method: str, path: str, args: list[dict] | None = None,
        body: dict | None = None, local: bool = False) -> dict:
    return {"name": name, "usage": usage, "summary": summary, "method": method, "path": path, "args": args or [],
            "body": body or {}, "local": local}


def task(name: str, usage: str, summary: str, kind: str, args: list[dict]) -> dict:
    return cmd(name, usage, summary, "POST", "/api/works/{work}/tasks", [ctx("work", "work"), *args], body={"kind": kind})


COMMANDS = [
    cmd("login", "cvgen login --base 服务地址 [--name 这台机器的名字]", "设备授权登录，等网页批准", "POST", "/api/device/start", local=True),
    cmd("logout", "cvgen logout", "删除本机凭证", "POST", "", local=True),
    cmd("status", "cvgen status", "当前登录、工作区、作品", "GET", "/api/auth/me", local=True),
    cmd("version", "cvgen version", "客户端版本", "GET", "", local=True),
    cmd("workspace list", "cvgen workspace list", "列出工作区", "GET", "/api/workspaces"),
    cmd("workspace use", "cvgen workspace use <工作区id>", "记住当前工作区（只存在本机）", "GET", "", local=True),
    cmd("work list", "cvgen work list", "列出当前工作区的作品", "GET", "/api/works",
        [ctx("workspace_id", "workspace", into="query"), flag("origin", "--origin", into="query", help="explore 或 run")]),
    cmd("work new", "cvgen work new <名称> [--kind 短片|广告] [--brief 主题]", "新建作品并设为当前作品", "POST", "/api/works",
        [ctx("workspace_id", "workspace", into="body"), pos("title", 0), flag("kind", "--kind"), flag("brief", "--brief")]),
    cmd("work use", "cvgen work use <作品id>", "记住当前作品（只存在本机）", "GET", "", local=True),
    cmd("work show", "cvgen work show", "当前作品的实体、关系和任务", "GET", "/api/works/{work}", [ctx("work", "work")]),
    cmd("storyboard", "cvgen storyboard [--resolution 768p横]", "按镜头顺序看提示词、参考、成片和花费", "GET",
        "/api/works/{work}/storyboard", [ctx("work", "work"), flag("resolution", "--resolution", into="query")]),
    cmd("entity add", "cvgen entity add <类型> <JSON> [--artifact 文件id]", "在当前作品里加实体", "POST",
        "/api/works/{work}/entities", [ctx("work", "work"), pos("type", 0), pos("data", 1, type="json"),
                                       flag("artifact_id", "--artifact")]),
    cmd("entity show", "cvgen entity show <实体id>", "看一个实体和它的关系", "GET", "/api/entities/{id}",
        [pos("id", 0, into="path")]),
    cmd("entity set", "cvgen entity set <实体id> <JSON> [--replace]", "修改实体字段（默认合并）", "PATCH", "/api/entities/{id}",
        [pos("id", 0, into="path"), pos("data", 1, type="json"), flag("replace", "--replace", type="bool")]),
    cmd("entity rm", "cvgen entity rm <实体id>", "删除实体（软删除，连带关系）", "DELETE", "/api/entities/{id}",
        [pos("id", 0, into="path")]),
    cmd("link", "cvgen link <关系> <起点> <终点> [说明]", "连关系。终点可以是实体 id 或 asset:名称@版本", "POST",
        "/api/works/{work}/links", [ctx("work", "work"), pos("name", 0), pos("source", 1), pos("target", 2),
                                    pos("note", 3, required=False)]),
    cmd("unlink", "cvgen unlink <关系id>", "删除一条关系", "DELETE", "/api/links/{id}", [pos("id", 0, into="path")]),
    cmd("shot compose", "cvgen shot compose <镜头> [--resolution 768p横]", "组合四段式提示词，不提交", "GET",
        "/api/entities/{shot}/compose", [pos("shot", 0, into="path"), flag("resolution", "--resolution", into="query")]),
    cmd("shot prompt", "cvgen shot prompt <镜头> <新的主动作>", "保存一版新的主动作文字", "POST", "/api/entities/{shot}/prompt",
        [pos("shot", 0, into="path"), pos("text", 1)]),
    task("generate", "cvgen generate <镜头> [--resolution 768p横] [--force] [--again] [--provider video.x] [--template asset:x@1]",
         "提交生视频。有组合警告时要 --force；已成片要再生成一版要 --again", "video",
         [pos("shot_id", 0, into="input"), flag("resolution", "--resolution", into="input"),
          flag("allow_warnings", "--force", into="input", type="bool"), flag("again", "--again", type="bool"),
          flag("provider", "--provider"), flag("template", "--template", into="input")]),
    task("image", "cvgen image <镜头> [--role 首帧] [--prompt 描述] [--n 2] [--ref 文件id,文件id]", "生图并连到镜头", "image",
         [pos("shot_id", 0, into="input"), flag("role", "--role", into="input", default="细节"),
          flag("prompt", "--prompt", into="input"), flag("n", "--n", into="input", type="int"),
          flag("references", "--ref", into="input", type="list"), flag("provider", "--provider")]),
    task("tts", "cvgen tts <台词> <音色>", "给一句台词配音。音色是实体 id 或 asset:名称@版本", "tts",
         [pos("line_id", 0, into="input"), pos("voice", 1, into="input"), flag("provider", "--provider")]),
    task("music", "cvgen music <描述> [--lyrics 歌词] [--duration 秒]", "生成配乐", "music",
         [pos("prompt", 0, into="input"), flag("lyrics", "--lyrics", into="input"),
          flag("duration", "--duration", into="input", type="int"), flag("provider", "--provider")]),
    task("pull", "cvgen pull <地址> [--role 风格] [--learn] [--title 名称]", "让服务下载网上的图或片子入库", "pull",
         [pos("url", 0, into="input"), flag("role", "--role", into="input"), flag("learn", "--learn", into="input", type="bool"),
          flag("title", "--title", into="input")]),
    task("inspect", "cvgen inspect <实体> [--mode inspect|reverse|style]", "量时长、声音、接触表；reverse 出复述草稿", "inspect",
         [pos("entity_id", 0, into="input"), flag("mode", "--mode", into="input")]),
    task("frame", "cvgen frame <成片> [--at last|first|秒] [--role 空间]", "抽一帧作为参考", "frame",
         [pos("clip_id", 0, into="input"), flag("at", "--at", into="input"), flag("role", "--role", into="input")]),
    task("check", "cvgen check <成片> [--resolution 768p横]", "核对时长、分辨率、声音，出接触表", "check",
         [pos("clip_id", 0, into="input"), flag("resolution", "--resolution", into="input")]),
    task("edit", "cvgen edit <成片...> [--fade 秒] [--music 成片或asset:] [--narration 成片] [--subtitle 台词JSON] [--export 分辨率] [--title 名称]",
         "拼接、混音、字幕、导出", "edit",
         [pos("clips", 0, into="input", type="list", variadic=True), flag("fade", "--fade", into="input", type="float"),
          flag("music", "--music", into="input"), flag("narration", "--narration", into="input"),
          flag("lines", "--subtitle", into="input", type="json"), flag("export", "--export", into="input"),
          flag("title", "--title", into="input")]),
    task("ffmpeg", "cvgen ffmpeg [--input 名=文件id,…] [--output 文件名,…] -- <ffmpeg 参数…>",
         "管理员打开透传后，在任务目录里跑 ffmpeg", "ffmpeg",
         [pos("args", 0, into="input", type="list", variadic=True), flag("inputs", "--input", into="input", type="list"),
          flag("outputs", "--output", into="input", type="list")]),
    cmd("upload", "cvgen upload <文件> [--label 名称]", "上传本机文件，返回文件 id", "POST", "/api/uploads",
        [ctx("workspace_id", "workspace", into="body"), pos("file", 0), flag("label", "--label")], local=True),
    cmd("media get", "cvgen media get <文件id> -o <保存路径>", "下载成片、接触表、参考图", "GET", "/media/{id}", local=True),
    cmd("job list", "cvgen job list [--status ready,running]", "当前作品的任务", "GET", "/api/tasks",
        [ctx("work_id", "work", into="query"), flag("status", "--status", into="query")]),
    cmd("job show", "cvgen job show <任务id>", "任务详情、排队位置、产物链接", "GET", "/api/tasks/{id}", [pos("id", 0, into="path")]),
    cmd("job wait", "cvgen job wait <任务id> [--timeout 秒]", "一直等到任务结束，持续打印进度", "GET", "/api/tasks/{id}/wait", local=True),
    cmd("job cancel", "cvgen job cancel <任务id>", "取消任务", "POST", "/api/tasks/{id}/cancel", [pos("id", 0, into="path")]),
    cmd("job retry", "cvgen job retry <任务id>", "失败或取消的探索任务再跑一次", "POST", "/api/tasks/{id}/retry",
        [pos("id", 0, into="path")]),
    cmd("asset list", "cvgen asset list [--kind Style]", "素材库", "GET", "/api/assets",
        [ctx("workspace_id", "workspace", into="query"), flag("kind", "--kind", into="query")]),
    cmd("asset show", "cvgen asset show <名称>", "素材的全部版本", "GET", "/api/assets/{workspace}/{name}",
        [ctx("workspace", "workspace"), pos("name", 0, into="path")]),
    cmd("asset save", "cvgen asset save <名称> <类型> <JSON> [--artifact 文件id] [--note 说明]", "新建素材或追加一个版本", "POST",
        "/api/assets", [ctx("workspace_id", "workspace", into="body"), pos("name", 0), pos("kind", 1),
                        pos("data", 2, type="json"), flag("artifact_id", "--artifact"), flag("note", "--note")]),
    cmd("asset promote", "cvgen asset promote <实体> <素材名> [--note 说明]", "把作品里的实体提升为素材库的新版本", "POST",
        "/api/assets/promote", [pos("entity_id", 0), pos("name", 1), flag("note", "--note")]),
    cmd("workflow list", "cvgen workflow list", "工作流和版本", "GET", "/api/workflows", [ctx("workspace_id", "workspace", into="query")]),
    cmd("workflow draft", "cvgen workflow draft <规格.json> [--notes 说明] [--from-work]", "提交一个新的草稿版本", "POST",
        "/api/workflows", [ctx("workspace_id", "workspace", into="body"), pos("spec", 0, type="json"),
                           flag("notes", "--notes"), flag("source_work_id", "--from-work")]),
    cmd("workflow show", "cvgen workflow show <工作流id> <版本>", "看规格、校验结果、样例", "GET",
        "/api/workflows/{id}/versions/{version}", [pos("id", 0, into="path"), pos("version", 1, into="path")]),
    cmd("workflow update", "cvgen workflow update <工作流id> <版本> <规格.json>", "修改草稿", "PUT",
        "/api/workflows/{id}/versions/{version}", [pos("id", 0, into="path"), pos("version", 1, into="path"),
                                                   pos("spec", 2, type="json")]),
    cmd("workflow validate", "cvgen workflow validate <工作流id> <版本> [--env]", "结构和语义校验；--env 核对 GPU 机环境", "POST",
        "/api/workflows/{id}/versions/{version}/validate", [pos("id", 0, into="path"), pos("version", 1, into="path"),
                                                            flag("check_env", "--env", into="query", type="bool")]),
    cmd("workflow dry-run", "cvgen workflow dry-run <工作流id> <版本> <输入.json> [--level compile|llm]",
        "不花钱编译全部提示词和估算；llm 级只真实调用大模型", "POST", "/api/workflows/{id}/versions/{version}/dry-run",
        [pos("id", 0, into="path"), pos("version", 1, into="path"), pos("inputs", 2, type="json"),
         flag("level", "--level", default="compile")]),
    cmd("workflow trial", "cvgen workflow trial <工作流id> <版本> <输入.json>", "完整试跑一次（会花钱）", "POST",
        "/api/workflows/{id}/versions/{version}/trial", [pos("id", 0, into="path"), pos("version", 1, into="path"),
                                                         pos("inputs", 2, type="json")]),
    cmd("workflow fixtures", "cvgen workflow fixtures <工作流id> <版本> --from-run <运行id>", "把一次运行的大模型输出存成试跑样例",
        "POST", "/api/workflows/{id}/versions/{version}/fixtures-from-run",
        [pos("id", 0, into="path"), pos("version", 1, into="path"), flag("run_id", "--from-run", required=True)]),
    cmd("workflow diff", "cvgen workflow diff <工作流id> <旧版本> <新版本>", "两个版本的差异", "GET", "/api/workflows/{id}/diff",
        [pos("id", 0, into="path"), pos("base", 1, into="query"), pos("head", 2, into="query")]),
    cmd("run list", "cvgen run list [--status running]", "运行列表", "GET", "/api/runs",
        [ctx("workspace_id", "workspace", into="query"), flag("status", "--status", into="query")]),
    cmd("run show", "cvgen run show <运行id>", "阶段、每条产物、花费", "GET", "/api/runs/{id}", [pos("id", 0, into="path")]),
    cmd("run wait", "cvgen run wait <运行id> [--timeout 秒]", "等到运行结束或停在闸门", "GET", "/api/runs/{id}", local=True),
    cmd("run cancel", "cvgen run cancel <运行id>", "取消运行", "POST", "/api/runs/{id}/cancel", [pos("id", 0, into="path")]),
    cmd("review list", "cvgen review list [--all]", "审计员给当前作品的意见", "GET", "/api/notes",
        [ctx("work_id", "work", into="query"), flag("all", "--all", into="query", type="bool")]),
    cmd("review resolve", "cvgen review resolve <意见id>", "处理完一条意见", "POST", "/api/notes/{id}/resolve",
        [pos("id", 0, into="path")]),
    cmd("cost", "cvgen cost [--group day|work|run]", "花费汇总", "GET", "/api/costs",
        [ctx("workspace_id", "workspace", into="query"), flag("group", "--group", into="query", default="day")]),
    cmd("queue", "cvgen queue", "各资源池占用和排队", "GET", "/api/queue"),
    cmd("skill list", "cvgen skill list", "操作手册目录", "GET", "/api/skills"),
    cmd("skill show", "cvgen skill show <名称>", "读一份操作手册（原文输出）", "GET", "/api/skills/{name}",
        [pos("name", 0, into="path")]),
    cmd("ontology", "cvgen ontology", "实体类型、关系和约束", "GET", "/api/ontology"),
]


def catalog() -> dict:
    return {"schema_version": SCHEMA_VERSION, "min_client": MIN_CLIENT, "commands": COMMANDS}
