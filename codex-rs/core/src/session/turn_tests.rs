use super::*;
use codex_extension_api::ExtensionData;
use codex_extension_api::TurnItemContributor;
use codex_protocol::ResponseItemId;
use codex_protocol::items::AgentMessageContent;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use tracing_subscriber::prelude::*;

use crate::environment_selection::EnvironmentConfigOrigin;
use crate::environment_selection::ThreadEnvironments;
use crate::environment_selection::TurnEnvironmentState;

#[test]
fn hepta_turn_recovery_blocks_only_pre_turn_auto_compaction() {
    assert!(hepta_turn_recovery_blocks_auto_compact(
        true,
        CompactionPhase::PreTurn,
    ));
    assert!(!hepta_turn_recovery_blocks_auto_compact(
        false,
        CompactionPhase::PreTurn,
    ));
    assert!(!hepta_turn_recovery_blocks_auto_compact(
        true,
        CompactionPhase::MidTurn,
    ));
    assert!(!hepta_turn_recovery_blocks_auto_compact(
        true,
        CompactionPhase::StandaloneTurn,
    ));
}

#[tokio::test]
async fn turn_recovery_checkpoint_accepts_only_nonempty_from_thread_environments() {
    let (_session, turn_context) = crate::session::tests::make_session_and_context().await;
    let primary = turn_context
        .environments
        .primary()
        .expect("ready primary environment")
        .clone();

    let mut first = primary.clone();
    first.selection.environment_id = "thread-environment-b".to_string();
    first.selection.workspace_roots = vec![first.selection.cwd.clone()];
    let mut second = primary.clone();
    second.selection.environment_id = "thread-environment-a".to_string();
    second.selection.workspace_roots = Vec::new();
    let from_thread = TurnEnvironmentSnapshot {
        environments: vec![
            TurnEnvironmentState::Ready(first.clone()),
            TurnEnvironmentState::Ready(second.clone()),
        ],
    };
    let expected = [first, second]
        .into_iter()
        .map(
            |environment| codex_history::TurnRecoveryEnvironmentSelection {
                environment_id: environment.selection.environment_id,
                cwd: environment.selection.cwd.to_string(),
                workspace_roots: environment
                    .selection
                    .workspace_roots
                    .into_iter()
                    .map(|root| root.to_string())
                    .collect(),
            },
        )
        .collect::<Vec<_>>();
    assert_eq!(
        turn_recovery_environment_selections(&from_thread),
        Some(expected)
    );

    let mut owner_ready = primary.clone();
    owner_ready.config_origin = EnvironmentConfigOrigin::Owner;
    assert_eq!(
        turn_recovery_environment_selections(&TurnEnvironmentSnapshot {
            environments: vec![TurnEnvironmentState::Ready(owner_ready)],
        }),
        None
    );

    let thread_environment_config = primary.config().clone();
    let environment_manager = Arc::new(codex_exec_server::EnvironmentManager::default_for_tests());
    let mut owner_pending_selection = primary.selection();
    owner_pending_selection.config = EnvironmentConfigState::Pending;
    let owner_pending = ThreadEnvironments::new(
        Arc::clone(&environment_manager),
        crate::shell::default_user_shell(),
        thread_environment_config.clone(),
        crate::shell_snapshot::ShellSnapshot::disabled(),
        TurnEnvironmentSnapshot::default(),
        /*non_blocking_snapshots*/ true,
    );
    owner_pending.update_selections(
        std::slice::from_ref(&owner_pending_selection),
        &thread_environment_config,
    );
    let owner_pending = owner_pending.snapshot().await;
    assert!(owner_pending.starting().next().is_some());
    assert_eq!(turn_recovery_environment_selections(&owner_pending), None);

    let mut owner_failed_selection = primary.selection();
    owner_failed_selection.config = EnvironmentConfigState::Failed("owner failed".to_string());
    let owner_failed = ThreadEnvironments::new(
        environment_manager,
        crate::shell::default_user_shell(),
        thread_environment_config.clone(),
        crate::shell_snapshot::ShellSnapshot::disabled(),
        TurnEnvironmentSnapshot::default(),
        /*non_blocking_snapshots*/ true,
    );
    owner_failed.update_selections(
        std::slice::from_ref(&owner_failed_selection),
        &thread_environment_config,
    );
    let owner_failed = owner_failed.snapshot().await;
    assert!(owner_failed.environments.is_empty());
    assert_eq!(turn_recovery_environment_selections(&owner_failed), None);

    assert_eq!(
        turn_recovery_environment_selections(&TurnEnvironmentSnapshot::default()),
        None
    );
}

