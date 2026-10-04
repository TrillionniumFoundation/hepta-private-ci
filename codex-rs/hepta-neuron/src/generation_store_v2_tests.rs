use super::*;
use crate::AbstainReasonV1;
use crate::DegradationReasonV1;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static FIXTURE: AtomicU64 = AtomicU64::new(1);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn present<T>(value: Option<T>) -> T {
    match value {
        Some(value) => value,
        None => panic!("fixture value is missing"),
    }
}

struct Fixture {
    root: PathBuf,
    file: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = FIXTURE.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-generation-store-v2-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir_all(&root));
        let file = root.join("generation.hptngs02");
        Self { root, file }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: digest(&format!("checkpoint-{sequence}")),
    }
}

fn context() -> NeuronGenerationStoreContextV2 {
    NeuronGenerationStoreContextV2 {
        generation: checked(Generation::new(4)),
        scope: JournalScope {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
        },
        runtime_config_digest: digest("config"),
        body_bundle_digest: digest("body"),
        max_records: 16,
        max_pending_witness: 16,
        max_checkpoint_bytes: 4096,
        max_full_receipt_bytes: 4096,
        max_file_bytes: 1024 * 1024,
        max_startup_replay_bytes: 1024 * 1024,
    }
}

fn commit(sequence: u64) -> NeuronGenerationCommitV2 {
    NeuronGenerationCommitV2 {
        key: NeuronOperationKeyV2 {
            tick_id: id(&format!("tick-{sequence}")),
            input_semantic_digest: digest(&format!("input-{sequence}")),
        },
        config_semantic_digest: digest("config"),
        body_bundle_digest: digest("body"),
        model_semantic_digest: digest("model"),
        model_observation_digest: digest(&format!("observation-{sequence}")),
        expected_anchor: (sequence > 1).then_some(anchor(sequence - 1)),
        next_anchor: anchor(sequence),
        checkpoint_bytes: format!("canonical-checkpoint-{sequence}").into_bytes(),
        full_receipt_bytes: format!("full-receipt-{sequence}").into_bytes(),
        disposition: if sequence == 1 {
            NeuronCommitDispositionV1::CommittedReady
        } else {
            checked(NeuronCommitDispositionV1::degraded(
                vec![DegradationReasonV1::LatencyEnvelope],
                vec![AbstainReasonV1::OutOfDomain],
            ))
        },
    }
}

#[test]
fn commit_duplicate_and_reopen_return_exact_full_result() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    let value = commit(1);
    let committed = match checked(store.commit_result(value.clone())) {
        NeuronGenerationCommitResultV2::Committed(record) => record,
        NeuronGenerationCommitResultV2::Duplicate(_) => panic!("fresh commit was duplicate"),
    };
    assert_eq!(committed.full_receipt_bytes, b"full-receipt-1");
    match checked(store.commit_result(value.clone())) {
        NeuronGenerationCommitResultV2::Duplicate(record) => assert_eq!(record, committed),
        NeuronGenerationCommitResultV2::Committed(_) => panic!("duplicate was committed twice"),
    }
    drop(store);

    let mut reopened = checked(FileNeuronGenerationStoreV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(
        present(checked(reopened.find_operation(&value.key))),
        committed
    );
    match checked(reopened.commit_result(value)) {
        NeuronGenerationCommitResultV2::Duplicate(record) => assert_eq!(record, committed),
        NeuronGenerationCommitResultV2::Committed(_) => panic!("restart duplicate recommitted"),
    }
}

#[test]
fn same_tick_with_changed_input_or_receipt_conflicts() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    let value = commit(1);
    checked(store.commit_result(value.clone()));

    let mut changed_input = value.clone();
    changed_input.key.input_semantic_digest = digest("different-input");
    assert_eq!(
        store.commit_result(changed_input),
        Err(GenerationStoreError::Conflict)
    );

    let mut changed_receipt = value;
    changed_receipt.full_receipt_bytes = b"different-result".to_vec();
    assert_eq!(
        store.commit_result(changed_receipt),
        Err(GenerationStoreError::Conflict)
    );
}

