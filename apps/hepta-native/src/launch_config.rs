//! Operator-owned launch configuration; signing keys and domain state stay with
//! their existing owners. Expansion freezes effective options for this process
//! and for its update restart, without copying any secret into an argument.
use crate::error::ShellError;
use serde::Deserialize;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct LaunchConfig {
    endpoint_manifest: PathBuf,
    trusted_keys: PathBuf,
    state_dir: PathBuf,
    #[serde(default)]
    final_use_authority: Option<PathBuf>,
    #[serde(default)]
    updater_helper: Option<PathBuf>,
    #[serde(default)]
    font_file: Option<PathBuf>,
    #[serde(default)]
    allowed_roots: Vec<PathBuf>,
    #[serde(default)]
    allow_clipboard: bool,
    #[serde(default)]
    allow_notifications: bool,
}

pub fn expand_launch_arguments(raw: &[String]) -> Result<Vec<String>, ShellError> {
    let check = raw.iter().any(|arg| arg == "--check-connection");
    let config_path = if raw.is_empty() || raw == ["--check-connection"] {
        Some(default_config_path()?)
    } else if raw.first().is_some_and(|arg| arg == "--config") {
        if raw.len() < 2 || raw.iter().skip(2).any(|arg| arg != "--check-connection") {
            return Err(ShellError::InvalidInput("--config accepts one path and optionally --check-connection; do not mix inline policy overrides".into()));
        }
        Some(PathBuf::from(&raw[1]))
    } else {
        None
    };
    let Some(path) = config_path else {
        return Ok(raw.to_vec());
    };
    let config: LaunchConfig = crate::file_input::read_json_file(&path, 64*1024)
        .map_err(|error|ShellError::InvalidInput(format!("load native launch config {}: {error}; provision signed endpoint/trust inputs and use --config PATH", path.display())))?;
    if config.allowed_roots.len() > 64 {
        return Err(ShellError::InvalidInput(
            "native launch config has too many allowed roots".into(),
        ));
    }
    let mut args = Vec::new();
    let mut push = |name: &str, path: PathBuf| -> Result<(), ShellError> {
        if !path.is_absolute() {
            return Err(ShellError::InvalidInput(format!("{name} must be absolute")));
        }
        args.push(name.to_owned());
        args.push(path.into_os_string().into_string().map_err(|_| {
            ShellError::InvalidInput(format!("{name} must be representable as UTF-8"))
        })?);
        Ok(())
    };
    push("--endpoint-manifest", config.endpoint_manifest)?;
    push("--trusted-keys", config.trusted_keys)?;
    push("--state-dir", config.state_dir)?;
    if let Some(path) = config.final_use_authority {
        push("--final-use-authority", path)?;
    }
    if let Some(path) = config.updater_helper {
        push("--updater-helper", path)?;
    }
    if let Some(path) = config.font_file {
        push("--font-file", path)?;
    }
    for path in config.allowed_roots {
        push("--allow-root", path)?;
    }
    if config.allow_clipboard {
        args.push("--allow-clipboard".into());
    }
    if config.allow_notifications {
        args.push("--allow-notifications".into());
    }
    if check {
        args.push("--check-connection".into());
    }
    Ok(args)
}

fn default_config_path() -> Result<PathBuf, ShellError> {
    #[cfg(windows)]
    let path =
        std::env::var_os("APPDATA").map(|root| PathBuf::from(root).join("HeptaNative/config.json"));
    #[cfg(target_os = "macos")]
    let path = std::env::var_os("HOME").map(|root| {
        PathBuf::from(root).join("Library/Application Support/HeptaNative/config.json")
    });
    #[cfg(not(any(windows, target_os = "macos")))]
    let path = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|root| PathBuf::from(root).join(".config")))
        .map(|root| root.join("hepta-native/config.json"));
    path.ok_or_else(|| {
        ShellError::InvalidInput("no user config directory; pass --config ABSOLUTE_PATH".into())
    })
}
