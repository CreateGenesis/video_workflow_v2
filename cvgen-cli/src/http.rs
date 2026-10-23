//! HTTP to the cvgen server: rustls, proxies from the environment, the client version on every request,
//! and one place that turns failures into exit codes.

use std::time::Duration;

use reqwest::blocking::{multipart, Client, RequestBuilder, Response};
use reqwest::Method;
use serde_json::Value;

use crate::catalog::CLIENT_VERSION;
use crate::error::{Failure, Result};

const CONNECT_TIMEOUT: Duration = Duration::from_secs(15);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(120);

pub struct Api {
    pub base: String,
    token: Option<String>,
    normal: Client,
    /// No total timeout: uploads, downloads and long-poll waits.
    long: Client,
}

pub struct Reply {
    pub content_type: String,
    pub text: String,
}

impl Reply {
    pub fn is_json(&self) -> bool {
        self.content_type.contains("json")
    }

    pub fn json(&self) -> Result<Value> {
        if self.text.trim().is_empty() {
            return Ok(Value::Null);
        }
        serde_json::from_str(&self.text).map_err(|err| Failure::server(format!("服务返回的不是 JSON：{err}")))
    }

    /// JSON is pretty-printed; anything else (e.g. text/plain skill bodies) is printed as is.
    pub fn print(&self) -> Result<()> {
        if self.is_json() {
            print_json(&self.json()?);
        } else {
            print!("{}", self.text);
            if !self.text.ends_with('\n') {
                println!();
            }
        }
        Ok(())
    }
}

pub fn print_json(value: &Value) {
    println!("{}", serde_json::to_string_pretty(value).unwrap_or_else(|_| value.to_string()));
}

pub fn normalize_base(base: &str) -> Result<String> {
    let base = base.trim().trim_end_matches('/');
    if !(base.starts_with("http://") || base.starts_with("https://")) || base.len() <= "https://".len() {
        return Err(Failure::usage(format!("服务地址要以 http:// 或 https:// 开头，收到 {base}")));
    }
    Ok(base.to_string())
}

fn build(timeout: Option<Duration>) -> Result<Client> {
    // Proxies come from HTTP_PROXY / HTTPS_PROXY / NO_PROXY (reqwest reads them by default).
    Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .timeout(timeout)
        .user_agent(format!("cvgen/{CLIENT_VERSION}"))
        .build()
        .map_err(|err| Failure::network(format!("无法初始化网络：{err}")))
}

impl Api {
    pub fn new(base: &str, token: Option<&str>) -> Result<Api> {
        Ok(Api {
            base: normalize_base(base)?,
            token: token.map(str::to_string),
            normal: build(Some(REQUEST_TIMEOUT))?,
            long: build(None)?,
        })
    }

    fn request(&self, long: bool, method: &str, path: &str) -> Result<RequestBuilder> {
        let method = Method::from_bytes(method.as_bytes()).map_err(|_| Failure::usage(format!("未知的请求方法 {method}")))?;
        let client = if long { &self.long } else { &self.normal };
        let mut builder = client.request(method, format!("{}{}", self.base, path)).header("X-CVGEN-Client", CLIENT_VERSION);
        if let Some(token) = &self.token {
            builder = builder.bearer_auth(token);
        }
        Ok(builder)
    }

    /// Send and check the status; non-2xx becomes exit code 2 with the server's `detail`.
    pub fn send(&self, builder: RequestBuilder) -> Result<Response> {
        let response = builder.send().map_err(|err| self.network(err))?;
        let status = response.status();
        if status.is_success() {
            return Ok(response);
        }
        let text = response.text().unwrap_or_default();
        if status.as_u16() == 401 && self.token.is_some() {
            return Err(Failure::server(format!(
                "凭证失效或设备已被下线，请重新运行 cvgen login --base {}",
                self.base
            )));
        }
        Err(Failure::server(format!("服务拒绝了请求（HTTP {}）：{}", status.as_u16(), detail(&text))))
    }

    fn network(&self, err: reqwest::Error) -> Failure {
        if err.is_timeout() {
            Failure::network(format!("请求 {} 超时：{err}", self.base))
        } else if err.is_connect() {
            Failure::network(format!("连不上 {}：{err}", self.base))
        } else {
            Failure::network(format!("和 {} 通信失败：{err}", self.base))
        }
    }

    fn reply(&self, response: Response) -> Result<Reply> {
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("")
            .to_ascii_lowercase();
        let text = response.text().map_err(|err| self.network(err))?;
        Ok(Reply { content_type, text })
    }

    pub fn call(&self, method: &str, path: &str, body: Option<&Value>) -> Result<Reply> {
        self.call_with(false, method, path, body)
    }

    pub fn call_with(&self, long: bool, method: &str, path: &str, body: Option<&Value>) -> Result<Reply> {
        let mut builder = self.request(long, method, path)?;
        if let Some(body) = body {
            builder = builder.json(body);
        }
        let response = self.send(builder)?;
        self.reply(response)
    }

    pub fn get_json(&self, path: &str) -> Result<Value> {
        self.call("GET", path, None)?.json()
    }

