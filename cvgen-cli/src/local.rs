//! Commands the catalog marks `local`: the client implements them itself (login, context, waits, files).

use std::collections::HashMap;
use std::fs::{self, File};
use std::io::{self, Read};
use std::path::{Path, PathBuf};
use std::thread::sleep;
use std::time::{Duration, Instant};

use reqwest::blocking::multipart;
use serde_json::{json, Value};

use crate::args::{self, encode};
use crate::catalog::{self, ArgSpec, Command, CLIENT_VERSION};
use crate::config::{self, Auth, Context, Paths};
use crate::error::{self, Failure, Result};
use crate::http::{print_json, Api};

fn local(name: &str, usage: &str, summary: &str, args: Vec<ArgSpec>) -> Command {
    Command { name: name.into(), usage: usage.into(), summary: summary.into(), args, local: true, ..Default::default() }
}

/// The local commands, with the argument specs this client parses for them.
pub fn commands() -> Vec<Command> {
    let id = |help: &str| ArgSpec::positional("id", 0, "string", true, help);
    let timeout = || ArgSpec::flag("timeout", "--timeout", "int", false, "最多等多少秒；不写就一直等");
    let mut output = ArgSpec::flag("output", "-o", "string", true, "保存到这个路径（已有目录则存到目录里）");
    output.aliases = vec!["--output".into()];
    vec![
        local("login", "cvgen login --base 服务地址 [--name 这台机器的名字]", "设备授权登录，等网页批准", vec![
            ArgSpec::flag("base", "--base", "string", true, "服务地址，例如 https://cvgen.example.com"),
            ArgSpec::flag("name", "--name", "string", false, "在网页设备列表里显示的名字，默认是主机名"),
        ]),
        local("logout", "cvgen logout", "删除本机凭证", vec![]),
        local("status", "cvgen status", "当前登录、工作区、作品", vec![]),
        local("version", "cvgen version", "客户端版本", vec![]),
        local("workspace use", "cvgen workspace use <工作区id>", "记住当前工作区（只存在本机）", vec![id("工作区 id（或名称）")]),
        local("work use", "cvgen work use <作品id>", "记住当前作品（只存在本机）", vec![id("作品 id")]),
        local("upload", "cvgen upload <文件> [--label 名称]", "上传本机文件，返回文件 id", vec![
            ArgSpec::context("workspace_id", "workspace"),
            ArgSpec::positional("file", 0, "string", true, "本机文件路径"),
            ArgSpec::flag("label", "--label", "string", false, "文件名称，默认用文件名"),
        ]),
        local("media get", "cvgen media get <文件id> -o <保存路径>", "下载成片、接触表、参考图", vec![id("文件 id（artifact）"), output]),
        local("job wait", "cvgen job wait <任务id> [--timeout 秒]", "一直等到任务结束，持续打印进度", vec![id("任务 id"), timeout()]),
        local("run wait", "cvgen run wait <运行id> [--timeout 秒]", "等到运行结束或停在闸门", vec![id("运行 id"), timeout()]),
        local(
            "comic missing",
            "cvgen comic missing --episode <集id> [--base 平台地址]",
            "查看缺什么：只问平台闸门，不在本地拼 H3 请求",
            vec![
                ArgSpec::flag("episode", "--episode", "string", true, "集 id"),
                ArgSpec::flag("base", "--base", "string", false, "平台地址；不写则用已登录地址"),
            ],
        ),
    ]
}

/// Parsed values of a local command, by argument name.
struct Values(HashMap<String, Value>);

impl Values {
    fn text(&self, name: &str) -> Option<String> {
        self.0.get(name).and_then(Value::as_str).map(str::to_string)
    }

    fn need(&self, name: &str) -> String {
        self.text(name).unwrap_or_default()
    }

    fn int(&self, name: &str) -> Option<i64> {
        self.0.get(name).and_then(Value::as_i64)
    }
}

