//! Turn argv into an HTTP call, driven only by a catalog command.
//!
//! Three steps, each testable on its own:
//! `parse` splits tokens into positionals and flags (flags anywhere, `--` ends flags, `-h/--help` anywhere);
//! `bind` resolves every argument from positionals, flags or the local context and converts its type;
//! `assemble` places the values into the path, the query, the body or `body.input`.

use std::fs;
use std::io;
use std::path::Path;

use serde_json::{Map, Number, Value};

use crate::catalog::{ArgSpec, Command};
use crate::config::Context;
use crate::error::{Failure, Result};

#[derive(Debug, Default, PartialEq)]
pub struct Parsed {
    pub help: bool,
    pub positionals: Vec<String>,
    /// (index into `command.args`, raw value). Bool flags carry "true" or "false".
    pub flags: Vec<(usize, String)>,
}

fn is_option(token: &str) -> bool {
    token.starts_with('-') && token != "-" && token.parse::<f64>().is_err()
}

pub fn parse(command: &Command, tokens: &[String]) -> Result<Parsed> {
    let before_dashes = tokens.iter().take_while(|token| *token != "--");
    if before_dashes.into_iter().any(|token| token == "-h" || token == "--help") {
        return Ok(Parsed { help: true, ..Default::default() });
    }
    let mut parsed = Parsed::default();
    let mut index = 0;
    let mut only_positionals = false;
    while index < tokens.len() {
        let token = &tokens[index];
        index += 1;
        if only_positionals || !is_option(token) {
            parsed.positionals.push(token.clone());
            continue;
        }
        if token == "--" {
            only_positionals = true;
            continue;
        }
        let (name, inline) = match token.split_once('=') {
            Some((name, value)) if name.starts_with("--") => (name, Some(value.to_string())),
            _ => (token.as_str(), None),
        };
        let Some(position) = command.args.iter().position(|arg| arg.matches_flag(name)) else {
            return Err(Failure::usage(format!(
                "{} 没有选项 {name}。要把以 - 开头的内容当参数，放在 -- 后面。用法：{}",
                command.name, command.usage
            )));
        };
        let spec = &command.args[position];
        let value = if spec.kind == "bool" {
            match inline.as_deref() {
                None => "true".to_string(),
                Some(text) => parse_bool(text).map(|b| b.to_string()).ok_or_else(|| {
                    Failure::usage(format!("{name} 只能是 true 或 false，收到 {text}"))
                })?,
            }
        } else if let Some(value) = inline {
            value
        } else {
            let value = tokens
                .get(index)
                .ok_or_else(|| Failure::usage(format!("{name} 后面要跟一个值。用法：{}", command.usage)))?;
            index += 1;
            value.clone()
        };
        parsed.flags.push((position, value));
    }
    Ok(parsed)
}

fn parse_bool(text: &str) -> Option<bool> {
    match text.to_ascii_lowercase().as_str() {
        "true" | "1" | "yes" | "on" => Some(true),
        "false" | "0" | "no" | "off" => Some(false),
        _ => None,
    }
}

enum Raw {
    One(String),
    Many(Vec<String>),
}

pub fn context_hint(key: &str) -> String {
    match key {
        "work" => "先运行 cvgen work use <作品id>".into(),
        "workspace" => "先运行 cvgen workspace use <工作区id>".into(),
        other => format!("缺少本机上下文 {other}"),
    }
}

