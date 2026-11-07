use std::fs::OpenOptions;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;

use pretty_assertions::assert_eq;

use super::*;

// The original inference owner survives independently of the Cell/Circuit
// process. This fixture retains only its controlled receipt and call counters.
#[derive(Clone)]
struct OriginalModelOwner(Arc<Mutex<Model>>);

impl NeuronInferenceControlPort for OriginalModelOwner {
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        checked(self.0.lock()).execute_feature(request)
    }
}

impl CellInferenceReadbackPortV1 for OriginalModelOwner {
    fn read_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        checked(self.0.lock()).read_feature(request)
    }
}

fn reopen_cell_owner(
    path: &Path,
    backend: &RegisteredCellBackendV1,
) -> CellOwnerJournalV1<FileAnchorWitnessStore> {
    let file = |name: &str| checked(OpenOptions::new().read(true).write(true).create(true)
        .truncate(false).open(path.join(name)));
    let witness = checked(FileAnchorWitnessStore::open(
        file("cell-witness"),
        JournalScope { scope_digest: d("represented-cell-journal"), objective_digest: d("original-owner") },
        checked(Generation::new(1)), 64,
    ));
    checked(CellOwnerJournalV1::open(file("cell-journal"), witness, vec![CellJournalPartitionV1 {
        scope: scope("run-1"), definition: backend.registration().definition.clone(),
        source_frontier: d("frontier"), writer_epoch: 1,
    }], 64))
}

#[tokio::test]
async fn represented_circuit_reopens_original_pending_then_committed_after_endpoint_change() {
    let (backend, projected, current, negotiation, source, selection) = projected_materials();
    let (definition, bindings) = configuration();
    let (directory, store, dispatch, request) = projected_run(&definition, &projected).await;
    let layout = checked(HeptaFleetRoot::parse(directory.path().join("fleet")))
        .layout().agent(&fence().owner_agent_id);
    let admission = claim(&store, &dispatch, &bindings[0].cell, &request, 13).await;
    let model = Model::new(20, true);
    let calls = model.calls.clone();
    let reads = model.reads.clone();
    let worker = OriginalModelOwner(Arc::new(Mutex::new(model)));
    let resolver = CurrentOwners { current: current.clone(), calls: Cell::new(0), stale_on: usize::MAX };
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition.clone(), bindings.clone())),
        reopen_cell_owner(directory.path(), &backend), worker.clone(), Encoder,
    );
    assert!(matches!(runtime.execute_representation(admission, request.clone(),
        CircuitCellRepresentationUseV1 { backend: &backend, input: &projected, resolver: &resolver }, time),
        Err(CircuitCellErrorV1::Cell(CellExecutionError::Backend(NeuronModelError::Indeterminate)))));
    let pending = checked(runtime.state_owner().pending_inference(&request.scope));
    assert!(pending.is_some());
    assert_eq!((calls.load(Ordering::SeqCst), resolver.calls.get()), (1, 3));
    drop(runtime);
    drop(projected);
    store.close().await;
    drop(store);

    let mut changed = current;
    changed.producer.generation = checked(Generation::new(3));
    assert!(matches!(CellNativeRepresentationInputV1::project(
        &backend, &negotiation, &source, &changed, &selection,
    ), Err(CellRepresentationErrorV1::StaleProducer)));
    let historical = CurrentOwners { current: changed, calls: Cell::new(0), stale_on: 1 };
    let state = reopen_cell_owner(directory.path(), &backend);
    assert_eq!(checked(state.pending_inference(&request.scope)), pending);
    let restored = checked(CellNativeRepresentationInputV1::restore_admitted(
        &backend, &state, &negotiation, &source, &selection, &request,
    ));
    let store = checked(AutomationStore::open(&layout).await);
    let recovery = checked(store.recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 21).await);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition.clone(), bindings.clone())), state, worker.clone(), Encoder,
    );
    let first = checked(runtime.execute_representation(recovery, request.clone(),
        CircuitCellRepresentationUseV1 { backend: &backend, input: &restored, resolver: &historical },
        || CircuitCellTimeV1 { circuit_millis: 22, cell_micros: 22 }));
    assert_eq!((calls.load(Ordering::SeqCst), reads.load(Ordering::SeqCst), historical.calls.get()), (1, 1, 0));
    assert_eq!(checked(runtime.state_owner().pending_inference(&request.scope)), None);
    drop(runtime);
    drop(restored);
    store.close().await;
    drop(store);

    // Lose the Cell -> Circuit completion acknowledgement as well. Reopening
    // the committed Cell owner must return the exact decision, with no new use.
    let state = reopen_cell_owner(directory.path(), &backend);
    let restored = checked(CellNativeRepresentationInputV1::restore_admitted(
        &backend, &state, &negotiation, &source, &selection, &request,
    ));
    let store = checked(AutomationStore::open(&layout).await);
    let recovery = checked(store.recover_circuit_computation("run-1", dispatch.activation_id, &fence(), 23).await);
    let mut runtime = AgentdCircuitCellOwnerV1::new(
        checked(CircuitCellRegistryV1::new(definition, bindings)), state, worker, Encoder,
    );
    let replayed = checked(runtime.execute_representation(recovery, request,
        CircuitCellRepresentationUseV1 { backend: &backend, input: &restored, resolver: &historical },
        || CircuitCellTimeV1 { circuit_millis: 24, cell_micros: 24 }));
    assert_eq!(replayed, first);
    assert_eq!((calls.load(Ordering::SeqCst), reads.load(Ordering::SeqCst), historical.calls.get()), (1, 1, 0));
    let completed = apply(&store, "complete-after-reopen", 25,
        CircuitEventV2::Complete { completion: replayed.completion }).await;
    assert_eq!((completed.run.budget().spent(), completed.run.budget().reserved()), (20, 0));
    drop(runtime);
    store.close().await;
}
