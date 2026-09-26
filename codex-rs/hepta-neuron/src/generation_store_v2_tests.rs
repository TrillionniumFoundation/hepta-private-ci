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
        fs::create_dir_all(&root).expect("fixture directory");
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
    StableId::new(label).expect("fixture id")
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: digest(&format!("checkpoint-{sequence}")),
    }
}

fn context() -> NeuronGenerationStoreContextV2 {
    NeuronGenerationStoreContextV2 {
        generation: Generation::new(4).expect("generation"),
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
        expected_anchor: (sequence > 1).then(|| anchor(sequence - 1)),
        next_anchor: anchor(sequence),
        checkpoint_bytes: format!("canonical-checkpoint-{sequence}").into_bytes(),
        full_receipt_bytes: format!("full-receipt-{sequence}").into_bytes(),
        disposition: if sequence == 1 {
            NeuronCommitDispositionV1::CommittedReady
        } else {
            NeuronCommitDispositionV1::degraded(
                vec![DegradationReasonV1::LatencyEnvelope],
                vec![AbstainReasonV1::OutOfDomain],
            )
            .expect("disposition")
        },
    }
}

#[test]
fn commit_duplicate_and_reopen_return_exact_full_result() {
    let fixture = Fixture::new();
    let mut store = FileNeuronGenerationStoreV2::create(&fixture.file, context()).expect("create");
    let value = commit(1);
    let committed = match store.commit_result(value.clone()).expect("commit") {
        NeuronGenerationCommitResultV2::Committed(record) => record,
        NeuronGenerationCommitResultV2::Duplicate(_) => panic!("fresh commit was duplicate"),
    };
    assert_eq!(committed.full_receipt_bytes, b"full-receipt-1");
    match store.commit_result(value.clone()).expect("duplicate") {
        NeuronGenerationCommitResultV2::Duplicate(record) => assert_eq!(record, committed),
        NeuronGenerationCommitResultV2::Committed(_) => panic!("duplicate was committed twice"),
    }
    drop(store);

    let mut reopened =
        FileNeuronGenerationStoreV2::open_existing(&fixture.file, context()).expect("reopen");
    assert_eq!(
        reopened
            .find_operation(&value.key)
            .expect("lookup")
            .expect("stored record"),
        committed
    );
    match reopened.commit_result(value).expect("restart duplicate") {
        NeuronGenerationCommitResultV2::Duplicate(record) => assert_eq!(record, committed),
        NeuronGenerationCommitResultV2::Committed(_) => panic!("restart duplicate recommitted"),
    }
}

#[test]
fn same_tick_with_changed_input_or_receipt_conflicts() {
    let fixture = Fixture::new();
    let mut store = FileNeuronGenerationStoreV2::create(&fixture.file, context()).expect("create");
    let value = commit(1);
    store.commit_result(value.clone()).expect("commit");

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
    let mut store = FileNeuronGenerationStoreV2::create(&fixture.file, context()).expect("create");
    let value = commit(1);
    let record = match store.commit_result(value.clone()).expect("commit") {
        NeuronGenerationCommitResultV2::Committed(record) => record,
        NeuronGenerationCommitResultV2::Duplicate(_) => panic!("unexpected duplicate"),
    };
    assert_eq!(store.pending_witness().expect("pending"), Some(record));
    drop(store);

    let mut reopened =
        FileNeuronGenerationStoreV2::open_existing(&fixture.file, context()).expect("reopen");
    assert_eq!(reopened.pending_witness_count().expect("count"), 1);
    reopened
        .acknowledge_witness(&value.key, value.next_anchor)
        .expect("acknowledge");
    assert_eq!(reopened.pending_witness().expect("pending"), None);
    drop(reopened);

    let reopened =
        FileNeuronGenerationStoreV2::open_existing(&fixture.file, context()).expect("reopen ack");
    assert_eq!(reopened.pending_witness_count().expect("count"), 0);
    assert_eq!(reopened.witnessed_anchor().expect("witness"), Some(anchor(1)));
}

