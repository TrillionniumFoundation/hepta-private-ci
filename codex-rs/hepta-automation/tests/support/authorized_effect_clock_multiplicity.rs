//! No implicit outcome aggregation may destroy another admitted effect's fence.
#![allow(
    clippy::expect_used,
    reason = "actual two-effect original-owner fixture"
)]

use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::Ordering;
use std::time::Duration;
use tokio::sync::Notify;
use tokio::sync::oneshot;

use super::super::EFFECT_PAYLOAD;
use super::super::Fixture;
use super::super::binding;
use super::super::fence;
use super::super::intent;
use super::driver::FileDriver;
use super::driver::activate;
use super::driver::queued_store;
use super::fixture::Clock;
use super::fixture::Security;
use super::fixture::signed_grant;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_multiple_admitted_effects_keep_original_fence_and_all_receipts() {
    let fixture = Fixture::new();
    let first = intent();
    let mut second = first.clone();
    second.attempt = 2;
    let store = queued_store(&fixture, &first.run_id).await;
    let observer = AutomationStore::open(&fixture.layout)
        .await
        .expect("second owner connection");
    let clock = Clock::new(/*now*/ 1_000);
    let security = Security::new(
        binding(&first),
        "multiple-first",
        clock,
        /*expiry*/ 5_000,
    );
    let second_grant = signed_grant(binding(&second), "multiple-second", /*expiry*/ 5_000);
    let authority = security.authority.clone();
    let path_a = fixture._temp.path().join("actual-effect-a");
    let path_b = fixture._temp.path().join("actual-effect-b");
    let mut driver_a = FileDriver::new(path_a.clone());
    let mut driver_b = FileDriver::new(path_b.clone());
    let calls_a = driver_a.calls.clone();
    let calls_b = driver_b.calls.clone();
    let entered_a = Arc::new(Notify::new());
    let entered_b = Arc::new(Notify::new());
    let release_a = Arc::new(Notify::new());
    let release_b = Arc::new(Notify::new());
    driver_a.pause = Some((entered_a.clone(), release_a.clone()));
    driver_b.pause = Some((entered_b.clone(), release_b.clone()));
    let first_task = first.clone();
    let second_task = second.clone();
    let (ready_sender, ready) = oneshot::channel();
    let (first_settled_sender, first_settled) = oneshot::channel();
    let running = tokio::spawn(async move {
        let owner = fence();
        let claim = store
            .claim_taskflow_run_with_authority_clock(
                &security.authority,
                &first_task.run_id,
                &owner,
                /*lease_duration_ms*/ 100,
            )
            .await
            .expect("one original typed lease");
        activate(&store, &claim, &first_task).await;
        let digest = second_task.digest().expect("second exact intent");
        store
            .prepare_taskflow_step(
                &second_task.run_id,
                &second_task.step_id,
                second_task.attempt,
                &owner,
                &digest,
                &second_task.payload_digest,
                "second-prepare",
                /*now_ms*/ 1_000,
            )
            .await
            .expect("second intent");
        store
            .claim_taskflow_step(
                &second_task.run_id,
                &second_task.step_id,
                second_task.attempt,
                &owner,
                &digest,
                &second_task.payload_digest,
                "second-claim",
                /*now_ms*/ 1_000,
            )
            .await
            .expect("second step");
        ready_sender.send(()).expect("controller ready");
        let first_binding = binding(&first_task);
        let second_binding = binding(&second_task);
        tokio::join!(
            async {
                let result = claim
                    .execute_authorized_effect_async(
                        &mut driver_a,
                        &first_task,
                        EFFECT_PAYLOAD,
                        &security.signed,
                        &first_binding,
                        "record-first",
                    )
                    .await;
                first_settled_sender
                    .send(())
                    .expect("first original settlement completed");
                result
            },
            claim.execute_authorized_effect_async(
                &mut driver_b,
                &second_task,
                EFFECT_PAYLOAD,
                &second_grant,
                &second_binding,
                "record-second"
            ),
        )
    });
    ready.await.expect("both original steps prepared");
    tokio::time::timeout(Duration::from_secs(/*secs*/ 3), entered_a.notified())
        .await
        .expect("first physical entry");
    tokio::time::timeout(Duration::from_secs(/*secs*/ 3), entered_b.notified())
        .await
        .expect("second physical entry");
    assert_eq!(
        observer
            .pending_authorized_taskflow_effects(/*limit*/ 8)
            .await
            .expect("two original attempts")
            .len(),
        2
    );
    release_a.notify_one();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 3), first_settled)
        .await
        .expect("first original receipt retained")
        .expect("first settlement notification");
    release_b.notify_one();
    let (result_a, result_b) = tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running)
        .await
        .expect("both entered effects return")
        .expect("task");
    result_a.expect("first original indeterminate receipt");
    result_b.expect("second original indeterminate receipt");
    for effect in [&first, &second] {
        let result = observer
            .recover_authorized_taskflow_effect(
                &effect.run_id,
                &effect.step_id,
                effect.attempt,
                &fence(),
                AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                    outcome: AuthorizedEffectOutcome::Succeeded,
                    receipt_digest: Sha256Digest::for_bytes(EFFECT_PAYLOAD),
                }),
                /*observed_at_ms*/ 1_000,
            )
            .await;
        assert!(
            result.is_err(),
            "no aggregate outcome or fence clearing is invented"
        );
        let run = observer
            .taskflow_run(&effect.run_id)
            .await
            .expect("recoverable run")
            .expect("present");
        assert_eq!(run.state, TaskFlowRunState::Indeterminate);
        assert_eq!(
            run.fencing_token.as_deref(),
            Some(fence().fencing_token.as_str())
        );
        assert_eq!(
            observer
                .read_taskflow_step(&effect.run_id, &effect.step_id, effect.attempt, &fence())
                .await
                .expect("retained terminal receipt")
                .expect("step")
                .state,
            TaskFlowStepState::Reconciled
        );
    }
    assert_eq!(
        std::fs::read(path_a).expect("first original effect"),
        EFFECT_PAYLOAD
    );
    assert_eq!(
        std::fs::read(path_b).expect("second original effect"),
        EFFECT_PAYLOAD
    );
    assert_eq!(calls_a.load(Ordering::SeqCst), 1);
    assert_eq!(calls_b.load(Ordering::SeqCst), 1);
    assert_eq!(
        authority
            .capacity()
            .expect("two explicit grants, no retries")
            .used_nonces,
        2
    );
}
