//! Handles reply-bearing turn-input operations.
//!
//! This is the one place Core decides whether submitted input starts a turn,
//! steers an active turn, or is rejected. It replies after that decision; it
//! does not wait for user-prompt hooks, updating the in-memory model context,
//! rollout persistence, or sampling.
//!
//! Persistent thread settings apply on Started and Steered. Turn start
//! options only apply on Started.

use super::TurnInput;
use super::session::Session;
use super::session::SessionSettingsUpdate;
use super::thread_settings;
use super::turn::TurnRunOrigin;
use super::turn_context::TurnContext;
use crate::state::ActiveTurn;
use crate::state::StartReservationHandle;
use crate::state::TurnState;
use crate::tasks::MailboxParentProvenance;
use crate::tasks::RecoveryHistoryTransition;
use crate::tasks::RegularTask;
use crate::tasks::StartReservationOwner;
use crate::tasks::StartReservationRelease;
use crate::tasks::StartTaskOutcome;
use codex_features::Feature;
use codex_protocol::config_types::ModeKind;
use codex_protocol::error::CodexErr;
use codex_protocol::error::Result as CodexResult;
use codex_protocol::protocol::AdditionalContextEntry;
use codex_protocol::protocol::CodexErrorInfo;
use codex_protocol::protocol::ErrorEvent;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::NonSteerableTurnKind;
use codex_protocol::protocol::ThreadSettingsOverrides;
use codex_protocol::protocol::TurnContextItem;
use codex_protocol::turn_input::NotSubmittedReason;
use codex_protocol::turn_input::TurnInput as SubmittedTurnInput;
use codex_protocol::turn_input::TurnInputMode;
use codex_protocol::turn_input::TurnInputRequest;
use codex_protocol::turn_input::TurnInputSubmission;
use codex_protocol::turn_input::TurnStartOptions;
use codex_protocol::user_input::UserInput;
use serde_json::Value;
use std::collections::BTreeMap;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use uuid::Uuid;

/// Releases a caller-owned start reservation after a pre-context failure.
/// The release is identity-fenced; both the ordinary cleanup path and an
/// accepted pre-context abort must settle a consumed recovery candidate.
async fn release_start_reservation_after_error(
    session: &Arc<Session>,
    handle: &StartReservationHandle,
) -> StartReservationRelease {
    let release = session.release_start_reservation_if_current(handle).await;
    if !matches!(release, StartReservationRelease::Stale) {
        session.settle_consumed_recovery_status();
    }
    release
}

/// Performs the final caller-reservation admission check after the async
/// recovery preamble. The active-turn lock is already held by both callers;
/// taking the short synchronous gate second makes the shutdown/fence check
/// and `reserve_start` one publication window without changing lock order.
#[expect(
    clippy::expect_used,
    reason = "the reservation invariant is established under the admission and active-turn fences"
)]
fn reserve_start_after_admission(
    session: &Session,
    active_turn: &mut Option<ActiveTurn>,
    turn_id: String,
    consumed_recovery: bool,
) -> Option<StartReservationHandle> {
    let admission_gate = session
        .start_admission_gate
        .lock()
        .expect("start admission gate mutex poisoned");
    if session.shutdown_started() || session.has_pending_admission_fence() {
        drop(admission_gate);
        if consumed_recovery {
            session.settle_consumed_recovery_status();
        }
        return None;
    }
    let active_turn = active_turn.get_or_insert_with(ActiveTurn::default);
    let start_reservation = active_turn
        .reserve_start(turn_id)
        .expect("idle slot should accept one start reservation");
    drop(admission_gate);
    Some(start_reservation)
}

#[cfg(test)]
#[path = "turn_input_tests.rs"]
mod tests;

/// Thread settings and start-only options prepared before Core knows whether
/// turn input starts or steers.
///
/// Thread settings are validated up front but only applied after Core accepts
/// the input. Start-only options are only consumed by `apply_started`.
struct PreparedTurnInputSettings {
    thread_settings_update: Option<SessionSettingsUpdate>,
    start_options: TurnStartOptions,
}

impl PreparedTurnInputSettings {
    /// Validates turn-input settings without applying them so rejected input
    /// leaves the thread unchanged.
    async fn prepare(
        session: &Session,
        thread_settings: ThreadSettingsOverrides,
        start_options: TurnStartOptions,
    ) -> CodexResult<Self> {
        let thread_settings_update = if thread_settings == ThreadSettingsOverrides::default() {
            None
        } else {
            let updates = thread_settings::prepare_update(session, thread_settings).await;
            session
                .preview_settings(&updates)
                .await
                .map_err(|error| CodexErr::InvalidRequest(error.to_string()))?;
            Some(updates)
        };
        Ok(Self {
            thread_settings_update,
            start_options,
        })
    }

