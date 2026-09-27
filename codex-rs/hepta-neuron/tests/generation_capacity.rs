//! Public-API regressions for durable completion capacity, not model efficacy.
use std::error::Error;
use std::fs;

use codex_hepta_neuron::FileNeuronGenerationStoreV2;
use codex_hepta_neuron::GenerationStoreError;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronCommitDispositionV1;
use codex_hepta_neuron::NeuronGenerationCommitResultV2;
use codex_hepta_neuron::NeuronGenerationCommitV2;
use codex_hepta_neuron::NeuronGenerationStoreContextV2;
use codex_hepta_neuron::NeuronOperationKeyV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: digest(&format!("capacity-checkpoint-{sequence}")),
    }
}

fn context() -> Result<NeuronGenerationStoreContextV2, Box<dyn Error>> {
    Ok(NeuronGenerationStoreContextV2 {
        generation: Generation::new(4)?,
        scope: JournalScope {
            scope_digest: digest("capacity-scope"),
            objective_digest: digest("capacity-objective"),
        },
        runtime_config_digest: digest("capacity-config"),
        body_bundle_digest: digest("capacity-body"),
        max_records: 16,
        max_pending_witness: 16,
        max_checkpoint_bytes: 4096,
        max_full_receipt_bytes: 4096,
        max_file_bytes: 1024 * 1024,
        max_startup_replay_bytes: 1024 * 1024,
    })
}

fn operation(sequence: u64) -> Result<NeuronGenerationCommitV2, Box<dyn Error>> {
    Ok(NeuronGenerationCommitV2 {
        key: NeuronOperationKeyV2 {
            tick_id: StableId::new(format!("capacity-tick-{sequence}"))?,
            input_semantic_digest: digest(&format!("capacity-input-{sequence}")),
        },
        config_semantic_digest: digest("capacity-config"),
        body_bundle_digest: digest("capacity-body"),
        model_semantic_digest: digest("capacity-model"),
        model_observation_digest: digest("capacity-observation"),
        expected_anchor: (sequence > 1).then(|| anchor(sequence - 1)),
        next_anchor: anchor(sequence),
        checkpoint_bytes: vec![17; 128],
        full_receipt_bytes: vec![29; 256],
        disposition: NeuronCommitDispositionV1::CommittedReady,
    })
}

// Measure actual canonical frames rather than hard-coding a second wire codec.
fn frame_sizes() -> Result<(u64, u64, u64, u64, u64), Box<dyn Error>> {
    let root = tempfile::tempdir()?;
    let path = root.path().join("probe");
    let mut store = FileNeuronGenerationStoreV2::create(&path, context()?)?;
    let header = fs::metadata(&path)?.len();
    let first = operation(1)?;
    store.commit_result(first.clone())?;
    let first_end = fs::metadata(&path)?.len();
    store.acknowledge_witness(&first.key, first.next_anchor)?;
    let ack_end = fs::metadata(&path)?.len();
    let second = operation(2)?;
    store.commit_result(second.clone())?;
    let second_end = fs::metadata(&path)?.len();
    store.acknowledge_witness(&second.key, second.next_anchor)?;
    let end = fs::metadata(&path)?.len();
    Ok((header, first_end - header, ack_end - first_end, second_end - ack_end, end - second_end))
}

#[test]
fn commit_cannot_consume_its_acknowledgement_capacity() -> Result<(), Box<dyn Error>> {
    let (header, commit_bytes, _, _, _) = frame_sizes()?;
    let root = tempfile::tempdir()?;
    let path = root.path().join("generation");
    let mut limits = context()?;
    limits.max_file_bytes = header + commit_bytes;
    let mut store = FileNeuronGenerationStoreV2::create(&path, limits)?;
    assert_eq!(store.commit_result(operation(1)?), Err(GenerationStoreError::Capacity));
    assert_eq!(store.current_anchor()?, None);
    assert_eq!(store.pending_witness_count()?, 0);
    assert_eq!(fs::metadata(path)?.len(), header);
    Ok(())
}

