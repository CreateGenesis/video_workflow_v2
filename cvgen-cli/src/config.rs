//! Local state: credentials, the current workspace and work, and the cached catalog.
//!
//! Everything lives in one per-user directory, never in the current directory:
//! Linux/macOS `$XDG_CONFIG_HOME/cvgen` or `~/.config/cvgen`; Windows `%APPDATA%\cvgen` (fallback `%USERPROFILE%\cvgen`).
//! On unix the directory is 0700 and every file 0600, including files that already existed.

use std::ffi::OsString;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};

use crate::error::{Failure, Result};

#[derive(Debug, Clone)]
pub struct Paths {
    pub dir: PathBuf,
}

impl Paths {
    pub fn discover() -> Result<Paths> {
        config_dir(|name| std::env::var_os(name), cfg!(windows))
            .map(|dir| Paths { dir })
            .ok_or_else(|| {
                Failure::usage(if cfg!(windows) {
                    "找不到用户目录（%APPDATA% 和 %USERPROFILE% 都没有设置），无法保存凭证"
                } else {
                    "找不到用户目录（$HOME 没有设置），无法保存凭证"
                })
            })
    }

    pub fn auth(&self) -> PathBuf {
        self.dir.join("auth.json")
    }

    pub fn context(&self) -> PathBuf {
        self.dir.join("context.json")
    }

    pub fn catalog(&self) -> PathBuf {
        self.dir.join("catalog.json")
    }
}

