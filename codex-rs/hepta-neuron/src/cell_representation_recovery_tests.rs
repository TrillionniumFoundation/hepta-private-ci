use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use pretty_assertions::assert_eq;

use super::*;

static NEXT: AtomicU64 = AtomicU64::new(0);

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-representation-recovery-{}-{serial}",
            std::process::id(),
        ));
        checked(std::fs::create_dir(&root));
        Self(root)
    }

    fn file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create(true)
                .truncate(false)
                .open(self.0.join(name)),
        )
    }

    fn open(
        &self,
        backend: &RegisteredCellBackendV1,
    ) -> CellOwnerJournalV1<FileAnchorWitnessStore> {
        let witness = checked(FileAnchorWitnessStore::open(
            self.file("witness"),
            JournalScope {
                scope_digest: d("representation-journal"),
                objective_digest: d("journal-owner"),
            },
            checked(Generation::new(/*value*/ 1)),
            /*max_records*/ 64,
        ));
        checked(CellOwnerJournalV1::open(
            self.file("journal"),
            witness,
            vec![CellJournalPartitionV1 {
                scope: scope("run1"),
                definition: backend.registration().definition.clone(),
                source_frontier: d("frontier"),
                writer_epoch: 1,
            }],
            /*max_records*/ 64,
        ))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = std::fs::remove_dir_all(&self.0);
    }
}

#[test]
fn cold_restore_binds_original_pending_and_committed_identity_after_endpoint_change() {
    let fixture = Fixture::new();
    let backend = native_backend(/*width*/ 2);
    let source = f32_source(&[1.0, 0.5, 0.0]);
    let selection = checked(CellGlobalQ24SelectionV1::new(vec![0, 1]));
    let negotiation = negotiated(&backend, &source, &selection);
    let mut current = current(&negotiation.producer, &negotiation.consumer);
    let projected = checked(CellNativeRepresentationInputV1::project(
        &backend,
        &negotiation,
        &source,
        &current,
        &selection,
    ));
    let input = request(&projected);
    let projection_receipt = projected.projection_receipt().clone();
    let mut owner = fixture.open(&backend);
    assert_eq!(
        CellNativeRepresentationInputV1::restore_admitted(
            &backend,
            &owner,
            &negotiation,
            &source,
            &selection,
            &input
        ),
        Err(CellExecutionError::InferenceNotAdmitted)
    );
    let prepared = ready(checked(backend.enter_representation(
        &owner,
        &projected,
        &current,
        input.clone(),
        /*now_micros*/ 10,
    )));
    let mut control = RecordedControl::new();
    control.failure = Some(NeuronModelError::Indeterminate);
    assert!(matches!(
        backend.infer_representation(
            &mut owner,
            &projected,
            prepared,
            &CurrentRepresentationOwners(&current),
            &mut control,
            || 11
        ),
        Err(CellExecutionError::Backend(NeuronModelError::Indeterminate))
    ));
    let pending = checked(owner.pending_inference(&input.scope));
    drop(projected);
    drop(owner);

    // Reopen actual journal/witness files with no retained projection or owner.
    let mut owner = fixture.open(&backend);
    assert_eq!(checked(owner.pending_inference(&input.scope)), pending);
    current.producer.generation = checked(Generation::new(/*value*/ 3));
    assert_eq!(
        CellNativeRepresentationInputV1::project(
            &backend,
            &negotiation,
            &source,
            &current,
            &selection
        ),
        Err(E::StaleProducer)
    );
    let restored = checked(CellNativeRepresentationInputV1::restore_admitted(
        &backend,
        &owner,
        &negotiation,
        &source,
        &selection,
        &input,
    ));
    assert_eq!(restored.projection_receipt(), &projection_receipt);
    assert_eq!(
        restored.validate_current_use(&backend, &current),
        Err(CellExecutionError::StaleSource)
    );
    assert!(matches!(
        backend.enter_representation(
            &owner,
            &restored,
            &current,
            input.clone(),
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::StaleSource)
    ));
    let changed_source = f32_source(&[1.0, 0.5, 0.25]);
    assert_eq!(
        CellNativeRepresentationInputV1::restore_admitted(
            &backend,
            &owner,
            &negotiation,
            &changed_source,
            &selection,
            &input
        ),
        Err(CellExecutionError::EncodingMismatch)
    );
    let mut replacement = input.clone();
    replacement.operation_id = id("replacement-operation");
    assert_eq!(
        CellNativeRepresentationInputV1::restore_admitted(
            &backend,
            &owner,
            &negotiation,
            &source,
            &selection,
            &replacement
        ),
        Err(CellExecutionError::OperationConflict)
    );
    assert_eq!(checked(owner.pending_inference(&input.scope)), pending);

    let observed = control.receipt.take();
    assert!(matches!(
        backend.recover_representation(
            &owner,
            &restored,
            input.clone(),
            &mut control,
            /*now_micros*/ 12
        ),
        Err(CellExecutionError::InferencePending)
    ));
    assert_eq!(checked(owner.pending_inference(&input.scope)), pending);
    control.receipt = observed;
    let inferred = checked(backend.recover_representation(
        &owner,
        &restored,
        input.clone(),
        &mut control,
        /*now_micros*/ 101,
    ));
    let receipt = checked(commit_cell_step(
        &mut owner,
        checked(decide_cell(inferred, /*now_micros*/ 102)),
        /*now_micros*/ 103,
    ));
    assert!(receipt.deadline_exceeded);
    assert_eq!(receipt.selected_candidate, id("abstain"));
    drop(restored);
    drop(owner);

    let owner = fixture.open(&backend);
    let restored = checked(CellNativeRepresentationInputV1::restore_admitted(
        &backend,
        &owner,
        &negotiation,
        &source,
        &selection,
        &input,
    ));
    assert_eq!(restored.projection_receipt(), &projection_receipt);
    assert_eq!(
        checked(owner.lookup(
            &input.scope,
            &input.operation_id,
            receipt.semantic_request_digest
        )),
        Some(receipt)
    );
    assert_eq!(
        restored.validate_current_use(&backend, &current),
        Err(CellExecutionError::StaleSource)
    );
    assert_eq!((control.executions, control.reads), (1, 2));
}
