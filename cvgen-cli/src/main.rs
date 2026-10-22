//! Shallow cvgen client. Commands come from the server catalog.

use std::env;
use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::thread;
use std::time::Duration;

use serde_json::{json, Map, Value};

fn main() -> std::process::ExitCode {
    let mut stdout = io::stdout();
    match run(env::args().skip(1).collect(), &mut stdout) {
        Ok(()) => std::process::ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error}");
            std::process::ExitCode::from(1)
        }
    }
}

fn run(args: Vec<String>, stdout: &mut dyn Write) -> Result<(), String> {
    let mut args = args.into_iter().peekable();
    let command = args.next().unwrap_or_else(|| "help".to_string());
    if command == "--help" || command == "-h" || command == "help" {
        return print_help(stdout);
    }
    if command == "setup" {
        return Err("没有 setup 命令。直接运行 cvgen login。".into());
    }
    if command == "login" {
        return login(stdout, &args.collect::<Vec<_>>());
    }
    let rest = args.collect::<Vec<_>>();
    let saved = load_auth()?;
    let catalog = fetch_catalog(&saved.base, &saved.token)?;
    let name = command_name(&command, &rest, &catalog)?;
    let spec = catalog
        .iter()
        .find(|item| item.get("name").and_then(Value::as_str) == Some(name.as_str()))
        .cloned()
        .ok_or_else(|| format!("未知命令 {name}。运行 cvgen --help。"))?;
    dispatch(stdout, &saved, &spec, &rest)
}

fn print_help(stdout: &mut dyn Write) -> Result<(), String> {
    writeln!(stdout, "cvgen 操作云端视频系统。执行由服务完成。").map_err(|err| err.to_string())?;
    writeln!(stdout, "用法：cvgen login --base 地址").map_err(|err| err.to_string())?;
    let saved = match load_auth() {
        Ok(auth) => auth,
        Err(_) => {
            writeln!(stdout, "先运行 cvgen login --base 服务地址。登录后的命令由服务目录提供。").map_err(|err| err.to_string())?;
            return Ok(());
        }
    };
    let catalog = fetch_catalog(&saved.base, &saved.token)?;
    for item in catalog {
        if let Some(usage) = item.get("usage").and_then(Value::as_str) {
            writeln!(stdout, "  {usage}").map_err(|err| err.to_string())?;
        }
    }
    Ok(())
}

fn command_name(first: &str, rest: &[String], catalog: &[Value]) -> Result<String, String> {
    let names: Vec<String> = catalog.iter().filter_map(|item| item.get("name").and_then(Value::as_str).map(str::to_string)).collect();
    let with_next = rest.first().map(|item| format!("{first} {item}")).unwrap_or_default();
    if names.iter().any(|name| name == &with_next) {
        return Ok(with_next);
    }
    if names.iter().any(|name| name == first) {
        return Ok(first.to_string());
    }
    Err(format!("未知命令 {first}。运行 cvgen --help。"))
}

fn dispatch(stdout: &mut dyn Write, auth: &Auth, spec: &Value, rest: &[String]) -> Result<(), String> {
    let args = spec.get("args").and_then(Value::as_array).cloned().unwrap_or_default();
    let consumed = if spec.get("name").and_then(Value::as_str).unwrap_or("").contains(' ') { 1 } else { 0 };
    let tokens = &rest[consumed.min(rest.len())..];
    if spec.get("file").and_then(Value::as_bool).unwrap_or(false) {
        return upload(stdout, auth, spec, tokens, &args);
    }
    if spec.get("binary").and_then(Value::as_bool).unwrap_or(false) {
        let path = fill_path(spec.get("path").and_then(Value::as_str).unwrap_or(""), tokens)?;
        let bytes = request_bytes(spec.get("method").and_then(Value::as_str).unwrap_or("GET"), &auth.base, &path, &auth.token)?;
        writeln!(stdout, "{}", serde_json::to_string_pretty(&json!({"status_code": 200, "bytes": bytes.len()})).unwrap()).map_err(|err| err.to_string())?;
        return Ok(());
    }
    let method = spec.get("method").and_then(Value::as_str).unwrap_or("GET");
    let path = build_path(spec, tokens, &args)?;
    let body = build_body(spec, tokens, &args)?;
    if spec.get("wait").and_then(Value::as_bool).unwrap_or(false) {
        return wait_job(stdout, auth, &path);
    }
    let value = request(method, &auth.base, &path, Some(&auth.token), body)?;
    print_json(stdout, &value)
}

