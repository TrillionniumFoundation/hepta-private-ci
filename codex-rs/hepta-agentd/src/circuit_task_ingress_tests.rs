//! Ordinary signed ingress and real SQLite/Cell journals. Issuer, source,
//! readiness and model observations are controlled fixtures, not serving proof.
#![cfg(target_os = "linux")]

use std::collections::BTreeMap;
use std::fs;
use std::fs::OpenOptions;
use std::os::unix::fs::PermissionsExt;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::AtomicUsize;

use codex_hepta_automation::*;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::*;
use codex_hepta_objective::canonical_objective_intent_digest_v1;
use codex_hepta_objective::decode_source_envelope_json_v1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

use super::*;
use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::AuthBusObjectiveBody;
use crate::AuthBusObjectiveIngress;
use crate::CircuitTaskInputModeV1;
use crate::CircuitTaskInputProviderV1;
use crate::CircuitTaskReceiptV1;
use crate::CircuitTaskRequestV1;
use crate::circuit_cell::tests::configuration;
use crate::circuit_cell::tests::support as cell;

const RUN: &str = "circuit.ingress.run.1";
const ISSUER: &str = "circuit-objective-test-issuer";

#[path = "circuit_task_drain_ingress_tests.rs"]
mod drain_tests;
#[path = "circuit_learning_source_tests.rs"]
mod learning_source_tests;
#[path = "circuit_q24_task_ingress_tests.rs"]
mod q24_tests;
#[path = "circuit_q24_successor_runtime_tests.rs"]
mod successor_tests;

#[path = "circuit_task_runtime_tests.rs"]
mod runtime_tests;

struct Invocation {
    records: Mutex<Vec<RunStartRecordV1>>,
    receipts: Mutex<Vec<CircuitTaskReceiptV1>>,
    lose_ack: AtomicBool,
    expire: bool,
    clock_floor: Arc<AtomicU64>,
    build_gate: Mutex<Option<Arc<drain_tests::Gate>>>,
    result_gate: Mutex<Option<Arc<drain_tests::Gate>>>,
}

impl AgentdCircuitTaskInvocationProviderV1 for Invocation {
    fn build(
        &self,
        identity: &AgentdIdentity,
        record: &RunStartRecordV1,
    ) -> Result<CircuitTaskRequestV1, crate::AgentdError> {
        assert_eq!(
            identity.agent_id.as_str(),
            cell::scope(RUN).agent_id.as_str()
        );
        self.records.lock().expect("records").push(record.clone());
        let gate = self.build_gate.lock().expect("build gate").clone();
        if let Some(gate) = gate {
            gate.wait()?;
        }
        let deadline_ms = record.admission.deadline_unix_micros / 1_000;
        if self.expire {
            self.clock_floor.store(deadline_ms, Ordering::SeqCst);
        }
        Ok(CircuitTaskRequestV1 {
            start: CircuitStartV2 {
                run_id: record.snapshot.run_id.to_string(),
                scope_digest: crate::circuit_cell_scope_digest_v1(&cell::scope(RUN))
                    .expect("fixture scope digest"),
                input_digest: Sha256Digest::for_bytes(&cell::input(RUN).observation),
                created_at_ms: record.admission.observed_at_unix_micros / 1_000,
                lease_duration_ms: 60_000,
            },
            objective_digest: record.snapshot.objective_digest,
            deadline_ms,
        })
    }

    fn publish_result(
        &self,
        _identity: &AgentdIdentity,
        record: &RunStartRecordV1,
        receipt: &CircuitTaskReceiptV1,
    ) -> Result<(), crate::AgentdError> {
        assert_eq!(
            receipt.trace().run().run_id(),
            record.snapshot.run_id.as_str()
        );
        let mut receipts = self.receipts.lock().expect("receipts");
        if let Some(original) = receipts.first() {
            assert_eq!(receipt, original, "retry must publish the original result");
        }
        receipts.push(receipt.clone());
        drop(receipts);
        let gate = self.result_gate.lock().expect("result gate").clone();
        if let Some(gate) = gate {
            gate.wait()?;
        }
        if self.lose_ack.swap(false, Ordering::SeqCst) {
            return Err(crate::AgentdError::Protocol(
                "fixture lost result ACK".into(),
            ));
        }
        Ok(())
    }
}

struct Inputs(BTreeMap<u64, CellStepInputV1>);