/// Pick the config directory from environment variables; `None` when no user directory is known.
pub fn config_dir(env: impl Fn(&str) -> Option<OsString>, windows: bool) -> Option<PathBuf> {
    let set = |name: &str| env(name).filter(|value| !value.is_empty()).map(PathBuf::from);
    if windows {
        return set("APPDATA").or_else(|| set("USERPROFILE")).map(|dir| dir.join("cvgen"));
    }
    if let Some(dir) = set("XDG_CONFIG_HOME").filter(|dir| dir.is_absolute()) {
        return Some(dir.join("cvgen"));
    }
    set("HOME").map(|home| home.join(".config").join("cvgen"))
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Auth {
    pub base: String,
    pub token: String,
    #[serde(default)]
    pub device_id: String,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Context {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub workspace: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub work: Option<String>,
}

impl Context {
    pub fn get(&self, key: &str) -> Option<&str> {
        match key {
            "workspace" => self.workspace.as_deref(),
            "work" => self.work.as_deref(),
            _ => None,
        }
        .filter(|value| !value.is_empty())
    }
}

pub fn load_auth(paths: &Paths) -> Result<Option<Auth>> {
    Ok(read_json::<Auth>(&paths.auth())?.filter(|auth| !auth.base.is_empty() && !auth.token.is_empty()))
}

pub fn save_auth(paths: &Paths, auth: &Auth) -> Result<()> {
    write_json(&paths.auth(), auth)
}

pub fn load_context(paths: &Paths) -> Result<Context> {
    Ok(read_json(&paths.context())?.unwrap_or_default())
}

pub fn save_context(paths: &Paths, context: &Context) -> Result<()> {
    write_json(&paths.context(), context)
}

pub fn remove(path: &Path) -> Result<bool> {
    match fs::remove_file(path) {
        Ok(()) => Ok(true),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(err) => Err(Failure::usage(format!("无法删除 {}：{err}", path.display()))),
    }
}

pub fn read_json<T: DeserializeOwned>(path: &Path) -> Result<Option<T>> {
    let text = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(err) => return Err(Failure::usage(format!("无法读取 {}：{err}", path.display()))),
    };
    tighten(path);
    serde_json::from_str(&text)
        .map(Some)
        .map_err(|err| Failure::usage(format!("{} 已损坏（{err}），删掉它后重试", path.display())))
}

pub fn write_json<T: Serialize>(path: &Path, value: &T) -> Result<()> {
    let text = serde_json::to_string_pretty(value).map_err(|err| Failure::usage(err.to_string()))?;
    write_private(path, text.as_bytes())
}

/// Write via a temporary file and rename, so a crash never leaves half a credential file.
pub fn write_private(path: &Path, bytes: &[u8]) -> Result<()> {
    let fail = |err: std::io::Error| Failure::usage(format!("无法写入 {}：{err}", path.display()));
    if let Some(parent) = path.parent() {
        create_private_dir(parent).map_err(fail)?;
    }
    let tmp = path.with_extension("tmp");
    let mut options = fs::OpenOptions::new();
    options.write(true).create(true).truncate(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(&tmp).map_err(fail)?;
    tighten(&tmp);
    file.write_all(bytes).map_err(fail)?;
    file.sync_all().ok();
    drop(file);
    fs::rename(&tmp, path).map_err(fail)?;
    tighten(path);
    Ok(())
}

fn create_private_dir(dir: &Path) -> std::io::Result<()> {
    if dir.is_dir() {
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Ok(meta) = fs::metadata(dir) {
                if meta.permissions().mode() & 0o077 != 0 {
                    let _ = fs::set_permissions(dir, fs::Permissions::from_mode(0o700));
                }
            }
        }
        return Ok(());
    }
    let mut builder = fs::DirBuilder::new();
    builder.recursive(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    builder.create(dir)
}

/// Make an existing file owner-only (unix). Best effort.
pub fn tighten(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(path) {
            if meta.permissions().mode() & 0o077 != 0 {
                let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
            }
        }
    }
    #[cfg(not(unix))]
    let _ = path;
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn env(pairs: &[(&str, &str)]) -> impl Fn(&str) -> Option<OsString> {
        let map: HashMap<String, OsString> = pairs.iter().map(|(k, v)| (k.to_string(), OsString::from(v))).collect();
        move |name| map.get(name).cloned()
    }

    #[test]
    fn unix_config_dir_prefers_xdg_then_home() {
        let dir = config_dir(env(&[("XDG_CONFIG_HOME", "/x/cfg"), ("HOME", "/home/a")]), false).unwrap();
        assert_eq!(dir, PathBuf::from("/x/cfg").join("cvgen"));
        let dir = config_dir(env(&[("XDG_CONFIG_HOME", "relative"), ("HOME", "/home/a")]), false).unwrap();
        assert_eq!(dir, PathBuf::from("/home/a").join(".config").join("cvgen"));
        assert_eq!(config_dir(env(&[]), false), None);
    }

    #[test]
    fn windows_config_dir_uses_appdata_then_userprofile() {
        let dir = config_dir(env(&[("APPDATA", r"C:\Users\a\AppData\Roaming"), ("HOME", "/ignored")]), true).unwrap();
        assert_eq!(dir, PathBuf::from(r"C:\Users\a\AppData\Roaming").join("cvgen"));
        let dir = config_dir(env(&[("USERPROFILE", r"C:\Users\a")]), true).unwrap();
        assert_eq!(dir, PathBuf::from(r"C:\Users\a").join("cvgen"));
        assert_eq!(config_dir(env(&[("HOME", "/home/a")]), true), None);
    }

    #[test]
    fn context_round_trip() {
        let dir = std::env::temp_dir().join(format!("cvgen-ctx-{}", std::process::id()));
        let paths = Paths { dir: dir.clone() };
        assert_eq!(load_context(&paths).unwrap(), Context::default());
        let ctx = Context { workspace: Some("ws_1".into()), work: Some("work_1".into()) };
        save_context(&paths, &ctx).unwrap();
        assert_eq!(load_context(&paths).unwrap(), ctx);
        assert_eq!(load_context(&paths).unwrap().get("work"), Some("work_1"));
        let _ = fs::remove_dir_all(dir);
    }

    #[cfg(unix)]
    #[test]
    fn files_are_owner_only_even_when_they_existed() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!("cvgen-perm-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        let paths = Paths { dir: dir.join("cvgen") };
        fs::create_dir_all(&paths.dir).unwrap();
        fs::write(paths.auth(), "{}").unwrap();
        fs::set_permissions(paths.auth(), fs::Permissions::from_mode(0o644)).unwrap();
        save_auth(&paths, &Auth { base: "http://x".into(), token: "t".into(), device_id: "d".into() }).unwrap();
        assert_eq!(fs::metadata(paths.auth()).unwrap().permissions().mode() & 0o777, 0o600);
        fs::set_permissions(paths.auth(), fs::Permissions::from_mode(0o644)).unwrap();
        assert!(load_auth(&paths).unwrap().is_some());
        assert_eq!(fs::metadata(paths.auth()).unwrap().permissions().mode() & 0o777, 0o600);
        let _ = fs::remove_dir_all(dir);
    }
}
