//! Real SQLite intents and serial actor readback; task material is fixture
//! data, not production ownership or learned successor-benefit evidence.

use pretty_assertions::assert_eq;
use std::collections::BTreeMap;

use super::*;

struct RegisteredReadbackPorts {
    original: Arc<CurrentEvidencePorts>,
    snapshots: BTreeMap<String, LearningIterationSnapshotV1>,
    restored: Mutex<Vec<String>>,
}

impl LearningIterationOwnerPortsV1 for RegisteredReadbackPorts {
    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        Box::pin(async move {
            ok(self.restored.lock()).push(request.operation_id.to_string());
            let snapshot = self.snapshots.get(request.operation_id.as_str()).cloned();
            if snapshot
                .as_ref()
                .is_some_and(|snapshot| snapshot.request != *request)
            {
                return Err(LearningIterationRuntimeErrorV1::WrongScope);
            }
            Ok(snapshot)
        })
    }
    fn checkpoint<'a>(
        &'a self,
        expected: Digest32,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, Digest32> {
        self.original.checkpoint(expected, snapshot)
    }
    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        self.original.execute_stage(snapshot, stage)
    }
    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        self.original.prepare_proposal(snapshot)
    }
    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        self.original.receipt_attestation(snapshot, receipt, now)
    }
}

#[test]
fn explicit_registry_rejects_aliases_foreign_agents_and_capacity() {
    let daemon = AgentdFixture::new();
    let request = iteration_request(&daemon);
    assert!(crate::CircuitLearningDeliveryRegistryV1::new(vec![]).is_err());
    assert!(crate::CircuitLearningDeliveryRegistryV1::new(vec![request.clone(); 65]).is_err());
    assert!(
        crate::CircuitLearningDeliveryRegistryV1::new(vec![request.clone(), request.clone()])
            .is_err()
    );
    let mut other = request.clone();
    other.operation_id = id("registry:other-operation");
    assert!(
        crate::CircuitLearningDeliveryRegistryV1::new(vec![request.clone(), other.clone()])
            .is_err()
    );
    other.source_run_id = id("registry:other-source");
    other.operation_id = request.operation_id.clone();
    assert!(
        crate::CircuitLearningDeliveryRegistryV1::new(vec![request.clone(), other.clone()])
            .is_err()
    );
    other.operation_id = id("registry:other-operation");
    other.agent_id = id("registry:foreign-agent");
    assert!(
        crate::CircuitLearningDeliveryRegistryV1::new(vec![request.clone(), other.clone()])
            .is_err()
    );
    other.agent_id = request.agent_id.clone();
    assert!(crate::CircuitLearningDeliveryRegistryV1::new(vec![request, other]).is_ok());
}

#[tokio::test]
async fn unavailable_or_full_actor_cannot_strand_a_fresh_delivery_claim() {
    let daemon = AgentdFixture::new();
    let (store, request) = completed_circuit(&daemon).await;
    let ports = CurrentEvidencePorts::new();
    let (handle, bootstrap) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        ports.inner.owners(),
        ports.clone(),
        ports.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let original = ok(store
        .circuit_learning_delivery(request.source_run_id.as_str())
        .await);
    let reserved = ok(handle.reserve());
    assert!(matches!(
        crate::deliver_circuit_learning_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
        )
        .await,
        Err(LearningIterationRuntimeErrorV1::QueueFull)
    ));
    drop(reserved);
    drop(bootstrap);
    assert!(matches!(
        crate::deliver_circuit_learning_v1(
            &store,
            Some(&handle),
            request.clone(),
            ports.inner.owners(),
        )
        .await,
        Err(LearningIterationRuntimeErrorV1::Unavailable)
    ));
    assert_eq!(
        ok(store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await),
        original
    );
    assert!(ok(ports.inner.executed.lock()).is_empty());
    assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());
    store.close().await;
}

#[tokio::test]
async fn serial_registry_keeps_missing_claim_pending_and_acknowledges_following_original_tasks() {
    let daemon = AgentdFixture::new();
    let (store, pending) = completed_circuit_named(&daemon, "registry-pending").await;
    let (other_store, second) = completed_circuit_named(&daemon, "registry-second").await;
    other_store.close().await;
    let (other_store, third) = completed_circuit_named(&daemon, "registry-third").await;
    other_store.close().await;
    let original = CurrentEvidencePorts::new();
    let mut snapshots = BTreeMap::new();
    for request in [&second, &third] {
        let snapshot = completed_snapshot(
            request.clone(),
            &original.inner,
            Decision::EvaluatedNoUpdate,
        )
        .await;
        snapshots.insert(request.operation_id.to_string(), snapshot);
    }
    ok(original.inner.executed.lock()).clear();
    let initial = ok(LearningIterationCoordinatorV1::new(
        pending.clone(),
        original.inner.owners(),
    ));
    let row = ok(store
        .circuit_learning_delivery(pending.source_run_id.as_str())
        .await)
    .unwrap();
    let request_digest = ok(Sha256Digest::parse(
        initial.snapshot().head_digest.to_string(),
    ));
    assert!(ok(store
        .claim_circuit_learning(&row.intent, &request_digest)
        .await));
    let claimed = ok(store
        .circuit_learning_delivery(pending.source_run_id.as_str())
        .await);
    let ports = Arc::new(RegisteredReadbackPorts {
        original: original.clone(),
        snapshots,
        restored: Mutex::default(),
    });
    let (state, cognitive) = admitted_state(&daemon).await;
    let (handle, bootstrap) = ok(learning_iteration_channel_v1(
        daemon.identity.agent_id.clone(),
        /*spawn_generation*/ 1,
        original.inner.owners(),
        ports.clone(),
        original.inner.verifier.clone(),
        /*capacity*/ 1,
    ));
    let registry = ok(crate::CircuitLearningDeliveryRegistryV1::new(vec![
        pending.clone(),
        second.clone(),
        third.clone(),
    ]));
    let mut bootstrap = ok(bootstrap.with_circuit_learning_registry(registry));
    let delivery = bootstrap.take_circuit_delivery().unwrap();
    drop(handle);
    let cancellation = CancellationToken::new();
    let actor = tokio::spawn(bootstrap.run(state.clone(), cancellation.clone()));
    let delivery = tokio::spawn(delivery.run(store.clone(), state, cancellation.clone()));
    let second_ack = await_ack(&store, &second).await;
    let third_ack = await_ack(&store, &third).await;
    for (request, ack) in [(&second, second_ack), (&third, third_ack)] {
        assert_eq!(
            ack.acknowledged_head,
            Some(ok(Sha256Digest::parse(
                ports.snapshots[request.operation_id.as_str()]
                    .head_digest
                    .to_string()
            )))
        );
    }
    assert_eq!(
        ok(store
            .circuit_learning_delivery(pending.source_run_id.as_str())
            .await),
        claimed
    );
    assert_eq!(
        &ok(ports.restored.lock())[..3],
        &[
            pending.operation_id.to_string(),
            second.operation_id.to_string(),
            third.operation_id.to_string()
        ]
    );
    assert!(ok(original.inner.executed.lock()).is_empty());
    assert!(ok(original.inner.checkpoint_calls.lock()).is_empty());
    assert!(!delivery.is_finished());
    cancellation.cancel();
    ok(ok(tokio::time::timeout(Duration::from_secs(5), delivery)
        .await
        .unwrap()));
    ok(ok(tokio::time::timeout(Duration::from_secs(5), actor)
        .await
        .unwrap()));
    cognitive.close().await;
    store.close().await;
}