fn build_path(spec: &Value, tokens: &[String], args: &[Value]) -> Result<String, String> {
    let mut path = spec.get("path").and_then(Value::as_str).unwrap_or("").to_string();
    for (index, token) in tokens.iter().enumerate() {
        path = path.replace(&format!("{{{index}}}"), token);
    }
    let mut query = Vec::new();
    for arg in args {
        if let Some(name) = arg.get("query").and_then(Value::as_str) {
            if let Some(value) = positional(arg, tokens)? {
                query.push(format!("{name}={value}"));
            }
        }
    }
    if !query.is_empty() {
        path.push('?');
        path.push_str(&query.join("&"));
    }
    if path.contains('{') {
        return Err("缺少参数".into());
    }
    Ok(path)
}

fn fill_path(template: &str, tokens: &[String]) -> Result<String, String> {
    let mut path = template.to_string();
    for (index, token) in tokens.iter().enumerate() {
        path = path.replace(&format!("{{{index}}}"), token);
    }
    if path.contains('{') {
        return Err("缺少参数".into());
    }
    Ok(path)
}

fn build_body(spec: &Value, tokens: &[String], args: &[Value]) -> Result<Option<Value>, String> {
    if spec.get("method").and_then(Value::as_str) == Some("GET") || args.is_empty() {
        return Ok(None);
    }
    let mut body = Map::new();
    let mut detail = Map::new();
    for arg in args {
        if arg.get("query").is_some() {
            continue;
        }
        let key = arg.get("name").and_then(Value::as_str).unwrap_or("value");
        let value = if let Some(constant) = arg.get("const") {
            constant.clone()
        } else if arg.get("rest").and_then(Value::as_bool).unwrap_or(false) {
            Value::Array(plain_tokens(tokens).into_iter().map(Value::String).collect())
        } else if arg.get("json").and_then(Value::as_bool).unwrap_or(false) {
            let raw = positional(arg, tokens)?.ok_or_else(|| format!("缺少 {key}"))?;
            serde_json::from_str(&raw).map_err(|err| format!("JSON 无法解析：{err}"))?
        } else {
            match positional(arg, tokens)? {
                Some(text) => Value::String(text),
                None if arg.get("optional").and_then(Value::as_bool).unwrap_or(false) => continue,
                None => return Err(format!("缺少 {key}")),
            }
        };
        if let Some(dotted) = arg.get("body").and_then(Value::as_str) {
            if let Some(name) = dotted.strip_prefix("detail.") {
                detail.insert(name.to_string(), value);
            }
        } else {
            body.insert(key.to_string(), value);
        }
    }
    if !detail.is_empty() {
        body.insert("detail".into(), Value::Object(detail));
    }
    if body.is_empty() {
        return Ok(None);
    }
    Ok(Some(Value::Object(body)))
}

fn plain_tokens(tokens: &[String]) -> Vec<String> {
    let mut plain = Vec::new();
    let mut skip = false;
    for item in tokens {
        if skip {
            skip = false;
            continue;
        }
        if item.starts_with("--") {
            skip = true;
            continue;
        }
        plain.push(item.clone());
    }
    plain
}

fn positional(arg: &Value, tokens: &[String]) -> Result<Option<String>, String> {
    if let Some(flag) = arg.get("flag").and_then(Value::as_str) {
        let mut items = tokens.iter();
        while let Some(item) = items.next() {
            if item == flag {
                return Ok(Some(items.next().cloned().ok_or_else(|| format!("缺少 {flag}"))?));
            }
        }
        return Ok(None);
    }
    let position = arg.get("position").and_then(Value::as_u64).unwrap_or(0) as usize;
    let flags_before = tokens.iter().take(position).filter(|item| item.starts_with("--")).count();
    let index = position + flags_before * 2;
    Ok(tokens.get(index).cloned().filter(|item| !item.starts_with("--")))
}

