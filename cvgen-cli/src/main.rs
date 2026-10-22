//! cvgen operator. It starts hosted work and reads results. It does not set up an environment.

use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::ExitCode;
use std::thread;
use std::time::Duration;

use serde_json::{json, Value};

const DEFAULT_BASE: &str = "http://127.0.0.1:8080";

fn main() -> ExitCode {
    let mut stdout = io::stdout();
    match run(env::args().skip(1).collect(), &mut stdout) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            ExitCode::from(1)
        }
    }
}

fn run(args: Vec<String>, stdout: &mut dyn Write) -> Result<(), String> {
    let mut args = args.into_iter().peekable();
    let command = args.next().unwrap_or_else(|| "help".to_string());
    if command == "--help" || command == "-h" || command == "help" {
        print_help(stdout)?;
        return Ok(());
    }
    if command == "setup" {
        return Err("没有 setup 命令。直接运行 cvgen login。".into());
    }
    match command.as_str() {
        "login" => login(stdout, &parse_flags(args.collect())?),
        "ontology" => authed_print(stdout, "GET", "/api/ontology", None),
        "entity" => entity(stdout, args.collect()),
        "link" => link(stdout, args.collect()),
        "derive" => derive(stdout, args.collect()),
        "shot" => shot(stdout, args.collect()),
        "story" => authed_print(stdout, "POST", "/api/stories/zero", Some(json!({}))),
        "generate" => generate(stdout, args.collect()),
        "tts" => one_body(stdout, args.collect(), |id| ("POST", "/api/tts".into(), json!({"target_id": id}))),
        "pull" => pull(stdout, args.collect()),
        "inspect" => one_body(stdout, args.collect(), |id| ("POST", "/api/inspect".into(), json!({"target_id": id}))),
        "reverse" => one_body(stdout, args.collect(), |id| ("POST", "/api/reverse".into(), json!({"target_id": id}))),
        "learn" => learn(stdout, args.collect()),
        "style" => style_cmd(stdout, args.collect()),
        "reference" => reference_upload(stdout, args.collect()),
        "preview" => one_path(stdout, args.collect(), |id| format!("/api/preview/{id}"), "GET"),
        "media" => media_cmd(stdout, args.collect()),
        "image" => image_cmd(stdout, args.collect()),
        "music" => music_cmd(stdout, args.collect()),
        "check" => one_body(stdout, args.collect(), |id| ("POST", "/api/check".into(), json!({"target_id": id}))),
        "ffmpeg" => ffmpeg(stdout, args.collect()),
        "edit" => edit(stdout, args.collect()),
        "job" => job(stdout, args.collect()),
        "skill" => skill(stdout, args.collect()),
        "canvas" => authed_print(stdout, "GET", "/api/canvas", None),
        "batch" => batch(stdout, args.collect()),
        "work" => work(stdout, args.collect()),
        other => Err(format!("未知命令 {other}。运行 cvgen --help。")),
    }
}

fn print_help(stdout: &mut dyn Write) -> Result<(), String> {
    let text = "\
cvgen 操作云端视频系统。执行由服务完成。

用法：
  cvgen login [--base 地址]
  cvgen ontology
  cvgen entity add <类型> <JSON>
  cvgen entity get <实体>
  cvgen entity query [类型]
  cvgen link <关系> <来源> <目标> [说明]
  cvgen derive <来源> <目标> [说明]
  cvgen shot compose <镜头> [分辨率]
  cvgen story
  cvgen generate <镜头> [分辨率] [--force]
  cvgen tts <台词>
  cvgen pull <地址> [角色]
  cvgen inspect <成片>
  cvgen reverse <实体>
  cvgen learn <地址>
  cvgen style extract <成片>
  cvgen reference upload <文件> --role <用途> [--title 名称]
  cvgen reference frame <成片> [--at first|last] [--role 首帧|尾帧|空间]
  cvgen preview <实体>
  cvgen media upload <文件> --kind image|video|audio
  cvgen media get <对象键>
  cvgen image <镜头> [--role 用途]
  cvgen music <台词或文本>
  cvgen check <成片>
  cvgen ffmpeg -- <参数>...
  cvgen edit join <成片>... [--fade 秒]
  cvgen edit export <剪辑>
  cvgen edit mix <剪辑>
  cvgen edit subtitle <剪辑>
  cvgen job show <任务>
  cvgen job wait <任务>
  cvgen skill list
  cvgen skill show <名称>
  cvgen canvas
  cvgen batch show <作品>
  cvgen work <标题> [类型] [简介]

先运行 cvgen login。网页管理员批准后，凭证只保存在本机。
";
    write!(stdout, "{text}").map_err(|err| err.to_string())
}

