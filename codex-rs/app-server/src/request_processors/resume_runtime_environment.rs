use super::PersistedResumeSettings;
use crate::config_manager::ConfigManager;
use codex_core::config::Config;
use codex_core::config::ConfigOverrides;
use codex_protocol::models::ActivePermissionProfile;
use codex_protocol::models::PermissionProfile;
use codex_protocol::protocol::TurnContextEnvironmentItem;
use codex_rollout::RolloutItem;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::PathBuf;

pub(super) enum RuntimeEnvironment {
    Legacy(AbsolutePathBuf, Vec<AbsolutePathBuf>),
    Native {
        environments: Vec<TurnContextEnvironmentItem>,
        rebuild_roots: bool,
    },
}

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
                .runtime_environments
                .clone()
                .map(|environments| RuntimeEnvironment::Native {
                    environments,
                    rebuild_roots: false,
                })
                .or_else(|| {
                    settings
                        .runtime_cwd
                        .clone()
                        .zip(settings.runtime_workspace_roots.clone())
                        .map(|(cwd, roots)| RuntimeEnvironment::Legacy(cwd, roots))
                })
        };
        let restored_workspace_roots =
            !explicit_roots && settings.runtime_workspace_roots.is_some();
        if restored_workspace_roots {
            typesafe_overrides.workspace_roots = settings.runtime_workspace_roots.clone();
        }
        // The inherited roots and native attachments belong to the most recent
        // TurnContext, not to any later ThreadSettingsApplied event. Use the
        // producer's permission identity for the reuse check; the current
        // Config remains the authority for permission enforcement.
        let (active_permission_profile, permission_profile) = history
            .iter()
            .rev()
            .find_map(|item| match item {
                RolloutItem::TurnContext(context) => Some((
                    context.active_permission_profile.clone(),
                    context.permission_profile.clone(),
                )),
                _ => None,
            })
            .unwrap_or((None, None));
        Self {
            environment,
            restored_workspace_roots,
            active_permission_profile,
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
        if matches!(
            runtime.environment.as_ref(),
            Some(RuntimeEnvironment::Legacy(..))
        ) {
            runtime.environment = None;
        }
        if runtime.restored_workspace_roots {
            typesafe_overrides.workspace_roots = None;
            config = manager
                .load_for_cwd(request_overrides, typesafe_overrides, history_cwd)
                .await?;
        }
        if let Some(RuntimeEnvironment::Native { rebuild_roots, .. }) = runtime.environment.as_mut()
        {
            *rebuild_roots = true;
        }
    }
    Ok((
        config,
        persisted_runtime.and_then(|runtime| runtime.environment),
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::request_processors::persisted_resume_settings::latest_persisted_resume_settings;
    use codex_protocol::config_types::ApprovalsReviewer;
    use codex_protocol::config_types::CollaborationMode;
    use codex_protocol::config_types::ModeKind;
    use codex_protocol::config_types::Settings;
    use codex_protocol::protocol::AskForApproval;
    use codex_protocol::protocol::EventMsg;
    use codex_protocol::protocol::SandboxPolicy;
    use codex_protocol::protocol::ThreadSettingsAppliedEvent;
    use codex_protocol::protocol::ThreadSettingsSnapshot;
    use codex_protocol::protocol::TurnContextItem;
    use pretty_assertions::assert_eq;

    fn root(name: &str) -> AbsolutePathBuf {
        AbsolutePathBuf::try_from(std::env::current_dir().expect("current directory").join(name))
            .expect("absolute workspace root")
    }

    fn turn(
        id: &str,
        roots: Vec<AbsolutePathBuf>,
        active: ActivePermissionProfile,
        permission: PermissionProfile,
    ) -> RolloutItem {
        RolloutItem::TurnContext(TurnContextItem {
            turn_id: Some(id.to_string()),
            cwd: root("current"),
            workspace_roots: Some(roots),
            environments: None,
            current_date: None,
            timezone: None,
            approval_policy: AskForApproval::Never,
            approvals_reviewer: None,
            sandbox_policy: SandboxPolicy::new_read_only_policy(),
            permission_profile: Some(permission),
            active_permission_profile: Some(active),
            network: None,
            file_system_sandbox_policy: None,
            model: "gpt-5".to_string(),
            comp_hash: None,
            personality: None,
            collaboration_mode: None,
            multi_agent_version: None,
            multi_agent_mode: None,
            realtime_active: None,
            effort: None,
            summary: codex_protocol::config_types::ReasoningSummary::Auto,
        })
    }

    fn settings_only(active: ActivePermissionProfile) -> RolloutItem {
        RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(ThreadSettingsAppliedEvent {
            thread_settings: ThreadSettingsSnapshot {
                model: "gpt-5".to_string(),
                model_provider_id: "openai".to_string(),
                service_tier: None,
                approval_policy: AskForApproval::OnRequest,
                approvals_reviewer: ApprovalsReviewer::User,
                permission_profile: PermissionProfile::read_only(),
                active_permission_profile: Some(active),
                cwd: root("current"),
                reasoning_effort: None,
                reasoning_summary: None,
                personality: None,
                collaboration_mode: CollaborationMode {
                    mode: ModeKind::Default,
                    settings: Settings {
                        model: "gpt-5".to_string(),
                        reasoning_effort: None,
                        developer_instructions: None,
                    },
                },
            },
        }))
    }

    #[test]
    fn settings_only_change_does_not_relabel_inherited_legacy_roots() {
        let old_roots = vec![root("old-root")];
        let history = vec![
            turn(
                "first",
                old_roots.clone(),
                ActivePermissionProfile::new("dev"),
                PermissionProfile::workspace_write(),
            ),
            settings_only(ActivePermissionProfile::read_only()),
        ];
        let settings = latest_persisted_resume_settings(&history).expect("persisted settings");
        assert_eq!(
            settings.active_permission_profile,
            Some(ActivePermissionProfile::read_only())
        );
        let mut overrides = ConfigOverrides::default();
        let source = PersistedResumeRuntime::apply(&settings, &history, None, &mut overrides);
        assert_eq!(
            source.active_permission_profile,
            Some(ActivePermissionProfile::new("dev"))
        );
        assert_eq!(
            source.permission_profile,
            Some(PermissionProfile::workspace_write())
        );
        assert_eq!(overrides.workspace_roots, Some(old_roots.clone()));
        let Some(RuntimeEnvironment::Legacy(_, roots)) = source.environment else {
            panic!("legacy roots should be retained until current-policy comparison");
        };
        assert_eq!(roots, old_roots);
    }

    #[test]
    fn later_turn_context_rebinds_native_runtime_to_its_own_permission_identity() {
        let mut later = turn(
            "second",
            vec![root("new-root")],
            ActivePermissionProfile::read_only(),
            PermissionProfile::read_only(),
        );
        let RolloutItem::TurnContext(context) = &mut later else {
            panic!("turn context fixture");
        };
        context.environments = Some(vec![TurnContextEnvironmentItem {
            environment_id: "remote".to_string(),
            cwd: r"C:\work".to_string(),
            workspace_roots: vec![r"C:\work".to_string()],
        }]);
        let history = vec![
            turn(
                "first",
                vec![root("old-root")],
                ActivePermissionProfile::new("dev"),
                PermissionProfile::workspace_write(),
            ),
            settings_only(ActivePermissionProfile::new("dev")),
            later,
        ];
        let settings = latest_persisted_resume_settings(&history).expect("persisted settings");
        let mut overrides = ConfigOverrides::default();
        let source = PersistedResumeRuntime::apply(&settings, &history, None, &mut overrides);
        assert_eq!(
            source.active_permission_profile,
            Some(ActivePermissionProfile::read_only())
        );
        assert_eq!(source.permission_profile, Some(PermissionProfile::read_only()));
        assert_eq!(overrides.workspace_roots, Some(vec![root("new-root")]));
        let Some(RuntimeEnvironment::Native {
            environments,
            rebuild_roots,
        }) = source.environment else {
            panic!("latest native environment should remain available for current-policy check");
        };
        assert_eq!(environments.len(), 1);
        assert!(!rebuild_roots);
    }

    #[test]
    fn explicit_roots_override_never_restores_older_roots() {
        let history = vec![
            turn(
                "first",
                vec![root("old-root")],
                ActivePermissionProfile::new("dev"),
                PermissionProfile::workspace_write(),
            ),
            settings_only(ActivePermissionProfile::read_only()),
        ];
        let settings = latest_persisted_resume_settings(&history).expect("persisted settings");
        let requested_roots = vec![root("request-root")];
        let mut overrides = ConfigOverrides {
            workspace_roots: Some(requested_roots.clone()),
            ..ConfigOverrides::default()
        };
        let source = PersistedResumeRuntime::apply(&settings, &history, None, &mut overrides);
        assert!(source.environment.is_none());
        assert!(!source.restored_workspace_roots);
        assert_eq!(overrides.workspace_roots, Some(requested_roots));
    }
}
