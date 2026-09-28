//! Public-API regressions for durable completion capacity, not model efficacy.
use std::error::Error;
use std::fs;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_neuron::FileNeuronGenerationStoreV2;
use codex_hepta_neuron::FileNeuronRuntimeIndexV2;
use codex_hepta_neuron::GenerationStoreError;
use codex_hepta_neuron::JournalAnchor;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronCommitDispositionV1;
use codex_hepta_neuron::NeuronGenerationCommitResultV2;
use codex_hepta_neuron::NeuronGenerationCommitV2;
use codex_hepta_neuron::NeuronGenerationStoreContextV2;
use codex_hepta_neuron::NeuronOperationKeyV2;
use codex_hepta_neuron::NeuronRuntimeIndexAdmissionV2;
use codex_hepta_neuron::NeuronRuntimeIndexContextV2;
use codex_hepta_neuron::NeuronRuntimeIndexError;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(1);
struct Fixture(PathBuf);

impl Fixture {
    fn new() -> io::Result<Self> {
        for _ in 0..128 {
            let serial = NEXT.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "hepta-capacity-integration-{}-{serial}",
                std::process::id()
            ));
            match fs::create_dir(&path) {
                Ok(()) => return Ok(Self(path)),
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error),
            }
        }
        Err(io::Error::other("fixture namespace exhausted"))
    }

    fn path(&self) -> &Path {
        &self.0
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

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

#[derive(Clone, Copy)]
struct GenerationFrameSizes {
    header: u64,
    first_commit: u64,
    first_ack: u64,
    second_commit: u64,
    second_ack: u64,
}

// Measure actual canonical frames rather than hard-coding a second wire codec.
fn frame_sizes() -> Result<GenerationFrameSizes, Box<dyn Error>> {
    let root = Fixture::new()?;
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
    Ok(GenerationFrameSizes {
        header,
        first_commit: first_end - header,
        first_ack: ack_end - first_end,
        second_commit: second_end - ack_end,
        second_ack: end - second_end,
    })
}

#[test]
fn commit_cannot_consume_its_acknowledgement_capacity() -> Result<(), Box<dyn Error>> {
    let sizes = frame_sizes()?;
    let root = Fixture::new()?;
    let path = root.path().join("generation");
    let mut limits = context()?;
    limits.max_file_bytes = sizes.header + sizes.first_commit;
    let mut store = FileNeuronGenerationStoreV2::create(&path, limits)?;
    assert_eq!(
        store.commit_result(operation(1)?),
        Err(GenerationStoreError::Capacity)
    );
    assert_eq!(store.current_anchor()?, None);
    assert_eq!(store.pending_witness_count()?, 0);
    assert_eq!(fs::metadata(path)?.len(), sizes.header);
    Ok(())
}

#[test]
fn replay_budget_is_also_a_new_work_admission_budget() -> Result<(), Box<dyn Error>> {
    let sizes = frame_sizes()?;
    let root = Fixture::new()?;
    let path = root.path().join("generation");
    let mut limits = context()?;
    limits.max_startup_replay_bytes = sizes.header;
    let mut store = FileNeuronGenerationStoreV2::create(&path, limits.clone())?;
    let first = operation(1)?;
    assert_eq!(
        store.admit_operation(&first.key, /*expected_anchor*/ None, 128, 256),
        Err(GenerationStoreError::Capacity)
    );
    assert_eq!(
        store.commit_result(first),
        Err(GenerationStoreError::Capacity)
    );
    drop(store);
    let reopened = FileNeuronGenerationStoreV2::open_existing(&path, limits)?;
    assert_eq!(reopened.current_anchor()?, None);
    Ok(())
}

#[test]
fn pending_acknowledgements_remain_reserved_after_reopen() -> Result<(), Box<dyn Error>> {
    let sizes = frame_sizes()?;
    let root = Fixture::new()?;
    let path = root.path().join("generation");
    let mut limits = context()?;
    limits.max_file_bytes = sizes.header
        + sizes.first_commit
        + sizes.first_ack
        + sizes.second_commit
        + sizes.second_ack
        - 1;
    let first = operation(1)?;
    let mut store = FileNeuronGenerationStoreV2::create(&path, limits.clone())?;
    store.commit_result(first.clone())?;
    drop(store);
    let mut reopened = FileNeuronGenerationStoreV2::open_existing(&path, limits)?;
    let before = fs::read(&path)?;
    assert_eq!(
        reopened.commit_result(operation(2)?),
        Err(GenerationStoreError::Capacity)
    );
    assert_eq!(fs::read(&path)?, before);
    assert_eq!(reopened.pending_witness_count()?, 1);
    reopened.acknowledge_witness(&first.key, first.next_anchor)?;
    assert_eq!(reopened.pending_witness_count()?, 0);
    Ok(())
}

#[test]
fn exact_capacity_finishes_and_preserves_full_result_and_conflict() -> Result<(), Box<dyn Error>> {
    let sizes = frame_sizes()?;
    let root = Fixture::new()?;
    let path = root.path().join("generation");
    let mut limits = context()?;
    limits.max_file_bytes = sizes.header + sizes.first_commit + sizes.first_ack;
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
    assert_eq!(
        reopened.commit_result(first.clone())?,
        NeuronGenerationCommitResultV2::Duplicate(expected.clone())
    );
    let mut changed = first;
    changed.key.input_semantic_digest = digest("changed-input");
    assert_eq!(
        reopened.commit_result(changed),
        Err(GenerationStoreError::Conflict)
    );
    drop(reopened);
    let reopened = FileNeuronGenerationStoreV2::open_existing(&path, limits.clone())?;
    assert_eq!(reopened.find_operation(&expected.key)?, Some(expected));
    assert_eq!(fs::metadata(path)?.len(), limits.max_file_bytes);
    Ok(())
}

fn index_context() -> Result<NeuronRuntimeIndexContextV2, Box<dyn Error>> {
    let limits = context()?;
    Ok(NeuronRuntimeIndexContextV2 {
        generation: limits.generation,
        scope: limits.scope,
        runtime_config_digest: limits.runtime_config_digest,
        body_bundle_digest: limits.body_bundle_digest,
        max_records: limits.max_records,
        max_file_bytes: limits.max_file_bytes,
        max_startup_replay_bytes: limits.max_startup_replay_bytes,
    })
}

fn index_frame_sizes() -> Result<(u64, u64, u64, u64), Box<dyn Error>> {
    let root = Fixture::new()?;
    let path = root.path().join("index-probe");
    let mut index = FileNeuronRuntimeIndexV2::create(&path, index_context()?)?;
    let header = fs::metadata(&path)?.len();
    let first = operation(1)?;
    index.prepare(first.key.clone(), /*expected_anchor*/ None)?;
    let prepared_end = fs::metadata(&path)?.len();
    let remaining_reserved = index.capacity_snapshot()?.reserved_bytes;
    index.complete(&first.key, first.next_anchor, digest("committed-operation"))?;
    Ok((
        header,
        prepared_end - header,
        remaining_reserved,
        fs::metadata(path)?.len() - prepared_end,
    ))
}

#[test]
fn index_rejects_preparation_without_completion_room() -> Result<(), Box<dyn Error>> {
    let (header, prepared, remaining_reserved, _) = index_frame_sizes()?;
    let root = Fixture::new()?;
    let path = root.path().join("index");
    let mut limits = index_context()?;
    limits.max_file_bytes = header + prepared + remaining_reserved - 1;
    let mut index = FileNeuronRuntimeIndexV2::create(&path, limits)?;
    let first = operation(1)?;
    assert_eq!(
        index.admit(&first.key, /*expected_anchor*/ None),
        Err(NeuronRuntimeIndexError::Capacity)
    );
    assert_eq!(
        index.prepare(first.key, /*expected_anchor*/ None),
        Err(NeuronRuntimeIndexError::Capacity)
    );
    assert_eq!(index.pending()?, None);
    assert_eq!(fs::metadata(path)?.len(), header);
    Ok(())
}

#[test]
fn index_exact_capacity_completes_after_restart() -> Result<(), Box<dyn Error>> {
    let (header, prepared, remaining_reserved, completed) = index_frame_sizes()?;
    let root = Fixture::new()?;
    let path = root.path().join("index");
    let mut limits = index_context()?;
    limits.max_file_bytes = header + prepared + remaining_reserved;
    limits.max_startup_replay_bytes = limits.max_file_bytes;
    let mut index = FileNeuronRuntimeIndexV2::create(&path, limits.clone())?;
    let first = operation(1)?;
    index.prepare(first.key.clone(), /*expected_anchor*/ None)?;
    drop(index);
    let mut index = FileNeuronRuntimeIndexV2::open_existing(&path, limits)?;
    let result = index.complete(&first.key, first.next_anchor, digest("committed-operation"))?;
    assert_eq!(index.pending()?, None);
    assert_eq!(
        index.admit(&first.key, /*expected_anchor*/ None)?,
        NeuronRuntimeIndexAdmissionV2::Historical(result)
    );
    assert!(remaining_reserved >= completed);
    assert_eq!(fs::metadata(path)?.len(), header + prepared + completed);
    Ok(())
}

#[test]
fn index_replay_ceiling_prevents_unreopenable_pending_work() -> Result<(), Box<dyn Error>> {
    let (header, _, _, _) = index_frame_sizes()?;
    let root = Fixture::new()?;
    let path = root.path().join("index");
    let mut limits = index_context()?;
    limits.max_startup_replay_bytes = header;
    let mut index = FileNeuronRuntimeIndexV2::create(&path, limits.clone())?;
    assert_eq!(
        index.prepare(operation(1)?.key, /*expected_anchor*/ None),
        Err(NeuronRuntimeIndexError::Capacity)
    );
    drop(index);
    let index = FileNeuronRuntimeIndexV2::open_existing(&path, limits)?;
    assert_eq!(index.pending()?, None);
    assert_eq!(index.frontier()?, None);
    Ok(())
}
