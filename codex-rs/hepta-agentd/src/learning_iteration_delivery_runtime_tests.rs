//! Actual SQLite outbox and live learning/delivery workers. Stage observations
//! and signing keys are explicit fixtures, not production training evidence.

use std::sync::atomic::AtomicUsize;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::CircuitCommandV2;
use codex_hepta_automation::CircuitEventV2;
use codex_hepta_automation::CircuitLearningDeliveryV1;
use codex_hepta_automation::CircuitStartV2;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use tokio::sync::Notify;

use super::*;

struct CurrentEvidencePorts {
    inner: Arc<IterationPorts>,
    planned: Mutex<Option<LearningIterationSnapshotV1>>,
    restores: AtomicUsize,
    restored: Notify,
}

impl CurrentEvidencePorts {
    fn new() -> Arc<Self> {
        let mut inner = recovery_ports(Decision::EvaluatedNoUpdate, Trust::Independent);
        let expires = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs()
            + 300;
        for principal in &mut inner.signing.principals {
            principal.expires_at = expires;
        }
        inner.verifier = ok(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("plasticity-scope"),
            objective_digest: digest("plasticity-objective"),
            authority_epoch: 7,
            signers: inner
                .signing
                .principals
                .iter()
                .zip(&inner.signing.keys)
                .enumerate()
                .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: id(&format!("live-fixture-controller-{index}")),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: match index {
                        0 => vec![LearningEvidenceRoleV1::Generator],
                        1 => vec![
                            LearningEvidenceRoleV1::Observer,
                            LearningEvidenceRoleV1::Selector,
                        ],
                        _ => vec![
                            LearningEvidenceRoleV1::Evaluator,
                            LearningEvidenceRoleV1::Observer,
                        ],
                    },
                    revoked_at: None,
                })
                .collect(),
        }));
        Arc::new(Self {
            inner: Arc::new(inner),
            planned: Mutex::new(None),
            restores: AtomicUsize::new(0),
            restored: Notify::new(),
        })
    }

    async fn wait_for_restores(&self, count: usize) {
        tokio::time::timeout(Duration::from_secs(5), async {
            while self.restores.load(Ordering::SeqCst) < count {
                self.restored.notified().await;
            }
        })
        .await
        .expect("delivery reached original checkpoint owner");
    }
}

impl LearningIterationOwnerPortsV1 for CurrentEvidencePorts {
    fn restore<'a>(
        &'a self,
        request: &'a LearningIterationRequestV1,
    ) -> LearningIterationOwnerFutureV1<'a, Option<LearningIterationSnapshotV1>> {
        Box::pin(async move {
            let result = self.inner.restore(request).await;
            self.restores.fetch_add(1, Ordering::SeqCst);
            self.restored.notify_one();
            result
        })
    }

    fn checkpoint<'a>(
        &'a self,
        expected: Digest32,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, Digest32> {
        self.inner.checkpoint(expected, snapshot)
    }

    fn execute_stage<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        stage: LearningIterationStageV1,
    ) -> LearningIterationOwnerFutureV1<'a, LearningIterationReceiptV1> {
        Box::pin(async move {
            let planned = ok(self.planned.lock()).clone();
            let Some(planned) = planned else {
                return self.inner.execute_stage(snapshot, stage).await;
            };
            let receipt = planned
                .receipts
                .get(snapshot.receipts.len())
                .cloned()
                .ok_or(LearningIterationRuntimeErrorV1::WrongScope)?;
            if planned.request != snapshot.request
                || planned.owners != snapshot.owners
                || !planned.receipts.starts_with(&snapshot.receipts)
                || receipt.predecessor != snapshot.head_digest
                || receipt.observation.stage() != stage
            {
                return Err(LearningIterationRuntimeErrorV1::WrongScope);
            }
            ok(self.inner.executed.lock()).push(stage);
            Ok(receipt)
        })
    }

    fn prepare_proposal<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
    ) -> LearningIterationOwnerFutureV1<'a, PreparedLearningIterationProposalV1> {
        self.inner.prepare_proposal(snapshot)
    }

    fn receipt_attestation<'a>(
        &'a self,
        snapshot: &'a LearningIterationSnapshotV1,
        receipt: &'a LearningIterationReceiptV1,
        now: u64,
    ) -> LearningIterationOwnerFutureV1<'a, SignedLearningEvidenceV1> {
        Box::pin(async move {
            let mut signed = self
                .inner
                .receipt_attestation(snapshot, receipt, now)
                .await?;
            let signer = self
                .inner
                .signing
                .principals
                .iter()
                .position(|principal| principal.principal_id == signed.principal_id)
                .expect("original fixture signer");
            signed.issued_at = now;
            signed.expires_at = now + 60;
            signed.signature = self.inner.signing.keys[signer]
                .sign(&signed.signing_bytes())
                .to_bytes();
            Ok(signed)
        })
    }
}

