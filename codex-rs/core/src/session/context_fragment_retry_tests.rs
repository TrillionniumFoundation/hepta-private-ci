use super::*;
use pretty_assertions::assert_eq;
use test_case::test_case;

fn spawn_fragment(fixture: &Fixture) -> tokio::task::JoinHandle<CodexResult<()>> {
    let io = Arc::clone(&fixture.io);
    let session = Arc::clone(&fixture.session);
    tokio::spawn(async move {
        io.inject_context_fragment_after_finish(&session, vec![item()])
            .await
    })
}

async fn assert_fragment_recorded_once(fixture: &Fixture) {
    assert_eq!(
        recorded_items(fixture).await,
        vec![ResponseItemEnvelope::new(item())],
    );
    assert!(fixture.session.reference_context_item().await.is_none());
}

#[tokio::test]
async fn fragment_waits_for_all_finish_owners_without_client_context_or_provenance() {
    let fixture = fixture(/*initial_context*/ false).await;
    let first = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let second = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await.append_items;
    let waiter = spawn_fragment(&fixture);
    captured(&first).await;
    captured(&second).await;
    assert_eq!(fixture.store.calls().await.append_items, before);
    finish_fence(&fixture.session, &first);
    assert!(!waiter.is_finished());
    assert!(!second.is_complete());
    assert!(recorded_items(&fixture).await.is_empty());
    finish_fence(&fixture.session, &second);
    join(waiter).await.expect("ordinary fragment admission");
    assert_fragment_recorded_once(&fixture).await;
}

#[test_case(TaskTerminalizationKind::Finish; "new_finish_requires_its_own_wait")]
#[test_case(TaskTerminalizationKind::Abort; "new_abort_refuses_without_recording")]
#[tokio::test]
async fn fragment_rechecks_the_new_owner_after_its_captured_finish(
    new_kind: TaskTerminalizationKind,
) {
    let fixture = fixture(/*initial_context*/ false).await;
    let old = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let waiter = spawn_fragment(&fixture);
    captured(&old).await;
    let new = install_fence(&fixture.session, new_kind);
    finish_fence(&fixture.session, &old);
    if new_kind == TaskTerminalizationKind::Finish {
        captured(&new).await;
        assert!(!waiter.is_finished());
        assert!(recorded_items(&fixture).await.is_empty());
        finish_fence(&fixture.session, &new);
        join(waiter).await.expect("fresh fragment admission");
        assert_fragment_recorded_once(&fixture).await;
    } else {
        assert_invalid_request(join(waiter).await);
        assert!(recorded_items(&fixture).await.is_empty());
        assert!(!new.is_complete());
        finish_fence(&fixture.session, &new);
    }
}

#[tokio::test]
async fn cancelling_fragment_wait_leaves_history_and_the_finish_owner_untouched() {
    let fixture = fixture(/*initial_context*/ false).await;
    let fence = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await.append_items;
    let waiter = spawn_fragment(&fixture);
    captured(&fence).await;
    waiter.abort();
    assert!(
        waiter
            .await
            .expect_err("cancelled fragment caller")
            .is_cancelled()
    );
    assert_eq!(Arc::strong_count(&fence), 2);
    assert!(!fence.is_complete());
    assert!(fixture.session.reference_context_item().await.is_none());
    assert_eq!(fixture.store.calls().await.append_items, before);
    assert!(recorded_items(&fixture).await.is_empty());
    finish_fence(&fixture.session, &fence);
}

#[tokio::test]
async fn actor_termination_releases_a_fragment_wait_without_recording() {
    let fixture = fixture(/*initial_context*/ false).await;
    let fence = install_fence(&fixture.session, TaskTerminalizationKind::Finish);
    let before = fixture.store.calls().await.append_items;
    let waiter = spawn_fragment(&fixture);
    captured(&fence).await;
    fixture.actor.abort();
    let error = join(waiter).await.expect_err("actor terminated");
    assert!(matches!(
        error.details(),
        CodexErrorDetails::InternalAgentDied
    ));
    assert_eq!(Arc::strong_count(&fence), 2);
    assert!(!fence.is_complete());
    assert!(fixture.session.reference_context_item().await.is_none());
    assert_eq!(fixture.store.calls().await.append_items, before);
    assert!(recorded_items(&fixture).await.is_empty());
    finish_fence(&fixture.session, &fence);
}

