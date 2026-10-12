use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_extension_api::ExtensionFuture;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadIdleInput;
use codex_extension_api::ThreadLifecycleContributor;
use codex_features::Feature;
use codex_protocol::protocol::EventMsg;
use pretty_assertions::assert_eq;
use test_case::test_case;
use tokio::sync::Notify;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::SessionTask;
use super::SessionTaskResult;
use super::TaskFinishHandoffPhase;
use super::finish_admission::FinishTerminalPublication;
use crate::config::Config;
use crate::session::TurnInput;
use crate::session::session::RolloutPersistenceFault;
use crate::session::session::Session;
use crate::session::session::TerminalPreparationGate;
use crate::session::session::TerminalPublicationGate;
use crate::session::tests::attach_in_memory_thread_store;
use crate::session::tests::make_session_and_context_without_git_enrichment_for_test;
use crate::session::turn_context::TurnContext;
use crate::state::DurableRecoveryState;
use crate::state::TaskKind;
use crate::state::TurnRecoveryAuthority;

struct ControlledTask {
    release: Arc<Notify>,
}

impl SessionTask for ControlledTask {
    fn kind(&self) -> TaskKind {
        TaskKind::Regular
    }

    fn span_name(&self) -> &'static str {
        "session_task.finish_publication_probe"
    }

    async fn run(
        self: Arc<Self>,
        _session: Arc<Session>,
        _ctx: Arc<TurnContext>,
        _input: Vec<TurnInput>,
        _cancellation_token: CancellationToken,
    ) -> SessionTaskResult {
        self.release.notified().await;
        Ok(None)
    }
}

#[derive(Default)]
struct IdleGate {
    entered: Notify,
    release: Notify,
    called: AtomicBool,
}

impl ThreadLifecycleContributor<Config> for IdleGate {
    fn on_thread_idle<'a>(&'a self, _input: ThreadIdleInput<'a>) -> ExtensionFuture<'a, ()> {
        Box::pin(async move {
            if !self.called.swap(true, Ordering::AcqRel) {
                self.entered.notify_one();
                self.release.notified().await;
            }
        })
    }
}

#[derive(Clone, Copy)]
enum Boundary {
    Preparing,
    ClosedReceiver,
    PreterminalFlushFailure,
    RecoveryRevoked,
    RecoveryRevokeFailure,
    RecoveryTombstoneFailure,
    TerminalFlushFailure,
    FinalGenerationChange,
    OwnerEpochChange,
    AfterRelease,
}

