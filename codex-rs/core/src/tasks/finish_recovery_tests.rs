use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_extension_api::ThreadIdleCause;
use codex_features::Feature;
use codex_protocol::protocol::Event;
use codex_protocol::protocol::EventMsg;
use codex_protocol::protocol::TurnCompleteEvent;
use pretty_assertions::assert_eq;
use test_case::test_case;
use tokio::sync::Notify;
use tokio::time::timeout;

use super::ControlledTask;
use crate::session::session::RolloutPersistenceFault;
use crate::session::session::Session;
use crate::session::tests::attach_in_memory_thread_store;
use crate::session::tests::make_session_and_context_without_git_enrichment_for_test;
use crate::state::DurableRecoveryState;
use crate::state::TaskTerminalizationKind;
use crate::state::TurnRecoveryAuthority;
use crate::tasks::RecoverySeed;
use crate::tasks::finish_admission::FinishTerminalPublication;
use crate::tasks::finish_admission::RecoveryPreparation;
use crate::tasks::finish_admission::RecoveryPublication;

#[derive(Clone, Copy)]
enum PublicationCase {
    Confirmed,
    AppendTombstoned,
    AppendTombstoneFailed,
    FlushTombstoned,
    FlushTombstoneFailed,
}

#[test_case(PublicationCase::Confirmed; "confirmed interrupted recovery does not authorize ordinary release")]
#[test_case(PublicationCase::AppendTombstoned; "confirmation append failure and tombstone deny release")]
#[test_case(PublicationCase::AppendTombstoneFailed; "confirmation append and both tombstones fail closed")]
#[test_case(PublicationCase::FlushTombstoned; "confirmation flush failure and tombstone deny release")]
#[test_case(PublicationCase::FlushTombstoneFailed; "confirmation flush and both tombstones fail closed")]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn recovery_publication_outcome_is_required_for_early_admission(case: PublicationCase) {
    let (mut session, turn, events) =
        make_session_and_context_without_git_enrichment_for_test(&[Feature::HeptaTurnRecovery])
            .await;
    attach_in_memory_thread_store(Arc::get_mut(&mut session).expect("unique session")).await;
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
        .expect("persist Ready authority");
    let release = Arc::new(Notify::new());
    session
        .spawn_task(
            Arc::clone(&turn),
            Vec::new(),
            ControlledTask {
                release: Arc::clone(&release),
            },
        )
        .await
        .expect("controlled task attached");
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
    let slot = session
        .claim_finish_handoff_for_test(Arc::clone(&turn), Ok(None))
        .await
        .expect("exact finish claim");
    let mut handoff = Session::take_finish_handoff(&slot).expect("claimed witness");
    let (done, task_identity, task_epoch) = {
        let task = handoff.task.as_ref().expect("retained task");
        (
            Arc::clone(&task.done),
            Arc::clone(&task.task),
            task.attach_epoch,
        )
    };
    let body_done = done.notified();
    tokio::pin!(body_done);
    body_done.as_mut().enable();
    release.notify_one();
    timeout(Duration::from_secs(2), body_done)
        .await
        .expect("controlled Ok body drained");

    // This directly exercises the shared recovery outcome/proof helpers. Normal
    // Completed finishes currently have no interrupt seed; this is not a claim
    // that the ordinary driver manufactures InterruptedConfirmed candidates.
    let seed = RecoverySeed {
        turn_id: turn.sub_id.clone(),
        authority: Arc::clone(&authority),
        generation: 0,
        request_fingerprint_sha256: "fixture-request".to_string(),
        replay,
        persistence_failure_generation: 0,
        attach_epoch: task_epoch,
        confirmation_generation: None,
    };
    let (seed, preparation) = session
        .prepare_recovery_seed_for_controlled_detach(&turn.sub_id, Some(&authority), Some(seed))
        .await;
    assert_eq!(preparation, RecoveryPreparation::SeedPrepared(1));
    handoff.prepared_terminal_event = Some(Event {
        id: turn.sub_id.clone(),
        msg: EventMsg::TurnComplete(TurnCompleteEvent {
            turn_id: turn.sub_id.clone(),
            last_agent_message: None,
            error: None,
            started_at: None,
            completed_at: None,
            duration_ms: None,
            time_to_first_token_ms: None,
        }),
    });
    session
        .prepare_terminal_event(
            &turn,
            handoff
                .prepared_terminal_event
                .as_ref()
                .expect("retained event"),
        )
        .await;
    session
        .flush_rollout()
        .await
        .expect("real terminal barrier");
    assert_eq!(session.rollout_persistence_failure_generation(), 0);
    {
        let mut active = session.active_turn.lock().await;
        assert!(
            Session::clear_task_terminalization_if_current_locked(
                &mut active,
                &handoff.terminalization_identity,
                TaskTerminalizationKind::Finish,
                &handoff.turn_state,
                &task_identity,
                &turn,
                task_epoch,
            )
            .is_some()
        );
    }
    match case {
        PublicationCase::Confirmed => {}
        PublicationCase::AppendTombstoned | PublicationCase::AppendTombstoneFailed => {
            session
                .inject_rollout_persistence_fault(
                    RolloutPersistenceFault::TurnRecoveryInterruptedConfirmedAppend,
                )
                .await
        }
        PublicationCase::FlushTombstoned | PublicationCase::FlushTombstoneFailed => {
            session
                .inject_rollout_persistence_fault(
                    RolloutPersistenceFault::TurnRecoveryInterruptedConfirmedFlush,
                )
                .await
        }
    }
    let tombstone_fails = matches!(
        case,
        PublicationCase::AppendTombstoneFailed | PublicationCase::FlushTombstoneFailed
    );
    if tombstone_fails {
        // Confirmation failure first tries its own successor, then the outer
        // publication helper attempts its independently observed tombstone.
        for _ in 0..2 {
            session
                .inject_rollout_persistence_fault(
                    RolloutPersistenceFault::TurnRecoveryUnreadyAppend,
                )
                .await;
        }
    }
    let publication = session
        .publish_recovery_seed_after_terminal(seed, /*task_quiesced*/ true, Some(0))
        .await;
    let clean = matches!(case, PublicationCase::Confirmed);
    assert_eq!(
        publication,
        if clean {
            RecoveryPublication::Confirmed(1)
        } else if tombstone_fails {
            RecoveryPublication::TombstoneFailed
        } else {
            RecoveryPublication::Tombstoned
        }
    );
    let result = session
        .publish_ordinary_finish_terminal(
            &mut handoff,
            task_epoch,
            &ThreadIdleCause::Completed,
            Some(0),
            preparation,
            publication,
        )
        .await;
    assert_eq!(
        (
            result,
            handoff.task.is_some(),
            handoff.completion.blocks_admission(),
            handoff.completion.is_complete(),
            handoff.prepared_terminal_event.is_some()
        ),
        (
            FinishTerminalPublication::Published,
            true,
            true,
            false,
            false
        )
    );
    assert!(session.has_pending_admission_fence());
    assert!(session.has_pending_task_terminalization());
    {
        let state = authority.state.lock().await;
        assert_eq!(
            (
                authority.ready.load(Ordering::Acquire),
                state.poisoned,
                state.durable_state,
                state.generation
            ),
            (
                false,
                !clean,
                if clean {
                    DurableRecoveryState::InterruptedConfirmed
                } else {
                    DurableRecoveryState::Unready
                },
                if clean || tombstone_fails { 1 } else { 3 }
            )
        );
    }
    assert_eq!(
        session
            .recovery_candidate
            .lock()
            .expect("candidate")
            .is_some(),
        clean
    );
    assert_eq!(
        session.rollout_persistence_failure_generation(),
        if clean {
            0
        } else if tombstone_fails {
            3
        } else {
            1
        }
    );
    let event = timeout(Duration::from_secs(2), events.recv())
        .await
        .expect("terminal is enqueued")
        .expect("channel open");
    assert!(matches!(event.msg, EventMsg::TurnComplete(_)));
    session.finish_task_terminalization(&handoff.terminalization_identity, &handoff.completion);
    assert!(!session.has_pending_task_terminalization());
}
