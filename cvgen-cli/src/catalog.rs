//! The command catalog (schema v2) served at GET /api/cli, its local cache, and help text.

use std::cmp::Ordering;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use crate::config::{self, Paths};
use crate::error::{self, Failure, Result};
use crate::http::Api;

pub const SCHEMA_VERSION: u64 = 2;
pub const CLIENT_VERSION: &str = env!("CARGO_PKG_VERSION");
/// A cached catalog younger than this is used without asking the server again.
const CACHE_SECONDS: u64 = 600;

#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct Catalog {
    #[serde(default)]
    pub schema_version: u64,
    #[serde(default)]
    pub min_client: String,
    #[serde(default)]
    pub commands: Vec<Command>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Command {
    pub name: String,
    #[serde(default)]
    pub usage: String,
    #[serde(default)]
    pub summary: String,
    #[serde(default)]
    pub method: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub args: Vec<ArgSpec>,
    #[serde(default)]
    pub body: Map<String, Value>,
    #[serde(default)]
    pub local: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ArgSpec {
    pub name: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub position: usize,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub flag: Option<String>,
    /// Extra spellings of the flag; only used by the client's own local commands (e.g. `-o` / `--output`).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub aliases: Vec<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub context: Option<String>,
    #[serde(rename = "in", default)]
    pub into: String,
    #[serde(rename = "type", default = "string_type")]
    pub kind: String,
    #[serde(default)]
    pub required: bool,
    #[serde(default)]
    pub variadic: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub default: Option<Value>,
    #[serde(default)]
    pub help: String,
}

fn string_type() -> String {
    "string".into()
}

impl ArgSpec {
    pub fn positional(name: &str, position: usize, kind: &str, required: bool, help: &str) -> Self {
        ArgSpec {
            name: name.into(), source: "positional".into(), position, into: "body".into(), kind: kind.into(),
            required, help: help.into(), ..Default::default()
        }
    }

    pub fn flag(name: &str, flag: &str, kind: &str, required: bool, help: &str) -> Self {
        ArgSpec {
            name: name.into(), source: "flag".into(), flag: Some(flag.into()), into: "body".into(), kind: kind.into(),
            required, help: help.into(), ..Default::default()
        }
    }

    pub fn context(name: &str, context: &str) -> Self {
        ArgSpec {
            name: name.into(), source: "context".into(), context: Some(context.into()), into: "body".into(),
            kind: "string".into(), required: true, ..Default::default()
        }
    }

    pub fn matches_flag(&self, token: &str) -> bool {
        self.source == "flag" && (self.flag.as_deref() == Some(token) || self.aliases.iter().any(|alias| alias == token))
    }

    /// How the argument is written on the command line, e.g. `<shot_id>`, `--resolution <string>`, `--force`.
    pub fn display(&self) -> String {
        match self.source.as_str() {
            "positional" if self.variadic => format!("<{}...>", self.name),
            "positional" => format!("<{}>", self.name),
            "flag" => {
                let mut names = vec![self.flag.clone().unwrap_or_default()];
                names.extend(self.aliases.iter().cloned());
                if self.kind == "bool" {
                    names.join(", ")
                } else {
                    format!("{} <{}>", names.join(", "), self.kind)
                }
            }
            _ => format!("({})", self.name),
        }
    }
}

impl Command {
    pub fn group(&self) -> &str {
        self.name.split(' ').next().unwrap_or("")
    }
}

/// Match the longest command name at the start of argv. Help switches between the words are allowed.
/// Returns the command and the remaining tokens (help switches kept).
pub fn split_command<'a>(commands: &'a [Command], argv: &[String]) -> Option<(&'a Command, Vec<String>)> {
    let mut words: Vec<(usize, &str)> = Vec::new();
    for (index, token) in argv.iter().enumerate() {
        if token == "-h" || token == "--help" {
            continue;
        }
        if token.starts_with('-') {
            break;
        }
        words.push((index, token));
    }
    let mut best: Option<(&Command, usize)> = None;
    for command in commands {
        let parts: Vec<&str> = command.name.split(' ').collect();
        if parts.len() <= words.len()
            && parts.iter().zip(&words).all(|(part, (_, word))| part == word)
            && best.map_or(true, |(_, len)| parts.len() > len)
        {
            best = Some((command, parts.len()));
        }
    }
    let (command, len) = best?;
    let used: Vec<usize> = words[..len].iter().map(|(index, _)| *index).collect();
    let rest = argv.iter().enumerate().filter(|(index, _)| !used.contains(index)).map(|(_, token)| token.clone()).collect();
    Some((command, rest))
}