async fn completed_circuit(
    daemon: &AgentdFixture,
) -> (AutomationStore, LearningIterationRequestV1) {
    let store = ok(AutomationStore::open(&daemon.identity.layout).await);
    let mut request = iteration_request(daemon);
    let (mut definition, _) = crate::circuit_cell::tests::configuration();
    let fallback = definition.programs[0].fallback_node.clone();
    definition.programs[0].entry_node = fallback.clone();
    definition.programs[0]
        .nodes
        .retain(|node| node.node_id == fallback);
    definition.programs[0].edges.clear();
    let fence = ok(TaskFlowFence::new(
        daemon.identity.agent_id.clone(),
        "delivery-test",
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        "delivery-fence",
    ));
    let start = CircuitStartV2 {
        run_id: "ordinary-learning-run".into(),
        scope_digest: Sha256Digest::for_bytes(b"test-scope"),
        input_digest: Sha256Digest::for_bytes(b"test-input"),
        created_at_ms: 10,
        lease_duration_ms: 100,
    };
    let created = ok(store
        .create_bounded_circuit_run(&definition, &start, &fence)
        .await);
    ok(store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: start.run_id.clone(),
            command_id: "abstain".into(),
            fence,
            expected_revision: created.run.revision(),
            now_ms: 11,
            event: CircuitEventV2::Advance { quantum: 1 },
        })
        .await);
    let trace = ok(store.bounded_circuit_committed_trace(&start.run_id).await).expect("trace");
    let intent = ok(store
        .enqueue_circuit_learning(
            &trace,
            ok(Sha256Digest::parse(
                request.envelope.objective_digest.to_string(),
            )),
        )
        .await);
    request.source_run_id = id(&intent.source_run_id);
    request.operation_id = id(&intent.operation_id);
    request.completed_task_receipt = ok(intent.completed_task_receipt.as_str().parse());
    (store, request)
}

async fn admitted_state(
    daemon: &AgentdFixture,
) -> (
    Arc<AgentdState>,
    codex_hepta_cognitive_store::DurableCognitiveStore,
) {
    let state = Arc::new(ok(AgentdState::new(
        daemon.identity.clone(),
        daemon.registry.clone(),
        /*event_capacity*/ 16,
    )));
    ok(state.refresh_generation());
    let cognitive =
        ok(codex_hepta_cognitive_store::DurableCognitiveStore::open(&daemon.identity.layout).await);
    ok(state.attach_cognitive_store(Arc::new(cognitive.clone())));
    ok(state.mark_runtime_prerequisites_ready());
    ok(state.mark_app_server_ready());
    assert!(ok(state.automation_admission_ready()));
    (state, cognitive)
}

