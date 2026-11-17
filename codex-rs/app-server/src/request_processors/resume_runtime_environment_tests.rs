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
        panic!("legacy roots remain pending current-policy comparison");
    };
    assert_eq!(roots, old_roots);
}

#[test]
fn later_turn_context_rebinds_native_runtime_to_its_permission_identity() {
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
        panic!("latest native environment should undergo current-policy validation");
    };
    assert_eq!(environments.len(), 1);
    assert!(!rebuild_roots);
}

#[test]
fn explicit_roots_override_does_not_restore_old_roots() {
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