fn entity(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    match args.next().as_deref() {
        Some("add") => {
            let type_name = need(args.next(), "缺少类型")?;
            let data = need(args.next(), "缺少 JSON")?;
            let parsed: Value = serde_json::from_str(&data).map_err(|err| format!("JSON 无法解析：{err}"))?;
            authed_print(stdout, "POST", "/api/entity", Some(json!({"type": type_name, "data": parsed})))
        }
        Some("get") => {
            let id = need(args.next(), "缺少实体")?;
            authed_print(stdout, "GET", &format!("/api/entity/{id}"), None)
        }
        Some("query") => {
            let type_name = args.next().unwrap_or_default();
            let path = if type_name.is_empty() {
                "/api/entities".to_string()
            } else {
                format!("/api/entities?type={type_name}")
            };
            authed_print(stdout, "GET", &path, None)
        }
        Some(other) => Err(format!("未知 entity 子命令 {other}")),
        None => Err("用法：cvgen entity add|get|query".into()),
    }
}

fn link(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    let name = need(args.next(), "缺少关系")?;
    let source = need(args.next(), "缺少来源")?;
    let target = need(args.next(), "缺少目标")?;
    let note = args.next().unwrap_or_default();
    authed_print(
        stdout,
        "POST",
        "/api/link",
        Some(json!({"name": name, "source_id": source, "target_id": target, "note": note})),
    )
}

fn derive(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    let source = need(args.next(), "缺少来源")?;
    let target = need(args.next(), "缺少目标")?;
    let note = args.next().unwrap_or_default();
    authed_print(
        stdout,
        "POST",
        "/api/derive",
        Some(json!({"name": "derived_from", "source_id": source, "target_id": target, "note": note})),
    )
}

fn shot(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    if args.next().as_deref() != Some("compose") {
        return Err("用法：cvgen shot compose <镜头> [分辨率]".into());
    }
    let shot_id = need(args.next(), "缺少镜头")?;
    let resolution = args.next().unwrap_or_else(|| "768p横".into());
    authed_print(stdout, "GET", &format!("/api/shot/{shot_id}/compose?resolution={resolution}"), None)
}

fn generate(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut positional = Vec::new();
    let mut force = false;
    for arg in args {
        if arg == "--force" {
            force = true;
        } else {
            positional.push(arg);
        }
    }
    let shot_id = need(positional.first().cloned(), "缺少镜头")?;
    let resolution = positional.get(1).cloned().unwrap_or_else(|| "768p横".into());
    authed_print(
        stdout,
        "POST",
        "/api/generate",
        Some(json!({"shot_id": shot_id, "resolution": resolution, "force": force})),
    )
}

fn pull(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    let url = need(args.next(), "缺少地址")?;
    let role = args.next().unwrap_or_else(|| "风格".into());
    authed_print(stdout, "POST", "/api/pull", Some(json!({"detail": {"url": url, "role": role}})))
}

fn learn(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let url = need(args.into_iter().next(), "缺少地址")?;
    authed_print(stdout, "POST", "/api/learn", Some(json!({"detail": {"url": url, "role": "风格"}})))
}

fn ffmpeg(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let ffmpeg_args: Vec<String> = args.into_iter().filter(|arg| arg != "--").collect();
    authed_print(stdout, "POST", "/api/ffmpeg", Some(json!({"detail": {"args": ffmpeg_args}})))
}

fn edit(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter().peekable();
    match args.next().as_deref() {
        Some("join") => {
            let mut clips = Vec::new();
            let mut fade = 2.0;
            while let Some(arg) = args.next() {
                if arg == "--fade" {
                    let value = need(args.next(), "缺少淡入秒数")?;
                    fade = value.parse().map_err(|_| format!("淡入秒数无法解析：{value}"))?;
                } else {
                    clips.push(arg);
                }
            }
            if clips.is_empty() {
                return Err("缺少成片".into());
            }
            authed_print(stdout, "POST", "/api/edit", Some(json!({"detail": {"op": "join", "clips": clips, "fade": fade}})))
        }
        Some("export") => {
            let id = need(args.next(), "缺少剪辑")?;
            authed_print(stdout, "POST", "/api/edit", Some(json!({"target_id": id, "detail": {"op": "export"}})))
        }
        Some("mix") => {
            let id = need(args.next(), "缺少剪辑")?;
            authed_print(stdout, "POST", "/api/edit", Some(json!({"target_id": id, "detail": {"op": "mix"}})))
        }
        Some("subtitle") => {
            let id = need(args.next(), "缺少剪辑")?;
            authed_print(stdout, "POST", "/api/edit", Some(json!({"target_id": id, "detail": {"op": "subtitle"}})))
        }
        _ => Err("用法：cvgen edit join|export|mix|subtitle".into()),
    }
}