fn upload(stdout: &mut dyn Write, auth: &Auth, spec: &Value, tokens: &[String], args: &[Value]) -> Result<(), String> {
    let file_arg = args.iter().find(|arg| arg.get("file").and_then(Value::as_bool).unwrap_or(false)).ok_or("缺少文件参数")?;
    let path = positional(file_arg, tokens)?.ok_or("缺少文件")?;
    let file = Path::new(&path);
    if !file.is_file() {
        return Err("文件不存在。".into());
    }
    let filename = file.file_name().and_then(|name| name.to_str()).unwrap_or("file.bin");
    let bytes = fs::read(file).map_err(|err| format!("无法读取文件：{err}"))?;
    let boundary = format!("cvgen{}", std::process::id());
    let mut body = Vec::new();
    for arg in args {
        if arg.get("file").and_then(Value::as_bool).unwrap_or(false) {
            continue;
        }
        if let Some(value) = positional(arg, tokens)? {
            let name = arg.get("name").and_then(Value::as_str).unwrap_or("field");
            body.extend_from_slice(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n").as_bytes());
        }
    }
    body.extend_from_slice(format!("--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: application/octet-stream\r\n\r\n").as_bytes());
    body.extend_from_slice(&bytes);
    body.extend_from_slice(format!("\r\n--{boundary}--\r\n").as_bytes());
    let url = format!("{}{}", auth.base.trim_end_matches('/'), spec.get("path").and_then(Value::as_str).unwrap_or(""));
    let response = client()?
        .post(url)
        .header("Authorization", format!("Bearer {}", auth.token))
        .header("Content-Type", format!("multipart/form-data; boundary={boundary}"))
        .body(body)
        .send()
        .map_err(|err| format!("请求失败：{err}"))?;
    finish(stdout, response)
}

fn wait_job(stdout: &mut dyn Write, auth: &Auth, path: &str) -> Result<(), String> {
    for _ in 0..60 {
        let value = request("GET", &auth.base, path, Some(&auth.token), None)?;
        let status = value.get("status").and_then(Value::as_str).unwrap_or("");
        if matches!(status, "succeeded" | "failed" | "unknown") {
            return print_json(stdout, &value);
        }
        thread::sleep(Duration::from_secs(1));
    }
    Err("等待任务超时".into())
}

fn login(stdout: &mut dyn Write, args: &[String]) -> Result<(), String> {
    let mut base = String::new();
    let mut items = args.iter();
    while let Some(item) = items.next() {
        if item == "--base" {
            base = items.next().cloned().ok_or("缺少服务地址")?;
        }
    }
    if base.is_empty() {
        return Err("登录必须带 --base 服务地址".into());
    }
    let started = request_public("POST", &base, "/api/device/start", Some(json!({})))?;
    let code = started.get("code").and_then(Value::as_str).unwrap_or("");
    writeln!(stdout, "设备码 {code}").map_err(|err| err.to_string())?;
    writeln!(stdout, "在网页批准：{}", started.get("approve_url").and_then(Value::as_str).unwrap_or("")).map_err(|err| err.to_string())?;
    for _ in 0..60 {
        let polled = request_public("GET", &base, &format!("/api/device/{code}"), None)?;
        if polled.get("status").and_then(Value::as_str) == Some("approved") {
            let token = polled.get("token").and_then(Value::as_str).unwrap_or("");
            save_auth(&base, token)?;
            writeln!(stdout, "已授权。凭证只保存在本机。").map_err(|err| err.to_string())?;
            return Ok(());
        }
        thread::sleep(Duration::from_secs(1));
    }
    Err("等待批准超时".into())
}

fn fetch_catalog(base: &str, token: &str) -> Result<Vec<Value>, String> {
    let value = request("GET", base, "/api/cli", Some(token), None)?;
    value.get("commands").and_then(Value::as_array).cloned().ok_or_else(|| "目录没有命令".into())
}

fn finish(stdout: &mut dyn Write, response: reqwest::blocking::Response) -> Result<(), String> {
    let status = response.status();
    let text = response.text().map_err(|err| format!("无法读取响应：{err}"))?;
    if !status.is_success() {
        let _ = io::stderr().write_all(text.as_bytes());
        return Err(format!("服务返回 {}", status.as_u16()));
    }
    let value: Value = serde_json::from_str(&text).unwrap_or(json!({"status_code": status.as_u16()}));
    print_json(stdout, &value)
}

fn request_public(method: &str, base: &str, path: &str, body: Option<Value>) -> Result<Value, String> {
    request(method, base, path, None, body)
}

fn request(method: &str, base: &str, path: &str, token: Option<&str>, body: Option<Value>) -> Result<Value, String> {
    let url = format!("{}{}", base.trim_end_matches('/'), path);
    let client = client()?;
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

fn request_bytes(method: &str, base: &str, path: &str, token: &str) -> Result<Vec<u8>, String> {
    let url = format!("{}{}", base.trim_end_matches('/'), path);
    let response = client()?
        .request(method.parse().map_err(|_| format!("未知方法 {method}"))?, url)
        .header("Authorization", format!("Bearer {token}"))
        .send()
        .map_err(|err| format!("请求失败：{err}"))?;
    if !response.status().is_success() {
        return Err(format!("服务返回 {}", response.status().as_u16()));
    }
    response.bytes().map(|item| item.to_vec()).map_err(|err| format!("无法读取响应：{err}"))
}

fn client() -> Result<reqwest::blocking::Client, String> {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(60))
        .no_proxy()
        .build()
        .map_err(|err| format!("无法建立连接：{err}"))
}

fn print_json(stdout: &mut dyn Write, value: &Value) -> Result<(), String> {
    writeln!(stdout, "{}", serde_json::to_string_pretty(value).map_err(|err| err.to_string())?).map_err(|err| err.to_string())
}

struct Auth {
    base: String,
    token: String,
}

fn auth_path() -> PathBuf {
    env::var_os("CVGEN_AUTH").map(PathBuf::from).unwrap_or_else(|| home_dir().join(".cvgen").join("auth.json"))
}

fn home_dir() -> PathBuf {
    env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("."))
}