struct RewriteAgentMessageContributor;

impl TurnItemContributor for RewriteAgentMessageContributor {
    fn contribute<'a>(
        &'a self,
        _thread_store: &'a ExtensionData,
        _turn_store: &'a ExtensionData,
        item: &'a mut TurnItem,
    ) -> codex_extension_api::ExtensionFuture<'a, Result<(), String>> {
        Box::pin(async move {
            if let TurnItem::AgentMessage(agent_message) = item {
                agent_message.content = vec![AgentMessageContent::Text {
                    text: "plan contributed assistant text".to_string(),
                }];
            }
            Ok(())
        })
    }
}

fn assistant_output_text(text: &str) -> ResponseItem {
    ResponseItem::Message {
        id: Some(ResponseItemId::with_suffix("msg", "1")),
        role: "assistant".to_string(),
        content: vec![ContentItem::OutputText {
            text: text.to_string(),
        }],
        phase: None,
        internal_chat_message_metadata_passthrough: None,
    }
}

#[tokio::test]
async fn post_sampling_token_estimate_is_filtered_from_always_on_sinks() {
    let codex_home = tempfile::tempdir().expect("create isolated state directory");
    let runtime = codex_state::StateRuntime::init(
        codex_state::SqliteConfig::new_for_testing(
            codex_utils_absolute_path::AbsolutePathBuf::try_from(codex_home.path())
                .expect("temporary state directory should be absolute"),
        ),
        "test-provider".to_string(),
    )
    .await
    .expect("initialize isolated state runtime");
    let feedback = codex_feedback::CodexFeedback::new();
    let log_db = codex_state::log_db::start(Arc::clone(&runtime));
    let subscriber = tracing_subscriber::registry()
        .with(feedback.logger_layer())
        .with(
            log_db
                .clone()
                .with_filter(codex_state::log_db::default_filter()),
        );

    tracing::subscriber::with_default(subscriber, || {
        tracing::trace!(
            target: POST_SAMPLING_TOKEN_ESTIMATE_TARGET,
            turn_id = "test-turn",
            estimated_token_count = 42_u64,
            "filtered post sampling token estimate"
        );
        tracing::trace!(
            target: "codex_core::turn_filter_control",
            "retained turn filter control"
        );
    });
    log_db.flush().await;

    let log_rows = runtime
        .query_logs(&codex_state::LogQuery {
            include_threadless: true,
            ..Default::default()
        })
        .await
        .expect("query isolated log database");
    assert!(
        !log_rows
            .iter()
            .any(|row| row.target == POST_SAMPLING_TOKEN_ESTIMATE_TARGET)
    );
    assert!(log_rows.iter().any(|row| {
        row.target == "codex_core::turn_filter_control"
            && row
                .message
                .as_deref()
                .is_some_and(|message| message.contains("retained turn filter control"))
    }));
}

#[tokio::test]
async fn plan_mode_uses_contributed_turn_item_for_last_agent_message() {
    let (mut session, turn_context) = crate::session::tests::make_session_and_context().await;
    let mut builder = codex_extension_api::ExtensionRegistryBuilder::new();
    builder.turn_item_contributor(Arc::new(RewriteAgentMessageContributor));
    session.services.extensions = Arc::new(builder.build());
    let turn_store = ExtensionData::new(turn_context.sub_id.clone());
    let mut state = PlanModeStreamState::new(&turn_context.sub_id);
    let mut last_agent_message = None;
    let item = assistant_output_text("original assistant text");

    let handled = handle_assistant_item_done_in_plan_mode(
        &session,
        &turn_context,
        &turn_store,
        &item,
        &mut state,
        /*previously_active_item*/ None,
        &mut last_agent_message,
    )
    .await;

    assert!(handled);
    assert_eq!(
        last_agent_message.as_deref(),
        Some("plan contributed assistant text")
    );
}