    fn required_active_final_output_json_schema(&self) -> Option<&Value> {
        self.start_options.final_output_json_schema.as_ref()
    }

    fn would_enter_plan_mode(&self) -> bool {
        self.thread_settings_update
            .as_ref()
            .and_then(|updates| updates.collaboration_mode.as_ref())
            .is_some_and(|collaboration_mode| collaboration_mode.mode == ModeKind::Plan)
    }

    /// Applies persistent settings and start-only options before creating a
    /// new turn context.
    async fn apply_started(
        self,
        session: &Arc<Session>,
        submission_id: String,
    ) -> CodexResult<Arc<TurnContext>> {
        let TurnStartOptions {
            final_output_json_schema,
            parent_turn_id,
            root_turn_id,
        } = self.start_options;
        let emit_thread_settings_applied = self.thread_settings_update.is_some();
        let mut updates = self.thread_settings_update.unwrap_or_default();
        updates.final_output_json_schema = Some(final_output_json_schema);

        // new_turn_with_sub_id already emits an error event when settings are invalid.
        let turn_context = session
            .new_turn_with_sub_id(submission_id.clone(), updates)
            .await?;
        if emit_thread_settings_applied {
            thread_settings::emit_applied(session, submission_id).await;
        }
        if let Some(parent_turn_id) = parent_turn_id {
            turn_context
                .turn_metadata_state
                .set_parent_turn_id(parent_turn_id);
        }
        if let Some(root_turn_id) = root_turn_id {
            turn_context
                .turn_metadata_state
                .set_root_turn_id(root_turn_id);
        }
        Ok(turn_context)
    }

    /// Applies only persistent settings after steering succeeds. The active
    /// turn keeps its existing context; subsequent turns see the update.
    async fn apply_steered(self, session: &Session, submission_id: String) -> CodexResult<()> {
        let Some(thread_settings_update) = self.thread_settings_update else {
            return Ok(());
        };
        thread_settings::apply_update(session, submission_id, thread_settings_update)
            .await
            .map_err(|error| CodexErr::InvalidRequest(error.to_string()))
    }
}

pub(super) async fn handle(
    session: &Arc<Session>,
    request: TurnInputRequest,
    mode: TurnInputMode,
    submission_id: String,
) -> CodexResult<TurnInputSubmission> {
    // Each routing mode carries a substantial state machine. Heap-erasing the
    // selected branch keeps polling `handle` within Tokio's default worker stack.
    match mode {
        TurnInputMode::StartOrSteer => {
            Box::pin(start_or_steer(session, request, submission_id)).await
        }
        TurnInputMode::StartIfIdle => {
            Box::pin(start_if_idle(
                session,
                request,
                submission_id,
                /*recovery_epoch*/ None,
                TurnRunOrigin::NewTurn,
            ))
            .await
        }
        TurnInputMode::Steer { expected_turn_id } => {
            Box::pin(steer(session, request, expected_turn_id, submission_id)).await
        }
    }
}

pub(super) async fn handle_recovery(
    session: &Arc<Session>,
    expected_epoch: u64,
    thread_settings: ThreadSettingsOverrides,
    submission_id: String,
) -> CodexResult<TurnInputSubmission> {
    let request = TurnInputRequest::user_input(Vec::new()).with_thread_settings(thread_settings);
    start_if_idle(
        session,
        request,
        submission_id,
        Some(expected_epoch),
        TurnRunOrigin::Recovery,
    )
    .await
}

