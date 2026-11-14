//! Physical data mechanism tests. The existing CURRENT double authors the
//! real journal; it supplies neither Root custody nor historical admission.

use super::*;
use crate::CellDecisionReceiptV1;
use crate::CellOriginalJournalFilesV1;
use crate::CellOriginalJournalObservationV1;
use crate::CellOwnerJournalReadbackV1;
use crate::CellOwnerSnapshotV1;
use crate::observe_original_guarded_cell_v1;
use pretty_assertions::assert_eq;
use std::io::Write;

struct Original {
    files: Files,
    partition: CellJournalPartitionV1,
    binding: CellGenerationOwnerBindingV1,
    current: Arc<Current>,
    expected: CellOriginalJournalObservationV1,
}

impl Original {
    fn new() -> Self {
        let files = Files::new();
        let (specs, binding) = profile();
        let current = Arc::new(Current(Mutex::new((Some(binding.clone()), None))));
        let mut owner = CellOwnerJournalV1::open_guarded(
            files.file("journal"),
            files.witness(),
            specs.clone(),
            /*max_records*/ 16,
            binding.clone(),
            current.clone(),
        )
        .unwrap();
        let proposal = cell::proposal(&mut owner, cell::input("feature"));
        let decision: CellDecisionReceiptV1 =
            commit_cell_step(&mut owner, proposal, /*now_micros*/ 13).unwrap();
        let snapshot: CellOwnerSnapshotV1 = owner.snapshot(&decision.scope).unwrap();
        drop(owner);
        let anchor = files.witness().current().unwrap().unwrap();
        Self {
            files,
            partition: specs[0].clone(),
            binding,
            current,
            expected: CellOriginalJournalObservationV1 {
                anchor,
                snapshot,
                decision,
            },
        }
    }

    fn inputs(&self) -> CellOriginalJournalFilesV1 {
        CellOriginalJournalFilesV1 {
            journal: File::open(self.files.0.join("journal")).unwrap(),
            witness: File::open(self.files.0.join("witness")).unwrap(),
            witness_scope: JournalScope {
                scope_digest: Digest32::of_bytes(b"guarded-scope"),
                objective_digest: Digest32::of_bytes(b"guarded-task"),
            },
            witness_generation: Generation::new(1).unwrap(),
            witness_records: 128,
        }
    }

    fn read(&self) -> Result<CellOriginalJournalObservationV1, CellExecutionError> {
        observe_original_guarded_cell_v1(
            self.inputs(),
            self.partition.clone(),
            /*max_records*/ 16,
            &self.binding,
            &self.expected.decision.operation_id,
            self.expected.decision.semantic_request_digest,
        )
    }

    fn bytes(&self) -> (Vec<u8>, Vec<u8>) {
        (
            self.files.bytes(),
            fs::read(self.files.0.join("witness")).unwrap(),
        )
    }
}

#[test]
fn original_cell_data_reads_full_physical_cut_after_current_is_unavailable() {
    let original = Original::new();
    let before = original.bytes();
    *original.current.0.lock().unwrap() = (None, None);
    assert_eq!(original.read().unwrap(), original.expected);
    assert!(
        CellOwnerJournalReadbackV1::open_guarded(
            original.files.file("journal"),
            original.files.witness(),
            vec![original.partition.clone()],
            /*max_records*/ 16,
            original.binding.clone(),
            original.current.clone(),
        )
        .is_err()
    );
    assert_eq!(original.bytes(), before);
}

#[test]
fn original_cell_data_requires_actual_release_of_both_writer_locks() {
    let original = Original::new();
    let owner = CellOwnerJournalV1::open_guarded(
        original.files.file("journal"),
        original.files.witness(),
        vec![original.partition.clone()],
        /*max_records*/ 16,
        original.binding.clone(),
        original.current.clone(),
    )
    .unwrap();
    assert!(original.read().is_err());
    drop(owner);
    let journal = original.files.file("journal");
    journal.try_lock().unwrap();
    assert!(original.read().is_err());
    drop(journal);
    let witness = original.files.witness();
    assert!(original.read().is_err());
    drop(witness);
    assert_eq!(original.read().unwrap(), original.expected);
}