pub fn run(paths: &Paths, command: &Command, tokens: &[String]) -> Result<()> {
    let parsed = args::parse(command, tokens)?;
    if parsed.help {
        print!("{}", catalog::command_help(command));
        return Ok(());
    }
    let context = config::load_context(paths)?;
    let bound = args::bind(command, &parsed, &context, &mut read_stdin)?;
    let values = Values(bound.into_iter().map(|(index, value)| (command.args[index].name.clone(), value)).collect());
    match command.name.as_str() {
        "login" => login(paths, &values),
        "logout" => logout(paths),
        "version" => {
            println!("cvgen {CLIENT_VERSION}");
            Ok(())
        }
        "status" => status(paths, &context),
        "workspace use" => workspace_use(paths, &signed_in(paths)?, &values.need("id"), context),
        "work use" => work_use(paths, &signed_in(paths)?, &values.need("id")),
        "upload" => upload(&signed_in(paths)?, &values),
        "media get" => media_get(&signed_in(paths)?, &values.need("id"), &values.need("output")),
        "job wait" => job_wait(&signed_in(paths)?, &values.need("id"), values.int("timeout")),
        "run wait" => run_wait(&signed_in(paths)?, &values.need("id"), values.int("timeout")),
        "comic missing" => {
            let api = if let Some(base) = values.text("base") {
                Api::new(&base, None)?
            } else {
                signed_in(paths)?
            };
            comic_missing(&api, &values.need("episode"))
        }
        other => Err(Failure::usage(format!("本客户端没有实现 {other}，请下载新版客户端"))),
    }
}

pub fn read_stdin() -> io::Result<String> {
    let mut text = String::new();
    io::stdin().read_to_string(&mut text)?;
    Ok(text)
}

pub fn not_signed_in() -> Failure {
    Failure::usage("还没有登录。先运行 cvgen login --base 服务地址")
}

pub fn signed_in(paths: &Paths) -> Result<Api> {
    let auth = config::load_auth(paths)?.ok_or_else(not_signed_in)?;
    Api::new(&auth.base, Some(&auth.token))
}

fn comic_missing(api: &Api, episode: &str) -> Result<()> {
    let reply = api.call("GET", &format!("/api/comic/missing?episode_id={}", episode), None)?;
    let body = reply.json()?;
    let stopped = body.get("stopped_at").and_then(Value::as_str).unwrap_or("未知");
    let missing = body.get("missing").cloned().unwrap_or(Value::Array(vec![]));
    println!("停在：{stopped}");
    println!("缺：{missing}");
    if body.get("local_h3").and_then(Value::as_bool).unwrap_or(false) {
        return Err(Failure::usage("客户端不能在本地拼 H3 请求"));
    }
    Ok(())
}

fn host_name() -> String {
    for key in ["COMPUTERNAME", "HOSTNAME"] {
        if let Ok(name) = std::env::var(key) {
            if !name.trim().is_empty() {
                return name.trim().to_string();
            }
        }
    }
    fs::read_to_string("/etc/hostname").map(|name| name.trim().to_string()).unwrap_or_default()
}