#[expect(
    clippy::await_holding_invalid_type,
    reason = "the active-turn guard serializes recovery consumption with start admission"
)]
async fn start_or_steer(
    session: &Arc<Session>,
    request: TurnInputRequest,
    submission_id: String,
) -> CodexResult<TurnInputSubmission> {
    let TurnInputRequest {
        input,
        thread_settings,
        start,
        additional_context,
        responsesapi_client_metadata,
        ..
    } = request;
    let SubmittedTurnInput::UserInput {
        content: mut items,
        client_id,
    } = input
    else {
        return Err(CodexErr::InvalidRequest(
            "only user input can steer a turn".to_string(),
        ));
    };
    let can_start_root_turn = start.parent_turn_id.is_none() && start.root_turn_id.is_none();
    let incoming_root_turn_id = start
        .parent_turn_id
        .as_ref()
        .map(|_| start.root_turn_id.clone());
    let settings = PreparedTurnInputSettings::prepare(session, thread_settings, start).await?;
    match session
        .steer_input(
            &mut items,
            additional_context.clone(),
            /*expected_turn_id*/ None,
            settings.required_active_final_output_json_schema(),
            client_id.clone(),
            responsesapi_client_metadata.clone(),
            incoming_root_turn_id,
        )
        .await
    {
        Ok(turn_context) => {
            settings
                .apply_steered(session, submission_id.clone())
                .await?;
            let turn_id = turn_context.sub_id.clone();
            session
                .pending_user_message_admissions
                .complete_steered(&submission_id, turn_context);
            Ok(TurnInputSubmission::Steered { turn_id })
        }
        Err(NotSubmittedReason::NoActiveTurn) => {
            let start_reservation = {
                let mut active_turn = session.active_turn.lock().await;
                if session.shutdown_started()
                    || session.has_pending_admission_fence()
                    || active_turn.is_some()
                {
                    return Ok(TurnInputSubmission::NotSubmitted {
                        reason: NotSubmittedReason::NotIdle,
                    });
                }
                let consumed_recovery =
                    match session.consume_recovery_candidate_for_mutation().await {
                        Ok(consumed_recovery) => consumed_recovery,
                        Err(_) => {
                            return Ok(TurnInputSubmission::NotSubmitted {
                                reason: NotSubmittedReason::RecoveryPersistenceFailed,
                            });
                        }
                    };
                let Some(start_reservation) = reserve_start_after_admission(
                    session,
                    &mut active_turn,
                    submission_id.clone(),
                    consumed_recovery,
                ) else {
                    return Ok(TurnInputSubmission::NotSubmitted {
                        reason: NotSubmittedReason::NotIdle,
                    });
                };
                start_reservation
            };
            let mut start_reservation_owner =
                StartReservationOwner::new(session, start_reservation);
            let turn_context = match settings.apply_started(session, submission_id.clone()).await {
                Ok(turn_context) => turn_context,
                Err(error) => {
                    release_start_reservation_after_error(
                        session,
                        start_reservation_owner.handle(),
                    )
                    .await;
                    return Err(error);
                }
            };
            if can_start_root_turn
                && !items.is_empty()
                && turn_context
                    .turn_metadata_state
                    .can_start_root_turn(&turn_context.session_source)
            {
                turn_context
                    .turn_metadata_state
                    .set_root_turn_id(submission_id.clone());
            }
            if let Some(responsesapi_client_metadata) = responsesapi_client_metadata {
                turn_context
                    .turn_metadata_state
                    .set_responsesapi_client_metadata(responsesapi_client_metadata);
            }
            session
                .maybe_emit_model_warnings_for_turn(turn_context.as_ref())
                .await;
            turn_context.session_telemetry.user_prompt(&items);
            let mut task_input = merge_additional_context_input(session, additional_context).await;
            if !items.is_empty() {
                task_input.push(TurnInput::UserInput {
                    content: items,
                    client_id,
                });
            }
            let start_outcome = session
                .start_task_owned(
                    Arc::clone(&turn_context),
                    task_input,
                    RegularTask::new(TurnRunOrigin::NewTurn),
                    MailboxParentProvenance::Ignore,
                    start_reservation_owner.handle().clone(),
                )
                .await;
            if start_outcome != StartTaskOutcome::Stale {
                start_reservation_owner.disarm();
            }
            if start_outcome != StartTaskOutcome::Attached {
                session
                    .pending_user_message_admissions
                    .complete_task_end(&submission_id);
                return Ok(TurnInputSubmission::NotSubmitted {
                    reason: NotSubmittedReason::NotIdle,
                });
            }
            session
                .pending_user_message_admissions
                .complete_started(&submission_id, turn_context);
            Ok(TurnInputSubmission::Started {
                turn_id: submission_id,
            })
        }
        Err(reason) => Ok(TurnInputSubmission::NotSubmitted { reason }),
    }
}