fn job(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    match args.next().as_deref() {
        Some("show") => {
            let id = need(args.next(), "缺少任务")?;
            authed_print(stdout, "GET", &format!("/api/job/{id}"), None)
        }
        Some("wait") => job_wait(stdout, args.collect()),
        _ => Err("用法：cvgen job show|wait <任务>".into()),
    }
}

fn job_wait(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let id = need(args.into_iter().next(), "缺少任务")?;
    let path = format!("/api/job/{id}");
    let saved = load_auth()?;
    let started = std::time::Instant::now();
    loop {
        let value = request_auth("GET", &saved.base, &path, &saved.token, None)?;
        let status = value.get("status").and_then(Value::as_str).unwrap_or("");
        if status == "succeeded" || status == "failed" || status == "unknown" {
            return print_json(stdout, &value);
        }
        if started.elapsed() > Duration::from_secs(120) {
            return Err("任务还没结束。".into());
        }
        thread::sleep(Duration::from_millis(400));
    }
}

fn style_cmd(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    let first = need(args.next(), "缺少成片")?;
    let id = if first == "extract" {
        need(args.next(), "缺少成片")?
    } else {
        first
    };
    authed_print(stdout, "POST", "/api/style", Some(json!({"target_id": id})))
}

fn reference_upload(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut positional = Vec::new();
    let mut role = String::new();
    let mut title = String::new();
    let mut take = String::new();
    let mut ignore = String::new();
    let mut at = "last".to_string();
    let mut args = args.into_iter();
    match args.next().as_deref() {
        Some("frame") => {
            while let Some(arg) = args.next() {
                match arg.as_str() {
                    "--at" => at = need(args.next(), "缺少位置")?,
                    "--role" => role = need(args.next(), "缺少用途")?,
                    other => positional.push(other.to_string()),
                }
            }
            let clip_id = need(positional.first().cloned(), "缺少成片")?;
            if role.is_empty() {
                role = "空间".into();
            }
            return authed_print(
                stdout,
                "POST",
                "/api/frame",
                Some(json!({"target_id": clip_id, "detail": {"at": at, "role": role}})),
            );
        }
        Some("upload") => {}
        _ => return Err("用法：cvgen reference upload|frame".into()),
    }
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--role" => role = need(args.next(), "缺少用途")?,
            "--title" => title = need(args.next(), "缺少名称")?,
            "--take" => take = need(args.next(), "缺少采用说明")?,
            "--ignore" => ignore = need(args.next(), "缺少忽略说明")?,
            other => positional.push(other.to_string()),
        }
    }
    let path = need(positional.first().cloned(), "缺少文件")?;
    if role.is_empty() {
        return Err("缺少用途。加上 --role。".into());
    }
    let saved = load_auth()?;
    let value = upload_reference(&saved.base, &saved.token, &path, &role, &title, &take, &ignore)?;
    print_json(stdout, &value)
}

fn upload_reference(
    base: &str,
    token: &str,
    path: &str,
    role: &str,
    title: &str,
    take: &str,
    ignore: &str,
) -> Result<Value, String> {
    let file = Path::new(path);
    if !file.is_file() {
        return Err("参考文件不存在。".into());
    }
    let filename = file.file_name().and_then(|name| name.to_str()).unwrap_or("ref.bin").to_string();
    let bytes = fs::read(file).map_err(|err| format!("无法读取参考文件：{err}"))?;
    let boundary = format!("cvgen{}", std::process::id());
    let mut body = Vec::new();
    for (name, value) in [("role", role), ("title", title), ("take", take), ("ignore", ignore)] {
        body.extend_from_slice(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").as_bytes());
    }
    body.extend_from_slice(
        format!("--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").as_bytes(),
    );
    body.extend_from_slice(&bytes);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    let url = format!("{}/api/reference", base.trim_end_matches('/'));
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(120))
        .no_proxy()
        .build()
        .map_err(|err| format!("无法建立连接：{err}"))?;
    let response = client
        .post(url)
        .header("Authorization", format!("Bearer {token}"))
        .header("Content-Type", format!("multipart/form-data; boundary={boundary}"))
        .body(body)
        .send()
        .map_err(|err| format!("请求失败：{err}"))?;
    let status = response.status();
    let text = response.text().map_err(|err| format!("无法读取响应：{err}"))?;
    if !status.is_success() {
        return Err(format!("服务返回 {}", status.as_u16()));
    }
    serde_json::from_str(&text).map_err(|err| format!("响应不是 JSON：{err}"))
}

