//! Recovery uses the original store, intent and explicit fixture issuer.

use super::*;
use codex_hepta_contracts::FinalUseRevocations;
use pretty_assertions::assert_eq;
use std::collections::BTreeSet;
use std::time::Duration;

#[tokio::test]
async fn uncertain_effect_reopens_and_reconciles_original_receipt_without_redispatch() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    provider.dispatch_mode.store(UNKNOWN, Ordering::SeqCst);
    let original = admitted(&frame, &intent, &fence, &grant);
    let key = original.operation_key();
    let mut effects =
        AutomationStatusEffectOwner::new(&store, &authority, driver(&intent, &provider), original);
    assert_eq!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("ambiguous contact retained"),
        EffectObservation::Unresolved
    );
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("effect run")
            .expect("present")
            .state,
        TaskFlowRunState::Indeterminate
    );
    drop(effects);
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen uncertain owner");
    let mut effects = AutomationStatusEffectOwner::new(
        &reopened,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    for mode in [UNKNOWN, WRONG_PAYLOAD] {
        provider.lookup_mode.store(mode, Ordering::SeqCst);
        assert_eq!(
            effects
                .execute_or_observe(&frame.binding, key, call(&frame))
                .await
                .expect("uncertain or mismatched lookup"),
            EffectObservation::Unresolved
        );
    }
    provider.lookup_mode.store(COMPLETE, Ordering::SeqCst);
    assert!(matches!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("original provider recovery"),
        EffectObservation::Completed(_)
    ));
    assert_eq!(provider.payload(), call(&frame).arguments.as_bytes());
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 3);
    let retained = reopened
        .read_authorized_taskflow_effect_receipt(&intent, "fixture-effect-dispatch")
        .await
        .expect("original terminal evidence")
        .expect("terminal receipt");
    assert_eq!(
        retained.final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded)
    );
}

#[tokio::test]
async fn dropped_dispatch_future_keeps_original_attempt_and_cancel_never_fakes_stop_ack() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    provider
        .dispatch_mode
        .store(HOLD_AFTER_PERSIST, Ordering::SeqCst);
    let original = admitted(&frame, &intent, &fence, &grant);
    let key = original.operation_key();
    let mut effects =
        AutomationStatusEffectOwner::new(&store, &authority, driver(&intent, &provider), original);
    {
        let pending = effects.execute_or_observe(&frame.binding, key, call(&frame));
        tokio::pin!(pending);
        tokio::select! {
            _ = &mut pending => panic!("fixture must hold after the physical effect"),
            entered = tokio::time::timeout(Duration::from_secs(3), provider.entered.notified()) => {
                entered.expect("original driver crossed its physical boundary");
            }
        }
    }
    assert_eq!(
        effects
            .cancel(&frame.binding)
            .await
            .expect("local cancellation observation"),
        StopObservation::Unresolved
    );
    assert_eq!(provider.payload(), call(&frame).arguments.as_bytes());
    assert!(
        store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .expect("original durable attempt")
            .is_some()
    );
    drop(effects);
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen lost acknowledgement");
    let mut recovery = AutomationStatusEffectOwner::new(
        &reopened,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    assert!(matches!(
        recovery
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("same-attempt status recovery"),
        EffectObservation::Completed(_)
    ));
    assert_eq!(
        recovery
            .cancel(&frame.binding)
            .await
            .expect("completion is not a stop ACK"),
        StopObservation::Unresolved
    );
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 1);
}

#[tokio::test]
async fn original_revocation_and_local_cancel_prevent_new_provider_entry() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    let key = admitted(&frame, &intent, &fence, &grant).operation_key();
    let mut cancelled = AutomationStatusEffectOwner::new(
        &store,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    assert_eq!(
        cancelled
            .cancel(&frame.binding)
            .await
            .expect("no provider cancellation API"),
        StopObservation::Unresolved
    );
    assert_eq!(
        cancelled
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("fresh contact disabled"),
        EffectObservation::Unresolved
    );
    drop(cancelled);
    authority
        .update_revocations(FinalUseRevocations {
            authority_epoch: 9,
            revision: 2,
            revoked_grant_ids: BTreeSet::from([grant.grant.grant_id.clone()]),
        })
        .expect("original authority revocation");
    let mut revoked = AutomationStatusEffectOwner::new(
        &store,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &fence, &grant),
    );
    assert!(
        revoked
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .is_err()
    );
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 0);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 0);
    assert!(
        store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
            .await
            .expect("no durable contact")
            .is_none()
    );
}

#[tokio::test]
async fn original_proven_absence_never_creates_another_attempt() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    provider
        .dispatch_mode
        .store(BEFORE_CONTACT, Ordering::SeqCst);
    let original = admitted(&frame, &intent, &fence, &grant);
    let key = original.operation_key();
    let mut effects =
        AutomationStatusEffectOwner::new(&store, &authority, driver(&intent, &provider), original);
    assert!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .is_err()
    );
    assert!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .is_err()
    );
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 0);
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("original run")
            .expect("present")
            .state,
        TaskFlowRunState::Queued
    );
    assert!(
        store
            .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt + 1)
            .await
            .expect("no replacement attempt")
            .is_none()
    );
}

#[tokio::test]
async fn stale_owner_fence_cannot_reconcile_or_contact_provider() {
    let fixture = Fixture::new();
    let (store, fence, frame) = fixture.native().await;
    let intent = prepare_effect(&store, &fence, &frame).await;
    let (authority, grant) = fixture.authority(&intent);
    let provider = FileProvider::new(fixture.temp.path());
    provider.dispatch_mode.store(UNKNOWN, Ordering::SeqCst);
    let original = admitted(&frame, &intent, &fence, &grant);
    let key = original.operation_key();
    let mut effects =
        AutomationStatusEffectOwner::new(&store, &authority, driver(&intent, &provider), original);
    assert_eq!(
        effects
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .expect("unknown contact"),
        EffectObservation::Unresolved
    );
    let original_run = store
        .taskflow_run(&intent.run_id)
        .await
        .expect("run")
        .expect("present");
    let mut replacement = fence.clone();
    replacement.generation = 2;
    replacement.fencing_token = "explicit-fixture-new-fence".into();
    // The original owner already forbids taking over an unresolved effect.
    assert!(
        store
            .claim_taskflow_run(
                &intent.run_id,
                &replacement,
                original_run.lease_expires_at_ms.expect("original lease") + 1,
                600_000
            )
            .await
            .is_err()
    );
    drop(effects);
    let mut stale_fence = fence.clone();
    stale_fence.fencing_token = "not-the-original-fence".into();
    let mut stale = AutomationStatusEffectOwner::new(
        &store,
        &authority,
        driver(&intent, &provider),
        admitted(&frame, &intent, &stale_fence, &grant),
    );
    assert!(
        stale
            .execute_or_observe(&frame.binding, key, call(&frame))
            .await
            .is_err()
    );
    assert_eq!(provider.dispatches.load(Ordering::SeqCst), 1);
    assert_eq!(provider.lookups.load(Ordering::SeqCst), 0);
    assert_eq!(
        store
            .taskflow_run(&intent.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Indeterminate
    );
}
