//! Concurrency controls over the original SQLite owners and existing file provider.
use super::*;
use pretty_assertions::assert_eq;
use std::time::Duration;

#[tokio::test]
async fn duplicate_admission_from_two_connections_dispatches_once() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let other = AutomationStore::open(&fixture.layout)
        .await
        .expect("second connection");
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    let key = admitted(&frame, &intent, &fence, &grant).operation_key();
    let mut left = AutomationStatusEffectOwner::new(
        &store,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    let mut right = AutomationStatusEffectOwner::new(
        &other,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    let (one, two) = tokio::time::timeout(Duration::from_secs(10), async {
        tokio::join!(
            left.execute_or_observe(&frame.binding, key, call(&frame)),
            right.execute_or_observe(&frame.binding, key, call(&frame)),
        )
    })
    .await
    .expect("bounded duplicate delivery race");
    assert!(
        one.is_ok() || two.is_ok(),
        "both attempts failed: {one:?} {two:?}"
    );
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    // One bounded observation after the race must settle the original attempt.
    let observed = left
        .execute_or_observe(&frame.binding, key, call(&frame))
        .await
        .expect("original attempt observation");
    assert!(matches!(observed, EffectObservation::Completed(_)));
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    let receipt = store
        .read_authorized_taskflow_effect_receipt(&intent, "fixture-effect-dispatch")
        .await
        .expect("original receipt lookup")
        .expect("terminal receipt");
    assert_eq!(
        other
            .read_authorized_taskflow_effect_receipt(&intent, "fixture-effect-dispatch")
            .await
            .expect("same durable receipt"),
        Some(receipt)
    );
    assert!(
        store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, 2)
            .await
            .expect("no second attempt")
            .is_none()
    );
    drop(left);
    drop(right);
    store.close().await;
    other.close().await;
}