fn login(paths: &Paths, values: &Values) -> Result<()> {
    let public = Api::new(&values.need("base"), None)?;
    let base = public.base.clone();
    let name = values.text("name").unwrap_or_else(host_name);
    let started = public.post_json("/api/device/start", &json!({"name": name, "client_version": CLIENT_VERSION}))?;
    let field = |key: &str| started.get(key).and_then(Value::as_str).unwrap_or("").to_string();
    let (device_id, secret, code) = (field("device_id"), field("poll_secret"), field("user_code"));
    if device_id.is_empty() || secret.is_empty() || code.is_empty() {
        return Err(Failure::server("服务没有返回设备码，服务端版本可能不对"));
    }
    let approve_path = started.get("approve_path").and_then(Value::as_str).map(str::to_string)
        .unwrap_or_else(|| format!("/approve/{code}"));
    let interval = started.get("interval").and_then(Value::as_u64).unwrap_or(3).max(1);
    let expires_in = started.get("expires_in").and_then(Value::as_u64).unwrap_or(600);
    println!("设备码：{code}");
    println!("请让有权限的人在浏览器打开下面的地址并批准（{} 分钟内有效）：", expires_in.div_ceil(60));
    println!("  {base}{approve_path}");
    println!("等待批准…");
    let deadline = Instant::now() + Duration::from_secs(expires_in);
    let poll_body = json!({"device_id": device_id, "poll_secret": secret});
    let mut network_errors = 0;
    loop {
        sleep(Duration::from_secs(interval));
        if Instant::now() >= deadline {
            return Err(Failure::new(error::TIMEOUT, "设备码已过期，没有等到批准。请重新运行 cvgen login"));
        }
        let polled = match public.post_json("/api/device/poll", &poll_body) {
            Ok(value) => value,
            Err(failure) if failure.message.contains("HTTP 429") => continue,
            Err(failure) if failure.code == error::NETWORK && network_errors < 5 => {
                network_errors += 1;
                eprintln!("网络错误，稍后重试：{}", failure.message);
                continue;
            }
            Err(failure) => return Err(failure),
        };
        network_errors = 0;
        match polled.get("status").and_then(Value::as_str).unwrap_or("") {
            "pending" => continue,
            "approved" => {
                let token = polled.get("token").and_then(Value::as_str).unwrap_or("");
                if token.is_empty() {
                    return Err(Failure::server("服务批准了但没有返回凭证"));
                }
                let previous = config::load_auth(paths).ok().flatten();
                let auth = Auth { base: base.clone(), token: token.to_string(), device_id: device_id.clone() };
                config::save_auth(paths, &auth)?;
                if previous.map_or(true, |old| old.base != base) {
                    // Workspace and work ids belong to the previous server.
                    config::remove(&paths.context())?;
                }
                config::remove(&paths.catalog())?;
                println!("已批准，凭证保存在 {}", paths.auth().display());
                let api = Api::new(&base, Some(token))?;
                match catalog::Store::new(paths, &api).refresh() {
                    Ok(catalog) => println!("已取得命令目录（{} 条命令）。", catalog.commands.len()),
                    Err(failure) => eprintln!("警告：暂时拿不到命令目录：{}", failure.message),
                }
                println!("下一步：cvgen workspace list，然后 cvgen workspace use <工作区id>");
                return Ok(());
            }
            "expired" => return Err(Failure::new(error::TIMEOUT, "设备码已过期，请重新运行 cvgen login")),
            "claimed" => return Err(Failure::server("这个设备码的凭证已经被领取过，请重新运行 cvgen login")),
            "denied" => return Err(Failure::server("设备申请被拒绝了")),
            other => return Err(Failure::server(format!("设备申请处于 {other} 状态，请重新运行 cvgen login"))),
        }
    }
}

fn logout(paths: &Paths) -> Result<()> {
    let removed = config::remove(&paths.auth())?;
    config::remove(&paths.catalog())?;
    if removed {
        println!("已删除本机凭证。网页“设置 → 设备”里还可以把这台设备下线。");
    } else {
        println!("本机没有凭证。");
    }
    Ok(())
}

fn status(paths: &Paths, context: &Context) -> Result<()> {
    let auth = config::load_auth(paths)?.ok_or_else(not_signed_in)?;
    let api = Api::new(&auth.base, Some(&auth.token))?;
    let me = api.get_json("/api/auth/me")?;
    print_json(&json!({
        "client_version": CLIENT_VERSION,
        "base": auth.base,
        "device_id": auth.device_id,
        "me": me,
        "workspace": context.workspace,
        "work": context.work,
        "config_dir": paths.dir.display().to_string(),
    }));
    Ok(())
}

