//! Lifetime regression for the original durable FinalUse authority fixture.
#![allow(clippy::expect_used, reason = "explicit clock race fixture invariants")]

use pretty_assertions::assert_eq;
use std::sync::atomic::Ordering;
use std::time::Duration;

use super::Fixture;
use super::binding;
use super::driver::FileDriver;
use super::driver::queued_store;
use super::driver::spawn_dispatch;
use super::fixture::Clock;
use super::fixture::Security;
use super::intent;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_spawned_fixture_retains_original_authority_directory_until_completion() {
    for asynchronous in [false, true] {
        let fixture = Fixture::new();
        let effect = intent();
        let store = queued_store(&fixture, &effect.run_id).await;
        let security = Security::new(
            binding(&effect),
            "owned-directory-lifetime",
            Clock::new(/*now*/ 1_000),
            /*expiry*/ 5_000,
        );
        let state_directory = security.state_directory().to_path_buf();
        let authority = security.authority.clone();
        let witness = fixture._temp.path().join("one-owned-effect");
        let driver = FileDriver::new(witness.clone());
        let calls = driver.calls.clone();
        let running = spawn_dispatch(
            store,
            security,
            effect,
            driver,
            /*lease_duration*/ 100,
            asynchronous,
        );
        tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.ready)
            .await
            .expect("bounded fixture setup")
            .expect("original lease and step ready");
        assert!(
            state_directory.join("authority.claims").is_file(),
            "spawn helper must retain the original durable nonce journal while its task owns the fixture"
        );
        running.start.send(()).expect("controlled effect entry");
        let receipt = tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running.task)
            .await
            .expect("bounded original dispatch")
            .expect("dispatch task")
            .expect(
                "retained original authority can persist its nonce and enter the registered driver",
            );
        assert_eq!(
            receipt.observation,
            Some(codex_hepta_automation::TaskFlowStepObservation::Indeterminate)
        );
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        assert_eq!(
            std::fs::read(&witness).expect("actual owned effect"),
            super::EFFECT_PAYLOAD
        );
        assert_eq!(
            authority
                .capacity()
                .expect("one original nonce, no replacement grant")
                .used_nonces,
            1
        );
        assert!(
            !state_directory.exists(),
            "fixture directory is released only after its task completes"
        );
    }
}
