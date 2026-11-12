//! Journal mechanism tests use an explicit CURRENT double, not Root custody.
use super::*;
use crate::AnchorWitnessStore;
use crate::CellExecutionError;
use crate::CellJournalPartitionV1;
use crate::CellOwnerJournalV1;
use crate::CellStateOwnerV1;
use crate::JournalAnchor;
use crate::WitnessStoreError;
use crate::cell_test_support as cell;
use crate::commit_cell_step;
use pretty_assertions::assert_eq;

#[path = "cell_feature_current_readback_tests.rs"]
mod readback;

#[cfg(target_os = "linux")]
#[path = "cell_journal_observer_tests.rs"]
mod original_data;

fn profile() -> (Vec<CellJournalPartitionV1>, CellGenerationOwnerBindingV1) {
    let spec = CellJournalPartitionV1 {
        scope: cell::scope("feature"),
        definition: cell::definition(),
        source_frontier: cell::d("frontier"),
        writer_epoch: 1,
    };
    let mut original = config();
    original.initial.scope = CellGenerationScopeV2 {
        agent_id: spec.scope.agent_id.to_string(),
        cell_id: spec.scope.cell_id.to_string(),
        run_id: spec.scope.run_id.to_string(),
        principal_digest: spec.scope.principal_digest.into_array(),
    };
    original.source_frontier = spec.source_frontier.into_array();
    (
        vec![spec],
        CellGenerationOwnerBindingV1::new(&original, /*max_records*/ 128).unwrap(),
    )
}

#[test]
fn published_feature_journal_requires_same_current_on_reopen_and_every_read() {
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
    let receipt = commit_cell_step(&mut owner, proposal, /*now_micros*/ 13).unwrap();
    assert_eq!(
        owner.reset_at_frontier(
            &cell::scope("feature"),
            cell::d("replacement"),
            /*writer_epoch*/ 2
        ),
        Err(CellExecutionError::ScopeMismatch)
    );
    drop(owner);
    let bytes = files.bytes();
    assert!(
        CellOwnerJournalV1::open(
            files.file("journal"),
            files.witness(),
            specs.clone(),
            /*max_records*/ 16
        )
        .is_err()
    );
    assert_eq!(files.bytes(), bytes);
    let mut owner = CellOwnerJournalV1::open_guarded(
        files.file("journal"),
        files.witness(),
        specs.clone(),
        /*max_records*/ 16,
        binding.clone(),
        current.clone(),
    )
    .unwrap();
    assert_eq!(
        owner
            .lookup(
                &receipt.scope,
                &receipt.operation_id,
                receipt.semantic_request_digest
            )
            .unwrap(),
        Some(receipt.clone())
    );
    assert_eq!(owner.pending_inference(&receipt.scope).unwrap(), None);
    *current.0.lock().unwrap() = (None, None);
    assert_eq!(
        owner.lookup(
            &receipt.scope,
            &receipt.operation_id,
            receipt.semantic_request_digest
        ),
        Err(CellExecutionError::OwnerUnavailable)
    );
    assert_eq!(
        owner.snapshot(&receipt.scope),
        Err(CellExecutionError::OwnerUnavailable)
    );
    assert_eq!(
        owner.pending_inference(&receipt.scope),
        Err(CellExecutionError::OwnerUnavailable)
    );
    assert_eq!(owner.recover(), Err(CellExecutionError::OwnerUnavailable));
    drop(owner);
    assert!(
        CellOwnerJournalV1::open_guarded(
            files.file("journal"),
            files.witness(),
            specs,
            /*max_records*/ 16,
            binding,
            current
        )
        .is_err()
    );
    assert_eq!(files.bytes(), bytes);
}

struct RevokeAfterWitness {
    witness: FileAnchorWitnessStore,
    current: Arc<Current>,
    at: Arc<AtomicU64>,
}
impl crate::AnchorWitnessStore for RevokeAfterWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.witness.current()
    }
    fn compare_and_swap(
        &mut self,
        before: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.witness.compare_and_swap(before, next)?;
        if self.at.load(Ordering::SeqCst) == next.sequence {
            *self.current.0.lock().unwrap() = (None, None);
        }
        Ok(())
    }
}

#[test]
fn published_feature_commit_revoked_after_fsync_is_uncertain_and_recovers_exact_bytes() {
    let files = Files::new();
    let (specs, binding) = profile();
    let current = Arc::new(Current(Mutex::new((Some(binding.clone()), None))));
    let at = Arc::new(AtomicU64::new(u64::MAX));
    let witness = RevokeAfterWitness {
        witness: files.witness(),
        current: current.clone(),
        at: at.clone(),
    };
    let mut owner = CellOwnerJournalV1::open_guarded(
        files.file("journal"),
        witness,
        specs.clone(),
        /*max_records*/ 16,
        binding.clone(),
        current.clone(),
    )
    .unwrap();
    let proposal = cell::proposal(&mut owner, cell::input("feature"));
    let expected = proposal.receipt().clone();
    at.store(2, Ordering::SeqCst); // Compatibility infer: durable admission, then commit.
    assert_eq!(
        commit_cell_step(&mut owner, proposal, /*now_micros*/ 13),
        Err(CellExecutionError::CommitUncertain)
    );
    assert_eq!(
        owner.lookup(
            &expected.scope,
            &expected.operation_id,
            expected.semantic_request_digest
        ),
        Err(CellExecutionError::OwnerUnavailable)
    );
    assert_eq!(owner.recover(), Err(CellExecutionError::OwnerUnavailable));
    drop(owner);
    let bytes = files.bytes();
    *current.0.lock().unwrap() = (Some(binding.clone()), None);
    let owner = CellOwnerJournalV1::open_guarded(
        files.file("journal"),
        files.witness(),
        specs,
        /*max_records*/ 16,
        binding,
        current,
    )
    .unwrap();
    let recovered = owner
        .lookup(
            &expected.scope,
            &expected.operation_id,
            expected.semantic_request_digest,
        )
        .unwrap()
        .unwrap();
    assert_eq!(
        (
            recovered.operation_digest,
            recovered.checkpoint_after,
            recovered.model_output_digest
        ),
        (
            expected.operation_digest,
            expected.checkpoint_after,
            expected.model_output_digest
        )
    );
    assert_eq!(owner.pending_inference(&expected.scope).unwrap(), None);
    assert_eq!(files.bytes(), bytes);
}

#[test]
fn published_feature_revoked_admission_does_not_create_pending_work() {
    let files = Files::new();
    let (specs, binding) = profile();
    let current = Arc::new(Current(Mutex::new((Some(binding.clone()), None))));
    let mut owner = CellOwnerJournalV1::open_guarded(
        files.file("journal"),
        files.witness(),
        specs,
        /*max_records*/ 16,
        binding.clone(),
        current.clone(),
    )
    .unwrap();
    let prepared = crate::prepare_cell_step(
        &cell::definition(),
        &owner,
        &cell::Encoder,
        cell::input("feature"),
        /*now_micros*/ 10,
    )
    .unwrap();
    let admission =
        crate::cell_inference::admission_for_step(&prepared, /*now_micros*/ 11).unwrap();
    let before = files.bytes();
    *current.0.lock().unwrap() = (None, None);
    assert_eq!(
        owner.admit_inference(admission),
        Err(CellExecutionError::OwnerUnavailable)
    );
    assert_eq!(files.bytes(), before);
    *current.0.lock().unwrap() = (Some(binding), None);
    assert_eq!(
        owner.pending_inference(&cell::scope("feature")).unwrap(),
        None
    );
    assert_eq!(owner.snapshot(&cell::scope("feature")).unwrap().revision, 0);
}