fn media_cmd(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    match args.next().as_deref() {
        Some("upload") => media_upload(stdout, args.collect()),
        Some("get") => media_get(stdout, args.collect()),
        Some(other) if !other.starts_with('-') && args.next().is_none() => media_get(stdout, vec![other.to_string()]),
        _ => Err("用法：cvgen media upload|get".into()),
    }
}

fn media_upload(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut positional = Vec::new();
    let mut kind = String::new();
    let mut title = String::new();
    let mut role = "细节".to_string();
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        match arg.as_str() {
            "--kind" => kind = need(args.next(), "缺少种类")?,
            "--title" => title = need(args.next(), "缺少名称")?,
            "--role" => role = need(args.next(), "缺少用途")?,
            other => positional.push(other.to_string()),
        }
    }
    let path = need(positional.first().cloned(), "缺少文件")?;
    if kind != "image" && kind != "video" && kind != "audio" {
        return Err("文件种类只能是 image、video 或 audio。".into());
    }
    let saved = load_auth()?;
    let value = upload_media(&saved.base, &saved.token, &path, &kind, &title, &role)?;
    print_json(stdout, &value)
}

fn upload_media(base: &str, token: &str, path: &str, kind: &str, title: &str, role: &str) -> Result<Value, String> {
    let file = Path::new(path);
    if !file.is_file() {
        return Err("文件不存在。".into());
    }
    let filename = file.file_name().and_then(|name| name.to_str()).unwrap_or("media.bin").to_string();
    let bytes = fs::read(file).map_err(|err| format!("无法读取文件：{err}"))?;
    let boundary = format!("cvgen{}", std::process::id());
    let mut body = Vec::new();
    for (name, value) in [("kind", kind), ("title", title), ("role", role)] {
        body.extend_from_slice(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").as_bytes());
    }
    body.extend_from_slice(
        format!("--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").as_bytes(),
    );
    body.extend_from_slice(&bytes);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    let url = format!("{}/api/media", base.trim_end_matches('/'));
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(120))
        .no_proxy()
        .build()
        .map_err(|err| format!("无法建立连接：{err}"))?;
    let response = client
        .post(url)
        .header("Authorization", format!("Bearer {token}"))
        .header("Content-Type", format!("multipart/form-data; boundary={boundary}"))
        .body(body)
        .send()
        .map_err(|err| format!("请求失败：{err}"))?;
    let status = response.status();
    let text = response.text().map_err(|err| format!("无法读取响应：{err}"))?;
    if !status.is_success() {
        return Err(format!("服务返回 {}", status.as_u16()));
    }
    serde_json::from_str(&text).map_err(|err| format!("响应不是 JSON：{err}"))
}

fn image_cmd(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut positional = Vec::new();
    let mut role = "细节".to_string();
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        if arg == "--role" {
            role = need(args.next(), "缺少用途")?;
        } else {
            positional.push(arg);
        }
    }
    let shot_id = need(positional.first().cloned(), "缺少镜头")?;
    authed_print(stdout, "POST", "/api/image", Some(json!({"target_id": shot_id, "detail": {"role": role}})))
}

fn music_cmd(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let text = args.join(" ");
    if text.trim().is_empty() {
        return Err("缺少台词或文本".into());
    }
    authed_print(stdout, "POST", "/api/music", Some(json!({"detail": {"text": text}})))
}

