use super::PersistedResumeRuntime;
use super::RuntimeEnvironment;
use crate::request_processors::persisted_resume_settings::latest_persisted_resume_settings;
use codex_core::config::ConfigOverrides;
use codex_protocol::config_types::ApprovalsReviewer;
use codex_protocol::config_types::CollaborationMode;
use codex_protocol::config_types::ModeKind;
use codex_protocol::config_types::Settings;
use codex_protocol::models::ActivePermissionProfile;
use codex_protocol::models::PermissionProfile;
use codex_protocol::protocol::AskForApproval;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::SandboxPolicy;
use codex_protocol::protocol::ThreadSettingsAppliedEvent;
use codex_protocol::protocol::ThreadSettingsSnapshot;
use codex_protocol::protocol::TurnContextItem;
use codex_rollout::RolloutItem;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;

fn root(name: &str) -> AbsolutePathBuf {
    AbsolutePathBuf::try_from(
        std::env::current_dir().expect("current directory").join(name),
    )
    .expect("absolute root")
}

fn old_turn() -> RolloutItem {
    RolloutItem::TurnContext(TurnContextItem {
        turn_id: Some("source".to_string()),
        cwd: root("cwd"),
        workspace_roots: Some(vec![root("old-root")]),
        environments: None,
        current_date: None,
        timezone: None,
        approval_policy: AskForApproval::Never,
        approvals_reviewer: None,
        sandbox_policy: SandboxPolicy::new_workspace_write_policy(),
        permission_profile: Some(PermissionProfile::workspace_write()),
        active_permission_profile: Some(ActivePermissionProfile::new("dev")),
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

fn new_settings() -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(
        ThreadSettingsAppliedEvent {
            thread_settings: ThreadSettingsSnapshot {
                model: "gpt-5".to_string(),
                model_provider_id: "openai".to_string(),
                service_tier: None,
                approval_policy: AskForApproval::OnRequest,
                approvals_reviewer: ApprovalsReviewer::User,
                permission_profile: PermissionProfile::read_only(),
                active_permission_profile: Some(ActivePermissionProfile::read_only()),
                cwd: root("cwd"),
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
        },
    ))
}

#[test]
fn settings_only_update_cannot_relabel_persisted_roots() {
    let history = vec![old_turn(), new_settings()];
    let settings = latest_persisted_resume_settings(&history).expect("settings");
    assert_eq!(
        settings.active_permission_profile,
        Some(ActivePermissionProfile::read_only())
    );
    let mut overrides = ConfigOverrides::default();
    let source = PersistedResumeRuntime::apply(
        &settings,
        &history,
        /*request_overrides*/ None,
        &mut overrides,
    );
    assert_eq!(
        source.active_permission_profile,
        Some(ActivePermissionProfile::new("dev"))
    );
    assert_eq!(
        source.permission_profile,
        Some(PermissionProfile::workspace_write())
    );
    assert_eq!(overrides.workspace_roots, Some(vec![root("old-root")]));
    let Some(RuntimeEnvironment::Legacy(_, roots)) = source.environment else {
        panic!("legacy environment expected");
    };
    assert_eq!(roots, vec![root("old-root")]);
}

#[test]
fn latest_turn_rebinds_roots_to_its_permissions() {
    let mut later = old_turn();
    let RolloutItem::TurnContext(context) = &mut later else {
        panic!("turn context expected");
    };
    context.workspace_roots = Some(vec![root("new-root")]);
    context.active_permission_profile = Some(ActivePermissionProfile::read_only());
    context.permission_profile = Some(PermissionProfile::read_only());
    let history = vec![old_turn(), new_settings(), later];
    let settings = latest_persisted_resume_settings(&history).expect("settings");
    let mut overrides = ConfigOverrides::default();
    let source = PersistedResumeRuntime::apply(
        &settings,
        &history,
        /*request_overrides*/ None,
        &mut overrides,
    );
    assert_eq!(
        source.active_permission_profile,
        Some(ActivePermissionProfile::read_only())
    );
    assert_eq!(source.permission_profile, Some(PermissionProfile::read_only()));
    assert_eq!(overrides.workspace_roots, Some(vec![root("new-root")]));
}

#[test]
fn explicit_workspace_roots_override_inherited_roots() {
    let history = vec![old_turn(), new_settings()];
    let settings = latest_persisted_resume_settings(&history).expect("settings");
    let roots = vec![root("request-root")];
    let mut overrides = ConfigOverrides {
        workspace_roots: Some(roots.clone()),
        ..ConfigOverrides::default()
    };
    let source = PersistedResumeRuntime::apply(
        &settings,
        &history,
        /*request_overrides*/ None,
        &mut overrides,
    );
    assert!(source.environment.is_none());
    assert!(!source.restored_workspace_roots);
    assert_eq!(overrides.workspace_roots, Some(roots));
}
