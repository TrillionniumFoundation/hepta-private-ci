//! One absent effect must not clear another effect's admitted recovery fence.
#![allow(
    clippy::expect_used,
    reason = "actual original-owner absence race fixture"
)]

use codex_hepta_automation::AsyncAuthorizedEffectDriver;
use codex_hepta_automation::AuthorizedEffectDriverError;
use codex_hepta_automation::AuthorizedEffectFuture;
use codex_hepta_automation::AuthorizedEffectOutcome;
use codex_hepta_automation::AuthorizedEffectProviderReceipt;
use codex_hepta_automation::AuthorizedEffectRecovery;
use codex_hepta_automation::AuthorizedProviderEffectRequest;
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

struct AbsentDriver {
    entered: Arc<Notify>,
    release: Arc<Notify>,
}

impl AsyncAuthorizedEffectDriver for AbsentDriver {
    fn dispatch<'a>(
        &'a mut self,
        _request: AuthorizedProviderEffectRequest<'a>,
    ) -> AuthorizedEffectFuture<'a> {
        Box::pin(async move {
            self.entered.notify_one();
            self.release.notified().await;
            // This registered test driver never performs any provider action.
            Err(AuthorizedEffectDriverError::BeforeProviderContact)
        })
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn effect_clock_absence_of_one_attempt_cannot_requeue_another_admitted_effect() {
    let fixture = Fixture::new();
    let absent = intent();
    let mut entered = absent.clone();
    entered.attempt = 2;
    let store = queued_store(&fixture, &absent.run_id).await;
    let observer = AutomationStore::open(&fixture.layout)
        .await
        .expect("second SQLite owner");
    let security = Security::new(
        binding(&absent),
        "one-absent",
        Clock::new(/*now*/ 1_000),
        /*expiry*/ 5_000,
    );
    let entered_grant = signed_grant(binding(&entered), "one-entered", /*expiry*/ 5_000);
    let authority = security.authority.clone();
    let absent_entry = Arc::new(Notify::new());
    let absent_release = Arc::new(Notify::new());
    let entered_entry = Arc::new(Notify::new());
    let entered_release = Arc::new(Notify::new());
    let mut absent_driver = AbsentDriver {
        entered: absent_entry.clone(),
        release: absent_release.clone(),
    };
    let witness = fixture._temp.path().join("only-actual-effect");
    let mut entered_driver = FileDriver::new(witness.clone());
    entered_driver.pause = Some((entered_entry.clone(), entered_release.clone()));
    let calls = entered_driver.calls.clone();
    let absent_task = absent.clone();
    let entered_task = entered.clone();
    let (absent_done_sender, absent_done) = oneshot::channel();
    let running = tokio::spawn(async move {
        let owner = fence();
        let claim = store
            .claim_taskflow_run_with_authority_clock(
                &security.authority,
                &absent_task.run_id,
                &owner,
                /*lease_duration_ms*/ 100,
            )
            .await
            .expect("original lease");
        activate(&store, &claim, &absent_task).await;
        let digest = entered_task.digest().expect("second intent");
        store
            .prepare_taskflow_step(
                &entered_task.run_id,
                &entered_task.step_id,
                entered_task.attempt,
                &owner,
                &digest,
                &entered_task.payload_digest,
                "entered-prepare",
                /*now_ms*/ 1_000,
            )
            .await
            .expect("prepare second");
        store
            .claim_taskflow_step(
                &entered_task.run_id,
                &entered_task.step_id,
                entered_task.attempt,
                &owner,
                &digest,
                &entered_task.payload_digest,
                "entered-claim",
                /*now_ms*/ 1_000,
            )
            .await
            .expect("claim second");
        let absent_binding = binding(&absent_task);
        let entered_binding = binding(&entered_task);
        tokio::join!(
            async {
                let result = claim
                    .execute_authorized_effect_async(
                        &mut absent_driver,
                        &absent_task,
                        EFFECT_PAYLOAD,
                        &security.signed,
                        &absent_binding,
                        "record-absence",
                    )
                    .await;
                absent_done_sender
                    .send(())
                    .expect("controller observes blocked requeue");
                result
            },
            claim.execute_authorized_effect_async(
                &mut entered_driver,
                &entered_task,
                EFFECT_PAYLOAD,
                &entered_grant,
                &entered_binding,
                "record-entered"
            ),
        )
    });
    tokio::time::timeout(Duration::from_secs(/*secs*/ 3), absent_entry.notified())
        .await
        .expect("first admitted driver");
    tokio::time::timeout(Duration::from_secs(/*secs*/ 3), entered_entry.notified())
        .await
        .expect("other actual effect");
    absent_release.notify_one();
    tokio::time::timeout(Duration::from_secs(/*secs*/ 3), absent_done)
        .await
        .expect("absence retained")
        .expect("requeue decision");
    let retained = observer
        .taskflow_run(&absent.run_id)
        .await
        .expect("run")
        .expect("present");
    assert_eq!(retained.state, TaskFlowRunState::Running);
    assert_eq!(
        retained.fencing_token.as_deref(),
        Some(fence().fencing_token.as_str())
    );
    assert_eq!(
        observer
            .read_taskflow_step(&absent.run_id, &absent.step_id, absent.attempt, &fence())
            .await
            .expect("first absence step")
            .expect("step")
            .state,
        TaskFlowStepState::Reconciled
    );
    entered_release.notify_one();
    let (absent_result, entered_result) =
        tokio::time::timeout(Duration::from_secs(/*secs*/ 3), running)
            .await
            .expect("both owner operations finish")
            .expect("task");
    assert!(absent_result.is_err());
    entered_result.expect("other original receipt remains writable");
    observer
        .recover_authorized_taskflow_effect(
            &entered.run_id,
            &entered.step_id,
            entered.attempt,
            &fence(),
            AuthorizedEffectRecovery::Observed(AuthorizedEffectProviderReceipt {
                outcome: AuthorizedEffectOutcome::Succeeded,
                receipt_digest: Sha256Digest::for_bytes(
                    &std::fs::read(&witness).expect("actual original witness"),
                ),
            }),
            /*observed_at_ms*/ 1_000,
        )
        .await
        .expect("one non-absent effect may settle after all absence receipts");
    assert_eq!(
        observer
            .taskflow_run(&entered.run_id)
            .await
            .expect("run")
            .expect("present")
            .state,
        TaskFlowRunState::Succeeded
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        authority
            .capacity()
            .expect("no replay or refund")
            .used_nonces,
        2
    );
}
