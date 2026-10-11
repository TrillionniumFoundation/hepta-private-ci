//! Handles persistent thread-settings updates shared by standalone settings
//! submissions and turn-input submission.

use super::session::Session;
use super::session::SessionSettingsUpdate;
use crate::config::ConstraintResult;
use codex_features::Feature;
use codex_protocol::protocol::CodexErrorInfo;
use codex_protocol::protocol::ErrorEvent;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::ThreadSettingsAppliedEvent;
use codex_protocol::protocol::ThreadSettingsOverrides;
use std::sync::Arc;

/// Applies standalone thread settings and reports invalid overrides through the
/// normal event stream.
pub(super) async fn update(
    session: &Arc<Session>,
    submission_id: String,
    overrides: ThreadSettingsOverrides,
) {
    let updates = prepare_update(session, overrides).await;
    if let Err(error) = apply_standalone_update(session, submission_id.clone(), updates).await {
        session
            .send_event_raw(Event {
                id: submission_id,
                msg: EventMsg::Error(ErrorEvent {
                    message: format!("failed to apply thread settings override: {error}"),
                    codex_error_info: Some(CodexErrorInfo::BadRequest),
                }),
            })
            .await;
    }
}

/// Serializes a standalone settings mutation with recovery publication. A
/// cold resume rebuilds its turn context from the current thread settings, so
/// changing those settings must first invalidate any Ready/Confirmed request
/// that was built under the previous authority snapshot.
#[expect(
    clippy::await_holding_invalid_type,
    reason = "active turn, recovery revoke, and settings mutation must remain atomic"
)]
async fn apply_standalone_update(
    session: &Session,
    submission_id: String,
    updates: SessionSettingsUpdate,
) -> Result<(), String> {
    if !session.enabled(Feature::HeptaTurnRecovery) {
        let active = session.active_turn.lock().await;
        if session.shutdown_started()
            || session.has_pending_task_terminalization()
            || active
                .as_ref()
                .is_some_and(|active_turn| active_turn.task_terminalization.is_some())
        {
            return Err(
                "turn is terminalizing and cannot accept a standalone settings update".to_string(),
            );
        }
        let result = apply_update(session, submission_id, updates)
            .await
            .map_err(|error| error.to_string());
        drop(active);
        return result;
    }

    session
        .preview_settings(&updates)
        .await
        .map_err(|error| error.to_string())?;

    let active = session.active_turn.lock().await;
    if session.shutdown_started() || session.has_pending_task_terminalization() {
        return Err(
            "turn is terminalizing and cannot accept a standalone settings update".to_string(),
        );
    }
    if active.as_ref().is_some_and(|active_turn| {
        active_turn.task_terminalization.is_some() || active_turn.task.is_none()
    }) {
        return Err(
            "turn is transitioning and cannot accept a standalone settings update".to_string(),
        );
    }
    let consumed_recovery = if let Some(task) = active
        .as_ref()
        .and_then(|active_turn| active_turn.task.as_ref())
        && let Some(authority) = task.recovery_authority.as_ref()
    {
        session
            .ensure_turn_recovery_unready(&task.turn_context.sub_id, authority.as_ref())
            .await
            .map_err(|error| error.to_string())?;
        false
    } else if active.is_none() {
        session
            .consume_recovery_candidate_for_mutation()
            .await
            .map_err(|error| error.to_string())?
    } else {
        false
    };

    let result = session
        .update_settings(updates)
        .await
        .map_err(|error| error.to_string());
    if consumed_recovery {
        session.settle_consumed_recovery_status();
    }
    drop(active);
    result?;
    emit_applied(session, submission_id).await;
    Ok(())
}

/// Converts protocol overrides into the internal settings update shape.
pub(super) async fn prepare_update(
    session: &Session,
    overrides: ThreadSettingsOverrides,
) -> SessionSettingsUpdate {
    let ThreadSettingsOverrides {
        environments,
        profile_workspace_roots,
        approval_policy,
        approvals_reviewer,
        sandbox_policy,
        permission_profile,
        active_permission_profile,
        windows_sandbox_level,
        model,
        effort,
        summary,
        service_tier,
        collaboration_mode,
        personality,
    } = overrides;
    let collaboration_mode = match collaboration_mode {
        Some(collaboration_mode) => collaboration_mode,
        None => {
            let state = session.state.lock().await;
            // Model and reasoning effort live in CollaborationMode settings today, so
            // partial thread-settings updates refresh those fields on the active mode.
            state
                .session_configuration
                .collaboration_mode
                .with_updates(model, effort, /*developer_instructions*/ None)
        }
    };
    SessionSettingsUpdate {
        environments,
        profile_workspace_roots,
        approval_policy,
        approvals_reviewer,
        sandbox_policy,
        permission_profile,
        active_permission_profile,
        windows_sandbox_level,
        collaboration_mode: Some(collaboration_mode),
        reasoning_summary: summary,
        service_tier,
        personality,
        ..Default::default()
    }
}