#[test]
fn admission_returns_history_before_model_and_conflicts_on_payload_drift() {
    let fixture = Fixture::new();
    let mut store = FileNeuronGenerationStoreV2::create(&fixture.file, context()).expect("create");
    let value = commit(1);
    let record = match store.commit_result(value.clone()).expect("commit") {
        NeuronGenerationCommitResultV2::Committed(record) => record,
        NeuronGenerationCommitResultV2::Duplicate(_) => panic!("unexpected duplicate"),
    };
    assert_eq!(
        store
            .admit_operation(&value.key, None, 100, 100)
            .expect("historical admission"),
        NeuronGenerationAdmissionV2::Historical(record)
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
    let mut store = FileNeuronGenerationStoreV2::create(&fixture.file, context()).expect("create");
    let first = commit(1);
    store.commit_result(first.clone()).expect("first");
    drop(store);

    let stable_length = fs::metadata(&fixture.file).expect("metadata").len();
    let mut file = OpenOptions::new()
        .append(true)
        .open(&fixture.file)
        .expect("append");
    file.write_all(&[0, 0, 0]).expect("partial prefix");
    file.sync_all().expect("sync partial");
    drop(file);

    let reopened =
        FileNeuronGenerationStoreV2::open_existing(&fixture.file, context()).expect("recover");
    assert_eq!(fs::metadata(&fixture.file).expect("metadata").len(), stable_length);
    assert_eq!(reopened.pending_witness_count().expect("pending"), 1);
    assert_eq!(
        reopened
            .find_operation(&first.key)
            .expect("lookup")
            .expect("first")
            .full_receipt_bytes,
        b"full-receipt-1"
    );
}

#[test]
fn complete_checksum_corruption_fails_closed() {
    let fixture = Fixture::new();
    let mut store = FileNeuronGenerationStoreV2::create(&fixture.file, context()).expect("create");
    store.commit_result(commit(1)).expect("commit");
    drop(store);

    let mut file = OpenOptions::new()
        .read(true)
        .write(true)
        .open(&fixture.file)
        .expect("open");
    file.seek(SeekFrom::Start(HEADER_BYTES as u64 + 8))
        .expect("seek");
    file.write_all(&[0xff]).expect("corrupt");
    file.sync_all().expect("sync corruption");
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
    let mut store = FileNeuronGenerationStoreV2::create(&fixture.file, context()).expect("create");
    store.fail_next_append(GenerationStoreFailpointV2::AfterFrameSync);
    assert_eq!(
        store.commit_result(value.clone()),
        Err(GenerationStoreError::Indeterminate)
    );
    drop(store);

    let mut reopened =
        FileNeuronGenerationStoreV2::open_existing(&fixture.file, context()).expect("recover");
    let recovered = reopened
        .find_operation(&value.key)
        .expect("lookup")
        .expect("recovered commit");
    assert_eq!(recovered.full_receipt_bytes, value.full_receipt_bytes);
    assert!(matches!(
        reopened.commit_result(value).expect("duplicate"),
        NeuronGenerationCommitResultV2::Duplicate(_)
    ));
}

#[test]
fn during_write_uncertainty_does_not_fabricate_success() {
    let fixture = Fixture::new();
    let value = commit(1);
    let mut store = FileNeuronGenerationStoreV2::create(&fixture.file, context()).expect("create");
    store.fail_next_append(GenerationStoreFailpointV2::DuringFrameWrite);
    assert_eq!(
        store.commit_result(value.clone()),
        Err(GenerationStoreError::Indeterminate)
    );
    drop(store);

    let reopened =
        FileNeuronGenerationStoreV2::open_existing(&fixture.file, context()).expect("recover");
    assert_eq!(reopened.find_operation(&value.key).expect("lookup"), None);
    assert_eq!(reopened.current_anchor().expect("anchor"), None);
}