/// Resolve every argument. Returns (index into `command.args`, value) for each argument that has a value.
pub fn bind(
    command: &Command,
    parsed: &Parsed,
    context: &Context,
    stdin: &mut dyn FnMut() -> io::Result<String>,
) -> Result<Vec<(usize, Value)>> {
    let positional_count = command.args.iter().filter(|arg| arg.source == "positional").count();
    let variadic = command.args.iter().any(|arg| arg.source == "positional" && arg.variadic);
    if !variadic && parsed.positionals.len() > positional_count {
        let extra = parsed.positionals[positional_count..].join(" ");
        return Err(Failure::usage(format!("多余的参数：{extra}。用法：{}", command.usage)));
    }
    let mut stdin_used = false;
    let mut values = Vec::new();
    for (index, spec) in command.args.iter().enumerate() {
        let raw = match spec.source.as_str() {
            "positional" if spec.variadic => {
                let items = parsed.positionals.get(spec.position..).unwrap_or(&[]).to_vec();
                (!items.is_empty()).then_some(Raw::Many(items))
            }
            "positional" => parsed.positionals.get(spec.position).cloned().map(Raw::One),
            "flag" => {
                let given: Vec<String> =
                    parsed.flags.iter().filter(|(at, _)| *at == index).map(|(_, value)| value.clone()).collect();
                if given.is_empty() {
                    None
                } else if spec.kind == "list" {
                    Some(Raw::Many(given.iter().flat_map(|value| split_list(value)).collect()))
                } else {
                    given.last().cloned().map(Raw::One)
                }
            }
            "context" => {
                let key = spec.context.as_deref().unwrap_or(&spec.name);
                match context.get(key) {
                    Some(value) => Some(Raw::One(value.to_string())),
                    None => return Err(Failure::usage(context_hint(key))),
                }
            }
            other => {
                return Err(Failure::usage(format!("命令目录里的参数来源 {other} 本客户端不认识，请下载新版客户端")))
            }
        };
        let value = match raw {
            Some(raw) => convert(spec, raw, stdin, &mut stdin_used)?,
            None => match &spec.default {
                Some(default) => default.clone(),
                None if spec.required => return Err(missing(command, spec)),
                None => continue,
            },
        };
        values.push((index, value));
    }
    Ok(values)
}

fn missing(command: &Command, spec: &ArgSpec) -> Failure {
    let what = if spec.source == "flag" {
        format!("选项 {}", spec.flag.as_deref().unwrap_or(&spec.name))
    } else {
        format!("参数 <{}>", spec.name)
    };
    Failure::usage(format!("缺少{what}。用法：{}", command.usage))
}

fn split_list(text: &str) -> Vec<String> {
    text.split(',').map(str::trim).filter(|item| !item.is_empty()).map(str::to_string).collect()
}

fn convert(spec: &ArgSpec, raw: Raw, stdin: &mut dyn FnMut() -> io::Result<String>, stdin_used: &mut bool) -> Result<Value> {
    let label = spec.display();
    let text = match raw {
        Raw::Many(items) if spec.kind == "list" => return Ok(Value::Array(items.into_iter().map(Value::String).collect())),
        Raw::Many(items) => items.join(" "),
        Raw::One(text) => text,
    };
    let bad = |what: &str| Failure::usage(format!("{label} 要是{what}，收到 {text}"));
    Ok(match spec.kind.as_str() {
        "string" | "" => Value::String(text.clone()),
        "int" => Value::Number(text.trim().parse::<i64>().map_err(|_| bad("整数"))?.into()),
        "float" => {
            let number = text.trim().parse::<f64>().map_err(|_| bad("数字"))?;
            Value::Number(Number::from_f64(number).ok_or_else(|| bad("有限的数字"))?)
        }
        "bool" => Value::Bool(parse_bool(&text).ok_or_else(|| bad("true 或 false"))?),
        "list" => Value::Array(split_list(&text).into_iter().map(Value::String).collect()),
        "json" => {
            if text == "-" {
                if *stdin_used {
                    return Err(Failure::usage("只能有一个参数从标准输入读取"));
                }
                *stdin_used = true;
            }
            parse_json_arg(&label, &text, stdin)?
        }
        other => return Err(Failure::usage(format!("命令目录里的参数类型 {other} 本客户端不认识，请下载新版客户端"))),
    })
}