async fn await_ack(
    store: &AutomationStore,
    request: &LearningIterationRequestV1,
) -> CircuitLearningDeliveryV1 {
    tokio::time::timeout(Duration::from_secs(5), async {
        loop {
            let row = ok(store
                .circuit_learning_delivery(request.source_run_id.as_str())
                .await)
            .unwrap();
            if row.acknowledged_head.is_some() {
                break row;
            }
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("completed original learning snapshot acknowledged")
}

struct Services {
    cancellation: CancellationToken,
    actor: tokio::task::JoinHandle<Result<(), crate::AgentdError>>,
    delivery: tokio::task::JoinHandle<Result<(), crate::AgentdError>>,
}

impl Services {
    fn start(
        daemon: &AgentdFixture,
        state: Arc<AgentdState>,
        store: &AutomationStore,
        request: LearningIterationRequestV1,
        ports: &Arc<CurrentEvidencePorts>,
    ) -> Self {
        let (external, bootstrap) = ok(learning_iteration_channel_v1(
            daemon.identity.agent_id.clone(),
            /*spawn_generation*/ 1,
            ports.inner.owners(),
            ports.clone(),
            ports.inner.verifier.clone(),
            /*capacity*/ 1,
        ));
        let mut bootstrap = ok(bootstrap.with_circuit_learning_delivery(request));
        drop(external);
        let delivery = bootstrap
            .take_circuit_delivery()
            .expect("configured delivery");
        assert!(bootstrap.take_circuit_delivery().is_none());
        let cancellation = CancellationToken::new();
        Self {
            actor: tokio::spawn(bootstrap.run(Arc::clone(&state), cancellation.clone())),
            delivery: tokio::spawn(delivery.run(store.clone(), state, cancellation.clone())),
            cancellation,
        }
    }

    async fn stop(self) {
        self.cancellation.cancel();
        ok(ok(tokio::time::timeout(
            Duration::from_secs(5),
            self.delivery,
        )
        .await
        .expect("delivery stop")));
        ok(ok(tokio::time::timeout(Duration::from_secs(5), self.actor)
            .await
            .expect("actor stop")));
    }
}

#[tokio::test]
async fn ordinary_delivery_authenticates_completed_snapshot_and_retains_required_service() {
    let daemon = AgentdFixture::new();
    let (store, request) = completed_circuit(&daemon).await;
    let ports = CurrentEvidencePorts::new();
    let snapshot =
        completed_snapshot(request.clone(), &ports.inner, Decision::EvaluatedNoUpdate).await;
    install_checkpoint(&ports.inner, &snapshot);
    let expected = CircuitLearningDeliveryV1 {
        intent: ok(store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await)
        .unwrap()
        .intent,
        request_digest: Some(ok(Sha256Digest::parse(
            ok(LearningIterationCoordinatorV1::new(
                request.clone(),
                ports.inner.owners(),
            ))
            .snapshot()
            .head_digest
            .to_string(),
        ))),
        acknowledged_head: Some(ok(Sha256Digest::parse(snapshot.head_digest.to_string()))),
    };
    let (state, cognitive) = admitted_state(&daemon).await;
    let services = Services::start(&daemon, state, &store, request.clone(), &ports);
    let actual = await_ack(&store, &request).await;
    assert_eq!(actual, expected);
    assert_no_work_or_checkpoint(&ports.inner, &snapshot);
    assert!(!ok(ports.inner.attested.lock()).is_empty());
    tokio::time::sleep(Duration::from_millis(25)).await;
    assert!(
        !services.delivery.is_finished(),
        "successful required service remains alive"
    );
    assert!(
        !services.actor.is_finished(),
        "dropped external sender does not disconnect owner"
    );
    services.stop().await;
    cognitive.close().await;
    store.close().await;
}

#[tokio::test]
async fn ordinary_delivery_fresh_request_executes_one_fixture_iteration_and_acknowledges_next_use()
{
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
    assert!(ok(ports.inner.checkpoint.lock()).is_none());
    let (state, cognitive) = admitted_state(&daemon).await;
    let services = Services::start(&daemon, state, &store, request.clone(), &ports);
    let row = await_ack(&store, &request).await;
    assert_eq!(
        row.acknowledged_head,
        Some(ok(Sha256Digest::parse(planned.head_digest.to_string())))
    );
    assert_eq!(*ok(ports.inner.checkpoint.lock()), Some(planned.clone()));
    let expected_stages = vec![
        LearningIterationStageV1::Experience,
        LearningIterationStageV1::Dataset,
        LearningIterationStageV1::Training,
        LearningIterationStageV1::Evaluation,
        LearningIterationStageV1::Selection,
        LearningIterationStageV1::NextUse,
    ];
    let mut expected_checkpoints = vec![Digest32::ZERO];
    expected_checkpoints.extend(planned.receipts.iter().map(|receipt| receipt.predecessor));
    assert_eq!(*ok(ports.inner.executed.lock()), expected_stages);
    assert_eq!(
        *ok(ports.inner.checkpoint_calls.lock()),
        expected_checkpoints
    );
    tokio::time::sleep(Duration::from_millis(1100)).await;
    assert_eq!(*ok(ports.inner.executed.lock()), expected_stages);
    assert_eq!(
        *ok(ports.inner.checkpoint_calls.lock()),
        expected_checkpoints
    );
    assert_eq!(ports.restores.load(Ordering::SeqCst), 1);
    services.stop().await;
    cognitive.close().await;
    store.close().await;
}

#[tokio::test]
async fn ordinary_delivery_claimed_missing_or_partial_state_only_reads_back() {
    for partial in [false, true] {
        let daemon = AgentdFixture::new();
        let (store, request) = completed_circuit(&daemon).await;
        let ports = CurrentEvidencePorts::new();
        let initial = ok(LearningIterationCoordinatorV1::new(
            request.clone(),
            ports.inner.owners(),
        ))
        .snapshot()
        .clone();
        let row = ok(store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await)
        .unwrap();
        assert!(ok(store
            .claim_circuit_learning(
                &row.intent,
                &ok(Sha256Digest::parse(initial.head_digest.to_string()))
            )
            .await));
        let claimed = ok(store.pending_circuit_learning(/*limit*/ 1).await);
        if partial {
            install_checkpoint(&ports.inner, &initial);
        }
        let state = daemon.state();
        assert!(ok(state.plasticity_admission_ready()));
        assert!(!ok(state.automation_admission_ready()));
        let services = Services::start(&daemon, state, &store, request, &ports);
        ports.wait_for_restores(/*count*/ 2).await;
        services.stop().await;
        assert_eq!(
            ok(store.pending_circuit_learning(/*limit*/ 1).await),
            claimed
        );
        assert_eq!(
            *ok(ports.inner.checkpoint.lock()),
            partial.then_some(initial)
        );
        assert!(ok(ports.inner.executed.lock()).is_empty());
        assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());
        store.close().await;
    }
}

#[tokio::test]
async fn ordinary_delivery_absent_source_never_consumes_other_intents() {
    let daemon = AgentdFixture::new();
    let (store, mut request) = completed_circuit(&daemon).await;
    let pending = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    request.source_run_id = id("uncompleted-source");
    let ports = CurrentEvidencePorts::new();
    let (state, cognitive) = admitted_state(&daemon).await;
    let services = Services::start(&daemon, state, &store, request, &ports);
    tokio::time::sleep(Duration::from_millis(1100)).await;
    services.stop().await;
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await),
        pending
    );
    assert_eq!(ports.restores.load(Ordering::SeqCst), 0);
    assert!(ok(ports.inner.executed.lock()).is_empty());
    assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());
    cognitive.close().await;
    store.close().await;
}