#[test]
fn witness_pending_and_ack_are_durable() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    let value = commit(1);
    let record = match checked(store.commit_result(value.clone())) {
        NeuronGenerationCommitResultV2::Committed(record) => record,
        NeuronGenerationCommitResultV2::Duplicate(_) => panic!("unexpected duplicate"),
    };
    assert_eq!(checked(store.pending_witness()), Some(record));
    drop(store);

    let mut reopened = checked(FileNeuronGenerationStoreV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(checked(reopened.pending_witness_count()), 1);
    checked(reopened.acknowledge_witness(&value.key, value.next_anchor));
    assert_eq!(checked(reopened.pending_witness()), None);
    drop(reopened);

    let reopened = checked(FileNeuronGenerationStoreV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(checked(reopened.pending_witness_count()), 0);
    assert_eq!(checked(reopened.witnessed_anchor()), Some(anchor(1)));
}

#[test]
fn admission_returns_history_before_model_and_conflicts_on_payload_drift() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    let value = commit(1);
    let record = match checked(store.commit_result(value.clone())) {
        NeuronGenerationCommitResultV2::Committed(record) => record,
        NeuronGenerationCommitResultV2::Duplicate(_) => panic!("unexpected duplicate"),
    };
    assert_eq!(
        checked(store.admit_operation(&value.key, None, 100, 100)),
        NeuronGenerationAdmissionV2::Historical(Box::new(record))
    );
    let changed = NeuronOperationKeyV2 {
        tick_id: value.key.tick_id,
        input_semantic_digest: digest("changed-input"),
    };
    assert_eq!(
        store.admit_operation(&changed, None, 100, 100),
        Err(GenerationStoreError::Conflict)
    );
}

#[test]
fn partial_tail_is_truncated_without_fabricated_success() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    let first = commit(1);
    checked(store.commit_result(first.clone()));
    drop(store);

    let stable_length = checked(fs::metadata(&fixture.file)).len();
    let mut file = checked(OpenOptions::new().append(true).open(&fixture.file));
    checked(file.write_all(&[0, 0, 0]));
    checked(file.sync_all());
    drop(file);

    let reopened = checked(FileNeuronGenerationStoreV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(checked(fs::metadata(&fixture.file)).len(), stable_length);
    assert_eq!(checked(reopened.pending_witness_count()), 1);
    assert_eq!(
        present(checked(reopened.find_operation(&first.key))).full_receipt_bytes,
        b"full-receipt-1"
    );
}

#[test]
fn complete_checksum_corruption_fails_closed() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    checked(store.commit_result(commit(1)));
    drop(store);

    let mut file = checked(
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(&fixture.file),
    );
    checked(file.seek(SeekFrom::Start(HEADER_BYTES as u64 + 8)));
    checked(file.write_all(&[0xff]));
    checked(file.sync_all());
    drop(file);

    assert!(matches!(
        FileNeuronGenerationStoreV2::open_existing(&fixture.file, context()),
        Err(GenerationStoreError::Corrupt)
    ));
}

#[test]
fn post_sync_uncertainty_recovers_as_one_commit() {
    let fixture = Fixture::new();
    let value = commit(1);
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    store.fail_next_append(GenerationStoreFailpointV2::AfterFrameSync);
    assert_eq!(
        store.commit_result(value.clone()),
        Err(GenerationStoreError::Indeterminate)
    );
    drop(store);

    let mut reopened = checked(FileNeuronGenerationStoreV2::open_existing(
        &fixture.file,
        context(),
    ));
    let recovered = present(checked(reopened.find_operation(&value.key)));
    assert_eq!(recovered.full_receipt_bytes, value.full_receipt_bytes);
    assert!(matches!(
        checked(reopened.commit_result(value)),
        NeuronGenerationCommitResultV2::Duplicate(_)
    ));
}