/// JSON from inline text, `@file`, or `-` (stdin). A bare path to an existing file also works.
pub fn parse_json_arg(label: &str, raw: &str, stdin: &mut dyn FnMut() -> io::Result<String>) -> Result<Value> {
    let read_file = |path: &str| {
        fs::read_to_string(path)
            .map(|text| text.trim_start_matches('\u{feff}').to_string())
            .map_err(|err| Failure::usage(format!("{label}：无法读取文件 {path}：{err}")))
    };
    let (text, origin) = if raw == "-" {
        let text = stdin().map_err(|err| Failure::usage(format!("{label}：无法读取标准输入：{err}")))?;
        (text, "标准输入".to_string())
    } else if let Some(path) = raw.strip_prefix('@') {
        (read_file(path)?, format!("文件 {path}"))
    } else {
        match serde_json::from_str(raw) {
            Ok(value) => return Ok(value),
            Err(_) if Path::new(raw).is_file() => (read_file(raw)?, format!("文件 {raw}")),
            Err(err) => {
                return Err(Failure::usage(format!(
                    "{label} 不是合法的 JSON（{err}）。可以直接写 JSON、写 @文件路径，或写 - 从标准输入读"
                )))
            }
        }
    };
    serde_json::from_str(&text).map_err(|err| Failure::usage(format!("{label}：{origin} 不是合法的 JSON（{err}）")))
}

#[derive(Debug, PartialEq)]
pub struct HttpCall {
    pub method: String,
    /// Path plus query string, relative to the server base.
    pub path: String,
    pub body: Option<Value>,
}

/// Percent-encode everything except RFC 3986 unreserved characters.
pub fn encode(text: &str) -> String {
    let mut out = String::new();
    for byte in text.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            out.push(byte as char);
        } else {
            out.push_str(&format!("%{byte:02X}"));
        }
    }
    out
}

fn as_text(value: &Value) -> String {
    match value {
        Value::String(text) => text.clone(),
        Value::Array(items) => items.iter().map(as_text).collect::<Vec<_>>().join(","),
        other => other.to_string(),
    }
}

