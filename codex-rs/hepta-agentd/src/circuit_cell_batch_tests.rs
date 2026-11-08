use pretty_assertions::assert_eq;

use std::fs::OpenOptions;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;

use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_types::Generation;

use super::*;
use support::feature_receipt;

#[derive(Default)]
struct BatchModel {
    batches: Vec<Vec<NeuronFeatureRequestV1>>,
    receipts: Vec<NeuronFeatureReceiptV1>,
    reads: usize,
    corrupt_last: bool,
}

impl NeuronInferenceControlPort for BatchModel {
    fn execute_feature(&mut self, _: &NeuronFeatureRequestV1) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        panic!("the batch entry must not fall back to scalar inference")
    }
}

impl CellMicrobatchInferenceControlPortV1 for BatchModel {
    fn execute_feature_batch(&mut self, requests: &[NeuronFeatureRequestV1]) -> Result<Vec<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.batches.push(requests.to_vec());
        let mut receipts: Vec<_> = requests.iter().map(|request| feature_receipt(request, /*latency*/ 20)).collect();
        self.receipts.extend(receipts.iter().cloned());
        if self.corrupt_last && let Some(last) = receipts.last_mut() {
            last.receipt_digest = d("damaged-response");
        }
        receipts.reverse();
        Ok(receipts)
    }
}

impl CellInferenceReadbackPortV1 for BatchModel {
    fn read_feature(&mut self, request: &NeuronFeatureRequestV1) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.reads += 1;
        let digest = checked(neuron_feature_request_digest_v1(request));
        Ok(self.receipts.iter().find(|receipt| receipt.request_digest == digest).cloned())
    }
}

struct BatchFixture {
    directory: tempfile::TempDir,
    store: AutomationStore,
    definition: BoundedCircuitDefinitionV2,
    bindings: Vec<CircuitCellBindingV1>,
    dispatches: Vec<CircuitDispatchV2>,
    inputs: Vec<CellStepInputV1>,
}

async fn fixture(deadlines: [u64; 2]) -> (BatchFixture, Vec<(CircuitComputationAdmissionV2, CellStepInputV1)>) {
    let (definition, bindings) = configuration();
    let (directory, store, first) = create_run(&definition).await;
    let created = checked(store.create_bounded_circuit_run(&definition, &CircuitStartV2 {
        run_id: "run-2".to_string(),
        scope_digest: checked(circuit_cell_scope_digest_v1(&scope("run-2"))),
        input_digest: Sha256Digest::for_bytes(&input("run-2").observation),
        created_at_ms: 10,
        lease_duration_ms: 500,
    }, &fence()).await);
    let second = checked(store.apply_bounded_circuit_command(&CircuitCommandV2 {
        run_id: "run-2".to_string(), command_id: "advance".to_string(), fence: fence(),
        expected_revision: created.run.revision(), now_ms: 11,
        event: CircuitEventV2::Advance { quantum: 1 },
    }).await).dispatches.remove(0);
    let dispatches = vec![first, second];
    let mut inputs = Vec::new();
    let mut items = Vec::new();
    for (index, dispatch) in dispatches.iter().enumerate() {
        let mut input = input(&dispatch.run_id);
        input.operation_id = checked(circuit_cell_operation_id_v1(dispatch));
        input.deadline_micros = deadlines[index];
        let run = checked(store.bounded_circuit_run(&dispatch.run_id).await).expect("run");
        let admission = checked(store.claim_circuit_computation(&CircuitComputationClaimV2 {
            run_id: dispatch.run_id.clone(), activation_id: dispatch.activation_id,
            command_id: "claim".to_string(), fence: fence(), expected_revision: run.revision(), now_ms: 13,
            execution_request_digest: checked(Sha256Digest::parse(
                checked(canonical_cell_step_request_digest_v1(&bindings[0].cell, &input)).to_string(),
            )),
        }).await);
        inputs.push(input.clone());
        items.push((admission, input));
    }
    (BatchFixture { directory, store, definition, bindings, dispatches, inputs }, items)
}