#[test]
fn replay_budget_is_also_a_new_work_admission_budget() -> Result<(), Box<dyn Error>> {
    let (header, _, _, _, _) = frame_sizes()?;
    let root = tempfile::tempdir()?;
    let path = root.path().join("generation");
    let mut limits = context()?;
    limits.max_startup_replay_bytes = header;
    let mut store = FileNeuronGenerationStoreV2::create(&path, limits.clone())?;
    let first = operation(1)?;
    assert_eq!(store.admit_operation(&first.key, None, 128, 256), Err(GenerationStoreError::Capacity));
    assert_eq!(store.commit_result(first), Err(GenerationStoreError::Capacity));
    drop(store);
    let reopened = FileNeuronGenerationStoreV2::open_existing(&path, limits)?;
    assert_eq!(reopened.current_anchor()?, None);
    Ok(())
}

#[test]
fn pending_acknowledgements_remain_reserved_after_reopen() -> Result<(), Box<dyn Error>> {
    let (header, first_bytes, first_ack, second_bytes, second_ack) = frame_sizes()?;
    let root = tempfile::tempdir()?;
    let path = root.path().join("generation");
    let mut limits = context()?;
    limits.max_file_bytes = header + first_bytes + first_ack + second_bytes + second_ack - 1;
    let first = operation(1)?;
    let mut store = FileNeuronGenerationStoreV2::create(&path, limits.clone())?;
    store.commit_result(first.clone())?;
    drop(store);
    let mut reopened = FileNeuronGenerationStoreV2::open_existing(&path, limits)?;
    let before = fs::read(&path)?;
    assert_eq!(reopened.commit_result(operation(2)?), Err(GenerationStoreError::Capacity));
    assert_eq!(fs::read(&path)?, before);
    assert_eq!(reopened.pending_witness_count()?, 1);
    reopened.acknowledge_witness(&first.key, first.next_anchor)?;
    assert_eq!(reopened.pending_witness_count()?, 0);
    Ok(())
}

#[test]
fn exact_capacity_finishes_and_preserves_full_result_and_conflict() -> Result<(), Box<dyn Error>> {
    let (header, commit_bytes, ack_bytes, _, _) = frame_sizes()?;
    let root = tempfile::tempdir()?;
    let path = root.path().join("generation");
    let mut limits = context()?;
    limits.max_file_bytes = header + commit_bytes + ack_bytes;
    limits.max_startup_replay_bytes = limits.max_file_bytes;
    let first = operation(1)?;
    let mut store = FileNeuronGenerationStoreV2::create(&path, limits.clone())?;
    let mut expected = match store.commit_result(first.clone())? {
        NeuronGenerationCommitResultV2::Committed(record) => record,
        NeuronGenerationCommitResultV2::Duplicate(_) => panic!("fresh operation was duplicate"),
    };
    drop(store);
    let mut reopened = FileNeuronGenerationStoreV2::open_existing(&path, limits.clone())?;
    reopened.acknowledge_witness(&first.key, first.next_anchor)?;
    expected.witness_acknowledged = true;
    assert_eq!(reopened.find_operation(&first.key)?, Some(expected.clone()));
    assert_eq!(reopened.commit_result(first.clone())?, NeuronGenerationCommitResultV2::Duplicate(expected.clone()));
    let mut changed = first;
    changed.key.input_semantic_digest = digest("changed-input");
    assert_eq!(reopened.commit_result(changed), Err(GenerationStoreError::Conflict));
    drop(reopened);
    let reopened = FileNeuronGenerationStoreV2::open_existing(&path, limits.clone())?;
    assert_eq!(reopened.find_operation(&expected.key)?, Some(expected));
    assert_eq!(fs::metadata(path)?.len(), limits.max_file_bytes);
    Ok(())
}