fn load_auth() -> Result<Auth, String> {
    let path = auth_path();
    let text = fs::read_to_string(&path).map_err(|_| "还没有登录。先运行 cvgen login --base 服务地址。".to_string())?;
    let value: Value = serde_json::from_str(&text).map_err(|err| format!("凭证无法读取：{err}"))?;
    Ok(Auth {
        base: value.get("base").and_then(Value::as_str).unwrap_or("").to_string(),
        token: value.get("token").and_then(Value::as_str).unwrap_or("").to_string(),
    })
}

fn save_auth(base: &str, token: &str) -> Result<(), String> {
    let path = auth_path();
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|err| format!("无法创建凭证目录：{err}"))?;
    }
    write_owner_only(&path, serde_json::to_string(&json!({"base": base, "token": token})).unwrap().as_bytes())
}

fn write_owner_only(path: &Path, bytes: &[u8]) -> Result<(), String> {
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

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::os::unix::fs::PermissionsExt;
    use std::sync::{Arc, Mutex, OnceLock};

    fn auth_lock() -> &'static Mutex<()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
    }

    fn catalog() -> String {
        r#"{"commands":[
            {"name":"workspace use","usage":"cvgen workspace use <工作区>","method":"POST","path":"/api/workspaces/use","args":[{"name":"id","position":0,"file":false}]},
            {"name":"work use","usage":"cvgen work use <作品>","method":"POST","path":"/api/works/use","args":[{"name":"id","position":0,"file":false}]},
            {"name":"retry","usage":"cvgen retry <任务>","method":"POST","path":"/api/jobs/{0}/retry","args":[{"name":"id","position":0,"file":false}]},
            {"name":"prompt save","usage":"cvgen prompt save <镜头> <文本>","method":"POST","path":"/api/shots/{0}/prompt","args":[{"name":"id","position":0,"file":false},{"name":"text","position":1,"file":false}]},
            {"name":"layout tidy","usage":"cvgen layout tidy","method":"POST","path":"/api/layout/tidy","args":[]},
            {"name":"learn","usage":"cvgen learn <地址>","method":"POST","path":"/api/learn","args":[{"name":"url","position":0,"file":false,"body":"detail.url"},{"name":"role","const":"风格","body":"detail.role"}]},
            {"name":"extra","usage":"cvgen extra <标记>","method":"POST","path":"/api/extra","args":[{"name":"mark","position":0,"file":false}]}
        ]}"#.into()
    }

    fn serve(routes: Arc<Mutex<Vec<(String, String, String)>>>) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        thread::spawn(move || {
            for incoming in listener.incoming().take(12) {
                let mut stream = incoming.unwrap();
                let mut buf = Vec::new();
                let mut chunk = [0u8; 2048];
                loop {
                    let n = stream.read(&mut chunk).unwrap_or(0);
                    if n == 0 {
                        break;
                    }
                    buf.extend_from_slice(&chunk[..n]);
                    if buf.windows(4).any(|window| window == b"\r\n\r\n") {
                        break;
                    }
                }
                let text = String::from_utf8_lossy(&buf).to_string();
                let request = text.lines().next().unwrap_or("").to_string();
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
                let payload = if request.contains("POST /api/device/start") {
                    r#"{"code":"abc123","approve_url":"http://127.0.0.1/approve/abc123"}"#.to_string()
                } else if request.contains("GET /api/device/abc123") {
                    r#"{"status":"approved","token":"device-token"}"#.to_string()
                } else if request.contains("GET /api/cli") && auth == "Bearer device-token" {
                    catalog()
                } else if auth == "Bearer device-token" {
                    r#"{"ok":true}"#.to_string()
                } else {
                    let response = "HTTP/1.1 401 Unauthorized\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}";
                    let _ = stream.write_all(response.as_bytes());
                    continue;
                };
                let response = format!(
                    "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    payload.len(),
                    payload
                );
                let _ = stream.write_all(response.as_bytes());
            }
        });
        format!("http://127.0.0.1:{port}")
    }

    #[test]
    fn help_comes_from_catalog_and_unknown_name_is_refused() {
        let _guard = auth_lock().lock().unwrap();
        let routes = Arc::new(Mutex::new(Vec::new()));
        let base = serve(routes.clone());
        let dir = std::env::temp_dir().join(format!("cvgen-help-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let auth = dir.join("auth.json");
        env::set_var("CVGEN_AUTH", &auth);
        let missing = run(vec!["--help".into()], &mut Vec::new()).unwrap();
        let _ = missing;
        let mut before = Vec::new();
        run(vec!["--help".into()], &mut before).unwrap();
        let early = String::from_utf8(before).unwrap();
        assert!(early.contains("login --base"));
        assert!(!early.contains("workspace use"));
        fs::write(&auth, format!(r#"{{"base":"{base}","token":"device-token"}}"#)).unwrap();
        let mut help = Vec::new();
        run(vec!["--help".into()], &mut help).unwrap();
        let text = String::from_utf8(help).unwrap();
        for phrase in ["workspace use", "work use", "retry", "prompt save", "layout tidy", "extra"] {
            assert!(text.contains(phrase), "{phrase} missing from {text}");
        }
        assert!(!text.contains("setup"));
        let refused = run(vec!["not-a-command".into()], &mut Vec::new()).unwrap_err();
        assert!(refused.contains("未知命令"));
        let extra = run(vec!["extra".into(), "mark-1".into()], &mut Vec::new()).unwrap();
        let _ = extra;
        let seen = routes.lock().unwrap().clone();
        assert!(seen.iter().any(|(req, header, body)| req.contains("POST /api/extra") && header == "Bearer device-token" && body.contains("mark-1")));
        env::remove_var("CVGEN_AUTH");
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn login_requires_base_and_writes_owner_only_credentials() {
        let _guard = auth_lock().lock().unwrap();
        let routes = Arc::new(Mutex::new(Vec::new()));
        let base = serve(routes);
        let dir = std::env::temp_dir().join(format!("cvgen-auth-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let auth = dir.join("auth.json");
        env::set_var("CVGEN_AUTH", &auth);
        let missing = run(vec!["login".into()], &mut Vec::new()).unwrap_err();
        assert!(missing.contains("--base"));
        assert!(!auth.exists());
        run(vec!["login".into(), "--base".into(), base], &mut Vec::new()).unwrap();
        let mode = fs::metadata(&auth).unwrap().permissions().mode() & 0o777;
        assert_eq!(mode, 0o600);
        assert!(fs::read_to_string(&auth).unwrap().contains("device-token"));
        env::remove_var("CVGEN_AUTH");
        let _ = fs::remove_dir_all(dir);
    }

    #[test]
    fn learn_posts_catalog_role() {
        let _guard = auth_lock().lock().unwrap();
        let routes = Arc::new(Mutex::new(Vec::new()));
        let base = serve(routes.clone());
        let dir = std::env::temp_dir().join(format!("cvgen-learn-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let auth = dir.join("auth.json");
        env::set_var("CVGEN_AUTH", &auth);
        fs::write(&auth, format!(r#"{{"base":"{base}","token":"device-token"}}"#)).unwrap();
        run(vec!["learn".into(), "https://example.test/clip.mp4".into(), "ignored".into()], &mut Vec::new()).unwrap();
        let seen = routes.lock().unwrap().clone();
        let learn = seen.iter().find(|(req, _, _)| req.contains("POST /api/learn")).expect("learn");
        assert!(learn.2.contains("https://example.test/clip.mp4"), "{}", learn.2);
        assert!(learn.2.contains("风格"), "{}", learn.2);
        assert!(!learn.2.contains("ignored"));
        env::remove_var("CVGEN_AUTH");
        let _ = fs::remove_dir_all(dir);
    }
}
