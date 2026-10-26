//! A finite Core execution profile for the original Notes thread. This checks
//! configuration observations; it neither grants authority nor creates tools.
use std::io::Read;
use std::path::Path;

use codex_app_server_client::RemoteAppServerClient;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::ConfigLayerSource;
use codex_app_server_protocol::ConfigReadParams;
use codex_app_server_protocol::ConfigReadResponse;
use codex_app_server_protocol::RequestId;
use codex_config::TomlValue;
use codex_hepta_types::Digest32;
use serde_json::Value;

use crate::AgentdError;
use crate::notes_literal_adapter::invalid;

pub(crate) const PROFILE: &str = "hepta.notes.core-execution.v2";

/// Fixed public configuration to append after root model settings and before
/// provider tables. The original Root Notes adapter remains the effect owner.
pub const ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG: &str = r#"approval_policy = "never"
sandbox_mode = "read-only"
web_search = "disabled"
[agents]
enabled = false
[features]
shell_tool = false
unified_exec = false
view_image = false
multi_agent = false
multi_agent_v2 = false
apps = false
plugins = false
tool_suggest = false
tool_search = false
enable_mcp_apps = false
js_repl = false
code_mode = false
code_mode_host = false
code_mode_only = false
browser_use = false
computer_use = false
image_generation = false
request_permissions_tool = false
deferred_executor = false
token_budget = false
current_time_reminder = false
goals = false
artifact = false
hooks = false
plugin_hooks = false
remote_control = false
[tools.update_plan]
enabled = false
[tools.experimental_request_user_input]
enabled = false
[orchestrator.mcp]
enabled = false
[orchestrator.skills]
enabled = false
"#;

/// Persistently disables execution environments, including after an unused
/// thread is resumed by a different actual App Server process.
pub const ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG: &str =
    "default = \"none\"\ninclude_local = false\n";

pub(crate) struct ExecutionFiles {
    pub config_sha256: String,
    pub environments_sha256: String,
    pub model: String,
    pub model_provider: String,
}

pub(crate) fn inspect(home: &Path) -> Result<ExecutionFiles, AgentdError> {
    let config = read_config(&home.join("config.toml"))?;
    let environments = read_config(&home.join("environments.toml"))?;
    let value = parse(&config)?;
    validate_config(&value)?;
    let model = value
        .get("model")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| invalid("original Notes requires an explicit persistent model"))?;
    let provider = value
        .get("model_provider")
        .and_then(Value::as_str)
        .filter(|value| {
            !value.is_empty()
                && value
                    .bytes()
                    .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
        })
        .ok_or_else(|| invalid("original Notes requires an explicit persistent provider"))?;
    if parse(&environments)? != parse(ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG.as_bytes())? {
        return Err(invalid(
            "original Notes execution environments are not disabled",
        ));
    }
    Ok(ExecutionFiles {
        config_sha256: Digest32::of_bytes(&config).to_string(),
        environments_sha256: Digest32::of_bytes(&environments).to_string(),
        model: model.into(),
        model_provider: provider.into(),
    })
}

fn read_config(path: &Path) -> Result<Vec<u8>, AgentdError> {
    if !std::fs::symlink_metadata(path)?.is_file() || path.canonicalize()? != path {
        return Err(invalid(
            "original Notes execution configuration is not a bounded regular file",
        ));
    }
    let mut options = std::fs::OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    let file = options.open(path)?;
    let before = file.metadata()?;
    if !before.is_file() || before.len() > 65_536 {
        return Err(invalid(
            "original Notes held execution configuration is not a bounded regular file",
        ));
    }
    let mut bytes = Vec::new();
    (&file).take(65_537).read_to_end(&mut bytes)?;
    let after = file.metadata()?;
    if bytes.is_empty()
        || bytes.len() > 65_536
        || before.len() != after.len()
        || before.modified()? != after.modified()?
    {
        return Err(invalid(
            "original Notes execution configuration exceeds its bound",
        ));
    }
    Ok(bytes)
}

fn parse(bytes: &[u8]) -> Result<Value, AgentdError> {
    let text = std::str::from_utf8(bytes)
        .map_err(|_| invalid("original Notes execution configuration is not UTF-8"))?;
    let value: TomlValue = text
        .parse()
        .map(TomlValue::Table)
        .map_err(|_| invalid("original Notes execution configuration is not valid TOML"))?;
    Ok(serde_json::to_value(value)?)
}

