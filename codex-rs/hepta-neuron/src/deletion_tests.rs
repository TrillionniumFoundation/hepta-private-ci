use super::*;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn plan() -> NeuronDeletionRebuildPlanV1 {
    NeuronDeletionRebuildPlanV1 {
        rebuild_id: checked(StableId::new("neuron-rebuild:1")),
        predecessor_generation: checked(Generation::new(7)),
        successor_generation: checked(Generation::new(8)),
        predecessor_checkpoint_digest: Digest32::of_bytes(b"checkpoint"),
        withdrawal_registry_head_digest: Digest32::of_bytes(b"withdrawal-head"),
        withdrawal_event_digest: Digest32::of_bytes(b"withdrawal-event"),
        retained_dataset_set_digest: Digest32::of_bytes(b"retained-datasets"),
        source_event_set_digest: Digest32::of_bytes(b"retained-events"),
        retained_event_count: 12,
        deleted_event_count: 3,
    }
}

#[test]
fn deletion_rebuild_is_fresh_generation_and_never_reuses_state() {
    let value = checked(validate_deletion_rebuild(&plan()));
    assert_eq!(value.predecessor_generation.get(), 7);
    assert_eq!(value.successor_generation.get(), 8);
    assert!(!value.state_reused);
    assert!(!value.receipt_digest.is_zero());
    assert!(!value.authority.grants_any());
}

#[test]
fn deletion_rebuild_rejects_skipped_generation_and_missing_deletion() {
    let mut value = plan();
    value.successor_generation = checked(Generation::new(9));
    assert_eq!(
        validate_deletion_rebuild(&value),
        Err(DeletionRebuildError::GenerationNotExactSuccessor)
    );
    let mut value = plan();
    value.deleted_event_count = 0;
    assert_eq!(
        validate_deletion_rebuild(&value),
        Err(DeletionRebuildError::NoDeletedEvents)
    );
}