/// Applies persistent settings and emits the resulting thread-owned snapshot.
pub(super) async fn apply_update(
    session: &Session,
    submission_id: String,
    updates: SessionSettingsUpdate,
) -> ConstraintResult<()> {
    session.update_settings(updates).await?;
    emit_applied(session, submission_id).await;
    Ok(())
}

/// Emits the thread-owned settings after a successful update.
pub(super) async fn emit_applied(session: &Session, submission_id: String) {
    let msg = applied_event(session).await;
    session
        .send_event_raw_without_materializing_rollout(Event {
            id: submission_id,
            msg,
        })
        .await;
}

/// Builds the thread-owned settings event used by live updates and
/// synthesized fork history.
pub(super) async fn applied_event(session: &Session) -> EventMsg {
    EventMsg::ThreadSettingsApplied(ThreadSettingsAppliedEvent {
        thread_settings: session.thread_settings_snapshot().await,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::session::session::RecoveryCandidate;
    use crate::session::tests::attach_in_memory_thread_store;
    use crate::session::tests::make_session_and_context_with_rx;
    use crate::state::ActiveTurn;
    use codex_history::RolloutItem;
    use codex_protocol::protocol::AgentStatus;
    use codex_protocol::protocol::TurnRecoveryCandidateState;
    use std::sync::Arc;
    use std::sync::atomic::Ordering;
    use tokio::time::Duration;
    use tokio::time::timeout;

    #[tokio::test]
    async fn standalone_update_rejects_taskless_transition_reservation() {
        let (mut session, _turn_context, rx) = make_session_and_context_with_rx().await;
        Arc::get_mut(&mut session)
            .expect("fresh session should be uniquely owned")
            .features
            .enable(Feature::HeptaTurnRecovery)
            .expect("enable recovery for settings test");
        *session.active_turn.lock().await = Some(ActiveTurn::default());
        let model_before = session.thread_config_snapshot().await.model;

        update(
            &session,
            "settings-during-transition".to_string(),
            ThreadSettingsOverrides {
                model: Some("gpt-5.5".to_string()),
                ..Default::default()
            },
        )
        .await;

        assert_eq!(session.thread_config_snapshot().await.model, model_before);
        let event = timeout(Duration::from_secs(2), async {
            loop {
                let event = rx.recv().await.expect("settings result event");
                if event.id == "settings-during-transition" {
                    return event;
                }
            }
        })
        .await
        .expect("settings rejection should be observable");
        assert!(matches!(
            event.msg,
            EventMsg::Error(ErrorEvent { message, .. })
                if message.contains("turn is transitioning")
        ));
    }

    #[tokio::test]
    async fn standalone_update_consumes_idle_recovery_before_apply() {
        let (mut session, _turn_context, _rx) = make_session_and_context_with_rx().await;
        let session_mut = Arc::get_mut(&mut session).expect("fresh session should be unique");
        session_mut
            .features
            .enable(Feature::HeptaTurnRecovery)
            .expect("enable recovery for settings test");
        attach_in_memory_thread_store(session_mut).await;
        let turn_id = "interrupted-settings-candidate".to_string();
        let marker_generation = 7;
        let epoch = session.turn_epoch.load(Ordering::Acquire);
        let history_boundary = session
            .current_recovery_history_boundary()
            .await
            .expect("history boundary");
        *session
            .recovery_candidate
            .lock()
            .expect("recovery candidate mutex poisoned") = Some(RecoveryCandidate {
            turn_id: turn_id.clone(),
            marker_generation,
            epoch,
            persistence_failure_generation: session.rollout_persistence_failure_generation(),
            request_fingerprint_sha256: "thread-settings-test-request-fingerprint".to_string(),
            replay: codex_history::TurnRecoveryReplayV1 {
                history_boundary,
                turn_context_sha256: "thread-settings-test-context".to_string(),
                start: codex_history::TurnRecoveryStartState {
                    final_output_json_schema: None,
                    parent_turn_id: None,
                    root_turn_id: Some(turn_id.clone()),
                    responses_metadata_extra: Default::default(),
                },
                environments: Vec::new(),
            },
        });
        session.agent_status.send_replace(AgentStatus::Interrupted);

        update(
            &session,
            "settings-after-interrupt".to_string(),
            ThreadSettingsOverrides {
                model: Some("gpt-5.5".to_string()),
                ..Default::default()
            },
        )
        .await;

        assert_eq!(session.thread_config_snapshot().await.model, "gpt-5.5");
        assert!(
            session
                .recovery_candidate
                .lock()
                .expect("recovery candidate mutex poisoned")
                .is_none()
        );
        assert_eq!(
            *session.agent_status.borrow(),
            AgentStatus::Completed(/*last_agent_message*/ None)
        );
        let persisted = session
            .live_thread()
            .expect("test session has persistence")
            .load_history(/*include_archived*/ true)
            .await
            .expect("load settings recovery reset");
        assert!(persisted.items.iter().any(|item| {
            matches!(
                item,
                RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                    if marker.turn_id == turn_id
                        && marker.generation == marker_generation + 1
                        && marker.state == TurnRecoveryCandidateState::Unready
            )
        }));
    }
}