fn contains_profile(actual: &Value, expected: &Value) -> bool {
    match expected {
        Value::Object(fields) => fields.iter().all(|(key, value)| {
            actual
                .get(key)
                .is_some_and(|actual| contains_profile(actual, value))
        }),
        _ => actual == expected,
    }
}

fn validate_config(actual: &Value) -> Result<(), AgentdError> {
    let expected = parse(ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG.as_bytes())?;
    if !contains_profile(actual, &expected)
        || actual
            .get("mcp_servers")
            .is_some_and(|servers| !servers.as_object().is_some_and(serde_json::Map::is_empty))
    {
        return Err(invalid(
            "original Notes Core execution profile is not finite",
        ));
    }
    Ok(())
}

pub(crate) async fn verify_effective(
    client: &RemoteAppServerClient,
    home: &Path,
    cwd: &Path,
    request_id: RequestId,
) -> Result<(), AgentdError> {
    let home_value = parse(&read_config(&home.join("config.toml"))?)?;
    let home_config: codex_config::config_toml::ConfigToml =
        serde_json::from_value(home_value.clone())?;
    let provider = home_value
        .get("model_provider")
        .and_then(Value::as_str)
        .ok_or_else(|| invalid("original Notes persistent provider is absent"))?;
    let response: ConfigReadResponse = tokio::time::timeout(
        std::time::Duration::from_secs(10),
        client.request_typed(ClientRequest::ConfigRead {
            request_id,
            params: ConfigReadParams {
                cwd: Some(
                    cwd.to_str()
                        .ok_or_else(|| invalid("original Notes cwd is not UTF-8"))?
                        .into(),
                ),
                include_layers: false,
            },
        }),
    )
    .await
    .map_err(|_| invalid("original Notes effective configuration observation timed out"))?
    .map_err(|_| invalid("original Notes effective configuration observation failed"))?;
    // The public API's ToolsV2 intentionally omits these two settings. Their
    // effective origins must therefore remain the inspected original file,
    // rather than a project/CLI layer, while the file's semantics are checked.
    let mut origin_keys = vec![
        "tools.update_plan.enabled".to_owned(),
        "tools.experimental_request_user_input.enabled".to_owned(),
        "model".to_owned(),
        "model_provider".to_owned(),
    ];
    let mut pending = vec![(
        format!("model_providers.{provider}"),
        home_value
            .get("model_providers")
            .and_then(|providers| providers.get(provider))
            .ok_or_else(|| {
                invalid("original Notes requires its explicit persistent provider definition")
            })?,
    )];
    while let Some((key, value)) = pending.pop() {
        if let Some(fields) = value.as_object() {
            pending.extend(
                fields
                    .iter()
                    .map(|(name, value)| (format!("{key}.{name}"), value)),
            );
        } else {
            origin_keys.push(key);
        }
    }
    for key in origin_keys {
        if !response.origins.get(&key).is_some_and(|origin| {
            matches!(&origin.name, ConfigLayerSource::User { file, .. } if file.as_path() == home.join("config.toml"))
        }) {
            return Err(invalid("original Notes model/provider/utility setting has another configuration origin"));
        }
    }
    let actual = serde_json::to_value(response.config)?;
    let expected_provider = home_config
        .model_providers
        .get(provider)
        .ok_or_else(|| invalid("original Notes normalized persistent provider is absent"))?;
    if actual.get("model") != home_value.get("model")
        || actual.get("model_provider") != home_value.get("model_provider")
        || actual
            .get("model_providers")
            .and_then(|providers| providers.get(provider))
            != Some(&serde_json::to_value(expected_provider)?)
    {
        return Err(invalid(
            "original Notes effective model/provider definition differs from the frozen Core file",
        ));
    }
    let mut expected = parse(ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG.as_bytes())?;
    expected
        .as_object_mut()
        .ok_or_else(|| invalid("original Notes profile is not an object"))?
        .remove("tools");
    if !contains_profile(&actual, &expected)
        || actual
            .get("mcp_servers")
            .is_some_and(|servers| !servers.as_object().is_some_and(serde_json::Map::is_empty))
    {
        return Err(invalid(
            "original Notes effective Core execution profile differs",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "notes_thread_execution_tests.rs"]
mod tests;