#[tokio::test]
async fn overlapping_recovery_settles_before_original_dispatch_future_is_dropped() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let other = AutomationStore::open(&fixture.layout)
        .await
        .expect("second connection");
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    provider
        .dispatch_mode
        .store(HOLD_AFTER_PERSIST, Ordering::SeqCst);
    let key = admitted(&frame, &intent, &fence, &grant).operation_key();
    let mut dispatch = AutomationStatusEffectOwner::new(
        &store,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    let mut recovery = AutomationStatusEffectOwner::new(
        &other,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    let retained;
    {
        let held = dispatch.execute_or_observe(&frame.binding, key, call(&frame));
        tokio::pin!(held);
        tokio::select! {
            result = &mut held => panic!("dispatch must remain held: {result:?}"),
            entered = tokio::time::timeout(Duration::from_secs(3), provider.entered.notified()) => {
                entered.expect("provider persisted before recovery starts");
            }
        }
        assert!(
            store
                .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
                .await
                .expect("attempt precedes contact")
                .is_some()
        );
        let observed = tokio::time::timeout(
            Duration::from_secs(3),
            recovery.execute_or_observe(&frame.binding, key, call(&frame)),
        )
        .await
        .unwrap_or_else(|_| {
            panic!(
                "recovery blocked; dispatch entries: {}",
                provider.dispatches.load(Ordering::SeqCst)
            )
        })
        .expect("overlapping original-attempt recovery");
        assert!(matches!(observed, EffectObservation::Completed(_)));
        assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
        assert_eq!(provider.lookups.load(Ordering::SeqCst), 1);
        retained = other
            .read_authorized_taskflow_effect_receipt(&intent, "fixture-effect-dispatch")
            .await
            .expect("settled while original future alive")
            .expect("terminal receipt");
    }
    assert_eq!(
        recovery
            .cancel(&frame.binding)
            .await
            .expect("no provider stop API"),
        StopObservation::Unresolved
    );
    drop(dispatch);
    drop(recovery);
    store.close().await;
    other.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("close and reopen");
    assert_eq!(
        reopened
            .read_authorized_taskflow_effect_receipt(&intent, "fixture-effect-dispatch")
            .await
            .expect("same terminal record after drop"),
        Some(retained)
    );
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    reopened.close().await;
}

#[tokio::test]
async fn tool_completion_and_cancellation_have_one_cursor_winner() {
    // Directed controls cover both outcomes; join adds a real competing-CAS schedule.
    for schedule in ["cancel-first", "tool-first", "concurrent"] {
        let fixture = Fixture::new();
        let (store, fence, frame) = fixture.native().await;
        let other = AutomationStore::open(&fixture.layout)
            .await
            .expect("second connection");
        let intent = prepare_effect(&store, &fence, &frame).await;
        let (authority, grant) = fixture.authority(&intent);
        let provider = FileProvider::new(fixture.temp.path());
        let key = admitted(&frame, &intent, &fence, &grant).operation_key();
        let mut effects = AutomationStatusEffectOwner::new(
            &store,
            &authority,
            driver(&intent, &provider),
            admitted(&frame, &intent, &fence, &grant),
        );
        let EffectObservation::Completed(status) = effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("actual authorized status")
        else {
            panic!("terminal status")
        };
        let mut tool_owner = TaskFlowTurnOwner::open(
            &store,
            fence.clone(),
            frame.binding.clone(),
            initial(),
            Limits::default(),
            StatusContext,
        )
        .await
        .expect("tool cursor owner");
        let mut cancel_owner = TaskFlowTurnOwner::open(
            &other,
            fence,
            frame.binding.clone(),
            initial(),
            Limits::default(),
            StatusContext,
        )
        .await
        .expect("cancel cursor owner");
        let completion = Transition::ToolCompleted {
            operation_key: key,
            output: status,
        };
        let (tool, cancel) = match schedule {
            "cancel-first" => {
                let cancel = cancel_owner
                    .commit(&frame, Transition::CancelRequested)
                    .await;
                (tool_owner.commit(&frame, completion.clone()).await, cancel)
            }
            "tool-first" => {
                let tool = tool_owner.commit(&frame, completion.clone()).await;
                (
                    tool,
                    cancel_owner
                        .commit(&frame, Transition::CancelRequested)
                        .await,
                )
            }
            _ => tokio::time::timeout(Duration::from_secs(10), async {
                tokio::join!(
                    tool_owner.commit(&frame, completion.clone()),
                    cancel_owner.commit(&frame, Transition::CancelRequested)
                )
            })
            .await
            .expect("bounded cursor race"),
        };
        assert_eq!(
            usize::from(tool.is_ok()) + usize::from(cancel.is_ok()),
            1,
            "{schedule}"
        );
        let tool_won = tool.is_ok();
        let (winner, next) = match (tool, cancel) {
            (Ok(winner), Err(_)) => {
                let next = cancel_owner
                    .commit(&winner, Transition::CancelRequested)
                    .await
                    .expect("cancel based on the new tool successor");
                (winner, next)
            }
            (Err(_), Ok(winner)) => {
                assert!(tool_owner.commit(&frame, completion).await.is_err());
                (winner.clone(), winner)
            }
            _ => unreachable!("one durable winner"),
        };
        assert_eq!(winner.revision, frame.revision + 1);
        assert_eq!(next.phase, Phase::CancelRequested);
        assert_eq!(next.consumed_tokens, frame.consumed_tokens);
        assert_eq!(
            next.round,
            if tool_won {
                frame.round + 1
            } else {
                frame.round
            }
        );
        let observed = cancel_owner.observe().await.expect("final cursor evidence");
        assert_eq!(observed.frame, next);
        assert_eq!(observed.cursor.revision, next.revision + 1);
        assert_eq!(observed.history.len() as u64, next.revision);
        assert_eq!(
            effects.cancel(&frame.binding).await.expect("no remote ACK"),
            StopObservation::Unresolved
        );
        assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
        drop(effects);
        drop(tool_owner);
        drop(cancel_owner);
        store.close().await;
        other.close().await;
    }
}
