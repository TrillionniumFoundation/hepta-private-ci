//! Accepted queue handoff survives the request waiter, not supervisor cancellation.
//! SQLite and actor paths are real; stage observations remain explicit fixtures.

use std::future::Future;
use std::future::poll_fn;
use std::pin::Pin;
use std::sync::atomic::AtomicBool;
use std::task::Poll;

use pretty_assertions::assert_eq;

use super::*;

async fn wait_for_queued_submission(
    mut delivery: Pin<
        &mut impl Future<Output = Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1>>,
    >,
    source_checked: &AtomicBool,
    handle: &crate::LearningIterationHandleV1,
) {
    tokio::time::timeout(
        Duration::from_secs(5),
        poll_fn(|context| {
            assert!(delivery.as_mut().poll(context).is_pending());
            // The post-claim callback does not yield. A pending delivery after
            // it returns has sent the reserved command and is waiting for its ACK.
            if source_checked.load(Ordering::SeqCst) {
                Poll::Ready(())
            } else {
                Poll::Pending
            }
        }),
    )
    .await
    .expect("original SQLite claim and actor enqueue");
    assert!(matches!(
        handle.reserve(),
        Err(LearningIterationRuntimeErrorV1::QueueFull)
    ));
}

#[tokio::test]
async fn queued_learning_submit_survives_waiter_loss_and_reconciles_once() {
    let daemon = AgentdFixture::new();
    let (store, mut request) = completed_circuit(&daemon).await;
    request.envelope.expiry_unix_seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 120;
    let ports = CurrentEvidencePorts::new();
    let planned =
        completed_snapshot(request.clone(), &ports.inner, Decision::EvaluatedNoUpdate).await;
    *ok(ports.planned.lock()) = Some(planned.clone());
    ok(ports.inner.executed.lock()).clear();
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let source_checked = AtomicBool::new(false);
    let mut delivery = Box::pin(
        crate::circuit_learning_delivery::deliver_circuit_learning_with_post_claim_source_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
            Box::pin(async {
                source_checked.store(true, Ordering::SeqCst);
                Ok(())
            }),
        ),
    );
    wait_for_queued_submission(delivery.as_mut(), &source_checked, &handle).await;
    drop(delivery);
    let claimed = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    assert_eq!(claimed.len(), 1);
    assert!(claimed[0].request_digest.is_some());
    assert_eq!(claimed[0].acknowledged_head, None);
    assert_eq!(ports.restores.load(Ordering::SeqCst), 0);
    assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());

    let (state, cognitive) = admitted_state(&daemon).await;
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(owner.run(state, cancellation.clone()));
    ports.wait_for_restores(1).await;
    tokio::time::timeout(Duration::from_secs(5), async {
        while *ok(ports.inner.checkpoint.lock()) != Some(planned.clone()) {
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("accepted submission finishes after its original waiter exits");
    assert_eq!(
        *ok(ports.inner.executed.lock()),
        planned
            .receipts
            .iter()
            .map(|receipt| receipt.observation.stage())
            .collect::<Vec<_>>()
    );
    assert_eq!(ok(store.pending_circuit_learning(/*limit*/ 1).await), claimed);
    let executed = ok(ports.inner.executed.lock()).clone();
    let checkpoints = ok(ports.inner.checkpoint_calls.lock()).clone();
    assert_eq!(
        ok(crate::reconcile_circuit_learning_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
        )
        .await),
        planned
    );
    assert_eq!(*ok(ports.inner.executed.lock()), executed);
    assert_eq!(*ok(ports.inner.checkpoint_calls.lock()), checkpoints);
    assert_eq!(
        await_ack(&store, &request).await.acknowledged_head,
        Some(ok(Sha256Digest::parse(planned.head_digest.to_string())))
    );
    cancellation.cancel();
    ok(ok(worker.await));
    cognitive.close().await;
    store.close().await;
}

#[tokio::test]
async fn explicit_learning_cancel_precedes_an_already_queued_submit() {
    let daemon = AgentdFixture::new();
    let (store, mut request) = completed_circuit(&daemon).await;
    request.envelope.expiry_unix_seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 120;
    let ports = CurrentEvidencePorts::new();
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let source_checked = AtomicBool::new(false);
    let mut delivery = Box::pin(
        crate::circuit_learning_delivery::deliver_circuit_learning_with_post_claim_source_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
            Box::pin(async {
                source_checked.store(true, Ordering::SeqCst);
                Ok(())
            }),
        ),
    );
    wait_for_queued_submission(delivery.as_mut(), &source_checked, &handle).await;
    let claimed = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    let (state, cognitive) = admitted_state(&daemon).await;
    let cancellation = CancellationToken::new();
    cancellation.cancel();
    ok(owner.run(state, cancellation).await);
    assert!(matches!(
        delivery.await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_eq!(ports.restores.load(Ordering::SeqCst), 0);
    assert!(ok(ports.inner.executed.lock()).is_empty());
    assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());
    assert_eq!(ok(store.pending_circuit_learning(/*limit*/ 1).await), claimed);
    cognitive.close().await;
    store.close().await;
}

#[tokio::test]
async fn detached_learning_submit_still_cancels_and_recovers_without_new_work() {
    let daemon = AgentdFixture::new();
    let (store, mut request) = completed_circuit(&daemon).await;
    request.envelope.expiry_unix_seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        + 120;
    let ports = CurrentEvidencePorts::new();
    let planned =
        completed_snapshot(request.clone(), &ports.inner, Decision::EvaluatedNoUpdate).await;
    *ok(ports.planned.lock()) = Some(planned);
    ok(ports.inner.executed.lock()).clear();
    let (entered, entered_rx) = tokio::sync::oneshot::channel();
    let (resume, resume_rx) = tokio::sync::oneshot::channel();
    *ok(ports.inner.attestation_barrier.lock()) = Some(AttestationBarrier {
        entered,
        resume: resume_rx,
    });
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let source_checked = AtomicBool::new(false);
    let mut delivery = Box::pin(
        crate::circuit_learning_delivery::deliver_circuit_learning_with_post_claim_source_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
            Box::pin(async {
                source_checked.store(true, Ordering::SeqCst);
                Ok(())
            }),
        ),
    );
    wait_for_queued_submission(delivery.as_mut(), &source_checked, &handle).await;
    drop(delivery);
    let claimed = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    let (state, cognitive) = admitted_state(&daemon).await;
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(owner.run(Arc::clone(&state), cancellation.clone()));
    ok(tokio::time::timeout(Duration::from_secs(5), entered_rx)
        .await
        .expect("original stage reaches its attestation barrier"));
    cancellation.cancel();
    ok(ok(tokio::time::timeout(Duration::from_secs(5), worker)
        .await
        .expect("original supervisor cancels the detached submission")));
    assert!(resume.send(()).is_err());
    let initial = ok(LearningIterationCoordinatorV1::new(
        request.clone(),
        ports.inner.owners(),
    ))
    .snapshot()
    .clone();
    assert_eq!(*ok(ports.inner.checkpoint.lock()), Some(initial.clone()));
    assert_eq!(
        *ok(ports.inner.executed.lock()),
        vec![LearningIterationStageV1::Experience]
    );
    assert_eq!(*ok(ports.inner.checkpoint_calls.lock()), vec![Digest32::ZERO]);

    // Reopen only the actor over the original test owners. A partial original
    // checkpoint permits readback, never a fresh attempt under another identity.
    let (recovery, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(owner.run(state, cancellation.clone()));
    assert!(matches!(
        crate::reconcile_circuit_learning_v1(
            &store,
            Some(&recovery),
            request,
            ports.inner.owners(),
        )
        .await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_eq!(*ok(ports.inner.checkpoint.lock()), Some(initial));
    assert_eq!(
        *ok(ports.inner.executed.lock()),
        vec![LearningIterationStageV1::Experience]
    );
    assert_eq!(*ok(ports.inner.checkpoint_calls.lock()), vec![Digest32::ZERO]);
    assert_eq!(ok(store.pending_circuit_learning(/*limit*/ 1).await), claimed);
    cancellation.cancel();
    ok(ok(worker.await));
    cognitive.close().await;
    store.close().await;
}

#[tokio::test]
async fn detached_learning_submit_preserves_its_expired_work_deadline() {
    let daemon = AgentdFixture::new();
    let (store, mut request) = completed_circuit(&daemon).await;
    request.envelope.expiry_unix_seconds = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
        .saturating_sub(1);
    let ports = CurrentEvidencePorts::new();
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let source_checked = AtomicBool::new(false);
    let mut delivery = Box::pin(
        crate::circuit_learning_delivery::deliver_circuit_learning_with_post_claim_source_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
            Box::pin(async {
                source_checked.store(true, Ordering::SeqCst);
                Ok(())
            }),
        ),
    );
    wait_for_queued_submission(delivery.as_mut(), &source_checked, &handle).await;
    drop(delivery);
    let claimed = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    let (state, cognitive) = admitted_state(&daemon).await;
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(owner.run(state, cancellation.clone()));
    ports.wait_for_restores(1).await;
    assert!(matches!(
        handle.readback(request).await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    assert_eq!(ports.restores.load(Ordering::SeqCst), 2);
    assert!(ok(ports.inner.executed.lock()).is_empty());
    assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());
    assert_eq!(ok(store.pending_circuit_learning(/*limit*/ 1).await), claimed);
    cancellation.cancel();
    ok(ok(worker.await));
    cognitive.close().await;
    store.close().await;
}
