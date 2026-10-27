use super::PersistedResumeSettings;
use super::latest_persisted_resume_settings;
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

fn cwd() -> AbsolutePathBuf {
    AbsolutePathBuf::try_from(std::env::current_dir().expect("current directory"))
        .expect("absolute current directory")
}

fn workspace_root(name: &str) -> AbsolutePathBuf {
    AbsolutePathBuf::try_from(
        std::env::current_dir()
            .expect("current directory")
            .join(name),
    )
    .expect("absolute workspace root")
}

fn settings_item(
    approval_policy: AskForApproval,
    approvals_reviewer: ApprovalsReviewer,
    active_permission_profile: Option<ActivePermissionProfile>,
) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(
        ThreadSettingsAppliedEvent {
            thread_settings: ThreadSettingsSnapshot {
                model: "gpt-5".to_string(),
                model_provider_id: "openai".to_string(),
                service_tier: None,
                approval_policy,
                approvals_reviewer,
                permission_profile: PermissionProfile::read_only(),
                active_permission_profile,
                cwd: cwd(),
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

fn turn_context_item(
    turn_id: &str,
    approval_policy: AskForApproval,
    approvals_reviewer: Option<ApprovalsReviewer>,
    active_permission_profile: Option<ActivePermissionProfile>,
    workspace_roots: Option<Vec<AbsolutePathBuf>>,
) -> RolloutItem {
    RolloutItem::TurnContext(TurnContextItem {
        turn_id: Some(turn_id.to_string()),
        cwd: cwd(),
        workspace_roots,
        current_date: None,
        timezone: None,
        approval_policy,
        approvals_reviewer,
        sandbox_policy: SandboxPolicy::new_read_only_policy(),
        permission_profile: Some(PermissionProfile::read_only()),
        active_permission_profile,
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

#[test]
fn latest_settings_snapshot_wins() {
    let expected = PersistedResumeSettings {
        approval_policy: AskForApproval::OnRequest,
        approvals_reviewer: Some(ApprovalsReviewer::AutoReview),
        active_permission_profile: Some(ActivePermissionProfile::new("dev")),
        runtime_cwd: None,
        runtime_workspace_roots: None,
        runtime_permission_profile: None,
    };
    let history = vec![
        settings_item(
            AskForApproval::Never,
            ApprovalsReviewer::User,
            /*active_permission_profile*/ None,
        ),
        settings_item(
            AskForApproval::OnRequest,
            ApprovalsReviewer::AutoReview,
            Some(ActivePermissionProfile::new("dev")),
        ),
    ];

    assert_eq!(latest_persisted_resume_settings(&history), Some(expected));
}

#[test]
fn latest_turn_context_wins_over_earlier_settings_update() {
    let expected = PersistedResumeSettings {
        approval_policy: AskForApproval::UnlessTrusted,
        approvals_reviewer: Some(ApprovalsReviewer::User),
        active_permission_profile: Some(ActivePermissionProfile::read_only()),
        runtime_cwd: Some(cwd()),
        runtime_workspace_roots: Some(vec![workspace_root("turn-2-root")]),
        runtime_permission_profile: Some(PermissionProfile::read_only()),
    };
    let history = vec![
        settings_item(
            AskForApproval::Never,
            ApprovalsReviewer::AutoReview,
            Some(ActivePermissionProfile::new("dev")),
        ),
        turn_context_item(
            "turn-2",
            AskForApproval::UnlessTrusted,
            Some(ApprovalsReviewer::User),
            Some(ActivePermissionProfile::read_only()),
            Some(vec![workspace_root("turn-2-root")]),
        ),
    ];

    assert_eq!(latest_persisted_resume_settings(&history), Some(expected));
}

#[test]
fn older_reviewer_is_used_when_latest_turn_context_omits_it() {
    let history = vec![
        turn_context_item(
            "turn-1",
            AskForApproval::Never,
            Some(ApprovalsReviewer::AutoReview),
            /*active_permission_profile*/ None,
            Some(vec![workspace_root("turn-1-root")]),
        ),
        turn_context_item(
            "turn-2",
            AskForApproval::OnRequest,
            /*approvals_reviewer*/ None,
            /*active_permission_profile*/ None,
            Some(vec![workspace_root("turn-2-root")]),
        ),
    ];

    assert_eq!(
        latest_persisted_resume_settings(&history),
        Some(PersistedResumeSettings {
            approval_policy: AskForApproval::OnRequest,
            approvals_reviewer: Some(ApprovalsReviewer::AutoReview),
            active_permission_profile: None,
            runtime_cwd: Some(cwd()),
            runtime_workspace_roots: Some(vec![workspace_root("turn-2-root")]),
            runtime_permission_profile: None,
        })
    );
}

#[test]
fn later_settings_snapshot_does_not_erase_turn_context_workspace_roots() {
    let persisted_root = workspace_root("persisted-root");
    let history = vec![
        turn_context_item(
            "turn-1",
            AskForApproval::Never,
            Some(ApprovalsReviewer::User),
            /*active_permission_profile*/ None,
            Some(vec![persisted_root.clone()]),
        ),
        settings_item(
            AskForApproval::OnRequest,
            ApprovalsReviewer::AutoReview,
            Some(ActivePermissionProfile::new("dev")),
        ),
    ];

    assert_eq!(
        latest_persisted_resume_settings(&history),
        Some(PersistedResumeSettings {
            approval_policy: AskForApproval::OnRequest,
            approvals_reviewer: Some(ApprovalsReviewer::AutoReview),
            active_permission_profile: Some(ActivePermissionProfile::new("dev")),
            runtime_cwd: Some(cwd()),
            runtime_workspace_roots: Some(vec![persisted_root]),
            runtime_permission_profile: None,
        })
    );
}

#[test]
fn latest_turn_context_workspace_roots_win() {
    let latest_root = workspace_root("latest-root");
    let history = vec![
        turn_context_item(
            "turn-1",
            AskForApproval::Never,
            Some(ApprovalsReviewer::User),
            /*active_permission_profile*/ None,
            Some(vec![workspace_root("older-root")]),
        ),
        settings_item(
            AskForApproval::UnlessTrusted,
            ApprovalsReviewer::AutoReview,
            /*active_permission_profile*/ None,
        ),
        turn_context_item(
            "turn-2",
            AskForApproval::OnRequest,
            Some(ApprovalsReviewer::User),
            /*active_permission_profile*/ None,
            Some(vec![latest_root.clone()]),
        ),
    ];

    assert_eq!(
        latest_persisted_resume_settings(&history)
            .expect("persisted settings")
            .runtime_workspace_roots,
        Some(vec![latest_root])
    );
}

#[test]
fn turn_context_without_workspace_roots_restores_explicit_empty_list() {
    let history = vec![turn_context_item(
        "turn-1",
        AskForApproval::Never,
        Some(ApprovalsReviewer::User),
        /*active_permission_profile*/ None,
        /*workspace_roots*/ None,
    )];

    assert_eq!(
        latest_persisted_resume_settings(&history)
            .expect("persisted settings")
            .runtime_workspace_roots,
        Some(Vec::new())
    );
}

#[test]
fn later_settings_do_not_rebind_old_roots_to_a_different_permission_policy() {
    let persisted_root = workspace_root("persisted-root");
    let mut history = vec![
        turn_context_item(
            "turn-1",
            AskForApproval::Never,
            Some(ApprovalsReviewer::User),
            Some(ActivePermissionProfile::new("dev")),
            Some(vec![persisted_root.clone()]),
        ),
        settings_item(
            AskForApproval::OnRequest,
            ApprovalsReviewer::User,
            Some(ActivePermissionProfile::new("dev")),
        ),
    ];
    let RolloutItem::EventMsg(EventMsg::ThreadSettingsApplied(event)) = &mut history[1] else {
        panic!("expected settings snapshot");
    };
    event.thread_settings.permission_profile = PermissionProfile::Disabled;

    assert_eq!(
        latest_persisted_resume_settings(&history),
        Some(PersistedResumeSettings {
            approval_policy: AskForApproval::OnRequest,
            approvals_reviewer: Some(ApprovalsReviewer::User),
            active_permission_profile: Some(ActivePermissionProfile::new("dev")),
            runtime_cwd: Some(cwd()),
            runtime_workspace_roots: Some(vec![persisted_root]),
            runtime_permission_profile: Some(PermissionProfile::read_only()),
        })
    );
}

#[test]
fn legacy_named_turn_context_uses_its_authoritative_permission_projection() {
    let mut item = turn_context_item(
        "legacy-turn",
        AskForApproval::Never,
        Some(ApprovalsReviewer::User),
        Some(ActivePermissionProfile::new("dev")),
        /*workspace_roots*/ None,
    );
    let RolloutItem::TurnContext(context) = &mut item else {
        panic!("expected turn context");
    };
    context.permission_profile = None;
    context.sandbox_policy = SandboxPolicy::DangerFullAccess;

    assert_eq!(
        latest_persisted_resume_settings(&[item])
            .expect("legacy named settings")
            .runtime_permission_profile,
        Some(PermissionProfile::Disabled)
    );
}