#[test_case(Boundary::Preparing; "cancellation after append retains prepared event")]
#[test_case(Boundary::ClosedReceiver; "closed receiver retains event and admission fence")]
#[test_case(Boundary::PreterminalFlushFailure; "preterminal flush failure withholds early admission")]
#[test_case(Boundary::RecoveryRevoked; "successful Ready revocation permits ordinary release")]
#[test_case(Boundary::RecoveryRevokeFailure; "recovery revoke failure with tombstone stays fenced")]
#[test_case(Boundary::RecoveryTombstoneFailure; "failed recovery tombstone stays fenced")]
#[test_case(Boundary::TerminalFlushFailure; "terminal flush failure withholds early admission")]
#[test_case(Boundary::FinalGenerationChange; "generation change after receipt withholds early admission")]
#[test_case(Boundary::OwnerEpochChange; "changed epoch retains exact stale owner witness")]
#[test_case(Boundary::AfterRelease; "cancellation after release preserves replacement ownership")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn finish_publication_boundary_retains_exact_witness_without_replay(boundary: Boundary) {
    let features: &[Feature] = if matches!(
        boundary,
        Boundary::RecoveryRevoked
            | Boundary::RecoveryRevokeFailure
            | Boundary::RecoveryTombstoneFailure
    ) {
        &[Feature::HeptaTurnRecovery]
    } else {
        &[]
    };
    let (mut session, turn, events) =
        make_session_and_context_without_git_enrichment_for_test(features).await;
    let store =
        attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("unique test session"))
            .await;
    let idle = Arc::new(IdleGate::default());
    let mut extensions = ExtensionRegistryBuilder::<Config>::new();
    extensions.thread_lifecycle_contributor(idle.clone());
    Arc::get_mut(&mut session)
        .expect("unique test session")
        .services
        .extensions = Arc::new(extensions.build());
    let preparation = session
        .services
        .session_extension_data
        .get_or_init(TerminalPreparationGate::default);
    let release_task = Arc::new(Notify::new());
    session
        .spawn_task(
            Arc::clone(&turn),
            Vec::new(),
            ControlledTask {
                release: Arc::clone(&release_task),
            },
        )
        .await
        .expect("controlled task attached");
    let recovery_authority = if matches!(
        boundary,
        Boundary::RecoveryRevoked
            | Boundary::RecoveryRevokeFailure
            | Boundary::RecoveryTombstoneFailure
    ) {
        let authority = Arc::new(TurnRecoveryAuthority::default());
        let replay = codex_history::TurnRecoveryReplayV1 {
            history_boundary: session
                .current_recovery_history_boundary()
                .await
                .expect("history boundary"),
            turn_context_sha256: "fixture-context".to_string(),
            start: codex_history::TurnRecoveryStartState {
                final_output_json_schema: None,
                parent_turn_id: None,
                root_turn_id: Some(turn.sub_id.clone()),
                responses_metadata_extra: Default::default(),
            },
            environments: Vec::new(),
        };
        session
            .mark_turn_recovery_ready(
                &turn.sub_id,
                &authority,
                /*persistence_failure_baseline*/ 0,
                "fixture-request",
                &replay,
            )
            .await
            .expect("persist initial Ready authority");
        session
            .active_turn
            .lock()
            .await
            .as_mut()
            .expect("active turn")
            .task
            .as_mut()
            .expect("attached task")
            .recovery_authority = Some(Arc::clone(&authority));
        Some(authority)
    } else {
        None
    };
    let slot = session
        .claim_finish_handoff_for_test(Arc::clone(&turn), Ok(None))
        .await
        .expect("exact finish owner claimed");
    let done = Arc::clone(
        &slot
            .lock()
            .expect("handoff slot")
            .as_ref()
            .expect("claimed witness")
            .task
            .as_ref()
            .expect("task witness")
            .done,
    );
    // The synthetic claim has the exact result the controlled body returns.
    // Let that body and its already-claimed finish callback drain before driving.
    let body_done = done.notified();
    tokio::pin!(body_done);
    body_done.as_mut().enable();
    release_task.notify_one();
    timeout(Duration::from_secs(2), body_done)
        .await
        .expect("old task body quiesced");
    let before = store.calls().await;
    if matches!(boundary, Boundary::ClosedReceiver) {
        events.close();
    }
    if matches!(boundary, Boundary::PreterminalFlushFailure) {
        session
            .inject_rollout_persistence_fault(RolloutPersistenceFault::RolloutFlush)
            .await;
    }
    if matches!(
        boundary,
        Boundary::RecoveryRevokeFailure | Boundary::RecoveryTombstoneFailure
    ) {
        session
            .inject_rollout_persistence_fault(RolloutPersistenceFault::TurnRecoveryUnreadyAppend)
            .await;
        if matches!(boundary, Boundary::RecoveryTombstoneFailure) {
            session
                .inject_rollout_persistence_fault(
                    RolloutPersistenceFault::TurnRecoveryUnreadyAppend,
                )
                .await;
        }
    }
    let publication = matches!(
        boundary,
        Boundary::FinalGenerationChange | Boundary::OwnerEpochChange
    )
    .then(|| {
        session
            .services
            .session_extension_data
            .get_or_init(TerminalPublicationGate::default)
    });
    let mut driver = tokio::spawn({
        let session = Arc::clone(&session);
        let slot = Arc::clone(&slot);
        async move { session.drive_finish_handoff(slot).await }
    });
    if !matches!(
        boundary,
        Boundary::PreterminalFlushFailure
            | Boundary::RecoveryRevokeFailure
            | Boundary::RecoveryTombstoneFailure
    ) {
        timeout(Duration::from_secs(2), preparation.entered.notified())
            .await
            .expect("terminal was appended before preparation returns");
        if matches!(boundary, Boundary::TerminalFlushFailure) {
            session
                .inject_rollout_persistence_fault(RolloutPersistenceFault::RolloutFlush)
                .await;
        }
        if !matches!(boundary, Boundary::Preparing) {
            preparation.release.notify_one();
        }
    }
    if let Some(publication) = publication.as_ref() {
        timeout(Duration::from_secs(2), publication.entered.notified())
            .await
            .expect("terminal receipt and recovery publication completed");
        assert_eq!(session.rollout_persistence_failure_generation(), 0);
        assert_eq!(store.calls().await.flush_thread, before.flush_thread + 2);
        match boundary {
            Boundary::FinalGenerationChange => session.mark_rollout_persistence_failure(),
            Boundary::OwnerEpochChange => {
                session.turn_epoch.fetch_add(1, Ordering::AcqRel);
            }
            _ => panic!("only final-proof cases install this gate"),
        }
        publication.release.notify_one();
    }
    let replacement = if matches!(boundary, Boundary::OwnerEpochChange) {
        timeout(Duration::from_secs(2), &mut driver)
            .await
            .expect("stale owner returns without callback")
            .expect("stale owner driver joins");
        None
    } else {
        if !matches!(boundary, Boundary::Preparing) {
            timeout(Duration::from_secs(2), idle.entered.notified())
                .await
                .expect("ordinary callback reached");
        }
        let replacement = if matches!(boundary, Boundary::AfterRelease) {
            assert!(!session.has_pending_admission_fence());
            assert!(session.has_pending_task_terminalization());
            let next = session.new_default_turn().await;
            let release = Arc::new(Notify::new());
            session
                .spawn_task(
                    Arc::clone(&next),
                    Vec::new(),
                    ControlledTask {
                        release: Arc::clone(&release),
                    },
                )
                .await
                .expect("replacement admitted while old callback waits");
            Some((next, release))
        } else {
            None
        };
        driver.abort();
        assert!(
            driver
                .await
                .expect_err("driver was cancelled")
                .is_cancelled()
        );
        replacement
    };
    let (retained_event, observed) = {
        let retained = slot.lock().expect("retained slot");
        let handoff = retained.as_ref().expect("advanced owner retains witness");
        (
            handoff.prepared_terminal_event.clone(),
            (
                handoff.phase,
                handoff.terminal_publication,
                handoff.failed_closed,
                handoff.task.is_some(),
                handoff.completion.blocks_admission(),
                handoff.completion.is_complete(),
            ),
        )
    };
    let expected_boundary = match boundary {
        Boundary::Preparing => (TaskFinishHandoffPhase::PersistencePublishing, None),
        Boundary::ClosedReceiver => (
            TaskFinishHandoffPhase::PendingWorkStarting,
            Some(FinishTerminalPublication::Undelivered),
        ),
        Boundary::PreterminalFlushFailure
        | Boundary::RecoveryRevokeFailure
        | Boundary::RecoveryTombstoneFailure => (
            TaskFinishHandoffPhase::PendingWorkStarting,
            Some(FinishTerminalPublication::NotDeferred),
        ),
        Boundary::TerminalFlushFailure
        | Boundary::RecoveryRevoked
        | Boundary::FinalGenerationChange
        | Boundary::AfterRelease => (
            TaskFinishHandoffPhase::PendingWorkStarting,
            Some(FinishTerminalPublication::Published),
        ),
        Boundary::OwnerEpochChange => (
            TaskFinishHandoffPhase::PendingWorkStarting,
            Some(FinishTerminalPublication::StaleOwner),
        ),
    };
    let admission_released = matches!(boundary, Boundary::AfterRelease | Boundary::RecoveryRevoked);
    assert_eq!(
        observed,
        (
            expected_boundary.0,
            expected_boundary.1,
            true,
            !admission_released,
            !admission_released,
            false
        )
    );
    let event_retained = matches!(
        boundary,
        Boundary::Preparing | Boundary::ClosedReceiver | Boundary::OwnerEpochChange
    );
    assert_eq!(retained_event.is_some(), event_retained);
    if let Some(event) = retained_event.as_ref() {
        assert_eq!(event.id, turn.sub_id);
        assert!(matches!(&event.msg, EventMsg::TurnComplete(_)));
    }
    assert_eq!(session.has_pending_admission_fence(), !admission_released);
    assert!(session.has_pending_task_terminalization());
    let mut terminal_count = 0;
    while let Ok(event) = events.try_recv() {
        if matches!(event.msg, EventMsg::TurnComplete(_)) {
            assert_eq!(event.id, turn.sub_id);
            terminal_count += 1;
        }
    }
    assert_eq!(terminal_count, usize::from(!event_retained));
    let expected_failures = match boundary {
        Boundary::PreterminalFlushFailure
        | Boundary::TerminalFlushFailure
        | Boundary::FinalGenerationChange
        | Boundary::RecoveryRevokeFailure => 1,
        Boundary::RecoveryTombstoneFailure => 2,
        Boundary::Preparing
        | Boundary::ClosedReceiver
        | Boundary::RecoveryRevoked
        | Boundary::OwnerEpochChange
        | Boundary::AfterRelease => 0,
    };
    assert_eq!(
        session.rollout_persistence_failure_generation(),
        expected_failures
    );
    assert!(session.rollout_persistence_faults.lock().await.is_empty());
    let after = store.calls().await;
    // A preterminal failure also writes the existing warning event.
    assert_eq!(
        after.append_items,
        before.append_items
            + if matches!(
                boundary,
                Boundary::PreterminalFlushFailure
                    | Boundary::RecoveryRevokeFailure
                    | Boundary::RecoveryRevoked
            ) {
                2
            } else {
                1
            }
    );
    session.drive_finish_handoff(Arc::clone(&slot)).await;
    assert_eq!(store.calls().await, after);
    assert_eq!(
        serde_json::to_value(
            &slot
                .lock()
                .expect("retained slot after attempted redrive")
                .as_ref()
                .expect("failed-closed witness remains")
                .prepared_terminal_event
        )
        .expect("retained event serializes"),
        serde_json::to_value(retained_event).expect("expected event serializes")
    );
    if let Some(authority) = recovery_authority {
        let state = authority.state.lock().await;
        let clean = matches!(boundary, Boundary::RecoveryRevoked);
        assert_eq!(
            (
                authority.ready.load(Ordering::Acquire),
                state.poisoned,
                state.durable_state
            ),
            (
                false,
                !clean,
                if matches!(boundary, Boundary::RecoveryTombstoneFailure) {
                    DurableRecoveryState::Ready
                } else {
                    DurableRecoveryState::Unready
                }
            )
        );
        assert_eq!(
            session.rollout_persistence_failure_generation(),
            if clean {
                0
            } else if matches!(boundary, Boundary::RecoveryRevokeFailure) {
                1
            } else {
                2
            }
        );
    }
    if let Some((next, release)) = replacement {
        let done = {
            let active = session.active_turn.lock().await;
            let task = active
                .as_ref()
                .expect("replacement active")
                .task
                .as_ref()
                .expect("replacement task");
            assert!(Arc::ptr_eq(&task.turn_context, &next));
            Arc::clone(&task.done)
        };
        let replacement_done = done.notified();
        tokio::pin!(replacement_done);
        replacement_done.as_mut().enable();
        preparation.release.notify_one();
        release.notify_one();
        timeout(Duration::from_secs(2), replacement_done)
            .await
            .expect("replacement finishes independently of cancelled callback");
        assert!(session.active_turn.lock().await.is_none());
        assert!(!session.has_pending_admission_fence());
        assert!(
            session.has_pending_task_terminalization(),
            "old completion remains tracked"
        );
    }
}

#[path = "finish_recovery_tests.rs"]
mod recovery;