#[tokio::test]
async fn ordinary_delivery_app_ready_with_closed_admission_never_claims() {
    let daemon = AgentdFixture::new();
    let (store, request) = completed_circuit(&daemon).await;
    let pending = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    let ports = CurrentEvidencePorts::new();
    let state = daemon.state();
    assert!(ok(state.plasticity_admission_ready()));
    assert!(!ok(state.automation_admission_ready()));
    let services = Services::start(&daemon, state, &store, request, &ports);
    tokio::time::sleep(Duration::from_millis(1100)).await;
    services.stop().await;
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await),
        pending
    );
    assert_eq!(ports.restores.load(Ordering::SeqCst), 0);
    assert!(ok(ports.inner.executed.lock()).is_empty());
    assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());
    store.close().await;
}

#[tokio::test]
async fn ordinary_delivery_waits_for_app_server_readiness_before_claim() {
    let daemon = AgentdFixture::new();
    let (store, request) = completed_circuit(&daemon).await;
    let pending = ok(store.pending_circuit_learning(/*limit*/ 1).await);
    let ports = CurrentEvidencePorts::new();
    let state = Arc::new(ok(AgentdState::new(
        daemon.identity.clone(),
        daemon.registry.clone(),
        /*event_capacity*/ 16,
    )));
    ok(state.refresh_generation());
    let services = Services::start(&daemon, state, &store, request, &ports);
    tokio::time::sleep(Duration::from_millis(1100)).await;
    services.stop().await;
    assert_eq!(
        ok(store.pending_circuit_learning(/*limit*/ 1).await),
        pending
    );
    assert_eq!(ports.restores.load(Ordering::SeqCst), 0);
    assert!(ok(ports.inner.executed.lock()).is_empty());
    assert!(ok(ports.inner.checkpoint_calls.lock()).is_empty());
    store.close().await;
}