fn media_get(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let key = need(args.into_iter().next(), "缺少对象键")?;
    let saved = load_auth()?;
    let url = format!("{}/media/{}", saved.base.trim_end_matches('/'), key.trim_start_matches('/'));
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(60))
        .no_proxy()
        .build()
        .map_err(|err| format!("无法建立连接：{err}"))?;
    let response = client
        .get(url)
        .header("Authorization", format!("Bearer {}", saved.token))
        .send()
        .map_err(|err| format!("请求失败：{err}"))?;
    let status = response.status();
    let bytes = response.bytes().map_err(|err| format!("无法读取文件：{err}"))?;
    if !status.is_success() {
        return Err(format!("服务返回 {}", status.as_u16()));
    }
    print_json(stdout, &json!({"object_key": key, "bytes": bytes.len()}))
}

fn skill(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    match args.next().as_deref() {
        Some("list") => authed_print(stdout, "GET", "/api/skills", None),
        Some("show") => {
            let name = need(args.next(), "缺少技能名")?;
            authed_print(stdout, "GET", &format!("/api/skills/{name}"), None)
        }
        _ => Err("用法：cvgen skill list|show".into()),
    }
}

fn batch(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    let first = need(args.next(), "缺少作品")?;
    let id = if first == "show" {
        need(args.next(), "缺少作品")?
    } else {
        first
    };
    authed_print(stdout, "GET", &format!("/api/batch/{id}"), None)
}

fn work(stdout: &mut dyn Write, args: Vec<String>) -> Result<(), String> {
    let mut args = args.into_iter();
    let title = need(args.next(), "缺少标题")?;
    let kind = args.next().unwrap_or_else(|| "短片".into());
    let brief = args.next().unwrap_or_default();
    authed_print(
        stdout,
        "POST",
        "/api/entity",
        Some(json!({"type": "Work", "data": {"title": title, "kind": kind, "brief": brief}})),
    )
}