/// Compare dotted versions numerically ("0.10.0" > "0.9.3"); missing parts count as 0, suffixes after '-' or '+' are ignored.
pub fn compare_versions(a: &str, b: &str) -> Ordering {
    fn parts(version: &str) -> Vec<u64> {
        let core = version.trim().trim_start_matches('v');
        let core = core.split(['-', '+']).next().unwrap_or("");
        core.split('.').map(|part| part.trim().parse::<u64>().unwrap_or(0)).collect()
    }
    let (left, right) = (parts(a), parts(b));
    for index in 0..left.len().max(right.len()) {
        let order = left.get(index).unwrap_or(&0).cmp(right.get(index).unwrap_or(&0));
        if order != Ordering::Equal {
            return order;
        }
    }
    Ordering::Equal
}

pub fn client_is_outdated(catalog: &Catalog) -> bool {
    !catalog.min_client.is_empty() && compare_versions(CLIENT_VERSION, &catalog.min_client) == Ordering::Less
}

#[derive(Debug, Serialize, Deserialize)]
struct Cached {
    base: String,
    fetched_at: u64,
    catalog: Catalog,
}

fn now() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

/// Loads the catalog from the cache or the server; refreshes from the server at most once per invocation.
pub struct Store<'a> {
    paths: &'a Paths,
    api: &'a Api,
    refreshed: bool,
    warned: bool,
}

impl<'a> Store<'a> {
    pub fn new(paths: &'a Paths, api: &'a Api) -> Self {
        Store { paths, api, refreshed: false, warned: false }
    }

    pub fn can_refresh(&self) -> bool {
        !self.refreshed
    }

    /// The cached catalog if it is fresh and for this server, otherwise a fresh one.
    pub fn get(&mut self) -> Result<Catalog> {
        let cached: Option<Cached> = config::read_json(&self.paths.catalog()).unwrap_or(None);
        let cached = cached.filter(|item| item.base == self.api.base);
        if let Some(item) = &cached {
            if now().saturating_sub(item.fetched_at) < CACHE_SECONDS || self.refreshed {
                return Ok(self.checked(item.catalog.clone()));
            }
        }
        match self.refresh() {
            Ok(catalog) => Ok(catalog),
            Err(failure) if failure.code == error::NETWORK && cached.is_some() => {
                eprintln!("警告：拿不到最新命令目录（{}），先用本机缓存", failure.message);
                Ok(self.checked(cached.unwrap().catalog))
            }
            Err(failure) => Err(failure),
        }
    }

    pub fn refresh(&mut self) -> Result<Catalog> {
        self.refreshed = true;
        let value = self.api.get_json("/api/cli")?;
        let catalog: Catalog = serde_json::from_value(value)
            .map_err(|err| Failure::server(format!("服务返回的命令目录无法解析：{err}")))?;
        let cached = Cached { base: self.api.base.clone(), fetched_at: now(), catalog: catalog.clone() };
        config::write_json(&self.paths.catalog(), &cached)?;
        Ok(self.checked(catalog))
    }

    fn checked(&mut self, catalog: Catalog) -> Catalog {
        if !self.warned {
            self.warned = true;
            if client_is_outdated(&catalog) {
                eprintln!(
                    "客户端版本过旧，请到网页“设置 → 工具下载”下载新版（本机 {CLIENT_VERSION}，服务要求至少 {}）",
                    catalog.min_client
                );
            } else if catalog.schema_version > SCHEMA_VERSION {
                eprintln!("服务的命令目录比客户端新，部分命令可能不可用。请到网页“设置 → 工具下载”下载新版");
            }
        }
        catalog
    }
}

/// Terminal columns: CJK and full-width characters take two.
fn width_of(text: &str) -> usize {
    text.chars()
        .map(|c| match c as u32 {
            0x1100..=0x115F | 0x2E80..=0xA4CF | 0xAC00..=0xD7A3 | 0xF900..=0xFAFF | 0xFE30..=0xFE4F | 0xFF00..=0xFF60
            | 0xFFE0..=0xFFE6 => 2,
            _ => 1,
        })
        .sum()
}