    pub fn get_json_long(&self, path: &str) -> Result<Value> {
        self.call_with(true, "GET", path, None)?.json()
    }

    pub fn post_json(&self, path: &str, body: &Value) -> Result<Value> {
        self.call("POST", path, Some(body))?.json()
    }

    pub fn upload(&self, path: &str, form: multipart::Form) -> Result<Reply> {
        let response = self.send(self.request(true, "POST", path)?.multipart(form))?;
        self.reply(response)
    }

    /// A streaming GET; the caller reads the body.
    pub fn download(&self, path: &str) -> Result<Response> {
        self.send(self.request(true, "GET", path)?)
    }

    pub fn map_read_error(&self, err: std::io::Error) -> Failure {
        Failure::network(format!("从 {} 读取数据失败：{err}", self.base))
    }
}

/// The server's error text: FastAPI `detail` as a string, or a list of validation errors.
pub fn detail(text: &str) -> String {
    let Ok(value) = serde_json::from_str::<Value>(text) else {
        let text = text.trim();
        return if text.is_empty() { "（没有说明）".into() } else { text.chars().take(500).collect() };
    };
    match value.get("detail") {
        Some(Value::String(message)) => message.clone(),
        Some(Value::Array(items)) => items
            .iter()
            .map(|item| {
                let place = item
                    .get("loc")
                    .and_then(Value::as_array)
                    .map(|loc| loc.iter().map(|part| part.as_str().map(str::to_string).unwrap_or(part.to_string())).collect::<Vec<_>>().join("."))
                    .unwrap_or_default();
                let message = item.get("msg").and_then(Value::as_str).unwrap_or("");
                if place.is_empty() { message.to_string() } else { format!("{place}：{message}") }
            })
            .collect::<Vec<_>>()
            .join("；"),
        Some(other) => other.to_string(),
        None => value.to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detail_reads_fastapi_errors() {
        assert_eq!(detail(r#"{"detail":"没有这个任务"}"#), "没有这个任务");
        assert_eq!(
            detail(r#"{"detail":[{"loc":["body","title"],"msg":"Field required"}]}"#),
            "body.title：Field required"
        );
        assert_eq!(detail("Internal Server Error"), "Internal Server Error");
        assert_eq!(detail(""), "（没有说明）");
    }

    /// One-shot HTTP server: answers with `status` and `body`, hands back the raw request.
    fn serve_once(status: &str, body: &'static str) -> (String, std::thread::JoinHandle<String>) {
        use std::io::{Read, Write};
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        let status = status.to_string();
        let handle = std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buf = Vec::new();
            let mut chunk = [0u8; 4096];
            while !buf.windows(4).any(|w| w == b"\r\n\r\n") {
                let n = stream.read(&mut chunk).unwrap();
                if n == 0 {
                    break;
                }
                buf.extend_from_slice(&chunk[..n]);
            }
            let reply = format!(
                "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}",
                body.len()
            );
            stream.write_all(reply.as_bytes()).unwrap();
            String::from_utf8_lossy(&buf).to_lowercase()
        });
        (base, handle)
    }

    #[test]
    fn every_request_carries_version_and_token() {
        let (base, handle) = serve_once("200 OK", r#"{"ok":true}"#);
        let api = Api::new(&base, Some("tok-1")).unwrap();
        assert_eq!(api.get_json("/api/queue").unwrap(), serde_json::json!({"ok": true}));
        let request = handle.join().unwrap();
        assert!(request.starts_with("get /api/queue http/1.1"), "{request}");
        assert!(request.contains(&format!("x-cvgen-client: {CLIENT_VERSION}")), "{request}");
        assert!(request.contains("authorization: bearer tok-1"), "{request}");
    }

    #[test]
    fn rejections_map_to_exit_code_2() {
        let (base, handle) = serve_once("401 Unauthorized", r#"{"detail":"未登录"}"#);
        let err = Api::new(&base, Some("tok")).unwrap().get_json("/api/cli").unwrap_err();
        handle.join().unwrap();
        assert_eq!(err.code, crate::error::SERVER);
        assert_eq!(err.message, format!("凭证失效或设备已被下线，请重新运行 cvgen login --base {base}"));
        let (base, handle) = serve_once("409 Conflict", r#"{"detail":"这个镜头已经成片"}"#);
        let err = Api::new(&base, Some("tok")).unwrap().post_json("/x", &Value::Null).unwrap_err();
        handle.join().unwrap();
        assert_eq!(err.code, crate::error::SERVER);
        assert!(err.message.contains("409") && err.message.contains("这个镜头已经成片"), "{}", err.message);
    }

    #[test]
    fn unreachable_server_is_a_network_error() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let base = format!("http://127.0.0.1:{}", listener.local_addr().unwrap().port());
        drop(listener);
        let err = Api::new(&base, None).unwrap().get_json("/api/health").unwrap_err();
        assert_eq!(err.code, crate::error::NETWORK);
    }

    #[test]
    fn base_is_normalized() {
        assert_eq!(normalize_base("http://127.0.0.1:8080/").unwrap(), "http://127.0.0.1:8080");
        assert!(normalize_base("127.0.0.1:8080").is_err());
    }
}
