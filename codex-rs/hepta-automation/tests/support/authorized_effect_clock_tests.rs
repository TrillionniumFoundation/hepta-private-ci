//! Same-clock tests use the real original SQLite and FinalUse owners.
#![allow(clippy::expect_used, reason = "explicit clock race fixture invariants")]

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_contracts::AuthorityClock;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;

use super::EFFECT_PAYLOAD;
use super::Fixture;
use super::binding;
use super::definition;
use super::fence;
use super::intent;
use super::prepared_effect_store;

#[path = "authorized_effect_clock_absence_race.rs"]
mod absence_race;
#[path = "authorized_effect_clock_driver.rs"]
mod driver;
#[path = "authorized_effect_clock_faults.rs"]
mod faults;
#[path = "authorized_effect_clock_fixture.rs"]
mod fixture;
#[path = "authorized_effect_clock_lifetime_tests.rs"]
mod lifetime;
#[path = "authorized_effect_clock_multiplicity.rs"]
mod multiplicity;
#[path = "authorized_effect_clock_recovery.rs"]
mod recovery;
#[path = "authorized_effect_clock_transitions.rs"]
mod transitions;

use driver::FileDriver;
use driver::activate;
use driver::queued_store;
use driver::spawn_dispatch;
use fixture::Clock;
use fixture::Security;

#[test]
fn effect_clock_observation_uses_existing_source_without_claim_or_fallback() {
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&intent()),
        "observe-only",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    let before = security
        .authority
        .frontier()
        .expect("original FinalUse frontier");
    assert_eq!(
        security
            .authority
            .observe_now_unix_ms()
            .expect("configured clock"),
        1_000
    );
    clock.set(/*now*/ 1_001);
    assert_eq!(
        security
            .authority
            .observe_now_unix_ms()
            .expect("fresh configured clock"),
        1_001
    );
    clock.unavailable(/*value*/ true);
    assert!(security.authority.observe_now_unix_ms().is_err());
    assert_eq!(
        security
            .authority
            .frontier()
            .expect("same FinalUse frontier"),
        before
    );
    assert_eq!(
        security
            .authority
            .capacity()
            .expect("nonce state")
            .used_nonces,
        0
    );
}

#[tokio::test]
async fn effect_clock_claim_refuses_legacy_lease_without_inferring_numeric_expiry() {
    let fixture = Fixture::new();
    let (store, owner, effect, expected) = prepared_effect_store(&fixture).await;
    let original = store
        .taskflow_run(&effect.run_id)
        .await
        .expect("run")
        .expect("present");
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        expected,
        "no-legacy-wrap",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    for now in [1_000, 2_000] {
        clock.set(now);
        let mut candidate = owner.clone();
        candidate.generation += 1;
        candidate.fencing_token = "no-clock-takeover-inference".into();
        assert!(
            store
                .claim_taskflow_run_with_authority_clock(
                    &security.authority,
                    &effect.run_id,
                    &candidate,
                    /*lease_duration_ms*/ 1_000
                )
                .await
                .is_err()
        );
        assert_eq!(
            store
                .taskflow_run(&effect.run_id)
                .await
                .expect("unchanged run")
                .expect("run"),
            original
        );
    }
    // Preserve old validation even when its active lease replay would succeed.
    assert!(matches!(
        store
            .claim_taskflow_run(&effect.run_id, &owner, /*now_ms*/ 21, u64::MAX)
            .await,
        Err(TaskFlowError::Invalid(_))
    ));
    assert_eq!(
        store
            .claim_taskflow_run(
                &effect.run_id,
                &owner,
                /*now_ms*/ 21,
                /*lease_duration_ms*/ 1_000
            )
            .await
            .expect("legacy replay"),
        original
    );
    assert_eq!(
        security
            .authority
            .capacity()
            .expect("no effect grant")
            .used_nonces,
        0
    );
}