pub fn assemble(command: &Command, values: &[(usize, Value)]) -> Result<HttpCall> {
    let mut path = command.path.clone();
    let mut query: Vec<(String, String)> = Vec::new();
    let mut body = command.body.clone();
    let mut input = match body.remove("input") {
        Some(Value::Object(map)) => map,
        _ => Map::new(),
    };
    for (index, value) in values {
        let spec = &command.args[*index];
        match spec.into.as_str() {
            "path" => {
                let placeholder = format!("{{{}}}", spec.name);
                if !path.contains(&placeholder) {
                    return Err(Failure::usage(format!("命令目录有误：路径 {} 里没有 {placeholder}", command.path)));
                }
                path = path.replace(&placeholder, &encode(&as_text(value)));
            }
            "query" => query.push((spec.name.clone(), as_text(value))),
            "body" | "" => {
                body.insert(spec.name.clone(), value.clone());
            }
            "input" => {
                input.insert(spec.name.clone(), value.clone());
            }
            other => return Err(Failure::usage(format!("命令目录里的参数去处 {other} 本客户端不认识，请下载新版客户端"))),
        }
    }
    if let (Some(start), true) = (path.find('{'), path.contains('}')) {
        let end = path[start..].find('}').map(|end| start + end + 1).unwrap_or(path.len());
        return Err(Failure::usage(format!("缺少路径参数 {}。用法：{}", &path[start..end], command.usage)));
    }
    if !input.is_empty() {
        body.insert("input".into(), Value::Object(input));
    }
    if !query.is_empty() {
        let joined: Vec<String> = query.iter().map(|(k, v)| format!("{}={}", encode(k), encode(v))).collect();
        path.push(if path.contains('?') { '&' } else { '?' });
        path.push_str(&joined.join("&"));
    }
    let method = if command.method.is_empty() { "GET".to_string() } else { command.method.to_ascii_uppercase() };
    let body = match method.as_str() {
        "GET" | "HEAD" => None,
        "DELETE" if body.is_empty() => None,
        _ => Some(Value::Object(body)),
    };
    Ok(HttpCall { method, path, body })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::catalog::Catalog;
    use serde_json::json;

    /// A slice of the real server catalog (server/catalog.py), in its JSON form.
    fn catalog() -> Catalog {
        let pos = |name: &str, position: usize, into: &str, kind: &str, required: bool, variadic: bool| {
            json!({"name": name, "source": "positional", "position": position, "in": into, "type": kind,
                   "required": required, "variadic": variadic, "help": ""})
        };
        let flag = |name: &str, flag: &str, into: &str, kind: &str| {
            json!({"name": name, "source": "flag", "flag": flag, "in": into, "type": kind, "required": false, "help": ""})
        };
        let ctx = |name: &str, context: &str, into: &str| {
            json!({"name": name, "source": "context", "context": context, "in": into, "type": "string", "required": true})
        };
        let task = |name: &str, kind: &str, args: Vec<Value>| {
            let mut all = vec![ctx("work", "work", "path")];
            all.extend(args);
            json!({"name": name, "usage": format!("cvgen {name} …"), "summary": "", "method": "POST",
                   "path": "/api/works/{work}/tasks", "args": all, "body": {"kind": kind}, "local": false})
        };
        let mut image_role = flag("role", "--role", "input", "string");
        image_role["default"] = json!("细节");
        let mut level = flag("level", "--level", "body", "string");
        level["default"] = json!("compile");
        let mut from_run = flag("run_id", "--from-run", "body", "string");
        from_run["required"] = json!(true);
        serde_json::from_value(json!({"schema_version": 2, "min_client": "0.2.0", "commands": [
            {"name": "work new", "usage": "cvgen work new <名称>", "method": "POST", "path": "/api/works",
             "args": [ctx("workspace_id", "workspace", "body"), pos("title", 0, "body", "string", true, false),
                      flag("kind", "--kind", "body", "string"), flag("brief", "--brief", "body", "string")]},
            {"name": "entity add", "usage": "cvgen entity add <类型> <JSON>", "method": "POST",
             "path": "/api/works/{work}/entities",
             "args": [ctx("work", "work", "path"), pos("type", 0, "body", "string", true, false),
                      pos("data", 1, "body", "json", true, false), flag("artifact_id", "--artifact", "body", "string")]},
            {"name": "entity set", "usage": "cvgen entity set <id> <JSON>", "method": "PATCH", "path": "/api/entities/{id}",
             "args": [pos("id", 0, "path", "string", true, false), pos("data", 1, "body", "json", true, false),
                      flag("replace", "--replace", "body", "bool")]},
            {"name": "entity rm", "usage": "cvgen entity rm <id>", "method": "DELETE", "path": "/api/entities/{id}",
             "args": [pos("id", 0, "path", "string", true, false)]},
            {"name": "link", "usage": "cvgen link <关系> <起点> <终点> [说明]", "method": "POST",
             "path": "/api/works/{work}/links",
             "args": [ctx("work", "work", "path"), pos("name", 0, "body", "string", true, false),
                      pos("source", 1, "body", "string", true, false), pos("target", 2, "body", "string", true, false),
                      pos("note", 3, "body", "string", false, false)]},
            {"name": "shot compose", "usage": "cvgen shot compose <镜头>", "method": "GET",
             "path": "/api/entities/{shot}/compose",
             "args": [pos("shot", 0, "path", "string", true, false), flag("resolution", "--resolution", "query", "string")]},
            task("generate", "video", vec![pos("shot_id", 0, "input", "string", true, false),
                 flag("resolution", "--resolution", "input", "string"), flag("allow_warnings", "--force", "input", "bool"),
                 flag("again", "--again", "body", "bool"), flag("provider", "--provider", "body", "string")]),
            task("image", "image", vec![pos("shot_id", 0, "input", "string", true, false), image_role,
                 flag("n", "--n", "input", "int"), flag("references", "--ref", "input", "list")]),
            task("edit", "edit", vec![pos("clips", 0, "input", "list", true, true), flag("fade", "--fade", "input", "float"),
                 flag("lines", "--subtitle", "input", "json")]),
            task("ffmpeg", "ffmpeg", vec![pos("args", 0, "input", "list", true, true),
                 flag("inputs", "--input", "input", "list"), flag("outputs", "--output", "input", "list")]),
            {"name": "workflow dry-run", "usage": "cvgen workflow dry-run <id> <版本> <输入.json>", "method": "POST",
             "path": "/api/workflows/{id}/versions/{version}/dry-run",
             "args": [pos("id", 0, "path", "string", true, false), pos("version", 1, "path", "string", true, false),
                      pos("inputs", 2, "body", "json", true, false), level]},
            {"name": "workflow fixtures", "usage": "cvgen workflow fixtures <id> <版本> --from-run <运行id>", "method": "POST",
             "path": "/api/workflows/{id}/versions/{version}/fixtures-from-run",
             "args": [pos("id", 0, "path", "string", true, false), pos("version", 1, "path", "string", true, false), from_run]},
            {"name": "workflow validate", "usage": "cvgen workflow validate <id> <版本> [--env]", "method": "POST",
             "path": "/api/workflows/{id}/versions/{version}/validate",
             "args": [pos("id", 0, "path", "string", true, false), pos("version", 1, "path", "string", true, false),
                      flag("check_env", "--env", "query", "bool")]},
            {"name": "workflow diff", "usage": "cvgen workflow diff <id> <旧> <新>", "method": "GET", "path": "/api/workflows/{id}/diff",
             "args": [pos("id", 0, "path", "string", true, false), pos("base", 1, "query", "string", true, false),
                      pos("head", 2, "query", "string", true, false)]},
            {"name": "asset show", "usage": "cvgen asset show <名称>", "method": "GET", "path": "/api/assets/{workspace}/{name}",
             "args": [ctx("workspace", "workspace", "path"), pos("name", 0, "path", "string", true, false)]},
            {"name": "job list", "usage": "cvgen job list", "method": "GET", "path": "/api/tasks",
             "args": [ctx("work_id", "work", "query"), flag("status", "--status", "query", "string")]},
            {"name": "job cancel", "usage": "cvgen job cancel <id>", "method": "POST", "path": "/api/tasks/{id}/cancel",
             "args": [pos("id", 0, "path", "string", true, false)]}
        ]}))
        .unwrap()
    }

    fn command(name: &str) -> Command {
        catalog().commands.into_iter().find(|c| c.name == name).unwrap()
    }

    fn argv(items: &[&str]) -> Vec<String> {
        items.iter().map(|item| item.to_string()).collect()
    }

    fn ctx() -> Context {
        Context { workspace: Some("ws_1".into()), work: Some("work_1".into()) }
    }

    fn no_stdin() -> io::Result<String> {
        panic!("stdin must not be read")
    }

    fn call_with(name: &str, tokens: &[&str], context: &Context) -> Result<HttpCall> {
        let command = command(name);
        let parsed = parse(&command, &argv(tokens))?;
        assert!(!parsed.help);
        let values = bind(&command, &parsed, context, &mut no_stdin)?;
        assemble(&command, &values)
    }

    fn http(name: &str, tokens: &[&str]) -> Result<HttpCall> {
        call_with(name, tokens, &ctx())
    }

    #[test]
    fn flags_may_appear_anywhere() {
        let expected = HttpCall {
            method: "POST".into(),
            path: "/api/works/work_1/tasks".into(),
            body: Some(json!({"kind": "video", "again": true, "provider": "video.mock",
                              "input": {"shot_id": "ent_1", "resolution": "768p横", "allow_warnings": true}})),
        };
        for tokens in [
            &["ent_1", "--force", "--resolution", "768p横", "--again", "--provider", "video.mock"][..],
            &["--force", "--resolution", "768p横", "ent_1", "--provider=video.mock", "--again"][..],
            &["--again", "--provider", "video.mock", "--force", "--resolution=768p横", "ent_1"][..],
        ] {
            assert_eq!(http("generate", tokens).unwrap(), expected, "{tokens:?}");
        }
    }

    #[test]
    fn help_anywhere_does_not_execute() {
        for tokens in [&["--help"][..], &["ent_1", "-h"][..], &["--resolution", "x", "--help", "extra", "args"][..],
                       &["--bogus", "--help"][..]] {
            let parsed = parse(&command("generate"), &argv(tokens)).unwrap();
            assert!(parsed.help, "{tokens:?}");
        }
        // After `--`, --help is just an ffmpeg argument.
        let parsed = parse(&command("ffmpeg"), &argv(&["--", "-h"])).unwrap();
        assert!(!parsed.help);
        assert_eq!(parsed.positionals, argv(&["-h"]));
    }

    #[test]
    fn double_dash_passes_everything_through() {
        let call = http("ffmpeg", &["--input", "a=art_1,b=art_2", "--output", "out.mp4", "--", "-i", "a", "-vf",
                                    "scale=1280:720,fps=24", "--help", "out.mp4"]).unwrap();
        assert_eq!(call.body.unwrap()["input"], json!({
            "inputs": ["a=art_1", "b=art_2"], "outputs": ["out.mp4"],
            "args": ["-i", "a", "-vf", "scale=1280:720,fps=24", "--help", "out.mp4"],
        }));
        let err = call_with("ffmpeg", &["-i", "a"], &ctx()).unwrap_err();
        assert_eq!(err.code, 1);
        assert!(err.message.contains("-i") && err.message.contains("--"), "{}", err.message);
    }

    #[test]
    fn types_are_converted() {
        let call = http("image", &["ent_1", "--n", "2", "--ref", "art_1, art_2", "--ref", "art_3"]).unwrap();
        assert_eq!(call.body.unwrap()["input"], json!({"shot_id": "ent_1", "role": "细节", "n": 2,
                                                         "references": ["art_1", "art_2", "art_3"]}));
        let err = http("image", &["ent_1", "--n", "two"]).unwrap_err();
        assert!(err.message.contains("整数"), "{}", err.message);
        let call = http("edit", &["c1", "--fade", "0.5", "c2", "c3"]).unwrap();
        assert_eq!(call.body.unwrap()["input"], json!({"clips": ["c1", "c2", "c3"], "fade": 0.5}));
        let call = http("entity set", &["ent_1", r#"{"title":"新"}"#, "--replace"]).unwrap();
        assert_eq!(call, HttpCall { method: "PATCH".into(), path: "/api/entities/ent_1".into(),
                                    body: Some(json!({"data": {"title": "新"}, "replace": true})) });
        let call = http("entity set", &["ent_1", "{}", "--replace=false"]).unwrap();
        assert_eq!(call.body.unwrap()["replace"], json!(false));
        let call = http("workflow validate", &["wf_1", "2", "--env"]).unwrap();
        assert_eq!(call.path, "/api/workflows/wf_1/versions/2/validate?check_env=true");
        let call = http("edit", &["c1", "--fade", "-1.5"]).unwrap();
        assert_eq!(call.body.unwrap()["input"]["fade"], json!(-1.5));
    }

    #[test]
    fn json_from_inline_file_and_stdin() {
        let dir = std::env::temp_dir().join(format!("cvgen-json-{}", std::process::id()));
        fs::create_dir_all(&dir).unwrap();
        let file = dir.join("shot.json");
        fs::write(&file, "\u{feff}{\"title\": \"开场\", \"duration\": 5}").unwrap();
        let at = format!("@{}", file.display());
        let call = http("entity add", &["Shot", &at, "--artifact", "art_9"]).unwrap();
        assert_eq!(call.body.unwrap(), json!({"type": "Shot", "data": {"title": "开场", "duration": 5}, "artifact_id": "art_9"}));
        // A bare existing path works too.
        let bare = file.display().to_string();
        let call = http("entity add", &["Shot", &bare]).unwrap();
        assert_eq!(call.body.unwrap()["data"]["duration"], json!(5));

        let command = command("entity add");
        let parsed = parse(&command, &argv(&["Shot", "-"])).unwrap();
        let mut stdin = || Ok::<_, io::Error>(r#"{"from": "stdin"}"#.to_string());
        let values = bind(&command, &parsed, &ctx(), &mut stdin).unwrap();
        assert_eq!(assemble(&command, &values).unwrap().body.unwrap()["data"], json!({"from": "stdin"}));

        let err = http("entity add", &["Shot", "{not json"]).unwrap_err();
        assert!(err.message.contains("JSON") && err.message.contains("@"), "{}", err.message);
        let missing = format!("@{}", dir.join("nope.json").display());
        let err = http("entity add", &["Shot", &missing]).unwrap_err();
        assert!(err.message.contains("无法读取文件"), "{}", err.message);
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn defaults_and_required() {
        let call = http("workflow dry-run", &["wf_1", "1", r#"{"passage":"x"}"#]).unwrap();
        assert_eq!(call.body.unwrap(), json!({"inputs": {"passage": "x"}, "level": "compile"}));
        let call = http("workflow dry-run", &["wf_1", "1", "{}", "--level", "llm"]).unwrap();
        assert_eq!(call.body.unwrap()["level"], json!("llm"));
        let err = http("workflow dry-run", &["wf_1", "1"]).unwrap_err();
        assert_eq!(err.code, 1);
        assert!(err.message.contains("<inputs>"), "{}", err.message);
        let err = http("workflow fixtures", &["wf_1", "1"]).unwrap_err();
        assert!(err.message.contains("--from-run"), "{}", err.message);
        let err = http("job cancel", &["t1", "t2"]).unwrap_err();
        assert!(err.message.contains("多余"), "{}", err.message);
        let err = http("generate", &["ent_1", "--resolution"]).unwrap_err();
        assert!(err.message.contains("--resolution"), "{}", err.message);
        // Optional positional is simply left out.
        let call = http("link", &["styled_as", "ent_1", "asset:style-snow-film@1"]).unwrap();
        assert_eq!(call.body.unwrap(), json!({"name": "styled_as", "source": "ent_1", "target": "asset:style-snow-film@1"}));
    }

    #[test]
    fn path_query_body_and_input_are_assembled() {
        let call = http("shot compose", &["ent 1/x", "--resolution", "768p横"]).unwrap();
        assert_eq!(call, HttpCall { method: "GET".into(),
                                    path: "/api/entities/ent%201%2Fx/compose?resolution=768p%E6%A8%AA".into(), body: None });
        let call = http("workflow diff", &["wf_1", "1", "2"]).unwrap();
        assert_eq!(call.path, "/api/workflows/wf_1/diff?base=1&head=2");
        let call = http("job list", &["--status", "ready,running"]).unwrap();
        assert_eq!(call.path, "/api/tasks?work_id=work_1&status=ready%2Crunning");
        let call = http("asset show", &["style-snow-film"]).unwrap();
        assert_eq!(call.path, "/api/assets/ws_1/style-snow-film");
        let call = http("work new", &["新片", "--kind", "短片"]).unwrap();
        assert_eq!(call.body.unwrap(), json!({"workspace_id": "ws_1", "title": "新片", "kind": "短片"}));
        let call = http("entity rm", &["ent_1"]).unwrap();
        assert_eq!(call, HttpCall { method: "DELETE".into(), path: "/api/entities/ent_1".into(), body: None });
        let call = http("job cancel", &["t1"]).unwrap();
        assert_eq!(call.body, Some(json!({})));
    }

    #[test]
    fn missing_context_explains_what_to_run() {
        let empty = Context::default();
        let err = call_with("generate", &["ent_1"], &empty).unwrap_err();
        assert_eq!(err, Failure::usage("先运行 cvgen work use <作品id>"));
        let err = call_with("work new", &["片子"], &empty).unwrap_err();
        assert_eq!(err, Failure::usage("先运行 cvgen workspace use <工作区id>"));
        // --help never needs the context.
        assert!(parse(&command("generate"), &argv(&["--help"])).unwrap().help);
    }

    #[test]
    fn unknown_flag_is_a_usage_error() {
        let err = http("generate", &["ent_1", "--nope"]).unwrap_err();
        assert_eq!(err.code, 1);
        assert!(err.message.contains("--nope"));
    }
}
