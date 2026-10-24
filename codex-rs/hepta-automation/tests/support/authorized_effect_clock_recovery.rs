//! Time uncertainty and entered effects remain with the original recovery owner.
#![allow(clippy::expect_used, reason = "actual original-owner recovery fixture")]

use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedEffectRecoveryResult;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;

use super::super::EFFECT_PAYLOAD;
use super::super::Fixture;
use super::super::binding;
use super::super::fence;
use super::super::intent;
use super::driver::FileDriver;
use super::driver::activate;
use super::driver::queued_store;
use super::driver::spawn_dispatch;
use super::fixture::Clock;
use super::fixture::Security;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_expiry_after_driver_entry_preserves_uncertainty_and_original_recovery() {
    let fixture = Fixture::new();
    let effect = intent();
    let store = queued_store(&fixture, &effect.run_id).await;
    let observer = AutomationStore::open(&fixture.layout)
        .await
        .expect("second owner connection");
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&effect),
        "entry-wins",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    let authority = security.authority.clone();
    let witness = fixture._temp.path().join("actual-effect");
    let mut driver = FileDriver::new(witness.clone());
    let calls = driver.calls.clone();
    let entered = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    driver.pause = Some((entered.clone(), release.clone()));
    let running = spawn_dispatch(
        store,
        security,
        effect.clone(),
        driver,
        /*lease_duration*/ 100,
        /*asynchronous*/ true,
    );
    running.ready.await.expect("original typed claim");
    running.start.send(()).expect("controlled entry");
    tokio::time::timeout(Duration::from_secs(/*secs*/ 3), entered.notified())
        .await
        .expect("actual effect entry");
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        std::fs::read(&witness).expect("actual effect bytes"),
        EFFECT_PAYLOAD
    );
    let run = observer
        .taskflow_run(&effect.run_id)
        .await
        .expect("run")
        .expect("present");
    let cancel = TaskFlowCommand::new(
        &effect.run_id,
        "no-stop-from-local-expiry",
        fence(),
        run.revision,
        TaskFlowTransition::Cancel {
            reason: "no provider cancellation ACK".into(),
        },
        /*now_ms*/ 1_000,
    )
    .expect("cancel request");
    assert!(observer.apply_taskflow_command(&cancel).await.is_err());
    assert_eq!(
        observer
            .taskflow_run(&effect.run_id)
            .await
            .expect("original fence")
            .expect("run"),
        run
    );
    clock.set(/*now*/ 1_100);
    release.notify_one();
    let receipt = tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.task)
        .await
        .expect("effect resolves")
        .expect("task")
        .expect("original uncertain receipt after expiry");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    let current = observer
        .taskflow_run(&effect.run_id)
        .await
        .expect("recoverable run")
        .expect("present");
    assert_eq!(current.state, TaskFlowRunState::Indeterminate);
    assert!(!current.cancel_requested);
    assert_eq!(
        current.fencing_token.as_deref(),
        Some(fence().fencing_token.as_str())
    );
    let recovered = observer
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &fence(),
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(
                    &std::fs::read(&witness).expect("original provider witness"),
                ),
            }),
            /*observed_at_ms*/ 1_100,
        )
        .await
        .expect("original-key terminal evidence after expiry");
    assert!(matches!(
        recovered,
        AuthorizedEffectRecoveryResult::Observed(_)
    ));
    assert_eq!(
        observer
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Succeeded
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(authority.capacity().expect("one grant").used_nonces, 1);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_unavailable_after_contact_does_not_fabricate_absence_or_retry() {
    let fixture = Fixture::new();
    let effect = intent();
    let store = queued_store(&fixture, &effect.run_id).await;
    let observer = AutomationStore::open(&fixture.layout)
        .await
        .expect("second original owner");
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&effect),
        "clock-fails-after-contact",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    let authority = security.authority.clone();
    let witness = fixture._temp.path().join("actual-effect");
    let mut driver = FileDriver::new(witness.clone());
    let calls = driver.calls.clone();
    driver.invalidate_clock = Some(clock.clone());
    let running = spawn_dispatch(
        store,
        security,
        effect.clone(),
        driver,
        /*lease_duration*/ 100,
        /*asynchronous*/ true,
    );
    running.ready.await.expect("typed claim ready");
    running.start.send(()).expect("controlled dispatch");
    assert!(
        tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.task)
            .await
            .expect("dispatch resolves")
            .expect("task")
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        std::fs::read(&witness).expect("actual effect"),
        EFFECT_PAYLOAD
    );
    assert!(
        observer
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("original attempt")
            .is_some()
    );
    assert!(
        observer
            .settle_authorized_taskflow_effect_observation(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &fence()
            )
            .await
            .expect("no invented terminal evidence")
            .is_none()
    );
    assert_eq!(
        observer
            .pending_authorized_taskflow_effects(/*limit*/ 8)
            .await
            .expect("recoverable original attempt")
            .len(),
        1
    );
    clock.unavailable(/*value*/ false);
    clock.set(/*now*/ 1_100);
    let recovered = observer
        .recover_authorized_taskflow_effect(
            &effect.run_id,
            &effect.step_id,
            effect.attempt,
            &fence(),
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(
                    &std::fs::read(&witness).expect("original owner output witness"),
                ),
            }),
            /*observed_at_ms*/ 1_100,
        )
        .await
        .expect("original effect can reconcile after time recovers");
    assert!(matches!(
        recovered,
        AuthorizedEffectRecoveryResult::Observed(_)
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(authority.capacity().expect("no new grant").used_nonces, 1);
}

#[tokio::test]
async fn effect_clock_claim_does_not_revive_after_owner_clear_and_same_fence_reclaim() {
    let fixture = Fixture::new();
    let effect = intent();
    let store = queued_store(&fixture, &effect.run_id).await;
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&effect),
        "clock-claim-no-aba",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    let owner = fence();
    let claim = store
        .claim_taskflow_run_with_authority_clock(
            &security.authority,
            &effect.run_id,
            &owner,
            /*lease_duration_ms*/ 100,
        )
        .await
        .expect("original typed claim");
    activate(&store, &claim, &effect).await;
    let mut driver = FileDriver::new(fixture._temp.path().join("no-provider-contact"));
    driver.reject_before_contact = true;
    assert!(
        claim
            .execute_authorized_effect(
                &mut driver,
                &effect,
                EFFECT_PAYLOAD,
                &security.signed,
                &binding(&effect),
                "clock-effect"
            )
            .await
            .is_err()
    );
    let cleared = store
        .taskflow_run(&effect.run_id)
        .await
        .expect("original absence recovery")
        .expect("run");
    assert_eq!(cleared.state, TaskFlowRunState::Queued);
    assert!(cleared.lease_expires_at_ms.is_none());
    // Original lease_claimed command identity is UNIQUE in taskflow_events.
    // Even identical clock/deadline/fence cannot commit a second same-generation lease.
    for epoch in [owner.owner_epoch, owner.owner_epoch + 1] {
        let mut reused = owner.clone();
        reused.owner_epoch = epoch;
        assert!(
            store
                .claim_taskflow_run_with_authority_clock(
                    &security.authority,
                    &effect.run_id,
                    &reused,
                    /*lease_duration_ms*/ 100
                )
                .await
                .is_err()
        );
        assert_eq!(
            store
                .taskflow_run(&effect.run_id)
                .await
                .expect("atomic rollback")
                .expect("run"),
            cleared
        );
    }
    let mut successor = owner.clone();
    successor.generation += 1;
    successor.fencing_token = "legitimate-new-clock-generation".into();
    let next = store
        .claim_taskflow_run_with_authority_clock(
            &security.authority,
            &effect.run_id,
            &successor,
            /*lease_duration_ms*/ 100,
        )
        .await
        .expect("new claim after original-owner absence proof");
    assert_eq!(next.fence(), &successor);
    let restart = TaskFlowCommand::new(
        &effect.run_id,
        "successor-start",
        successor.clone(),
        next.run().revision,
        TaskFlowTransition::Start,
        /*now_ms*/ 1_000,
    )
    .expect("successor command");
    store
        .apply_taskflow_command(&restart)
        .await
        .expect("historical absent step keeps its old fence");
    let mut subsequent = effect.clone();
    subsequent.attempt += 1;
    let digest = subsequent.digest().expect("new attempt exact intent");
    store
        .prepare_taskflow_step(
            &subsequent.run_id,
            &subsequent.step_id,
            subsequent.attempt,
            &successor,
            &digest,
            &subsequent.payload_digest,
            "successor-prepare",
            /*now_ms*/ 1_000,
        )
        .await
        .expect("new generation may prepare a distinct attempt");
    store
        .claim_taskflow_step(
            &subsequent.run_id,
            &subsequent.step_id,
            subsequent.attempt,
            &successor,
            &digest,
            &subsequent.payload_digest,
            "successor-step-claim",
            /*now_ms*/ 1_000,
        )
        .await
        .expect("new generation may claim its exact attempt");
    driver.reject_before_contact = false;
    assert!(
        claim
            .execute_authorized_effect(
                &mut driver,
                &effect,
                EFFECT_PAYLOAD,
                &security.signed,
                &binding(&effect),
                "clock-effect"
            )
            .await
            .is_err()
    );
    assert_eq!(driver.calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        security
            .authority
            .capacity()
            .expect("no refund/new grant")
            .used_nonces,
        1
    );
}