impl CircuitTaskInputProviderV1 for Inputs {
    fn resolve(
        &mut self,
        request: &CircuitTaskRequestV1,
        dispatch: &CircuitDispatchV2,
        _completed: &BTreeMap<u64, crate::CircuitCellExecutionV1>,
        mode: CircuitTaskInputModeV1,
    ) -> Result<CellStepInputV1, crate::CircuitTaskErrorV1> {
        if let Some(original) = self.0.get(&dispatch.activation_id) {
            return Ok(original.clone());
        }
        if mode == CircuitTaskInputModeV1::Readback {
            return Err(crate::CircuitTaskErrorV1::ReconciliationRequired);
        }
        let mut input = cell::input(&request.start.run_id);
        input.operation_id = crate::circuit_cell_operation_id_v1(dispatch)?;
        input.objective_digest = request.objective_digest;
        self.0.insert(dispatch.activation_id, input.clone());
        Ok(input)
    }
}

fn cell_owner(fixture: &RuntimeFixture) -> CellOwnerJournalV1<FileAnchorWitnessStore> {
    let file = |name| {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create(true)
            .truncate(false)
            .open(fixture.identity.home_root.join(name))
            .expect("owner file")
    };
    let witness = FileAnchorWitnessStore::open(
        file("circuit-cell.witness"),
        JournalScope {
            scope_digest: cell::d("ingress-owner"),
            objective_digest: cell::d("journal"),
        },
        Generation::new(1).expect("generation"),
        /*max_records*/ 64,
    )
    .expect("independent durable witness");
    CellOwnerJournalV1::open(
        file("circuit-cell.journal"),
        witness,
        vec![CellJournalPartitionV1 {
            scope: cell::scope(RUN),
            definition: cell::definition(),
            source_frontier: cell::d("frontier"),
            writer_epoch: 1,
        }],
        /*max_records*/ 64,
    )
    .expect("real Cell owner")
}

struct Fixture {
    runtime: RuntimeFixture,
    store: AutomationStore,
    invocation: Arc<Invocation>,
    request: AuthBusObjectiveIngress,
    calls: Arc<AtomicUsize>,
    cancellation: CancellationToken,
    worker: Option<tokio::task::JoinHandle<Result<(), crate::AgentdError>>>,
}