fn pad(text: &str, width: usize) -> String {
    let len = width_of(text);
    if len >= width {
        format!("{text}  ")
    } else {
        format!("{text}{}", " ".repeat(width - len))
    }
}

/// `cvgen --help`: commands grouped by first word, then exit codes.
pub fn global_help(commands: &[Command], note: Option<&str>, config_dir: &str) -> String {
    let mut out = String::new();
    out.push_str(&format!("cvgen {CLIENT_VERSION}：操作云端视频系统。命令来自服务端目录，执行在服务端。\n\n"));
    out.push_str("用法：cvgen <命令> [参数…] [选项…]\n");
    out.push_str("      选项可以写在任何位置；`--` 之后的内容全部当作参数原样传递；\n");
    out.push_str("      任何命令后加 -h 或 --help 只看说明，不执行。\n");
    out.push_str("      JSON 参数可以直接写、写 @文件路径，或写 - 从标准输入读。\n\n");
    out.push_str("开始：cvgen login --base 服务地址 → cvgen workspace use <工作区id> → cvgen work new <名称>（或 cvgen work use <作品id>）\n\n");
    out.push_str("命令：\n");
    let mut groups: Vec<&str> = Vec::new();
    for command in commands {
        if !groups.contains(&command.group()) {
            groups.push(command.group());
        }
    }
    let width = commands.iter().map(|c| width_of(&c.name)).max().unwrap_or(0) + 3;
    let mut previous_size = 0;
    for (index, group) in groups.iter().enumerate() {
        let members: Vec<&Command> = commands.iter().filter(|c| c.group() == *group).collect();
        if index > 0 && (members.len() > 1 || previous_size > 1) {
            out.push('\n');
        }
        previous_size = members.len();
        for command in members {
            out.push_str(&format!("  {}{}\n", pad(&command.name, width), command.summary));
        }
    }
    if let Some(note) = note {
        out.push_str(&format!("\n{note}\n"));
    }
    out.push_str("\n退出码：\n");
    for (code, meaning) in error::EXIT_CODES {
        out.push_str(&format!("  {code}  {meaning}\n"));
    }
    out.push_str(&format!("\n凭证和当前工作区、作品保存在 {config_dir}\n"));
    out
}

/// Commands whose first word is `group`, for `cvgen work` without a subcommand.
pub fn group_help(commands: &[Command], group: &str) -> Option<String> {
    let members: Vec<&Command> = commands.iter().filter(|c| c.group() == group).collect();
    if members.is_empty() {
        return None;
    }
    let width = members.iter().map(|c| width_of(&c.usage)).max().unwrap_or(0) + 3;
    let mut out = String::new();
    for command in members {
        out.push_str(&format!("  {}{}\n", pad(&command.usage, width), command.summary));
    }
    out.push_str("任何命令后加 --help 看详细说明。\n");
    Some(out)
}

/// `cvgen <command> --help`: usage, summary and every argument.
pub fn command_help(command: &Command) -> String {
    let mut out = format!("用法：{}\n\n{}\n", command.usage, command.summary);
    let shown: Vec<&ArgSpec> = command.args.iter().filter(|arg| arg.source != "context").collect();
    if !shown.is_empty() {
        out.push_str("\n参数：\n");
        let width = shown.iter().map(|a| width_of(&a.display())).max().unwrap_or(0) + 3;
        for arg in shown {
            let mut notes = Vec::new();
            if !arg.help.is_empty() {
                notes.push(arg.help.clone());
            }
            notes.push(type_note(arg));
            if arg.source == "positional" && !arg.required {
                notes.push("可省略".into());
            }
            if arg.source == "flag" && arg.required {
                notes.push("必填".into());
            }
            if let Some(default) = &arg.default {
                let text = default.as_str().map(str::to_string).unwrap_or_else(|| default.to_string());
                notes.push(format!("默认 {text}"));
            }
            out.push_str(&format!("  {}{}\n", pad(&arg.display(), width), notes.join("；")));
        }
    }
    let contexts: Vec<&str> = command.args.iter().filter_map(|arg| arg.context.as_deref()).collect();
    if contexts.contains(&"workspace") {
        out.push_str("\n使用当前工作区（cvgen workspace use <工作区id> 设置）。\n");
    }
    if contexts.contains(&"work") {
        out.push_str("\n使用当前作品（cvgen work use <作品id> 或 cvgen work new 设置）。\n");
    }
    out
}