fn one_body(
    stdout: &mut dyn Write,
    args: Vec<String>,
    build: impl Fn(String) -> (&'static str, String, Value),
) -> Result<(), String> {
    let id = need(args.into_iter().next(), "缺少参数")?;
    let (method, path, body) = build(id);
    authed_print(stdout, method, &path, Some(body))
}

fn one_path(stdout: &mut dyn Write, args: Vec<String>, path: impl Fn(String) -> String, method: &str) -> Result<(), String> {
    let id = need(args.into_iter().next(), "缺少参数")?;
    authed_print(stdout, method, &path(id), None)
}

fn login(stdout: &mut dyn Write, flags: &Flags) -> Result<(), String> {
    let base = flags.base.clone().unwrap_or_else(|| DEFAULT_BASE.into());
    let started = request_public("POST", &base, "/api/device/start", None)?;
    let code = started["code"].as_str().unwrap_or("").to_string();
    let approve = started["approve_url"].as_str().unwrap_or("").to_string();
    println!("设备码 {code}");
    println!("在网页批准：{approve}");
    for _ in 0..60 {
        let polled = request_public("GET", &base, &format!("/api/device/{code}"), None)?;
        if polled.get("status").and_then(Value::as_str) == Some("approved") {
            let token = polled["token"].as_str().unwrap_or("").to_string();
            save_auth(&base, &token)?;
            writeln!(stdout, "已授权。凭证只保存在本机。").map_err(|err| err.to_string())?;
            return Ok(());
        }
        thread::sleep(Duration::from_secs(2));
    }
    Err("等待批准超时。".into())
}

fn parse_flags(args: Vec<String>) -> Result<Flags, String> {
    let mut flags = Flags { base: None };
    let mut args = args.into_iter();
    while let Some(arg) = args.next() {
        if arg == "--base" {
            flags.base = Some(need(args.next(), "缺少地址")?);
        } else if let Some(value) = arg.strip_prefix("--base=") {
            flags.base = Some(value.to_string());
        } else {
            return Err(format!("未知参数 {arg}"));
        }
    }
    Ok(flags)
}

struct Flags {
    base: Option<String>,
}

fn authed_print(stdout: &mut dyn Write, method: &str, path: &str, body: Option<Value>) -> Result<(), String> {
    let saved = load_auth()?;
    let value = request_auth(method, &saved.base, path, &saved.token, body)?;
    print_json(stdout, &value)
}

fn print_json(stdout: &mut dyn Write, value: &Value) -> Result<(), String> {
    let text = serde_json::to_string_pretty(value).map_err(|err| err.to_string())?;
    writeln!(stdout, "{text}").map_err(|err| err.to_string())
}

struct Auth {
    base: String,
    token: String,
}

fn auth_path() -> PathBuf {
    if let Ok(path) = env::var("CVGEN_AUTH") {
        return PathBuf::from(path);
    }
    home_dir().join(".cvgen").join("auth.json")
}

fn home_dir() -> PathBuf {
    env::var_os("HOME")
        .or_else(|| env::var_os("USERPROFILE"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn load_auth() -> Result<Auth, String> {
    let path = auth_path();
    if !path.is_file() {
        return Err("还没有登录。先运行 cvgen login。".into());
    }
    let text = fs::read_to_string(&path).map_err(|err| format!("无法读取凭证：{err}"))?;
    let value: Value = serde_json::from_str(&text).map_err(|err| format!("凭证无法解析：{err}"))?;
    Ok(Auth {
        base: value["base"].as_str().unwrap_or("").to_string(),
        token: value["token"].as_str().unwrap_or("").to_string(),
    })
}

fn save_auth(base: &str, token: &str) -> Result<(), String> {
    let path = auth_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("无法建立凭证目录：{err}"))?;
    }
    let payload = serde_json::to_string(&json!({"base": base, "token": token})).map_err(|err| err.to_string())?;
    write_owner_only(&path, payload.as_bytes())
}

fn write_owner_only(path: &Path, bytes: &[u8]) -> Result<(), String> {
    use std::io::Write as _;
    let mut options = fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).map_err(|err| format!("无法写入凭证：{err}"))?;
    file.write_all(bytes).map_err(|err| format!("无法写入凭证：{err}"))?;
    file.sync_all().ok();
    Ok(())
}

fn request_public(method: &str, base: &str, path: &str, body: Option<Value>) -> Result<Value, String> {
    request(method, base, path, None, body)
}

fn request_auth(method: &str, base: &str, path: &str, token: &str, body: Option<Value>) -> Result<Value, String> {
    request(method, base, path, Some(token), body)
}

fn request(method: &str, base: &str, path: &str, token: Option<&str>, body: Option<Value>) -> Result<Value, String> {
    let url = format!("{}{}", base.trim_end_matches('/'), path);
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(60))
        .no_proxy()
        .build()
        .map_err(|err| format!("无法建立连接：{err}"))?;
    let mut builder = client.request(method.parse().map_err(|_| format!("未知方法 {method}"))?, &url);
    if let Some(token) = token {
        builder = builder.header("Authorization", format!("Bearer {token}"));
    }
    if let Some(body) = body {
        builder = builder.json(&body);
    }
    let response = builder.send().map_err(|err| format!("请求失败：{err}"))?;
    let status = response.status();
    let text = response.text().map_err(|err| format!("无法读取响应：{err}"))?;
    if !status.is_success() {
        let _ = io::stderr().write_all(text.as_bytes());
        let _ = io::stderr().write_all(b"\n");
        return Err(format!("服务返回 {}", status.as_u16()));
    }
    serde_json::from_str(&text).map_err(|err| format!("响应不是 JSON：{err}"))
}