fn workspace_use(paths: &Paths, api: &Api, wanted: &str, mut context: Context) -> Result<()> {
    let listed = api.get_json("/api/workspaces")?;
    let items = listed.get("items").and_then(Value::as_array).cloned().unwrap_or_default();
    let found = items
        .iter()
        .find(|item| item.get("id").and_then(Value::as_str) == Some(wanted))
        .or_else(|| items.iter().find(|item| item.get("name").and_then(Value::as_str) == Some(wanted)))
        .cloned()
        .ok_or_else(|| Failure::usage(format!("没有工作区 {wanted}。运行 cvgen workspace list 查看")))?;
    let id = found.get("id").and_then(Value::as_str).unwrap_or(wanted).to_string();
    if context.workspace.as_deref() != Some(id.as_str()) {
        context.work = None;
    }
    context.workspace = Some(id);
    config::save_context(paths, &context)?;
    print_json(&found);
    eprintln!("当前工作区已设为 {}。下一步：cvgen work new <名称> 或 cvgen work use <作品id>",
              found.get("name").and_then(Value::as_str).unwrap_or(""));
    Ok(())
}

fn work_use(paths: &Paths, api: &Api, id: &str) -> Result<()> {
    let snapshot = api.get_json(&format!("/api/works/{}", encode(id)))?;
    let work = snapshot.get("work").cloned().unwrap_or(Value::Null);
    set_current_work(paths, &work)?;
    print_json(&work);
    Ok(())
}

/// Remember a work (and its workspace) as current. Used by `work use` and after `work new`.
pub fn set_current_work(paths: &Paths, work: &Value) -> Result<()> {
    let id = work.get("id").and_then(Value::as_str).ok_or_else(|| Failure::server("服务返回的作品没有 id"))?;
    let mut context = config::load_context(paths)?;
    context.work = Some(id.to_string());
    if let Some(workspace) = work.get("workspace_id").and_then(Value::as_str) {
        context.workspace = Some(workspace.to_string());
    }
    config::save_context(paths, &context)?;
    eprintln!("当前作品已设为 {id}（{}）", work.get("title").and_then(Value::as_str).unwrap_or(""));
    Ok(())
}

pub fn guess_mime(path: &Path) -> &'static str {
    let ext = path.extension().and_then(|ext| ext.to_str()).unwrap_or("").to_ascii_lowercase();
    match ext.as_str() {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "bmp" => "image/bmp",
        "mp4" | "m4v" => "video/mp4",
        "mov" => "video/quicktime",
        "webm" => "video/webm",
        "mkv" => "video/x-matroska",
        "mp3" => "audio/mpeg",
        "wav" => "audio/wav",
        "m4a" => "audio/mp4",
        "aac" => "audio/aac",
        "flac" => "audio/flac",
        "ogg" => "audio/ogg",
        "json" => "application/json",
        "txt" | "srt" => "text/plain",
        "pdf" => "application/pdf",
        _ => "application/octet-stream",
    }
}

fn upload(api: &Api, values: &Values) -> Result<()> {
    let path = PathBuf::from(values.need("file"));
    let file = File::open(&path).map_err(|err| Failure::usage(format!("无法打开 {}：{err}", path.display())))?;
    let meta = file.metadata().map_err(|err| Failure::usage(format!("无法读取 {}：{err}", path.display())))?;
    if !meta.is_file() {
        return Err(Failure::usage(format!("{} 不是文件", path.display())));
    }
    let filename = path.file_name().and_then(|name| name.to_str()).unwrap_or("upload.bin").to_string();
    // Streamed from disk; the file is never read into memory.
    let part = multipart::Part::reader_with_length(file, meta.len())
        .file_name(filename.clone())
        .mime_str(guess_mime(&path))
        .map_err(|err| Failure::usage(err.to_string()))?;
    let form = multipart::Form::new()
        .text("workspace_id", values.need("workspace_id"))
        .text("label", values.text("label").unwrap_or(filename))
        .part("file", part);
    eprintln!("上传 {}（{} 字节）…", path.display(), meta.len());
    api.upload("/api/uploads", form)?.print()
}

