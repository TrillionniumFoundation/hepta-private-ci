use super::PersistedResumeSettings;
use crate::config_manager::ConfigManager;
use codex_core::config::Config;
use codex_core::config::ConfigOverrides;
use codex_protocol::models::ActivePermissionProfile;
use codex_protocol::models::PermissionProfile;
use codex_protocol::protocol::EventMsg;
use codex_rollout::RolloutItem;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::PathBuf;

type RuntimeEnvironment = (AbsolutePathBuf, Vec<AbsolutePathBuf>);

/// Runtime context from a previous turn is reusable only under the permission
/// selection and policy that produced it. Current configuration remains the
/// authority for resolving named profiles and their default workspace roots.
pub(super) struct PersistedResumeRuntime {
    environment: Option<RuntimeEnvironment>,
    restored_workspace_roots: bool,
    active_permission_profile: Option<ActivePermissionProfile>,
    permission_profile: Option<PermissionProfile>,
}

impl PersistedResumeRuntime {
    pub(super) fn apply(
        settings: &PersistedResumeSettings,
        history: &[RolloutItem],
        request_overrides: Option<&HashMap<String, serde_json::Value>>,
        typesafe_overrides: &mut ConfigOverrides,
    ) -> Self {
        let explicit_cwd = typesafe_overrides.cwd.is_some()
            || request_overrides.is_some_and(|overrides| overrides.contains_key("cwd"));
        let explicit_roots = typesafe_overrides.workspace_roots.is_some()
            || request_overrides.is_some_and(|overrides| overrides.contains_key("workspace_roots"));
        let environment = if explicit_cwd || explicit_roots {
            None
        } else {
            settings
                .runtime_cwd
                .clone()
                .zip(settings.runtime_workspace_roots.clone())
        };
        let restored_workspace_roots =
            !explicit_roots && settings.runtime_workspace_roots.is_some();
        if restored_workspace_roots {
            typesafe_overrides.workspace_roots = settings.runtime_workspace_roots.clone();
        }
        let permission_profile = history
            .iter()
            .rev()
            .find_map(|item| match item {
                RolloutItem::TurnContext(context) => Some(context.permission_profile.clone()),
                RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) => {
                    Some(Some(event.thread_settings.permission_profile.clone()))
                }
                _ => None,
            })
            .flatten();
        Self {
            environment,
            restored_workspace_roots,
            active_permission_profile: settings.active_permission_profile.clone(),
            permission_profile,
        }
    }

    fn matches_permissions(&self, config: &Config) -> bool {
        self.active_permission_profile == config.permissions.active_permission_profile()
            && self.permission_profile.as_ref().is_none_or(|previous| {
                previous == config.permissions.permission_profile()
                    || previous == &config.permissions.effective_permission_profile()
            })
    }
}

pub(super) async fn load_config_for_resume(
    manager: &ConfigManager,
    request_overrides: Option<HashMap<String, serde_json::Value>>,
    mut typesafe_overrides: ConfigOverrides,
    history_cwd: Option<PathBuf>,
    mut persisted_runtime: Option<PersistedResumeRuntime>,
) -> std::io::Result<(Config, Option<RuntimeEnvironment>)> {
    let mut config = manager
        .load_for_cwd(
            request_overrides.clone(),
            typesafe_overrides.clone(),
            history_cwd.clone(),
        )
        .await?;
    if let Some(runtime) = persisted_runtime.as_mut()
        && !runtime.matches_permissions(&config)
    {
        // Never overwrite an explicit request. Only undo roots inherited from
        // the old turn, and ask the normal loader to recompute current profile
        // defaults and constraints instead of editing its resolved permissions.
        runtime.environment = None;
        if runtime.restored_workspace_roots {
            typesafe_overrides.workspace_roots = None;
            config = manager
                .load_for_cwd(request_overrides, typesafe_overrides, history_cwd)
                .await?;
        }
    }
    Ok((
        config,
        persisted_runtime.and_then(|runtime| runtime.environment),
    ))
}
