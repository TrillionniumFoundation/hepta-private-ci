//! Real SQLite claims and original live actor drain. The gated checkpoint and
//! training callbacks are fixtures, not remote-job cancellation evidence.

use pretty_assertions::assert_eq;

use crate::state::learning_iteration::LearningIterationDrainStatusV1;

use super::*;

#[tokio::test]
async fn learning_drain_keeps_checkpoint_and_training_pending_after_delivery_ack_loss() {
    for point in [OwnerWaitPoint::Checkpoint, OwnerWaitPoint::Training] {
        let daemon = AgentdFixture::new();
        let (store, mut request) = completed_circuit(&daemon).await;
        request.envelope.expiry_unix_seconds = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
            + 120;
        request.budget.maximum_training_milliseconds = 10_000;
        let ports = CurrentEvidencePorts::new();
        let planned =
            completed_snapshot(request.clone(), &ports.inner, Decision::EvaluatedNoUpdate).await;
        *ok(ports.planned.lock()) = Some(planned);
        let (entered, receive) = tokio::sync::oneshot::channel();
        let (resume, waiting) = tokio::sync::oneshot::channel();
        *ok(ports.owner_wait.lock()) = Some(OwnerWait {
            point,
            entered,
            resume: waiting,
        });
        let (state, cognitive) = admitted_state(&daemon).await;
        ok(state.attach_automation_store(store.clone()));
        let services = Services::start(&daemon, Arc::clone(&state), &store, request, &ports);
        ok(tokio::time::timeout(Duration::from_secs(5), receive)
            .await
            .unwrap());
        services.delivery.abort();
        assert!(services.delivery.await.unwrap_err().is_cancelled());
        assert_eq!(
            ok(state.learning_iteration_drain_status().await),
            LearningIterationDrainStatusV1 {
                queued_or_active: 1,
                unacknowledged_claims: 1,
            }
        );
        let drain = crate::runtime::drain_runtime(Arc::clone(&state));
        tokio::pin!(drain);
        assert!(
            tokio::time::timeout(Duration::from_millis(50), &mut drain)
                .await
                .is_err(),
            "live original owner work cannot acknowledge ordinary drain"
        );
        ok(resume.send(()));
        tokio::time::timeout(Duration::from_secs(5), async {
            while state.learning_iteration_pending_count() != 0 {
                tokio::task::yield_now().await;
            }
        })
        .await
        .expect("original callback returned");
        assert_eq!(
            ok(state.learning_iteration_drain_status().await),
            LearningIterationDrainStatusV1 {
                queued_or_active: 0,
                unacknowledged_claims: 1,
            }
        );
        services.cancellation.cancel();
        ok(ok(services.actor.await));
        // Draining did not ACK or discard the original pending claim/checkpoint.
        assert_eq!(
            ok(store.pending_circuit_learning(/*limit*/ 1).await).len(),
            1
        );
        cognitive.close().await;
        store.close().await;
    }
}

#[tokio::test]
async fn learning_claim_blocks_supervisor_and_shutdown_drain_after_restart_without_profile() {
    let daemon = AgentdFixture::new();
    let (store, request) = completed_circuit(&daemon).await;
    let row = ok(store
        .circuit_learning_delivery(request.source_run_id.as_str())
        .await)
    .unwrap();
    assert!(ok(store
        .claim_circuit_learning(&row.intent, &Sha256Digest::for_bytes(b"registered-request"))
        .await));
    store.close().await;
    let reopened = ok(AutomationStore::open(&daemon.identity.layout).await);
    let state = daemon.state();
    ok(state.attach_automation_store(reopened.clone()));
    assert_eq!(
        ok(state.learning_iteration_drain_status().await),
        LearningIterationDrainStatusV1 {
            queued_or_active: 0,
            unacknowledged_claims: 1,
        }
    );
    ok(daemon.registry.compare_and_transition(
        &daemon.identity.agent_id,
        2,
        AgentLifecycle::Draining,
    ));
    assert!(!ok(state.request_drain(Some(&reopened)).await).drained);
    let error = crate::runtime::drain_runtime(Arc::clone(&state))
        .await
        .unwrap_err()
        .to_string();
    assert!(error.contains("0 queued/active learning command(s)"));
    assert!(error.contains("1 unacknowledged learning claim(s)"));
    assert_eq!(
        ok(reopened.pending_circuit_learning(/*limit*/ 1).await),
        vec![CircuitLearningDeliveryV1 {
            intent: row.intent,
            request_digest: Some(Sha256Digest::for_bytes(b"registered-request")),
            acknowledged_head: None,
        },]
    );
    reopened.close().await;
    assert!(state.learning_iteration_drain_status().await.is_err());
}

#[tokio::test]
async fn learning_queue_rejection_and_caller_drop_preserve_exact_pending_count() {
    let daemon = AgentdFixture::new();
    let ports = CurrentEvidencePorts::new();
    let request = iteration_request(&daemon);
    let (handle, bootstrap) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let state = daemon.state();
    ok(bootstrap.attach_drain(&state));
    let first = tokio::spawn({
        let handle = handle.clone();
        let request = request.clone();
        async move { handle.submit(request).await }
    });
    tokio::time::timeout(Duration::from_secs(5), async {
        while state.learning_iteration_pending_count() == 0 {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert!(matches!(
        handle.readback(request).await,
        Err(LearningIterationRuntimeErrorV1::QueueFull)
    ));
    assert_eq!(state.learning_iteration_pending_count(), 1);
    first.abort();
    assert!(first.await.unwrap_err().is_cancelled());
    assert_eq!(state.learning_iteration_pending_count(), 1);
    drop(bootstrap);
    assert_eq!(state.learning_iteration_pending_count(), 0);
}