#[test_case(TaskTerminalizationKind::Abort, false; "abort")]
#[test_case(TaskTerminalizationKind::Suspend, false; "suspend")]
#[test_case(TaskTerminalizationKind::Finish, true; "shutdown")]
#[tokio::test]
async fn fragment_refuses_non_finish_barriers_without_writing(
    kind: TaskTerminalizationKind,
    shutting_down: bool,
) {
    let fixture = fixture(/*initial_context*/ false).await;
    let fence = install_fence(&fixture.session, kind);
    if shutting_down {
        fixture.session.begin_shutdown();
    }
    let before = fixture.store.calls().await.append_items;
    assert_invalid_request(join(spawn_fragment(&fixture)).await);
    assert_eq!(Arc::strong_count(&fence), 2);
    assert!(!fence.is_complete());
    assert!(fixture.session.reference_context_item().await.is_none());
    assert_eq!(fixture.store.calls().await.append_items, before);
    assert!(recorded_items(&fixture).await.is_empty());
    finish_fence(&fixture.session, &fence);
}

#[test_case(false; "ordinary_envelope_after_durable_revoke")]
#[test_case(true; "failed_revoke_prevents_enqueue")]
#[tokio::test]
async fn live_fragment_preserves_recovery_ordering_and_ordinary_provenance(poisoned: bool) {
    let fixture = fixture(/*initial_context*/ false).await;
    let authority = Arc::new(TurnRecoveryAuthority::default());
    fixture
        .session
        .spawn_task(
            Arc::clone(&fixture.turn_context),
            Vec::new(),
            PendingRecoverableTask {
                authority: Arc::clone(&authority),
            },
        )
        .await
        .expect("live recovery task");
    assert_eq!(
        fixture
            .session
            .mark_recovery_ready_for_sampling(
                &fixture.turn_context.sub_id,
                &authority,
                fixture.session.rollout_persistence_failure_generation(),
                "context-fragment-finish-test",
            )
            .await
            .expect("durable Ready marker"),
        RecoveryReadyForSampling::Ready,
    );
    authority.state.lock().await.poisoned = poisoned;
    let result = join(spawn_fragment(&fixture)).await;
    let pending = fixture
        .session
        .input_queue
        .get_pending_input(&fixture.session.active_turn)
        .await
        .0;
    let markers = fixture
        .session
        .live_thread()
        .expect("attached history store")
        .load_history(/*include_archived*/ true)
        .await
        .expect("history snapshot")
        .items
        .into_iter()
        .filter_map(|item| match item {
            RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker))
                if marker.turn_id == fixture.turn_context.sub_id =>
            {
                Some(marker.state)
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    if poisoned {
        assert!(
            result
                .expect_err("failed revoke must reject")
                .to_string()
                .contains("recovery provenance is poisoned")
        );
        assert!(pending.is_empty());
        assert_eq!(markers, vec![TurnRecoveryCandidateState::Ready]);
    } else {
        result.expect("accepted live fragment");
        assert!(!authority.ready.load(Ordering::Acquire));
        assert_eq!(
            markers,
            vec![
                TurnRecoveryCandidateState::Ready,
                TurnRecoveryCandidateState::Unready
            ],
        );
        let [PendingTurnInput::ResponseItem(envelope)] = pending.as_slice() else {
            panic!("exactly one ordinary context item must enter the live turn");
        };
        assert_eq!(envelope, &ResponseItemEnvelope::new(item()));
    }
    assert!(fixture.session.reference_context_item().await.is_none());
    authority.state.lock().await.poisoned = false;
    fixture
        .session
        .abort_all_tasks(TurnAbortReason::Interrupted)
        .await;
}