#[tokio::test]
async fn effect_clock_claim_cannot_be_reconstructed_from_another_connection() {
    let fixture = Fixture::new();
    let effect = intent();
    let store = queued_store(&fixture, &effect.run_id).await;
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&effect),
        "no-reconstruction",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    let claim = store
        .claim_taskflow_run_with_authority_clock(
            &security.authority,
            &effect.run_id,
            &fence(),
            /*lease_duration_ms*/ 100,
        )
        .await
        .expect("new original clock claim");
    assert_eq!(claim.run().updated_at_ms, 1_000);
    assert_eq!(claim.expires_at_unix_ms(), 1_100);
    let other = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopened original DB");
    for now in [1_000, 1_200] {
        clock.set(now);
        assert!(
            other
                .claim_taskflow_run_with_authority_clock(
                    &security.authority,
                    &effect.run_id,
                    &fence(),
                    /*lease_duration_ms*/ 100
                )
                .await
                .is_err()
        );
    }
    assert_eq!(
        security
            .authority
            .capacity()
            .expect("clock claim is not final-use")
            .used_nonces,
        0
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_expiry_during_actual_sqlite_lock_wait_prevents_attempt_and_contact() {
    let fixture = Fixture::new();
    let effect = intent();
    let store = queued_store(&fixture, &effect.run_id).await;
    let workflow = definition();
    store
        .create_taskflow_run(
            "clock-lock-holder",
            &workflow.workflow_id,
            workflow.version,
            workflow.definition_digest(),
            "clock-blocker",
            /*now_ms*/ 1_000,
        )
        .await
        .expect("unleased lock-holder run");
    let competitor = AutomationStore::open(&fixture.layout)
        .await
        .expect("second actual SQLite owner");
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&effect),
        "expires-during-lock",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    let authority = security.authority.clone();
    let witness = fixture._temp.path().join("effect");
    let driver = FileDriver::new(witness.clone());
    let calls = driver.calls.clone();
    let running = spawn_dispatch(
        store,
        security,
        effect.clone(),
        driver,
        /*lease_duration*/ 100,
        /*asynchronous*/ true,
    );
    running
        .ready
        .await
        .expect("typed claim and original step ready");

    let blocker_clock = Clock::new(/*now*/ 1_000);
    let blocker = Security::new(
        binding(&effect),
        "only-holds-original-sqlite-tx",
        blocker_clock.clone(),
        /*expiry*/ 5_000,
    );
    blocker_clock.block_on(/*call*/ 1);
    let holding = tokio::spawn(async move {
        competitor
            .claim_taskflow_run_with_authority_clock(
                &blocker.authority,
                "clock-lock-holder",
                &fence(),
                /*lease_duration_ms*/ 100,
            )
            .await
            .map(|_| ())
    });
    // The new claim samples only AFTER BEGIN IMMEDIATE and awaited state reads.
    blocker_clock.entered().await;
    running
        .start
        .send(())
        .expect("start effect behind actual SQLite writer");
    clock.calls_reached(/*count*/ 2).await; // Original nonce claim persisted; next boundary is DB admission.
    clock.set(/*now*/ 1_100); // Lease expiry; grant remains valid until 5,000.
    blocker_clock.release();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 3), holding)
        .await
        .expect("release SQLite owner")
        .expect("writer task")
        .expect("other run's original lease");
    let result = tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.task)
        .await
        .expect("bounded dispatch")
        .expect("dispatch task");
    assert!(result.is_err());
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert!(!witness.exists());
    assert_eq!(
        authority
            .capacity()
            .expect("original nonce retained")
            .used_nonces,
        1
    );
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("original store verification");
    assert!(
        reopened
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("original attempt lookup")
            .is_none()
    );
    assert_eq!(
        reopened
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Running
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_postcommit_expiry_uses_original_proven_absence_for_both_entry_paths() {
    for (asynchronous, lease, elapsed) in [
        (false, 100, 1_100),
        (true, 100, 1_100),
        (true, 10_000, 5_000),
    ] {
        let fixture = Fixture::new();
        let effect = intent();
        let store = queued_store(&fixture, &effect.run_id).await;
        let observer = AutomationStore::open(&fixture.layout)
            .await
            .expect("independent original connection");
        let clock = Clock::new(/*now*/ 1_000);
        let security = Security::new(
            binding(&effect),
            "postcommit-expiry",
            clock.clone(),
            /*expiry*/ 5_000,
        );
        let authority = security.authority.clone();
        let witness = fixture._temp.path().join("effect");
        let driver = FileDriver::new(witness.clone());
        let calls = Arc::clone(&driver.calls);
        let running = spawn_dispatch(store, security, effect.clone(), driver, lease, asynchronous);
        running.ready.await.expect("new typed claim ready");
        // Two claim samples, one inside-TX admission sample, one original
        // FinalUse entry sample, then this additional guarded driver sample.
        clock.block_on(/*call*/ 5);
        running.start.send(()).expect("controlled start");
        clock.entered().await;
        let pending = observer
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("original attempt")
            .expect("committed before final clock sample");
        assert_eq!(pending.grant_id, "postcommit-expiry");
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        clock.set(elapsed);
        clock.release();
        assert!(
            tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.task)
                .await
                .expect("entry resolves")
                .expect("task")
                .is_err()
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
        assert!(!witness.exists());
        let result = observer
            .settle_authorized_taskflow_effect_observation(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &fence(),
            )
            .await
            .expect("original local absence evidence");
        assert!(matches!(
            result,
            Some(codex_hepta_automation::AuthorizedEffectRecoveryResult::ProvenAbsent)
        ));
        let run = observer
            .taskflow_run(&effect.run_id)
            .await
            .expect("run")
            .expect("present");
        assert_eq!(run.state, TaskFlowRunState::Queued);
        assert!(run.lease_expires_at_ms.is_none());
        assert!(
            !run.cancel_requested,
            "local no-contact proof is not a cancellation ACK"
        );
        assert_eq!(
            authority.capacity().expect("no nonce refund").used_nonces,
            1
        );
    }
}

#[tokio::test]
async fn effect_clock_wrong_run_is_rejected_before_final_use_claim() {
    let fixture = Fixture::new();
    let effect = intent();
    let store = queued_store(&fixture, &effect.run_id).await;
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&effect),
        "wrong-run-clock-claim",
        clock,
        /*expiry*/ 5_000,
    );
    let claim = store
        .claim_taskflow_run_with_authority_clock(
            &security.authority,
            &effect.run_id,
            &fence(),
            /*lease_duration_ms*/ 100,
        )
        .await
        .expect("typed claim");
    activate(&store, &claim, &effect).await;
    let mut wrong = effect.clone();
    wrong.run_id = "different-run".into();
    let mut driver = FileDriver::new(fixture._temp.path().join("must-not-exist"));
    assert!(
        claim
            .execute_authorized_effect(
                &mut driver,
                &wrong,
                super::EFFECT_PAYLOAD,
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
            .expect("no grant consumed")
            .used_nonces,
        0
    );
    assert_eq!(security.clock.now_unix_ms().expect("original clock"), 1_000);
}