fn filename_from(disposition: &str) -> Option<String> {
    const STAR: &str = "filename*=utf-8''";
    if let Some(index) = disposition.to_ascii_lowercase().find(STAR) {
        let raw = disposition[index + STAR.len()..].split(';').next()?.trim();
        return Some(percent_decode(raw));
    }
    let index = disposition.find("filename=")?;
    Some(disposition[index + "filename=".len()..].split(';').next()?.trim().trim_matches('"').to_string())
}

fn percent_decode(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'%' && i + 2 < bytes.len() {
            let hex = std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap_or("");
            if let Ok(byte) = u8::from_str_radix(hex, 16) {
                out.push(byte);
                i += 3;
                continue;
            }
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

fn media_get(api: &Api, id: &str, output: &str) -> Result<()> {
    let mut response = api.download(&format!("/media/{}", encode(id)))?;
    let mut target = PathBuf::from(output);
    if target.is_dir() {
        let disposition = response
            .headers()
            .get(reqwest::header::CONTENT_DISPOSITION)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("");
        let name = filename_from(disposition)
            .and_then(|name| Path::new(&name).file_name().map(|n| n.to_string_lossy().into_owned()))
            .filter(|name| !name.is_empty())
            .unwrap_or_else(|| id.to_string());
        target = target.join(name);
    }
    let mime = response
        .headers()
        .get(reqwest::header::CONTENT_TYPE)
        .and_then(|value| value.to_str().ok())
        .unwrap_or("")
        .to_string();
    let mut partial = target.clone().into_os_string();
    partial.push(".part");
    let partial = PathBuf::from(partial);
    let write_error = |err: io::Error| Failure::usage(format!("无法写入 {}：{err}", target.display()));
    let mut file = File::create(&partial).map_err(write_error)?;
    let copied = io::copy(&mut response, &mut file);
    let bytes = match copied {
        Ok(bytes) => bytes,
        Err(err) => {
            let _ = fs::remove_file(&partial);
            return Err(api.map_read_error(err));
        }
    };
    file.sync_all().ok();
    drop(file);
    fs::rename(&partial, &target).map_err(write_error)?;
    let shown = fs::canonicalize(&target).unwrap_or(target);
    print_json(&json!({"saved": shown.display().to_string(), "bytes": bytes, "mime": mime}));
    Ok(())
}

fn text<'a>(value: &'a Value, key: &str) -> &'a str {
    value.get(key).and_then(Value::as_str).unwrap_or("")
}

pub fn task_line(task: &Value) -> String {
    let mut line = format!("任务 {}：{}", text(task, "id"), text(task, "status"));
    if let Some(progress) = task.get("progress").and_then(Value::as_f64) {
        if progress > 0.0 {
            line.push_str(&format!(" {:.0}%", progress * 100.0));
        }
    }
    if !text(task, "progress_message").is_empty() {
        line.push_str(&format!(" {}", text(task, "progress_message")));
    }
    if let Some(position) = task.get("queue_position").and_then(Value::as_i64) {
        if position > 0 {
            line.push_str(&format!("（排队第 {position} 位）"));
        }
    }
    if !text(task, "attention").is_empty() {
        line.push_str(&format!(" 需要处理：{}", text(task, "attention")));
    }
    line
}

