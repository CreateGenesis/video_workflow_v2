//! One error type that carries the process exit code.

/// Exit codes, documented in `cvgen --help`.
pub const USAGE: u8 = 1;
pub const SERVER: u8 = 2;
pub const FAILED: u8 = 3;
pub const ATTENTION: u8 = 4;
pub const TIMEOUT: u8 = 5;
pub const NETWORK: u8 = 6;

pub const EXIT_CODES: &[(u8, &str)] = &[
    (0, "成功"),
    (USAGE, "用法错误（参数不对、还没登录、没有选当前工作区或作品）"),
    (SERVER, "服务拒绝了请求（4xx/5xx，原因打印在 stderr）"),
    (FAILED, "任务或运行以失败或取消结束"),
    (ATTENTION, "停下来等人处理（needs_attention / waiting / paused）"),
    (TIMEOUT, "等待超时（--timeout）"),
    (NETWORK, "网络错误（连不上服务、超时）"),
];

#[derive(Debug, Clone, PartialEq)]
pub struct Failure {
    pub code: u8,
    pub message: String,
}

impl Failure {
    pub fn new(code: u8, message: impl Into<String>) -> Self {
        Failure { code, message: message.into() }
    }

    pub fn usage(message: impl Into<String>) -> Self {
        Self::new(USAGE, message)
    }

    pub fn server(message: impl Into<String>) -> Self {
        Self::new(SERVER, message)
    }

    pub fn network(message: impl Into<String>) -> Self {
        Self::new(NETWORK, message)
    }
}

pub type Result<T> = std::result::Result<T, Failure>;