#[expect(
    clippy::expect_used,
    clippy::await_holding_invalid_type,
    reason = "the guarded idle-to-start transition validates exact recovery and reservation identities"
)]
async fn start_if_idle(
    session: &Arc<Session>,
    request: TurnInputRequest,
    submission_id: String,
    recovery_epoch: Option<u64>,
    run_origin: TurnRunOrigin,
) -> CodexResult<TurnInputSubmission> {
    if run_origin == TurnRunOrigin::Recovery && !session.enabled(Feature::HeptaTurnRecovery) {
        return Err(CodexErr::InvalidRequest(
            "turn recovery requires features.hepta_turn_recovery=true".to_string(),
        ));
    }
    let TurnInputRequest {
        input,
        thread_settings,
        start,
        additional_context,
        responsesapi_client_metadata,
        ..
    } = request;
    let has_user_input = has_nonempty_user_input(&input);
    let is_recovery = run_origin == TurnRunOrigin::Recovery;
    debug_assert_eq!(is_recovery, recovery_epoch.is_some());
    let is_automatic_idle_work = !has_user_input && !is_recovery;
    let can_start_root_turn = start.parent_turn_id.is_none() && start.root_turn_id.is_none();
    if session.shutdown_started() || session.has_pending_admission_fence() {
        return Ok(TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        });
    }
    if session.input_queue.has_trigger_turn_mailbox_items().await {
        return Ok(TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::PendingTriggerTurn,
        });
    }
    // Empty non-recovery starts are automatic wakeups, not explicit user requests.
    // Do not let them start a Plan turn.
    if is_automatic_idle_work && session.collaboration_mode().await.mode == ModeKind::Plan {
        return Ok(TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::PlanMode,
        });
    }

    let mut recovery_restart = None;
    let mut recovery_history_snapshot = None;
    let mut recovery_expected_context = None;
    let (turn_state, start_reservation) = {
        let mut active_turn = session.active_turn.lock().await;
        if session.shutdown_started()
            || session.has_pending_admission_fence()
            || active_turn.is_some()
        {
            return Ok(TurnInputSubmission::NotSubmitted {
                reason: NotSubmittedReason::NotIdle,
            });
        }
        if let Some(expected_epoch) = recovery_epoch
            && (session.turn_epoch.load(Ordering::Acquire) != expected_epoch
                || !session
                    .recovery_candidate
                    .lock()
                    .expect("recovery candidate mutex poisoned")
                    .as_ref()
                    .is_some_and(|candidate| {
                        candidate.turn_id == submission_id
                            && candidate.epoch == expected_epoch
                            && candidate.persistence_failure_generation
                                == session.rollout_persistence_failure_generation()
                    }))
        {
            return Ok(TurnInputSubmission::NotSubmitted {
                reason: NotSubmittedReason::RecoveryStateChanged,
            });
        }
        if is_recovery && thread_settings != ThreadSettingsOverrides::default() {
            return Err(CodexErr::InvalidRequest(
                "turn recovery cannot override the interrupted turn settings".to_string(),
            ));
        }
        if is_recovery {
            let candidate = session
                .recovery_candidate
                .lock()
                .expect("recovery candidate mutex poisoned")
                .clone()
                .ok_or_else(|| {
                    CodexErr::Fatal(
                        "turn recovery candidate disappeared before consumption".to_string(),
                    )
                })?;
            let consumed_generation =
                candidate.marker_generation.checked_add(1).ok_or_else(|| {
                    CodexErr::Fatal("turn recovery generation exhausted before restart".to_string())
                })?;
            recovery_restart = Some((
                candidate.request_fingerprint_sha256,
                consumed_generation,
                candidate.marker_generation,
                candidate.replay,
            ));
        }
        if let Some((_, _, _, replay)) = recovery_restart.as_ref() {
            let Some(expected_context) =
                recovery_reference_context(session, &submission_id, replay).await
            else {
                if session
                    .consume_recovery_candidate_for_mutation()
                    .await
                    .is_err()
                {
                    return Ok(TurnInputSubmission::NotSubmitted {
                        reason: NotSubmittedReason::RecoveryPersistenceFailed,
                    });
                }
                session.settle_consumed_recovery_status();
                return Ok(TurnInputSubmission::NotSubmitted {
                    reason: NotSubmittedReason::RecoveryStateChanged,
                });
            };
            recovery_history_snapshot = match session
                .validated_recovery_history_snapshot(&replay.history_boundary)
                .await
            {
                Ok(history) => Some(history),
                Err(_) => {
                    if session
                        .consume_recovery_candidate_for_mutation()
                        .await
                        .is_err()
                    {
                        return Ok(TurnInputSubmission::NotSubmitted {
                            reason: NotSubmittedReason::RecoveryPersistenceFailed,
                        });
                    }
                    session.settle_consumed_recovery_status();
                    return Ok(TurnInputSubmission::NotSubmitted {
                        reason: NotSubmittedReason::RecoveryStateChanged,
                    });
                }
            };
            recovery_expected_context = Some(expected_context);
        }
        let consumed_recovery = match session.consume_recovery_candidate_for_mutation().await {
            Ok(consumed_recovery) => consumed_recovery,
            Err(_) => {
                return Ok(TurnInputSubmission::NotSubmitted {
                    reason: NotSubmittedReason::RecoveryPersistenceFailed,
                });
            }
        };
        let Some(start_reservation) = reserve_start_after_admission(
            session,
            &mut active_turn,
            submission_id.clone(),
            consumed_recovery,
        ) else {
            return Ok(TurnInputSubmission::NotSubmitted {
                reason: NotSubmittedReason::NotIdle,
            });
        };
        let active_turn = active_turn
            .as_ref()
            .expect("caller reservation should retain the active turn state");
        (Arc::clone(&active_turn.turn_state), start_reservation)
    };
    let mut start_reservation_owner = StartReservationOwner::new(session, start_reservation);

    if session.input_queue.has_trigger_turn_mailbox_items().await {
        release_start_reservation_after_error(session, start_reservation_owner.handle()).await;
        session.maybe_start_turn_for_pending_work().await;
        return Ok(TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::PendingTriggerTurn,
        });
    }

    let settings = match PreparedTurnInputSettings::prepare(session, thread_settings, start).await {
        Ok(settings) => settings,
        Err(error) => {
            release_start_reservation_after_error(session, start_reservation_owner.handle()).await;
            return Err(error);
        }
    };
    // Automatic work must not use persistent settings to start a turn
    // whose effective collaboration mode is Plan.
    if is_automatic_idle_work && settings.would_enter_plan_mode() {
        release_start_reservation_after_error(session, start_reservation_owner.handle()).await;
        return Ok(TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::PlanMode,
        });
    }

    let mut turn_context = match settings.apply_started(session, submission_id.clone()).await {
        Ok(turn_context) => turn_context,
        Err(error) => {
            release_start_reservation_after_error(session, start_reservation_owner.handle()).await;
            return Err(error);
        }
    };
    if let Some(responsesapi_client_metadata) = responsesapi_client_metadata {
        turn_context
            .turn_metadata_state
            .set_responsesapi_client_metadata(responsesapi_client_metadata);
    }
    if let Some((_, _, _, replay)) = recovery_restart.as_ref() {
        let expected_context = recovery_expected_context
            .as_ref()
            .expect("validated recovery context captured before candidate consumption");
        let Some(turn_context) = Arc::get_mut(&mut turn_context) else {
            release_start_reservation_after_error(session, start_reservation_owner.handle()).await;
            return Err(CodexErr::Fatal(
                "turn recovery context became shared before replay was applied".to_string(),
            ));
        };
        // Date and timezone are model-visible request inputs. A cold recovery
        // may happen after the local clock crosses a date boundary, so replay
        // the values persisted with the interrupted request before comparing.
        turn_context.current_date = expected_context.current_date.clone();
        turn_context.timezone = expected_context.timezone.clone();
        turn_context.final_output_json_schema = replay.start.final_output_json_schema.clone();
        turn_context
            .turn_metadata_state
            .apply_recovery_start_state(&replay.start);
        if turn_context.to_turn_context_item() != *expected_context
            || super::turn::turn_recovery_environment_selections(&turn_context.environments)
                .as_ref()
                != Some(&replay.environments)
        {
            release_start_reservation_after_error(session, start_reservation_owner.handle()).await;
            return Ok(TurnInputSubmission::NotSubmitted {
                reason: NotSubmittedReason::RecoveryStateChanged,
            });
        }
    }
    let mut recovery_history_to_install = None;
    if let Some((request_fingerprint_sha256, consumed_generation, source_generation, replay)) =
        recovery_restart.as_ref()
    {
        if let Err(error) = session
            .persist_recovery_replay_applied(
                &submission_id,
                *consumed_generation,
                *source_generation,
                request_fingerprint_sha256,
                replay,
            )
            .await
        {
            release_start_reservation_after_error(session, start_reservation_owner.handle()).await;
            return Err(error);
        }
        let Some(history) = recovery_history_snapshot.take() else {
            release_start_reservation_after_error(session, start_reservation_owner.handle()).await;
            return Err(CodexErr::Fatal(
                "turn recovery history snapshot disappeared before installation".to_string(),
            ));
        };
        // Defer installation of the rewound snapshot until `start_task` has
        // fenced its async transition.  Capture the original view as late as
        // possible, after all caller-owned preparation awaits have completed.
        recovery_history_to_install = Some(history);
    }
    if has_user_input
        && can_start_root_turn
        && turn_context
            .turn_metadata_state
            .can_start_root_turn(&turn_context.session_source)
    {
        turn_context
            .turn_metadata_state
            .set_root_turn_id(submission_id.clone());
    }
    session
        .maybe_emit_model_warnings_for_turn(turn_context.as_ref())
        .await;

    let mut task_input = merge_additional_context_input(session, additional_context).await;
    if has_user_input {
        session.clear_connector_selection().await;
        if let SubmittedTurnInput::UserInput { content, .. } = &input {
            turn_context.session_telemetry.user_prompt(content);
        }
        task_input.push(pending_turn_input(input));
    } else if is_automatic_idle_work && !matches!(&input, SubmittedTurnInput::UserInput { .. }) {
        // Automatic response-item work still needs to be queued, but an empty
        // user-input request should start sampling without adding a message.
        session
            .input_queue
            .extend_pending_input_for_turn_state(
                turn_state.as_ref(),
                vec![pending_turn_input(input)],
            )
            .await;
    }
    let regular_task = match recovery_restart {
        Some((request_fingerprint_sha256, consumed_generation, _source_generation, _replay)) => {
            RegularTask::for_recovery(request_fingerprint_sha256, consumed_generation)
        }
        None => RegularTask::new(run_origin),
    };
    let recovery_history_transition = if let Some(install) = recovery_history_to_install {
        let restore = session.clone_history().await;
        Some(RecoveryHistoryTransition { install, restore })
    } else {
        None
    };
    let start_outcome = session
        .start_task_with_recovery_owned(
            Arc::clone(&turn_context),
            task_input,
            regular_task,
            MailboxParentProvenance::Ignore,
            recovery_history_transition,
            start_reservation_owner.handle().clone(),
        )
        .await;
    if start_outcome != StartTaskOutcome::Stale {
        start_reservation_owner.disarm();
    }
    if start_outcome != StartTaskOutcome::Attached {
        if has_user_input && !is_recovery {
            session
                .pending_user_message_admissions
                .complete_task_end(&submission_id);
        }
        return Ok(TurnInputSubmission::NotSubmitted {
            reason: NotSubmittedReason::NotIdle,
        });
    }
    if has_user_input && !is_recovery {
        session
            .pending_user_message_admissions
            .complete_started(&submission_id, turn_context);
    }
    Ok(TurnInputSubmission::Started {
        turn_id: submission_id,
    })
}