/// What a finished wait means for the exit code. `None` means keep waiting.
pub fn task_outcome(task: &Value) -> Option<Result<()>> {
    let status = text(task, "status");
    let id = text(task, "id");
    let done = task.get("done").and_then(Value::as_bool).unwrap_or(false);
    match status {
        "succeeded" => Some(Ok(())),
        "failed" | "canceled" => {
            let reason = task.get("error").and_then(Value::as_str).unwrap_or("");
            Some(Err(Failure::new(error::FAILED, format!("任务 {id} 以 {status} 结束 {reason}").trim_end().to_string())))
        }
        "needs_attention" | "waiting" => Some(Err(Failure::new(
            error::ATTENTION,
            format!("任务 {id} 停在 {status}，需要人处理 {}", text(task, "attention")).trim_end().to_string(),
        ))),
        _ if done => Some(Err(Failure::new(error::FAILED, format!("任务 {id} 以 {status} 结束")))),
        _ => None,
    }
}

pub fn run_outcome(run: &Value) -> Option<Result<()>> {
    let status = text(run, "status");
    let id = text(run, "id");
    match status {
        "succeeded" => Some(Ok(())),
        "failed" | "canceled" => Some(Err(Failure::new(error::FAILED, format!("运行 {id} 以 {status} 结束")))),
        "waiting" | "paused" => Some(Err(Failure::new(
            error::ATTENTION,
            format!("运行 {id} 停在 {status}，需要人在网页上处理闸门或恢复"),
        ))),
        _ => None,
    }
}

fn timed_out(kind: &str, id: &str, seconds: i64, again: &str) -> Failure {
    Failure::new(error::TIMEOUT, format!("等了 {seconds} 秒{kind} {id} 还没结束。之后可以再运行 {again} {id}"))
}

/// Retry a few network errors in a row during long waits; after that give up with exit code 6.
struct Retries(u32);

impl Retries {
    fn absorb(&mut self, failure: Failure) -> Result<()> {
        if failure.code != error::NETWORK || self.0 >= 5 {
            return Err(failure);
        }
        self.0 += 1;
        eprintln!("网络错误，5 秒后重试（第 {} 次）：{}", self.0, failure.message);
        sleep(Duration::from_secs(5));
        Ok(())
    }
}

fn job_wait(api: &Api, id: &str, timeout: Option<i64>) -> Result<()> {
    let started = Instant::now();
    let deadline = timeout.map(|seconds| started + Duration::from_secs(seconds.max(0) as u64));
    let mut last_line = String::new();
    let mut last: Option<Value> = None;
    let mut retries = Retries(0);
    loop {
        // The first call returns almost at once so the current status shows up immediately.
        let wait = match deadline {
            _ if last.is_none() => 1,
            Some(deadline) => {
                let left = deadline.saturating_duration_since(Instant::now()).as_secs_f64().ceil() as u64;
                if left == 0 {
                    if let Some(task) = &last {
                        print_json(task);
                    }
                    return Err(timed_out("任务", id, timeout.unwrap_or(0), "cvgen job wait"));
                }
                left.min(55)
            }
            None => 55,
        };
        let task = match api.get_json_long(&format!("/api/tasks/{}/wait?timeout={wait}", encode(id))) {
            Ok(task) => task,
            Err(failure) => {
                retries.absorb(failure)?;
                continue;
            }
        };
        retries.0 = 0;
        let line = task_line(&task);
        if line != last_line {
            eprintln!("[{:>4}s] {line}", started.elapsed().as_secs());
            last_line = line;
        }
        if let Some(outcome) = task_outcome(&task) {
            print_json(&task);
            return outcome;
        }
        last = Some(task);
    }
}