fn owner(fixture: &BatchFixture) -> CellPartitionOwnerV1 {
    let mut owner = checked(CellPartitionOwnerV1::new(/*max_partitions*/ 2, /*max_receipts_per_partition*/ 8));
    for input in &fixture.inputs {
        checked(owner.admit(input.scope.clone(), &fixture.bindings[0].cell, input.source_frontier, /*writer_epoch*/ 1));
    }
    owner
}

fn runtime<O: CellStateOwnerV1>(fixture: &BatchFixture, owner: O, model: BatchModel) -> AgentdCircuitCellOwnerV1<O, BatchModel, Encoder> {
    AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(fixture.definition.clone(), fixture.bindings.clone())),
        owner, model, Encoder,
    )
}

async fn recovery_items(fixture: &BatchFixture) -> Vec<(CircuitComputationAdmissionV2, CellStepInputV1)> {
    let mut items = Vec::new();
    for (dispatch, input) in fixture.dispatches.iter().zip(&fixture.inputs) {
        let admission = checked(fixture.store.recover_circuit_computation(
            &dispatch.run_id, dispatch.activation_id, &fence(), /*now_ms*/ 21,
        ).await);
        assert!(admission.reconciliation_only());
        items.push((admission, input.clone()));
    }
    items
}

#[tokio::test]
async fn one_frozen_batch_keeps_scoped_state_and_ack_replay_independent() {
    let (fixture, items) = fixture([100, 100]).await;
    let mut runtime = runtime(&fixture, owner(&fixture), BatchModel::default());
    let first: Vec<_> = checked(runtime.execute_batch(items, time)).into_iter().map(checked).collect();
    assert_eq!(runtime.inference_control.batches.len(), 1);
    assert_eq!(runtime.inference_control.batches[0].len(), 2);
    let snapshots: Vec<_> = fixture.inputs.iter().map(|input| checked(runtime.state_owner().snapshot(&input.scope))).collect();
    assert!(snapshots.iter().all(|snapshot| snapshot.revision == 1));
    assert_ne!(snapshots[0].checkpoint, snapshots[1].checkpoint);
    let replayed: Vec<_> = checked(runtime.execute_batch(recovery_items(&fixture).await, || CircuitCellTimeV1 {
        circuit_millis: 22, cell_micros: 22,
    })).into_iter().map(checked).collect();
    assert_eq!(replayed, first);
    assert_eq!((runtime.inference_control.batches.len(), runtime.inference_control.reads), (1, 0));
    for (index, execution) in replayed.into_iter().enumerate() {
        let run_id = fixture.inputs[index].scope.run_id.as_str();
        let run = checked(fixture.store.bounded_circuit_run(run_id).await).expect("run");
        let committed = checked(fixture.store.apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: run_id.to_string(), command_id: "complete".to_string(), fence: fence(),
            expected_revision: run.revision(), now_ms: 22,
            event: CircuitEventV2::Complete { completion: execution.completion },
        }).await);
        assert_eq!((committed.run.budget().spent(), committed.run.budget().reserved()), (20, 0));
    }
    fixture.store.close().await;
}

#[tokio::test]
async fn partial_batch_receipt_failure_recovers_only_original_pending_work() {
    let (fixture, items) = fixture([100, 100]).await;
    let mut runtime = runtime(&fixture, owner(&fixture), BatchModel { corrupt_last: true, ..BatchModel::default() });
    let first = checked(runtime.execute_batch(items, time));
    assert!(first[0].is_ok());
    assert!(first[1].is_err());
    assert!(checked(runtime.state_owner().pending_inference(&fixture.inputs[0].scope)).is_none());
    assert!(checked(runtime.state_owner().pending_inference(&fixture.inputs[1].scope)).is_some());
    let recovered: Vec<_> = checked(runtime.execute_batch(recovery_items(&fixture).await, || CircuitCellTimeV1 {
        circuit_millis: 22, cell_micros: 22,
    })).into_iter().map(checked).collect();
    assert_eq!((runtime.inference_control.batches.len(), runtime.inference_control.reads), (1, 1));
    assert_eq!(recovered[0], first[0].clone().expect("first committed"));
    assert!(recovered.iter().all(|result| result.completion.actual_work == 20));
    for input in &fixture.inputs {
        assert_eq!(checked(runtime.state_owner().snapshot(&input.scope)).revision, 1);
        assert!(checked(runtime.state_owner().pending_inference(&input.scope)).is_none());
    }
    fixture.store.close().await;
}