/// Proves that a resumed request will rebuild the exact execution/model
/// context recorded before its durable Ready boundary. The active-turn lock is
/// held by the caller, serializing this comparison with settings mutation.
async fn recovery_reference_context(
    session: &Session,
    turn_id: &str,
    replay: &codex_history::TurnRecoveryReplayV1,
) -> Option<TurnContextItem> {
    let expected = session.reference_context_item().await?;
    if expected.turn_id.as_deref() != Some(turn_id) {
        return None;
    }
    let mut current = session
        .new_default_turn_with_sub_id(turn_id.to_string())
        .await;
    let current_mut = Arc::get_mut(&mut current)?;
    // These values are model-visible but intentionally replayable across a
    // local date boundary. All configuration- and environment-derived fields
    // below remain strict comparisons against the resumed session.
    current_mut.current_date = expected.current_date.clone();
    current_mut.timezone = expected.timezone.clone();
    let current_item = current.to_turn_context_item();
    if expected != current_item {
        return None;
    }
    let expected_context_sha256 = crate::model_provider_policy::canonical_sha256(&expected)
        .ok()
        .map(|digest| digest.as_str().to_string());
    if expected_context_sha256.as_deref() != Some(replay.turn_context_sha256.as_str())
        || super::turn::turn_recovery_environment_selections(&current.environments).as_ref()
            != Some(&replay.environments)
    {
        return None;
    }
    Some(expected)
}

