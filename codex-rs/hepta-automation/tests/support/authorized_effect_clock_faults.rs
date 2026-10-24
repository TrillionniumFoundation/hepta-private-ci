//! Failures must not publish a usable stale clock claim or a fabricated effect.
#![allow(
    clippy::expect_used,
    reason = "controlled original-owner clock failure fixtures"
)]

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowRunState;
use pretty_assertions::assert_eq;
use std::sync::atomic::Ordering;
use std::time::Duration;

use super::super::Fixture;
use super::super::binding;
use super::super::fence;
use super::super::intent;
use super::driver::FileDriver;
use super::driver::queued_store;
use super::driver::spawn_dispatch;
use super::fixture::Clock;
use super::fixture::Security;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_claim_expiring_after_commit_returns_no_reconstructible_handle() {
    let fixture = Fixture::new();
    let effect = intent();
    let store = queued_store(&fixture, &effect.run_id).await;
    let observer = AutomationStore::open(&fixture.layout)
        .await
        .expect("second actual store");
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&effect),
        "claim-commit-expiry",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    let authority = security.authority.clone();
    let run_id = effect.run_id.clone();
    // Initial in-TX sample, refreshed pre-update sample, then post-commit sample.
    clock.block_on(/*call*/ 3);
    let task = tokio::spawn(async move {
        store
            .claim_taskflow_run_with_authority_clock(
                &authority,
                &run_id,
                &fence(),
                /*lease_duration_ms*/ 100,
            )
            .await
            .map(|_| ())
    });
    clock.entered().await;
    let committed = observer
        .taskflow_run(&effect.run_id)
        .await
        .expect("committed original claim")
        .expect("run");
    assert_eq!(committed.lease_expires_at_ms, Some(1_100));
    clock.set(/*now*/ 1_100);
    clock.release();
    assert!(
        tokio::time::timeout(Duration::from_secs(/*secs*/ 3), task)
            .await
            .expect("claim completes")
            .expect("claim task")
            .is_err()
    );
    assert_eq!(
        observer
            .taskflow_run(&effect.run_id)
            .await
            .expect("claim is not rolled back")
            .expect("run"),
        committed
    );
    assert!(
        observer
            .claim_taskflow_run_with_authority_clock(
                &security.authority,
                &effect.run_id,
                &fence(),
                /*lease_duration_ms*/ 100
            )
            .await
            .is_err()
    );
    assert_eq!(
        security
            .authority
            .capacity()
            .expect("no grant minted or consumed")
            .used_nonces,
        0
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_unavailable_at_sqlite_admission_has_no_system_time_fallback() {
    let fixture = Fixture::new();
    let effect = intent();
    let store = queued_store(&fixture, &effect.run_id).await;
    let observer = AutomationStore::open(&fixture.layout)
        .await
        .expect("second original owner");
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&effect),
        "clock-admission-unavailable",
        clock.clone(),
        /*expiry*/ 5_000,
    );
    let authority = security.authority.clone();
    let witness = fixture._temp.path().join("must-not-exist");
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
    running.ready.await.expect("original clock claim ready");
    clock.block_on(/*call*/ 3); // Claim verified/persisted twice; new original SQL admission sample.
    running.start.send(()).expect("controlled start");
    clock.entered().await;
    clock.unavailable(/*value*/ true);
    clock.release();
    assert!(
        tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.task)
            .await
            .expect("admission resolves")
            .expect("task")
            .is_err()
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert!(!witness.exists());
    assert!(
        observer
            .authorized_taskflow_effect_attempt(&effect.run_id, &effect.step_id, effect.attempt)
            .await
            .expect("transaction rolled back")
            .is_none()
    );
    assert_eq!(
        observer
            .taskflow_run(&effect.run_id)
            .await
            .expect("original run")
            .expect("present")
            .state,
        TaskFlowRunState::Running
    );
    assert_eq!(
        authority
            .capacity()
            .expect("grant conservatively consumed")
            .used_nonces,
        1
    );
}