impl Fixture {
    async fn stop(&mut self) {
        self.cancellation.cancel();
        if let Some(worker) = self.worker.take() {
            timeout(Duration::from_secs(5), worker)
                .await
                .expect("owner stopped")
                .expect("owner task")
                .expect("owner shutdown");
        }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

async fn fixture(lose_ack: bool, expire: bool) -> anyhow::Result<Fixture> {
    let model = cell::Model::new(/*latency*/ 20, /*lose_response*/ false);
    let calls = Arc::clone(&model.calls);
    fixture_with_model(lose_ack, expire, model, calls).await
}

async fn fixture_with_model<P>(
    lose_ack: bool,
    expire: bool,
    model: P,
    calls: Arc<AtomicUsize>,
) -> anyhow::Result<Fixture>
where
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1 + Send + 'static,
{
    let runtime = runtime_fixture();
    attach_runtime_prerequisites(&runtime).await;
    runtime.registry.compare_and_transition(
        &runtime.identity.agent_id,
        1,
        AgentLifecycle::Running,
    )?;
    runtime.state.refresh_generation()?;
    runtime.state.mark_app_server_ready()?;
    let request = signed_ingress(&runtime.state).await?;
    let store = AutomationStore::open(&runtime.identity.layout).await?;
    runtime.state.attach_automation_store(store.clone())?;
    let clock_floor = Arc::new(AtomicU64::new(0));
    let invocation = Arc::new(Invocation {
        records: Mutex::new(Vec::new()),
        receipts: Mutex::new(Vec::new()),
        lose_ack: AtomicBool::new(lose_ack),
        expire,
        clock_floor: Arc::clone(&clock_floor),
        build_gate: Mutex::new(None),
        result_gate: Mutex::new(None),
    });
    let (mut definition, bindings) = configuration();
    definition.limits.max_elapsed_ms = 60_000;
    let cells = crate::AgentdCircuitCellOwnerV1::new(
        crate::CircuitCellRegistryV1::new(definition, bindings)?,
        cell_owner(&runtime),
        model,
        cell::Encoder,
    );
    let fence = TaskFlowFence::new(
        runtime.identity.agent_id.clone(),
        "circuit-ingress-owner",
        /*owner_epoch*/ 1,
        runtime.state.current_generation()?,
        "circuit-ingress-fence",
    )?;
    let (handle, bootstrap) = crate::circuit_task_channel_v1(
        &runtime.identity,
        fence,
        cells,
        Inputs(BTreeMap::new()),
        move || crate::CircuitCellTimeV1 {
            circuit_millis: crate::authbus_ingress::now_ms()
                .expect("host clock")
                .max(clock_floor.load(Ordering::SeqCst)),
            cell_micros: 20,
        },
        /*capacity*/ 4,
    )?;
    assert!(runtime.state.circuit_task.set(handle).is_ok());
    assert!(
        runtime
            .state
            .circuit_task_invocation
            .set(invocation.clone())
            .is_ok()
    );
    assert!(runtime.state.notes_objective.get().is_none());
    assert!(!runtime.state.canonical_intelligence_enabled());
    let cancellation = CancellationToken::new();
    let worker = tokio::spawn(bootstrap.run(Arc::clone(&runtime.state), cancellation.clone()));
    Ok(Fixture {
        runtime,
        store,
        invocation,
        request,
        calls,
        cancellation,
        worker: Some(worker),
    })
}

async fn signed_ingress(state: &AgentdState) -> anyhow::Result<AuthBusObjectiveIngress> {
    signed_ingress_for_run(state, RUN).await
}

async fn signed_ingress_for_run(
    state: &AgentdState,
    run: &str,
) -> anyhow::Result<AuthBusObjectiveIngress> {
    let identity = state.identity();
    fs::set_permissions(&identity.home_root, fs::Permissions::from_mode(0o700))?;
    let key = SigningKey::from_bytes(&[91; 32]);
    let public_key_hex: String = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    let trust = identity.home_root.join("circuit-trust.json");
    let checkpoint = identity.run_root.join("circuit-checkpoint.json");
    let evidence = codex_hepta_evidence::HeptaEvidenceStore::open(
        &codex_state::SqliteConfig::from_sqlite_home(
            codex_utils_absolute_path::AbsolutePathBuf::from_absolute_path(&identity.home_root)?,
        ),
    )
    .await?;
    let frontier = evidence.authbus_replay_frontier_digest().await?;
    drop(evidence);
    for (path, value) in [
        (
            &trust,
            json!({"schema_version":1,"agent_id":identity.agent_id.as_str(),"issuer_id":ISSUER,
            "key_epoch":1,"public_key_hex":public_key_hex,"revoked":false,"thread_ids":[]}),
        ),
        (
            &checkpoint,
            json!({"schema_version":1,"agent_id":identity.agent_id.as_str(),
            "generation":1,"digest":frontier.to_string()}),
        ),
    ] {
        fs::write(path, serde_json::to_vec(&value)?)?;
        fs::set_permissions(path, fs::Permissions::from_mode(0o600))?;
    }
    let ingress = crate::authbus_ingress::TextIngress::open(identity, trust, checkpoint).await?;
    assert!(state.authbus.set(Arc::new(ingress)).is_ok());
    // Reuse the frozen structured admission schema with computation labels.
    // Neither the Notes owner nor the finite Notes execution profile is enabled.
    let mut document: Value = serde_json::from_str(
        &include_str!("../tests/fixtures/notes-objective-literal-v1.json")
            .replace("notes.replace", "circuit.compute")
            .replace("notes", "circuit"),
    )?;
    let profile = identity.home_root.join("circuit-profile.json");
    fs::write(&profile, serde_json::to_vec(&document["profile"])?)?;
    fs::set_permissions(&profile, fs::Permissions::from_mode(0o600))?;
    let host = crate::objective_runtime::ObjectiveRuntimeHost::open(identity, &profile)?;
    assert!(state.objective_runtime.set(Arc::new(host)).is_ok());
    let now = crate::authbus_ingress::now_ms()?;
    let source = &mut document["source"];
    source["requestId"] = json!(run);
    source["observedAt"] = json!(crate::notes_literal_prepare::utc_millis(now)?);
    source["deadline"] = json!(crate::notes_literal_prepare::utc_millis(now + 60_000)?);
    source["structuredIntent"]["resources"]["externalEffectCount"] = json!(0);
    source["structuredIntent"]["provenance"]["sourceDigest"] =
        json!(cell::d("original source").to_string());
    let decoded = decode_source_envelope_json_v1(&serde_json::to_vec(source)?)?;
    source["intentDigest"] = json!(canonical_objective_intent_digest_v1(&decoded)?.to_string());
    let digest = cell::d("explicit fixture runtime").to_string();
    let mut request = AuthBusObjectiveIngress {
        issuer_id: ISSUER.into(),
        key_epoch: 1,
        message_id: "circuit-ingress-message".into(),
        sequence: 1,
        expires_at_ms: now + 120_000,
        signature_hex: String::new(),
        body: AuthBusObjectiveBody {
            spawn_generation: identity.spawn_generation,
            run_id: run.into(),
            objective_revision: 1,
            source_envelope_json: serde_json::to_string(source)?,
            runtime_body_digest: digest.clone(),
            preference_state_digest: digest.clone(),
            model_tuple_digest: digest.clone(),
            prompt_registry_digest: digest.clone(),
            artifact_set_digest: digest,
            authority_epoch: 13,
        },
    };
    let claims = crate::authbus_objective_claims(identity, &request)?;
    request.signature_hex = key
        .sign(&claims.signing_bytes())
        .to_bytes()
        .iter()
        .map(|b| format!("{b:02x}"))
        .collect();
    Ok(request)
}

#[tokio::test]
async fn signed_objective_sink_ack_loss_replays_original_circuit_and_cell_result()
-> anyhow::Result<()> {
    let mut f = fixture(/*lose_ack*/ true, /*expire*/ false).await?;
    let state = Arc::clone(&f.runtime.state);
    state.attach_circuit_learning_source(StableId::new(RUN)?)?;
    assert!(
        state
            .response(
                1,
                1,
                AgentdMethod::ObjectiveStart {
                    request: f.request.clone()
                }
            )
            .await
            .is_err()
    );
    let first = f.invocation.receipts.lock().expect("receipt")[0].clone();
    assert_eq!(
        first.trace().run().outcome(),
        Some(CircuitExitV2::Succeeded)
    );
    assert_eq!(first.executions().len(), 1);
    assert_eq!(first.trace().run().budget().spent(), 20);
    assert_eq!(first.trace().run().budget().reserved(), 0);
    assert_eq!(
        f.store.bounded_circuit_committed_trace(RUN).await?.as_ref(),
        Some(first.trace()),
        "the service uses the attached original AutomationStore",
    );
    assert!(
        f.store
            .pending_circuit_learning(/*limit*/ 1)
            .await
            .unwrap()
            .is_empty()
    );
    // The sink observed the committed result but lost its ACK. Startup repair
    // derives a pointer from original journals, without a second Objective call.
    state
        .objective_runtime
        .get()
        .expect("original objective owner")
        .reconcile_learning_outbox(&f.store, state.circuit_learning_source(), &state)
        .await?;
    let pending = f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap();
    assert_eq!(pending.len(), 1);
    assert_eq!(
        pending[0].intent.completed_task_receipt,
        *first.trace().history_digest()
    );
    assert_eq!(pending[0].request_digest, None);
    assert_eq!(pending[0].acknowledged_head, None);
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    let authentication = crate::authbus_objective_claims(state.identity(), &f.request)?;
    let record = f.invocation.records.lock().expect("record")[0].clone();
    assert_eq!(
        record.authentication.signed_body_digest,
        authentication.payload_digest
    );
    assert_eq!(record.snapshot.generation, state.current_generation()?);
    assert_ne!(
        record.snapshot.generation,
        state.identity().spawn_generation
    );
    for request_id in [2, 3] {
        let response = state
            .response(
                request_id,
                1,
                AgentdMethod::ObjectiveStart {
                    request: f.request.clone(),
                },
            )
            .await?;
        let AgentdPayload::ObjectiveRun(admission) = response.payload else {
            panic!("ordinary objective admission")
        };
        assert_eq!(admission.disposition, "circuit_succeeded");
        assert!(admission.idempotent);
    }
    assert_eq!(
        *f.invocation.receipts.lock().expect("receipts"),
        vec![first.clone(); 3]
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        f.store.bounded_circuit_committed_trace(RUN).await?.as_ref(),
        Some(first.trace())
    );
    assert_eq!(
        f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap(),
        pending
    );
    f.stop().await;
    let reopened = cell_owner(&f.runtime);
    let decision = &first
        .executions()
        .values()
        .next()
        .expect("one Cell")
        .decision;
    assert_eq!(
        reopened.lookup(
            &decision.scope,
            &decision.operation_id,
            decision.semantic_request_digest
        )?,
        Some(decision.clone())
    );
    let snapshot = reopened.snapshot(&decision.scope)?;
    assert_eq!(snapshot.revision, 1);
    assert_eq!(
        snapshot.checkpoint.expect("durable checkpoint").digest(),
        decision.checkpoint_after
    );
    assert_eq!(reopened.pending_inference(&decision.scope)?, None);
    f.store.close().await;
    Ok(())
}

#[tokio::test]
async fn ordinary_ingress_rejects_invalid_trust_generation_and_deadline_before_contact()
-> anyhow::Result<()> {
    for boundary in ["signature", "revoked", "generation", "deadline"] {
        let mut f = fixture(/*lose_ack*/ false, boundary == "deadline").await?;
        let mut request = f.request.clone();
        if boundary == "signature" {
            request.signature_hex = "00".repeat(64);
        }
        if boundary == "revoked" {
            let path = f.runtime.identity.home_root.join("circuit-trust.json");
            let mut trust: Value = serde_json::from_slice(&fs::read(&path)?)?;
            trust["revoked"] = json!(true);
            fs::write(path, serde_json::to_vec(&trust)?)?;
        }
        let spawn_generation = if boundary == "generation" { 2 } else { 1 };
        assert!(
            f.runtime
                .state
                .response(
                    1,
                    spawn_generation,
                    AgentdMethod::ObjectiveStart { request }
                )
                .await
                .is_err(),
            "{boundary}"
        );
        assert_eq!(f.calls.load(Ordering::SeqCst), 0, "{boundary}");
        assert!(f.invocation.receipts.lock().expect("receipts").is_empty());
        assert_eq!(f.store.bounded_circuit_run(RUN).await?, None, "{boundary}");
        f.stop().await;
        let owner = cell_owner(&f.runtime);
        assert_eq!(owner.snapshot(&cell::scope(RUN))?.revision, 0);
        assert_eq!(owner.pending_inference(&cell::scope(RUN))?, None);
        f.store.close().await;
    }
    Ok(())
}

#[tokio::test]
async fn historical_completion_repair_does_not_renew_revoked_objective_authority()
-> anyhow::Result<()> {
    let mut f = fixture(/*lose_ack*/ true, /*expire*/ false).await?;
    let state = Arc::clone(&f.runtime.state);
    state.attach_circuit_learning_source(StableId::new(RUN)?)?;
    assert!(
        state
            .response(
                /*request_id*/ 1,
                /*spawn_generation*/ 1,
                AgentdMethod::ObjectiveStart {
                    request: f.request.clone()
                }
            )
            .await
            .is_err()
    );
    let path = f.runtime.identity.home_root.join("circuit-trust.json");
    let mut trust: Value = serde_json::from_slice(&fs::read(&path)?)?;
    trust["revoked"] = json!(true);
    fs::write(path, serde_json::to_vec(&trust)?)?;
    state
        .objective_runtime
        .get()
        .expect("objective owner")
        .reconcile_learning_outbox(&f.store, state.circuit_learning_source(), &state)
        .await?;
    let pending = f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap();
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].request_digest, None);
    assert_eq!(pending[0].acknowledged_head, None);
    assert!(
        state
            .response(
                /*request_id*/ 2,
                /*spawn_generation*/ 1,
                AgentdMethod::ObjectiveStart {
                    request: f.request.clone()
                }
            )
            .await
            .is_err()
    );
    assert_eq!(f.calls.load(Ordering::SeqCst), 1);
    assert_eq!(
        f.store.pending_circuit_learning(/*limit*/ 1).await.unwrap(),
        pending
    );
    f.stop().await;
    f.store.close().await;
    Ok(())
}