#[test]
fn original_cell_data_detects_corruption_without_repair_or_a_fake_sticky_claim() {
    let original = Original::new();
    for name in ["journal", "witness"] {
        let path = original.files.0.join(name);
        let intact = fs::read(&path).unwrap();
        let mut corrupt = intact.clone();
        *corrupt.last_mut().unwrap() ^= 1;
        fs::write(&path, &corrupt).unwrap();
        assert!(original.read().is_err());
        assert_eq!(fs::read(&path).unwrap(), corrupt);
        fs::write(&path, intact).unwrap();
        // A separate Root durable refusal must reject reuse. This stateless
        // decoder intentionally proves no persistent decision by itself.
        assert_eq!(original.read().unwrap(), original.expected);
    }
}

#[test]
fn original_cell_data_rejects_torn_tail_and_lagging_witness_without_writes() {
    let original = Original::new();
    let before = original.bytes();
    OpenOptions::new()
        .append(true)
        .open(original.files.0.join("journal"))
        .unwrap()
        .write_all(&[0, 0])
        .unwrap();
    let torn = original.bytes();
    assert!(original.read().is_err());
    assert_eq!(original.bytes(), torn);
    fs::write(original.files.0.join("journal"), &before.0).unwrap();
    let lagging = &before.1[..before.1.len() - 112];
    fs::write(original.files.0.join("witness"), lagging).unwrap();
    assert!(original.read().is_err());
    assert_eq!(original.bytes(), (before.0, lagging.to_vec()));
}

#[test]
fn original_cell_data_rejects_scope_request_and_record_limit_substitution() {
    let original = Original::new();
    let before = original.bytes();
    let mut partition = original.partition.clone();
    partition.writer_epoch += 1;
    assert!(
        observe_original_guarded_cell_v1(
            original.inputs(),
            partition,
            /*max_records*/ 16,
            &original.binding,
            &original.expected.decision.operation_id,
            original.expected.decision.semantic_request_digest,
        )
        .is_err()
    );
    assert!(
        observe_original_guarded_cell_v1(
            original.inputs(),
            original.partition.clone(),
            /*max_records*/ 16,
            &original.binding,
            &original.expected.decision.operation_id,
            cell::d("changed-request"),
        )
        .is_err()
    );
    assert!(
        observe_original_guarded_cell_v1(
            original.inputs(),
            original.partition.clone(),
            /*max_records*/ 15,
            &original.binding,
            &original.expected.decision.operation_id,
            original.expected.decision.semantic_request_digest,
        )
        .is_err()
    );
    let mut inputs = original.inputs();
    inputs.witness_scope.objective_digest = cell::d("changed-witness");
    assert!(
        observe_original_guarded_cell_v1(
            inputs,
            original.partition.clone(),
            /*max_records*/ 16,
            &original.binding,
            &original.expected.decision.operation_id,
            original.expected.decision.semantic_request_digest,
        )
        .is_err()
    );
    assert_eq!(original.bytes(), before);
}

#[test]
fn original_cell_data_rejects_aliased_or_unlinked_descriptors() {
    let original = Original::new();
    let mut inputs = original.inputs();
    inputs.witness = File::open(original.files.0.join("journal")).unwrap();
    assert!(
        observe_original_guarded_cell_v1(
            inputs,
            original.partition.clone(),
            /*max_records*/ 16,
            &original.binding,
            &original.expected.decision.operation_id,
            original.expected.decision.semantic_request_digest,
        )
        .is_err()
    );
    let inputs = original.inputs();
    fs::remove_file(original.files.0.join("journal")).unwrap();
    assert!(
        observe_original_guarded_cell_v1(
            inputs,
            original.partition.clone(),
            /*max_records*/ 16,
            &original.binding,
            &original.expected.decision.operation_id,
            original.expected.decision.semantic_request_digest,
        )
        .is_err()
    );
}

#[test]
fn original_cell_data_rejects_empty_original_files_without_initialization() {
    let original = Original::new();
    fs::write(original.files.0.join("journal"), []).unwrap();
    assert!(original.read().is_err());
    assert!(original.files.bytes().is_empty());
    fs::write(original.files.0.join("witness"), []).unwrap();
    assert!(original.read().is_err());
    assert_eq!(original.bytes(), (Vec::new(), Vec::new()));
}
