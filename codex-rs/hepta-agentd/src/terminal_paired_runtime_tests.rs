//! Real native fixture owners and real local fixture signatures exercise the
//! supervised exchange. Constructed deliveries are not original human consent.

use super::*;
use crate::terminal_learning_runtime::paired_terminal_evaluator_channel_v1;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use tokio::sync::oneshot;

#[tokio::test]
async fn late_evaluator_returns_native_receipt_and_scopes_followup_commands() {
    let fixture = FixtureOwners::new().await;
    let (delivery, plan) = inputs(&fixture);
    let (evaluator, mut inbox) = paired_terminal_evaluator_channel_v1();
    let (handle, bootstrap) = terminal_learning_channel_v1(
        fixture.daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        fixture.native_owner(),
        /*capacity*/ 1,
    )
    .unwrap();
    let mut bootstrap = bootstrap
        .with_original_paired_policy(plan, evaluator)
        .unwrap();
    let (send, receive) = oneshot::channel();
    bootstrap
        .install_original_paired_delivery(receive, Instant::now() + Duration::from_secs(30))
        .unwrap();
    assert!(send.send(delivery).is_ok());
    let clock = Arc::new(AtomicU64::new(FIXTURE_NOW));
    let clock_owner = Arc::clone(&clock);
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(bootstrap.run_with_clock(
        fixture.daemon.state(),
        cancellation.clone(),
        move || Ok(clock_owner.load(Ordering::SeqCst)),
    ));
    let request = tokio::time::timeout(Duration::from_secs(5), inbox.receive())
        .await
        .unwrap()
        .unwrap();
    assert!(
        request
            .signing_payload()
            .starts_with(b"hepta.agentd.paired-terminal-owner-binding.v1\0")
    );
    let mut queued = Box::pin(handle.readback(fixture.request.clone()));
    poll_fn(|context| {
        assert!(queued.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    let signed = {
        let ledger = fixture.ledger.lock().unwrap();
        let mut signed = sign(
            ledger.verifier(),
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            request.signing_payload(),
        );
        signed.issued_at = request.prepared_at();
        signed.signature = SigningKey::from_bytes(&[4; 32])
            .sign(&signed.signing_bytes())
            .to_bytes();
        clock.store(signed.issued_at, Ordering::SeqCst);
        signed
    };
    let receipt = request.submit_signed_evidence(signed).await.unwrap();
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert_eq!((receipt.source_records, receipt.training_samples), (4, 2));
    assert_eq!(queued.await.unwrap(), receipt);
    assert_eq!(
        handle.submit(fixture.request.clone()).await.unwrap_err(),
        TerminalLearningErrorV1::WrongScope
    );
    let mut other = fixture.request.clone();
    other.operation_id = id("outside-original-paired-job");
    assert_eq!(
        handle.submit(other.clone()).await.unwrap_err(),
        TerminalLearningErrorV1::WrongScope
    );
    assert_eq!(
        handle.readback(other).await.unwrap_err(),
        TerminalLearningErrorV1::WrongScope
    );
    assert_eq!(
        handle.readback(fixture.request.clone()).await.unwrap(),
        receipt
    );
    cancellation.cancel();
    worker.await.unwrap().unwrap();
}

#[tokio::test]
async fn missing_evaluator_and_foreign_pins_refuse_before_intake_attachment() {
    let fixture = FixtureOwners::new().await;
    let (_, plan) = inputs(&fixture);
    let (evaluator, inbox) = paired_terminal_evaluator_channel_v1();
    drop(inbox);
    let (_, bootstrap) = terminal_learning_channel_v1(
        fixture.daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        fixture.native_owner(),
        /*capacity*/ 1,
    )
    .unwrap();
    assert!(
        bootstrap
            .with_original_paired_policy(plan.clone(), evaluator)
            .is_err()
    );
    let (evaluator, _inbox) = paired_terminal_evaluator_channel_v1();
    let (_, bootstrap) = terminal_learning_channel_v1(
        fixture.daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        fixture.native_owner(),
        /*capacity*/ 1,
    )
    .unwrap();
    let bootstrap = bootstrap
        .with_original_paired_policy(plan.clone(), evaluator)
        .unwrap();
    let mut pins = plan.records;
    pins.failure_record_digest = digest("foreign canonical record");
    assert!(
        bootstrap
            .require_original_paired_policy(&plan.original, pins)
            .is_err()
    );
    let mut original = plan.original.clone();
    original.operation = digest("foreign original operation");
    assert!(
        bootstrap
            .require_original_paired_policy(&original, plan.records)
            .is_err()
    );
    bootstrap
        .require_original_paired_policy(&plan.original, plan.records)
        .unwrap();
}

#[tokio::test]
async fn original_deadline_and_cancellation_end_pending_delivery_without_a_read() {
    for cancel in [false, true] {
        let fixture = FixtureOwners::new().await;
        let (_, plan) = inputs(&fixture);
        let (evaluator, _inbox) = paired_terminal_evaluator_channel_v1();
        let (_, bootstrap) = terminal_learning_channel_v1(
            fixture.daemon.identity.agent_id.clone(),
            /*spawn_generation*/ 1,
            fixture.native_owner(),
            /*capacity*/ 1,
        )
        .unwrap();
        let mut bootstrap = bootstrap
            .with_original_paired_policy(plan, evaluator)
            .unwrap();
        let (_send, receive) = oneshot::channel();
        let end = Instant::now() + Duration::from_millis(200);
        bootstrap
            .install_original_paired_delivery(receive, end)
            .unwrap();
        let cancellation = CancellationToken::new();
        let mut running = Box::pin(bootstrap.run_with_clock(
            fixture.daemon.state(),
            cancellation.clone(),
            || Ok(FIXTURE_NOW),
        ));
        // Poll synchronously so the registered original wait precedes the
        // cancellation/deadline observation; no timer is reset or slept.
        poll_fn(|context| {
            assert!(running.as_mut().poll(context).is_pending());
            Poll::Ready(())
        })
        .await;
        if cancel {
            cancellation.cancel();
        }
        let error = running.await.unwrap_err().to_string();
        assert!(error.contains(if cancel {
            "paired intake owner cancelled"
        } else {
            "original paired session expired"
        }));
    }
}

#[tokio::test]
async fn dropped_late_signature_is_required_failure_without_a_success_reply() {
    let fixture = FixtureOwners::new().await;
    let (delivery, plan) = inputs(&fixture);
    let (evaluator, mut inbox) = paired_terminal_evaluator_channel_v1();
    let (_, bootstrap) = terminal_learning_channel_v1(
        fixture.daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        fixture.native_owner(),
        /*capacity*/ 1,
    )
    .unwrap();
    let mut bootstrap = bootstrap
        .with_original_paired_policy(plan, evaluator)
        .unwrap();
    let (send, receive) = oneshot::channel();
    bootstrap
        .install_original_paired_delivery(receive, Instant::now() + Duration::from_secs(30))
        .unwrap();
    assert!(send.send(delivery).is_ok());
    let cancellation = CancellationToken::new();
    let worker =
        tokio::spawn(
            bootstrap.run_with_clock(fixture.daemon.state(), cancellation, || Ok(FIXTURE_NOW)),
        );
    let request = tokio::time::timeout(Duration::from_secs(5), inbox.receive())
        .await
        .unwrap()
        .unwrap();
    drop(request);
    let error = worker.await.unwrap().unwrap_err().to_string();
    assert!(error.contains("original paired Evaluator abandoned its request"));
}