#[test]
fn during_write_uncertainty_does_not_fabricate_success() {
    let fixture = Fixture::new();
    let value = commit(1);
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    store.fail_next_append(GenerationStoreFailpointV2::DuringFrameWrite);
    assert_eq!(
        store.commit_result(value.clone()),
        Err(GenerationStoreError::Indeterminate)
    );
    drop(store);

    let reopened = checked(FileNeuronGenerationStoreV2::open_existing(
        &fixture.file,
        context(),
    ));
    assert_eq!(checked(reopened.find_operation(&value.key)), None);
    assert_eq!(checked(reopened.current_anchor()), None);
}

// Inject same-inode retained-byte faults through the already-held fixture
// descriptor. Windows also enforces its owner lock against separate handles.
fn overwrite_held_fixture(store: &mut FileNeuronGenerationStoreV2, bytes: &[u8]) {
    let position = checked(store.file.stream_position());
    checked(store.file.seek(SeekFrom::Start(0)));
    checked(store.file.write_all(bytes));
    checked(store.file.set_len(bytes.len() as u64));
    checked(store.file.sync_data());
    checked(store.file.seek(SeekFrom::Start(position)));
}

#[test]
fn live_retained_same_length_corruption_cannot_return_historical_result() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    let request = commit(1);
    checked(store.commit_result(request.clone()));
    let original = store.held_fixture_bytes();
    let mut changed = original.clone();
    let last = changed.len() - 1;
    changed[last] ^= 1;
    overwrite_held_fixture(&mut store, &changed);
    assert!(
        store.find_operation(&request.key).is_err(),
        "changed live bytes returned cached success"
    );
    overwrite_held_fixture(&mut store, &original);
    assert!(matches!(
        store.current_anchor(),
        Err(GenerationStoreError::Poisoned)
    ));
}

#[test]
fn live_retained_truncation_cannot_admit_from_a_cached_frontier() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    checked(store.commit_result(commit(1)));
    let original = store.held_fixture_bytes();
    checked(store.file.set_len(HEADER_BYTES as u64));
    let request = commit(2);
    assert!(
        store
            .admit_operation(
                &request.key,
                Some(anchor(1)),
                request.checkpoint_bytes.len(),
                request.full_receipt_bytes.len()
            )
            .is_err(),
        "missing retained history admitted another model operation"
    );
    overwrite_held_fixture(&mut store, &original);
    assert!(matches!(
        store.find_operation(&commit(1).key),
        Err(GenerationStoreError::Poisoned)
    ));
}

#[test]
fn live_retained_header_substitution_blocks_append_without_overwriting() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    checked(store.commit_result(commit(1)));
    let mut changed = store.held_fixture_bytes();
    changed[8] ^= 1;
    overwrite_held_fixture(&mut store, &changed);
    assert!(
        store.commit_result(commit(2)).is_err(),
        "a changed live header admitted another commit"
    );
    assert_eq!(store.held_fixture_bytes(), changed);
}

#[test]
fn live_retained_rehashed_alternate_history_cannot_replace_cached_frontier() {
    let fixture = Fixture::new();
    let mut store = checked(FileNeuronGenerationStoreV2::create(
        &fixture.file,
        context(),
    ));
    let request = commit(1);
    checked(store.commit_result(request.clone()));
    let original = store.held_fixture_bytes();
    let alternate_path = fixture.root.join("alternate.hptngs02");
    let mut alternate = checked(FileNeuronGenerationStoreV2::create(
        &alternate_path,
        context(),
    ));
    let mut changed_request = request.clone();
    changed_request.full_receipt_bytes[0] ^= 1;
    checked(alternate.commit_result(changed_request));
    drop(alternate);
    let alternate_bytes = checked(fs::read(&alternate_path));
    assert_eq!(alternate_bytes.len(), original.len());
    overwrite_held_fixture(&mut store, &alternate_bytes);
    assert!(
        store.find_operation(&request.key).is_err(),
        "valid frame hashes were accepted against a different retained frontier"
    );
    assert_eq!(store.held_fixture_bytes(), alternate_bytes);
}