#[test]
fn ordinary_delivery_bootstrap_rejects_duplicate_and_foreign_request() {
    let daemon = AgentdFixture::new();
    let ports = Arc::new(recovery_ports(
        Decision::EvaluatedNoUpdate,
        Trust::Independent,
    ));
    let request = iteration_request(&daemon);
    let bootstrap = ok(runtime(&daemon, &ports).with_circuit_learning_delivery(request.clone()));
    assert!(matches!(
        bootstrap.with_circuit_learning_delivery(request.clone()),
        Err(crate::AgentdError::Invalid(_))
    ));
    let mut foreign = request;
    foreign.agent_id = id("another-agent");
    assert!(matches!(
        runtime(&daemon, &ports).with_circuit_learning_delivery(foreign),
        Err(crate::AgentdError::GenerationFenced(_))
    ));
}

#[tokio::test]
async fn original_root_delivery_refuses_missing_objective_before_claim_or_stage_work() {
    let daemon = AgentdFixture::new();
    let (store, request) = completed_circuit(&daemon).await;
    let ports = Arc::new(recovery_ports(
        Decision::EvaluatedNoUpdate,
        Trust::Independent,
    ));
    let (state, cognitive) = admitted_state(&daemon).await;
    ok(state.attach_circuit_learning_source(request.source_run_id.clone()));
    let strict = ok(runtime(&daemon, &ports)
        .with_original_circuit_learning_delivery(request.clone()));
    assert!(matches!(
        strict.with_circuit_learning_delivery(request.clone()),
        Err(crate::AgentdError::Invalid(_))
    ));
    let mut bootstrap = ok(runtime(&daemon, &ports)
        .with_original_circuit_learning_delivery(request.clone()));
    let delivery = bootstrap.take_circuit_delivery().expect("Root delivery");
    let result = tokio::time::timeout(
        Duration::from_secs(5),
        delivery.run(store.clone(), state, CancellationToken::new()),
    )
    .await
    .expect("source refusal");
    assert!(matches!(
        result,
        Err(crate::AgentdError::Invalid(message))
            if message.contains("original learning Objective owner is unavailable")
    ));
    let row = ok(store.circuit_learning_delivery(request.source_run_id.as_str()).await)
        .expect("original completion");
    assert_eq!(row.request_digest, None);
    assert_eq!(row.acknowledged_head, None);
    assert!(ok(ports.executed.lock()).is_empty());
    assert!(ok(ports.checkpoint_calls.lock()).is_empty());
    cognitive.close().await;
    store.close().await;
}