#[tokio::test]
async fn ordinary_completion_without_matching_learning_source_does_not_enqueue()
-> anyhow::Result<()> {
    for configured in [None, Some("another-learning-source")] {
        let mut f = fixture(/*lose_ack*/ false, /*expire*/ false).await?;
        let state = Arc::clone(&f.runtime.state);
        if let Some(source) = configured {
            state.attach_circuit_learning_source(StableId::new(source)?)?;
        }
        let response = state
            .response(
                /*request_id*/ 1,
                /*spawn_generation*/ 1,
                AgentdMethod::ObjectiveStart {
                    request: f.request.clone(),
                },
            )
            .await?;
        let AgentdPayload::ObjectiveRun(admission) = response.payload else {
            panic!("ordinary objective admission");
        };
        assert_eq!(admission.disposition, "circuit_succeeded");
        assert_eq!(f.calls.load(Ordering::SeqCst), 1);
        assert!(
            f.store
                .pending_circuit_learning(/*limit*/ 1)
                .await
                .unwrap()
                .is_empty()
        );
        state
            .objective_runtime
            .get()
            .expect("original objective owner")
            .reconcile_learning_outbox(&f.store, state.circuit_learning_source(), &state)
            .await?;
        assert!(
            f.store
                .pending_circuit_learning(/*limit*/ 1)
                .await
                .unwrap()
                .is_empty()
        );
        assert_eq!(f.calls.load(Ordering::SeqCst), 1);
        f.stop().await;
        f.store.close().await;
    }
    Ok(())
}