fn need(value: Option<String>, message: &str) -> Result<String, String> {
    value.filter(|item| !item.is_empty()).ok_or_else(|| message.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex, OnceLock};

    fn auth_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }
    use std::os::unix::fs::PermissionsExt;

    fn serve(routes: Arc<Mutex<Vec<(String, String, String)>>>) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        thread::spawn(move || {
            for incoming in listener.incoming().take(8) {
                let mut stream = incoming.unwrap();
                let mut buf = Vec::new();
                let mut chunk = [0u8; 1024];
                loop {
                    let n = stream.read(&mut chunk).unwrap_or(0);
                    if n == 0 {
                        break;
                    }
                    buf.extend_from_slice(&chunk[..n]);
                    if buf.windows(4).any(|window| window == b"\r\n\r\n") && buf.len() > 16 {
                        break;
                    }
                }
                let text = String::from_utf8_lossy(&buf).to_string();
                let mut lines = text.lines();
                let request = lines.next().unwrap_or("").to_string();
                let mut auth = String::new();
                for line in text.lines() {
                    if let Some((name, value)) = line.split_once(':') {
                        if name.eq_ignore_ascii_case("authorization") {
                            auth = value.trim().to_string();
                        }
                    }
                }
                let body = text.split("\r\n\r\n").nth(1).unwrap_or("").to_string();
                routes.lock().unwrap().push((request.clone(), auth.clone(), body));
                let body = if request.contains("POST /api/device/start") {
                    r#"{"code":"abc123","approve_url":"http://127.0.0.1/approve/abc123"}"#
                } else if request.contains("GET /api/device/abc123") {
                    r#"{"status":"approved","token":"device-token"}"#
                } else if auth == "Bearer device-token" {
                    r#"{"ok":true}"#
                } else {
                    let response = "HTTP/1.1 401 Unauthorized\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}";
                    let _ = stream.write_all(response.as_bytes());
                    continue;
                };
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    body.len(),
                    body
                );
                let _ = stream.write_all(response.as_bytes());
            }
        });
        format!("http://127.0.0.1:{port}")
    }

    #[test]
    fn help_lists_operator_commands_and_has_no_setup() {
        let mut help = Vec::new();
        run(vec!["--help".into()], &mut help).unwrap();
        let text = String::from_utf8(help).unwrap();
        for command in [
            "login", "ontology", "entity", "link", "derive", "shot", "story", "generate", "tts", "pull",
            "inspect", "reverse", "learn", "style extract", "reference upload", "preview", "ffmpeg",
            "edit join", "edit export", "edit mix", "edit subtitle", "job show", "job wait", "skill", "canvas", "batch show", "work",
            "media upload", "image", "music", "check", "reference frame",
        ] {
            assert!(text.contains(command), "{command} missing from help");
        }
        assert!(!text.contains("setup"));
        let err = run(vec!["setup".into()], &mut Vec::new()).unwrap_err();
        assert!(err.contains("没有 setup"));
    }

    #[test]
    fn login_writes_owner_only_credentials_and_protected_call_sends_bearer() {
        let _guard = auth_lock().lock().unwrap();
        let routes = Arc::new(Mutex::new(Vec::new()));
        let base = serve(routes.clone());
        let dir = std::env::temp_dir().join(format!("cvgen-auth-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let auth = dir.join("auth.json");
        env::set_var("CVGEN_AUTH", &auth);
        let missing = run(vec!["ontology".into()], &mut Vec::new());
        assert!(missing.is_err());
        assert!(!auth.exists());
        run(vec!["login".into(), "--base".into(), base.clone()], &mut Vec::new()).unwrap();
        let mode = fs::metadata(&auth).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        let saved = fs::read_to_string(&auth).unwrap();
        assert!(saved.contains("device-token"));
        let mut ontology_out = Vec::new();
        let ontology = run(vec!["ontology".into()], &mut ontology_out);
        let seen = routes.lock().unwrap().clone();
        assert!(ontology.is_ok(), "{ontology:?} seen={seen:?}");
        let printed = String::from_utf8(ontology_out).unwrap();
        assert!(printed.contains("\"ok\": true"), "{printed}");
        assert!(seen.iter().any(|(req, header, _)| req.contains("GET /api/ontology") && header == "Bearer device-token"));
        env::remove_var("CVGEN_AUTH");
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn learn_posts_fixed_role_and_unauthenticated_call_fails() {
        let _guard = auth_lock().lock().unwrap();
        let routes = Arc::new(Mutex::new(Vec::new()));
        let base = serve(routes.clone());
        let dir = std::env::temp_dir().join(format!("cvgen-learn-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let auth = dir.join("auth.json");
        env::set_var("CVGEN_AUTH", &auth);
        fs::write(&auth, format!(r#"{{"base":"{base}","token":"device-token"}}"#)).unwrap();
        let mut out = Vec::new();
        run(vec!["learn".into(), "https://example.test/clip.mp4".into(), "ignored".into()], &mut out).unwrap();
        let printed = String::from_utf8(out).unwrap();
        assert!(printed.contains("\"ok\": true"), "{printed}");
        let seen = routes.lock().unwrap().clone();
        let learn = seen.iter().find(|(req, _, _)| req.contains("POST /api/learn")).expect("learn request");
        assert_eq!(learn.1, "Bearer device-token");
        assert!(learn.2.contains(r#""url":"https://example.test/clip.mp4""#), "{}", learn.2);
        assert!(learn.2.contains(r#""role":"风格""#), "{}", learn.2);
        assert!(!learn.2.contains("ignored"));
        fs::write(&auth, format!(r#"{{"base":"{base}","token":"wrong-token"}}"#)).unwrap();
        let failed = run(vec!["learn".into(), "https://example.test/clip.mp4".into()], &mut Vec::new());
        assert!(failed.unwrap_err().contains("401"));
        env::remove_var("CVGEN_AUTH");
        let _ = fs::remove_dir_all(dir);
    }
}