fn type_note(arg: &ArgSpec) -> String {
    match arg.kind.as_str() {
        "int" => "整数".into(),
        "float" => "数字".into(),
        "bool" => "开关，不带值".into(),
        "json" => "JSON：直接写、@文件路径，或 - 从标准输入读".into(),
        "list" if arg.variadic => "后面所有参数组成列表（-- 之后的也算）".into(),
        "list" => "列表，用逗号分隔".into(),
        _ => "文字".into(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn names(items: &[&str]) -> Vec<Command> {
        items.iter().map(|name| Command { name: name.to_string(), ..Default::default() }).collect()
    }

    fn argv(items: &[&str]) -> Vec<String> {
        items.iter().map(|item| item.to_string()).collect()
    }

    #[test]
    fn longest_command_name_wins() {
        let commands = names(&["job", "job wait", "work new", "link"]);
        let (command, rest) = split_command(&commands, &argv(&["job", "wait", "t1", "--timeout", "5"])).unwrap();
        assert_eq!(command.name, "job wait");
        assert_eq!(rest, argv(&["t1", "--timeout", "5"]));
        let (command, rest) = split_command(&commands, &argv(&["job", "x"])).unwrap();
        assert_eq!(command.name, "job");
        assert_eq!(rest, argv(&["x"]));
        let (command, rest) = split_command(&commands, &argv(&["work", "--help", "new"])).unwrap();
        assert_eq!(command.name, "work new");
        assert_eq!(rest, argv(&["--help"]));
        assert!(split_command(&commands, &argv(&["work"])).is_none());
        assert!(split_command(&commands, &argv(&["--kind", "work", "new"])).is_none());
    }

    #[test]
    fn versions_compare_numerically() {
        assert_eq!(compare_versions("0.2.0", "0.2.0"), Ordering::Equal);
        assert_eq!(compare_versions("0.2", "0.2.0"), Ordering::Equal);
        assert_eq!(compare_versions("0.10.0", "0.9.9"), Ordering::Greater);
        assert_eq!(compare_versions("0.2.0", "0.3.0"), Ordering::Less);
        assert_eq!(compare_versions("1.0.0-beta", "1.0.0"), Ordering::Equal);
        assert_eq!(compare_versions("v1.2.3", "1.2.4"), Ordering::Less);
        let mut catalog = Catalog { min_client: "0.2.0".into(), ..Default::default() };
        assert!(!client_is_outdated(&catalog));
        catalog.min_client = "9.0.0".into();
        assert!(client_is_outdated(&catalog));
        catalog.min_client = String::new();
        assert!(!client_is_outdated(&catalog));
    }

    #[test]
    fn help_groups_commands_and_lists_exit_codes() {
        let mut commands = names(&["work list", "login", "work new"]);
        commands[0].summary = "列出作品".into();
        let text = global_help(&commands, Some("先运行 cvgen login --base 服务地址"), "/tmp/x");
        let listing = &text[text.find("命令：").unwrap()..];
        let list = listing.find("work list").unwrap();
        let new = listing.find("work new").unwrap();
        let login = listing.find("  login").unwrap();
        assert!(list < new && new < login, "work commands are grouped together:\n{text}");
        assert!(text.contains("cvgen login --base"));
        for code in 0..=6 {
            assert!(text.contains(&format!("  {code}  ")), "exit code {code} documented");
        }
    }

    #[test]
    fn schema_v2_catalog_parses() {
        let text = r#"{"schema_version":2,"min_client":"0.2.0","commands":[{"name":"job show","usage":"cvgen job show <任务id>",
            "summary":"s","method":"GET","path":"/api/tasks/{id}","args":[{"name":"id","source":"positional","position":0,
            "in":"path","type":"string","required":true,"variadic":false,"help":""}],"body":{},"local":false}]}"#;
        let catalog: Catalog = serde_json::from_str(text).unwrap();
        assert_eq!(catalog.commands[0].args[0].into, "path");
        let help = command_help(&catalog.commands[0]);
        assert!(help.contains("<id>") && help.contains("cvgen job show"));
    }
}