struct AdvancingWitness {
    inner: FileAnchorWitnessStore,
    clock: Arc<AtomicU64>,
    elapsed: u64,
}

impl AnchorWitnessStore for AdvancingWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> { self.inner.current() }
    fn compare_and_swap(&mut self, expected: Option<JournalAnchor>, next: JournalAnchor) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)?;
        self.clock.fetch_add(self.elapsed, Ordering::SeqCst);
        Ok(())
    }
}

fn journal(fixture: &BatchFixture, clock: Arc<AtomicU64>, elapsed: u64) -> CellOwnerJournalV1<AdvancingWitness> {
    let file = |name| checked(OpenOptions::new().read(true).write(true).create(true).truncate(false).open(fixture.directory.path().join(name)));
    let witness = checked(FileAnchorWitnessStore::open(
        file("cell-witness"), JournalScope { scope_digest: d("batch-owner"), objective_digest: d("journal-owner") },
        checked(Generation::new(1)), /*max_records*/ 64,
    ));
    let specs = fixture.inputs.iter().map(|input| CellJournalPartitionV1 {
        scope: input.scope.clone(), definition: fixture.bindings[0].cell.clone(),
        source_frontier: input.source_frontier, writer_epoch: 1,
    }).collect();
    checked(CellOwnerJournalV1::open(file("cell-journal"), AdvancingWitness { inner: witness, clock, elapsed }, specs, /*max_records*/ 64))
}

#[tokio::test]
async fn circuit_deadline_after_cell_fsync_prevents_batch_contact_and_reopens_pending() {
    let (fixture, items) = fixture([100, 100]).await;
    let clock = Arc::new(AtomicU64::new(20));
    let mut runtime = runtime(&fixture, journal(&fixture, Arc::clone(&clock), /*elapsed*/ 300), BatchModel::default());
    let results = checked(runtime.execute_batch(items, || CircuitCellTimeV1 {
        circuit_millis: clock.load(Ordering::SeqCst), cell_micros: 20,
    }));
    assert!(results.iter().all(Result::is_err));
    assert!(runtime.inference_control.batches.is_empty());
    assert!(clock.load(Ordering::SeqCst) >= 620);
    drop(runtime);
    let reopened = journal(&fixture, clock, /*elapsed*/ 0);
    for input in &fixture.inputs {
        assert!(checked(reopened.pending_inference(&input.scope)).is_some());
        assert_eq!(checked(reopened.snapshot(&input.scope)).revision, 0);
    }
    fixture.store.close().await;
}

#[tokio::test]
async fn filtered_expired_member_does_not_block_live_request_after_fsync() {
    let (fixture, items) = fixture([100, 200]).await;
    let clock = Arc::new(AtomicU64::new(90));
    let mut runtime = runtime(&fixture, journal(&fixture, Arc::clone(&clock), /*elapsed*/ 10), BatchModel::default());
    let results = checked(runtime.execute_batch(items, || CircuitCellTimeV1 {
        circuit_millis: 20, cell_micros: clock.load(Ordering::SeqCst),
    }));
    assert!(results[0].is_err());
    let live = results[1].as_ref().expect("the actual batch omits the expired request");
    assert_eq!((runtime.inference_control.batches.len(), runtime.inference_control.batches[0].len()), (1, 1));
    assert_eq!(live.decision.scope, fixture.inputs[1].scope);
    assert_eq!(live.completion.actual_work, 20);
    assert!(live.decision.cost.queue_age_micros >= 23);
    assert!(checked(runtime.state_owner().pending_inference(&fixture.inputs[0].scope)).is_some());
    assert!(checked(runtime.state_owner().pending_inference(&fixture.inputs[1].scope)).is_none());
    fixture.store.close().await;
}
