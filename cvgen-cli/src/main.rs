//! cvgen: the agent CLI for the hosted cvgen video system.
//!
//! Almost every command comes from the server's catalog (GET /api/cli, schema v2) and is executed
//! generically; the few marked `local` (login, context, waits, uploads, downloads) live in `local.rs`.

mod args;
mod catalog;
mod config;
mod error;
mod http;
mod local;

use std::process::ExitCode;

use catalog::{Catalog, Command};
use config::Paths;
use error::{Failure, Result};
use http::Api;

fn main() -> ExitCode {
    let argv: Vec<String> = std::env::args().skip(1).collect();
    match run(&argv) {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => {
            if !failure.message.is_empty() {
                eprintln!("{}", failure.message);
            }
            ExitCode::from(failure.code)
        }
    }
}

fn is_help(token: &str) -> bool {
    token == "-h" || token == "--help"
}

fn run(argv: &[String]) -> Result<()> {
    match argv.first().map(String::as_str).unwrap_or("") {
        "" | "-h" | "--help" => return print_global_help(),
        "help" if argv.len() > 1 => {
            let mut rest = argv[1..].to_vec();
            rest.push("--help".into());
            return run(&rest);
        }
        "help" => return print_global_help(),
        "-V" | "--version" => {
            println!("cvgen {}", catalog::CLIENT_VERSION);
            return Ok(());
        }
        _ => {}
    }
    if let Some(name) = removed_command(argv) {
        return Err(Failure::usage(format!("命令已移除：{name}。不得新建 Reference 或 references")));
    }
    let paths = Paths::discover()?;
    let builtins = local::commands();
    if let Some((command, rest)) = catalog::split_command(&builtins, argv) {
        return local::run(&paths, command, &rest);
    }
    let auth = config::load_auth(&paths)?.ok_or_else(local::not_signed_in)?;
    let api = Api::new(&auth.base, Some(&auth.token))?;
    let mut store = catalog::Store::new(&paths, &api);
    let mut current = store.get()?;
    let mut found = find_remote(&current, argv);
    if found.is_none() && store.can_refresh() {
        current = store.refresh()?;
        found = find_remote(&current, argv);
    }
    match found {
        Some((command, rest)) => execute(&paths, &api, &command, &rest),
        None => not_found(&current, &builtins, argv),
    }
}

fn find_remote(catalog: &Catalog, argv: &[String]) -> Option<(Command, Vec<String>)> {
    let remote: Vec<Command> = catalog.commands.iter().filter(|command| !command.local).cloned().collect();
    catalog::split_command(&remote, argv).map(|(command, rest)| (command.clone(), rest))
}

fn removed_command(argv: &[String]) -> Option<String> {
    let words: Vec<&str> = argv
        .iter()
        .filter(|token| !is_help(token) && !token.starts_with('-'))
        .map(String::as_str)
        .collect();
    let joined = words.join(" ");
    if joined == "entity add Reference" || joined.starts_with("entity add Reference ") {
        return Some("entity add Reference".into());
    }
    if joined == "entity add references" || joined.starts_with("entity add references ") {
        return Some("entity add references".into());
    }
    if words.first() == Some(&"entity") && words.get(1) == Some(&"add") {
        return Some("entity add".into());
    }
    if joined == "link references" || joined.starts_with("link references ") {
        return Some("link references".into());
    }
    None
}

fn not_found(catalog: &Catalog, builtins: &[Command], argv: &[String]) -> Result<()> {
    if let Some(name) = removed_command(argv) {
        return Err(Failure::usage(format!("命令已移除：{name}。不得新建 Reference 或 references")));
    }
    let first = argv.iter().find(|token| !is_help(token)).cloned().unwrap_or_default();
    let local_only: Vec<Command> = catalog.commands.iter().filter(|command| command.local).cloned().collect();
    if let Some((command, _)) = catalog::split_command(&local_only, argv) {
        return Err(Failure::usage(format!("本客户端还不支持 {}，请到网页“设置 → 工具下载”下载新版", command.name)));
    }
    let all = merged(catalog, builtins);
    if let Some(text) = catalog::group_help(&all, &first) {
        if argv.iter().any(|token| is_help(token)) {
            print!("{text}");
            return Ok(());
        }
        eprint!("{first} 后面要跟子命令：\n{text}");
        return Err(Failure::usage(""));
    }
    Err(Failure::usage(format!("未知命令 {first}。运行 cvgen --help 查看全部命令")))
}

/// Catalog order, plus local commands this client has that the catalog does not list.
fn merged(catalog: &Catalog, builtins: &[Command]) -> Vec<Command> {
    let mut all = catalog.commands.clone();
    for command in builtins {
        if !all.iter().any(|item| item.name == command.name) {
            all.push(command.clone());
        }
    }
    all
}

fn execute(paths: &Paths, api: &Api, command: &Command, tokens: &[String]) -> Result<()> {
    let parsed = args::parse(command, tokens)?;
    if parsed.help {
        print!("{}", catalog::command_help(command));
        return Ok(());
    }
    let context = config::load_context(paths)?;
    let values = args::bind(command, &parsed, &context, &mut local::read_stdin)?;
    let call = args::assemble(command, &values)?;
    let reply = api.call(&call.method, &call.path, call.body.as_ref())?;
    if command.name == "comic missing" {
        return print_comic_missing(&reply);
    }
    reply.print()?;
    if command.name == "work new" && reply.is_json() {
        local::set_current_work(paths, &reply.json()?)?;
    }
    Ok(())
}

fn print_comic_missing(reply: &http::Reply) -> Result<()> {
    let body = reply.json()?;
    if body.get("local_h3").and_then(serde_json::Value::as_bool).unwrap_or(false) {
        return Err(Failure::usage("客户端不能在本地拼 H3 请求"));
    }
    let stopped = body.get("stopped_at").and_then(serde_json::Value::as_str).unwrap_or("未知");
    let missing = body.get("missing").cloned().unwrap_or(serde_json::Value::Array(vec![]));
    println!("停在：{stopped}");
    println!("缺：{missing}");
    Ok(())
}

fn print_global_help() -> Result<()> {
    let builtins = local::commands();
    let paths = Paths::discover().ok();
    let dir = paths.as_ref().map(|p| p.dir.display().to_string()).unwrap_or_else(|| "（找不到用户目录）".into());
    let auth = paths.as_ref().and_then(|p| config::load_auth(p).ok().flatten());
    let (commands, note) = match (&paths, auth) {
        (Some(paths), Some(auth)) => {
            let loaded = Api::new(&auth.base, Some(&auth.token)).and_then(|api| catalog::Store::new(paths, &api).get());
            match loaded {
                Ok(current) => (merged(&current, &builtins), None),
                Err(failure) => (
                    builtins,
                    Some(format!("拿不到服务端命令目录，只列出本机命令：{}", failure.message)),
                ),
            }
        }
        _ => (
            builtins,
            Some("还没有登录，只列出本机命令。先运行 cvgen login --base 服务地址，登录后能看到全部命令。".to_string()),
        ),
    };
    print!("{}", catalog::global_help(&commands, note.as_deref(), &dir));
    Ok(())
}