async fn steer(
    session: &Arc<Session>,
    request: TurnInputRequest,
    expected_turn_id: String,
    submission_id: String,
) -> CodexResult<TurnInputSubmission> {
    let TurnInputRequest {
        input,
        thread_settings,
        start,
        additional_context,
        responsesapi_client_metadata,
        ..
    } = request;
    let SubmittedTurnInput::UserInput {
        content: mut items,
        client_id,
    } = input
    else {
        return Err(CodexErr::InvalidRequest(
            "only user input can steer a turn".to_string(),
        ));
    };
    let incoming_root_turn_id = start
        .parent_turn_id
        .as_ref()
        .map(|_| start.root_turn_id.clone());
    let settings = PreparedTurnInputSettings::prepare(session, thread_settings, start).await?;
    match session
        .steer_input(
            &mut items,
            additional_context,
            Some(expected_turn_id.as_str()),
            settings.required_active_final_output_json_schema(),
            client_id,
            responsesapi_client_metadata,
            incoming_root_turn_id,
        )
        .await
    {
        Ok(turn_context) => {
            settings
                .apply_steered(session, submission_id.clone())
                .await?;
            let turn_id = turn_context.sub_id.clone();
            session
                .pending_user_message_admissions
                .complete_steered(&submission_id, turn_context);
            Ok(TurnInputSubmission::Steered { turn_id })
        }
        Err(reason) => Ok(TurnInputSubmission::NotSubmitted { reason }),
    }
}

