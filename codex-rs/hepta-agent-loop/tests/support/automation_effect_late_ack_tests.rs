//! Late dispatch returns cannot replace a receipt already settled through lookup.
use super::*;
use pretty_assertions::assert_eq;
use std::time::Duration;

enum LateAck {
    Matching,
    Contradictory,
}

#[tokio::test]
async fn same_late_ack_replays_the_canonical_recovered_receipt() {
    check_late_ack(LateAck::Matching).await;
}

#[tokio::test]
async fn contradictory_late_ack_cannot_overwrite_recovered_receipt_or_cursor() {
    check_late_ack(LateAck::Contradictory).await;
}

async fn check_late_ack(late_ack: LateAck) {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let other = AutomationStore::open(&fixture.layout)
        .await
        .expect("second connection");
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    provider.dispatch_mode.store(
        match late_ack {
            LateAck::Matching => RELEASE_MATCHING_ACK,
            LateAck::Contradictory => RELEASE_CONTRADICTORY_ACK,
        },
        Ordering::SeqCst,
    );
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
    let mut turn = TaskFlowTurnOwner::open(
        &other,
        fence.clone(),
        frame.binding.clone(),
        initial(),
        Limits::default(),
        StatusContext,
    )
    .await
    .expect("original native cursor");
    let retained;
    let settled_frame;
    let settled_cursor;
    let settled_history;
    {
        let held = dispatch.execute_or_observe(&frame.binding, key, call(&frame));
        tokio::pin!(held);
        tokio::select! {
            result = &mut held => panic!("dispatch returned before explicit release: {result:?}"),
            entered = tokio::time::timeout(Duration::from_secs(3), provider.entered.notified()) => {
                entered.expect("provider persisted original receipt");
            }
        }
        let recovered = tokio::time::timeout(
            Duration::from_secs(3),
            recovery.execute_or_observe(&frame.binding, key, call(&frame)),
        )
        .await
        .expect("bounded lookup recovery")
        .expect("original attempt recovered");
        let EffectObservation::Completed(status) = &recovered else {
            panic!("terminal lookup")
        };
        assert_eq!(provider.lookups.load(Ordering::SeqCst), 1);
        retained = other
            .read_authorized_taskflow_effect_receipt(&intent, "fixture-effect-dispatch")
            .await
            .expect("settled receipt")
            .expect("terminal receipt before late return");
        settled_frame = turn
            .commit(
                &frame,
                Transition::ToolCompleted {
                    operation_key: key,
                    output: status.clone(),
                },
            )
            .await
            .expect("native cursor consumes canonical status");
        let observed = turn.observe().await.expect("capture settled cursor");
        assert_eq!(observed.frame, settled_frame);
        settled_cursor = observed.cursor;
        settled_history = observed.history;
        provider.release.notify_one();
        let late = tokio::time::timeout(Duration::from_secs(3), &mut held)
            .await
            .expect("original dispatch must actually return after release");
        match late_ack {
            LateAck::Matching => assert_eq!(late.expect("idempotent late ACK"), recovered),
            LateAck::Contradictory => assert!(matches!(late,
                Err(codex_hepta_agent_loop::Error::Owner(reason))
                    if reason == "original authorized effect dispatch failed")),
        }
        assert_eq!(
            other
                .read_authorized_taskflow_effect_receipt(&intent, "fixture-effect-dispatch")
                .await
                .expect("unchanged terminal receipt"),
            Some(retained.clone())
        );
        let after = turn.observe().await.expect("unchanged native cursor");
        assert_eq!(after.frame, settled_frame);
        assert_eq!(after.cursor, settled_cursor);
        assert_eq!(after.history, settled_history);
    }
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 1);
    drop(dispatch);
    drop(recovery);
    drop(turn);
    store.close().await;
    other.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("fresh store after late ACK");
    assert_eq!(
        reopened
            .read_authorized_taskflow_effect_receipt(&intent, "fixture-effect-dispatch")
            .await
            .expect("retained full receipt"),
        Some(retained)
    );
    let turn = TaskFlowTurnOwner::open(
        &reopened,
        fence,
        frame.binding,
        initial(),
        Limits::default(),
        StatusContext,
    )
    .await
    .expect("reopen native owner");
    let after = turn.observe().await.expect("retained exact cursor");
    assert_eq!(after.frame, settled_frame);
    assert_eq!(after.cursor, settled_cursor);
    assert_eq!(after.history, settled_history);
    drop(turn);
    reopened.close().await;
}