fn run_wait(api: &Api, id: &str, timeout: Option<i64>) -> Result<()> {
    let started = Instant::now();
    let deadline = timeout.map(|seconds| started + Duration::from_secs(seconds.max(0) as u64));
    let mut last_line = String::new();
    let mut retries = Retries(0);
    loop {
        let run = match api.get_json(&format!("/api/runs/{}", encode(id))) {
            Ok(run) => run,
            Err(failure) => {
                retries.absorb(failure)?;
                continue;
            }
        };
        retries.0 = 0;
        let progress = run.get("progress").cloned().unwrap_or(Value::Null);
        let count = |key: &str| progress.get(key).and_then(Value::as_i64).unwrap_or(0);
        let line = format!(
            "运行 {id}：{} 完成 {}/{} 进行中 {} 等人 {}",
            text(&run, "status"), count("succeeded"), count("total"), count("active"), count("waiting")
        );
        if line != last_line {
            eprintln!("[{:>4}s] {line}", started.elapsed().as_secs());
            last_line = line;
        }
        if let Some(outcome) = run_outcome(&run) {
            print_json(&run);
            return outcome;
        }
        if let Some(deadline) = deadline {
            if Instant::now() + Duration::from_secs(5) > deadline {
                let left = deadline.saturating_duration_since(Instant::now());
                sleep(left);
                if let Ok(run) = api.get_json(&format!("/api/runs/{}", encode(id))) {
                    if let Some(outcome) = run_outcome(&run) {
                        print_json(&run);
                        return outcome;
                    }
                    print_json(&run);
                }
                return Err(timed_out("运行", id, timeout.unwrap_or(0), "cvgen run wait"));
            }
        }
        sleep(Duration::from_secs(5));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wait_outcomes_map_to_exit_codes() {
        assert_eq!(task_outcome(&json!({"status": "succeeded", "done": true})), Some(Ok(())));
        assert_eq!(task_outcome(&json!({"status": "failed", "done": true})).unwrap().unwrap_err().code, 3);
        assert_eq!(task_outcome(&json!({"status": "canceled", "done": true})).unwrap().unwrap_err().code, 3);
        assert_eq!(task_outcome(&json!({"status": "needs_attention", "done": false})).unwrap().unwrap_err().code, 4);
        assert_eq!(task_outcome(&json!({"status": "waiting", "done": false})).unwrap().unwrap_err().code, 4);
        assert_eq!(task_outcome(&json!({"status": "running", "done": false})), None);
        assert_eq!(run_outcome(&json!({"status": "paused"})).unwrap().unwrap_err().code, 4);
        assert_eq!(run_outcome(&json!({"status": "failed"})).unwrap().unwrap_err().code, 3);
        assert_eq!(run_outcome(&json!({"status": "running"})), None);
    }

    #[test]
    fn progress_line_shows_status_message_and_queue() {
        let line = task_line(&json!({"id": "t1", "status": "ready", "progress": 0.25,
                                     "progress_message": "排队中", "queue_position": 3}));
        assert_eq!(line, "任务 t1：ready 25% 排队中（排队第 3 位）");
    }

    #[test]
    fn local_commands_parse_like_catalog_ones() {
        let commands = commands();
        let media = commands.iter().find(|c| c.name == "media get").unwrap();
        for tokens in [["-o", "out.mp4", "art_1"], ["art_1", "--output", "out.mp4"]] {
            let tokens: Vec<String> = tokens.iter().map(|t| t.to_string()).collect();
            let parsed = args::parse(media, &tokens).unwrap();
            let values = args::bind(media, &parsed, &Context::default(), &mut read_stdin).unwrap();
            assert_eq!(values, vec![(0, json!("art_1")), (1, json!("out.mp4"))]);
        }
        let upload = commands.iter().find(|c| c.name == "upload").unwrap();
        let parsed = args::parse(upload, &["a.png".to_string()]).unwrap();
        let err = args::bind(upload, &parsed, &Context::default(), &mut read_stdin).unwrap_err();
        assert_eq!(err.message, "先运行 cvgen workspace use <工作区id>");
    }

    #[test]
    fn content_disposition_filename() {
        assert_eq!(filename_from("inline; filename*=utf-8''%E9%95%9C%E5%A4%B4.mp4").unwrap(), "镜头.mp4");
        assert_eq!(filename_from("attachment; filename=\"a.png\"").unwrap(), "a.png");
        assert_eq!(guess_mime(Path::new("x.PNG")), "image/png");
    }
}