impl Session {
    pub(crate) async fn route_realtime_text_input(self: &Arc<Self>, text: String) {
        let submission_id = Uuid::now_v7().to_string();
        let submission = handle(
            self,
            TurnInputRequest::user_input(vec![UserInput::Text {
                text,
                text_elements: Vec::new(),
            }]),
            TurnInputMode::StartOrSteer,
            submission_id.clone(),
        )
        .await;
        match submission {
            Ok(TurnInputSubmission::Started { .. } | TurnInputSubmission::Steered { .. }) => {}
            Ok(TurnInputSubmission::NotSubmitted { reason }) => {
                self.send_event_raw(Event {
                    id: submission_id,
                    msg: EventMsg::Error(ErrorEvent {
                        message: format!("failed to submit turn input: {reason:?}"),
                        codex_error_info: Some(CodexErrorInfo::BadRequest),
                    }),
                })
                .await;
            }
            Err(error) => {
                self.send_event_raw(Event {
                    id: submission_id,
                    msg: EventMsg::Error(error.to_error_event(/*message_prefix*/ None)),
                })
                .await;
            }
        }
    }

    #[expect(
        dead_code,
        reason = "retained for focused lifecycle qualification and recovery probes"
    )]
    pub(crate) async fn clear_reserved_idle_turn(
        &self,
        turn_state: &Arc<tokio::sync::Mutex<TurnState>>,
    ) {
        let mut active_turn_guard = self.active_turn.lock().await;
        if let Some(active_turn) = active_turn_guard.as_ref()
            && active_turn.task.is_none()
            && active_turn.start_reservation.is_none()
            && active_turn.start_transition.is_none()
            && active_turn.task_terminalization.is_none()
            && Arc::ptr_eq(&active_turn.turn_state, turn_state)
        {
            *active_turn_guard = None;
        }
    }

    /// Clears a start/history reservation after no task was attached. If the
    /// reservation consumed the only interrupted recovery candidate, publish a
    /// final idle status so subagent completion waiters cannot remain stuck on
    /// an unrecoverable `Interrupted` state.
    pub(crate) async fn settle_and_clear_reserved_idle_turn(
        &self,
        turn_state: &Arc<tokio::sync::Mutex<TurnState>>,
    ) {
        let mut active_turn_guard = self.active_turn.lock().await;
        if let Some(active_turn) = active_turn_guard.as_ref()
            && active_turn.task.is_none()
            && active_turn.start_reservation.is_none()
            && active_turn.start_transition.is_none()
            && active_turn.task_terminalization.is_none()
            && Arc::ptr_eq(&active_turn.turn_state, turn_state)
        {
            self.settle_consumed_recovery_status();
            *active_turn_guard = None;
        }
    }

    /// Inject additional user input into the currently active turn.
    ///
    /// Returns the active turn id when accepted.
    #[expect(
        clippy::await_holding_invalid_type,
        reason = "active turn checks and turn state updates must remain atomic"
    )]
    #[expect(
        clippy::too_many_arguments,
        reason = "steering carries the accepted input plus its turn-scoped metadata"
    )]
    #[expect(
        clippy::expect_used,
        reason = "steering only dereferences state after the active-turn identity check"
    )]
    async fn steer_input(
        &self,
        input: &mut Vec<UserInput>,
        additional_context: BTreeMap<String, AdditionalContextEntry>,
        expected_turn_id: Option<&str>,
        required_final_output_json_schema: Option<&Value>,
        client_user_message_id: Option<String>,
        responsesapi_client_metadata: Option<HashMap<String, String>>,
        incoming_root_turn_id: Option<Option<String>>,
    ) -> Result<Arc<TurnContext>, NotSubmittedReason> {
        let mut active = self.active_turn.lock().await;
        let Some(active_turn) = active.as_mut() else {
            return Err(NotSubmittedReason::NoActiveTurn);
        };

        // Establish the steer admission order against shutdown.  The active
        // turn lock is taken first, matching start publication; the short
        // gate makes `begin_shutdown` either win before this check (rejecting
        // the input) or observe this steer as admitted before sealing.  Do
        // not hold the synchronous gate across the async input/persistence
        // work below.
        {
            let _admission_gate = self
                .start_admission_gate
                .lock()
                .expect("start admission gate mutex poisoned");
            if self.shutdown_started() {
                return Err(NotSubmittedReason::NotIdle);
            }
        }

        if active_turn.task_terminalization.is_some() {
            return Err(NotSubmittedReason::NotIdle);
        }

        let Some(active_task) = active_turn.task.as_ref() else {
            return Err(NotSubmittedReason::NoActiveTurn);
        };
        let active_turn_id = &active_task.turn_context.sub_id;

        if let Some(expected_turn_id) = expected_turn_id
            && expected_turn_id != active_turn_id
        {
            return Err(NotSubmittedReason::ExpectedTurnMismatch {
                expected: expected_turn_id.to_string(),
                actual: active_turn_id.clone(),
            });
        }

        match active_task.kind {
            crate::state::TaskKind::Regular => {}
            crate::state::TaskKind::Review => {
                return Err(NotSubmittedReason::ActiveTurnNotSteerable {
                    turn_kind: NonSteerableTurnKind::Review,
                });
            }
            crate::state::TaskKind::Compact => {
                return Err(NotSubmittedReason::ActiveTurnNotSteerable {
                    turn_kind: NonSteerableTurnKind::Compact,
                });
            }
        }

        if input.is_empty() {
            return Err(NotSubmittedReason::EmptyInput);
        }
        // Compare JSON values directly instead of serialized schema text.
        // Value equality ignores object key order while preserving array and
        // scalar distinctions; broader JSON Schema equivalence is out of scope.
        if let Some(required_schema) = required_final_output_json_schema
            && active_task.turn_context.final_output_json_schema.as_ref() != Some(required_schema)
        {
            return Err(NotSubmittedReason::ActiveTurnOutputSchemaMismatch);
        }
        if let Some(authority) = active_task.recovery_authority.as_ref()
            && self
                .ensure_turn_recovery_unready(active_turn_id, authority.as_ref())
                .await
                .is_err()
        {
            return Err(NotSubmittedReason::RecoveryPersistenceFailed);
        }
        active_task
            .turn_context
            .session_telemetry
            .user_prompt(input);

        let mut pending_input = merge_additional_context_input(self, additional_context).await;

        if let Some(responsesapi_client_metadata) = responsesapi_client_metadata {
            active_task
                .turn_context
                .turn_metadata_state
                .set_responsesapi_client_metadata(responsesapi_client_metadata);
        }

        pending_input.push(TurnInput::UserInput {
            content: std::mem::take(input),
            client_id: client_user_message_id,
        });
        if let Some(incoming_root_turn_id) = incoming_root_turn_id
            && active_task.turn_context.turn_metadata_state.root_turn_id() != incoming_root_turn_id
        {
            active_task
                .turn_context
                .turn_metadata_state
                .mark_root_turn_ambiguous();
        }
        self.input_queue
            .extend_pending_input_and_accept_mailbox_delivery_for_turn_state(
                active_turn.turn_state.as_ref(),
                pending_input,
            )
            .await;
        Ok(Arc::clone(&active_task.turn_context))
    }
}

fn has_nonempty_user_input(input: &SubmittedTurnInput) -> bool {
    matches!(input, SubmittedTurnInput::UserInput { content, .. } if !content.is_empty())
}

async fn merge_additional_context_input(
    session: &Session,
    additional_context: BTreeMap<String, AdditionalContextEntry>,
) -> Vec<TurnInput> {
    let additional_context_input = {
        let mut state = session.state.lock().await;
        state.additional_context.merge(additional_context)
    };
    additional_context_input
        .into_iter()
        .map(|item| session.annotate_client_response_item(item))
        .map(TurnInput::ResponseItem)
        .collect()
}

fn pending_turn_input(input: SubmittedTurnInput) -> TurnInput {
    match input {
        SubmittedTurnInput::UserInput { content, client_id } => {
            TurnInput::UserInput { content, client_id }
        }
        SubmittedTurnInput::ResponseItem(item) => TurnInput::ResponseItem(item.into()),
        SubmittedTurnInput::InterAgentCommunication(communication) => {
            TurnInput::InterAgentCommunication(communication)
        }
    }
}
