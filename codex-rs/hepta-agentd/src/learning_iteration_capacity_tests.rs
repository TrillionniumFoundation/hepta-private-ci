//! Capacity and lost-response regressions using SQLite and the real actor.
//! Stage results remain explicit fixtures, not evidence of production training.

use std::future::Future;
use std::future::poll_fn;
use std::task::Poll;

use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn full_learning_actor_leaves_completion_unclaimed_then_delivers_once() {
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
    let pending = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    let (handle, owner) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let mut occupied = Box::pin(handle.readback(request.clone()));
    poll_fn(|context| {
        assert!(occupied.as_mut().poll(context).is_pending());
        Poll::Ready(())
    })
    .await;
    assert!(matches!(
        crate::circuit_learning_delivery::deliver_circuit_learning_with_post_claim_source_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
            Box::pin(async { panic!("full actor must refuse before claim and source recheck") }),
        )
        .await,
        Err(LearningIterationRuntimeErrorV1::QueueFull)
    ));
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await),
        pending
    );
    assert_eq!(ports.restores.load(Ordering::SeqCst), 0);
    assert!(ok(ports.inner.executed.lock()).is_empty());
    assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());

    let (state, cognitive) = admitted_state(&daemon).await;
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(owner.run(state, cancellation.clone()));
    assert!(matches!(
        occupied.await,
        Err(LearningIterationRuntimeErrorV1::CommitUncertain)
    ));
    let completed = ok(
        crate::circuit_learning_delivery::deliver_circuit_learning_with_post_claim_source_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
            Box::pin(async {
                // The same actor permit survives the async claim and source check.
                assert!(matches!(
                    handle.reserve(),
                    Err(LearningIterationRuntimeErrorV1::QueueFull)
                ));
                Ok(())
            }),
        )
        .await,
    );
    assert_eq!(completed, planned);
    assert_eq!(
        *ok(ports.inner.executed.lock()),
        planned
            .receipts
            .iter()
            .map(|receipt| receipt.observation.stage())
            .collect::<Vec<_>>()
    );
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
async fn lost_learning_delivery_response_reconciles_without_repeating_stages() {
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
    let (state, cognitive) = admitted_state(&daemon).await;
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(owner.run(state, cancellation.clone()));
    let mut delivery = Box::pin(crate::deliver_circuit_learning_v1(
        &store,
        Some(&handle),
        request.clone(),
        ports.inner.owners(),
    ));
    tokio::time::timeout(Duration::from_secs(5), async {
        tokio::select! {
            result = &mut delivery => panic!("delivery completed before owner barrier: {result:?}"),
            result = entered_rx => ok(result),
        }
    })
    .await
    .expect("original worker entered stage verification");
    drop(delivery);
    ok(resume.send(()));
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            if *ok(ports.inner.checkpoint.lock()) == Some(planned.clone()) {
                break;
            }
            tokio::task::yield_now().await;
        }
    })
    .await
    .expect("same worker committed the original iteration");
    let claimed = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    assert!(claimed[0].request_digest.is_some());
    assert_eq!(claimed[0].acknowledged_head, None);
    let executed = ok(ports.inner.executed.lock()).clone();
    let checkpoints = ok(ports.inner.checkpoint_calls.lock()).clone();
    let recovered = ok(crate::reconcile_circuit_learning_v1(
        &store,
        Some(&handle),
        request.clone(),
        ports.inner.owners(),
    )
    .await);
    assert_eq!(recovered, planned);
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
