use super::*;
use crate::generation_store_v2::GenerationStoreFailpointV2;
use crate::AnchorWitnessStore;
use crate::FileNeuronWitnessStoreV2;
use crate::JournalError;
use crate::NeuronWitnessContextV2;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::SparseTick;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

const EXIT_CODE: i32 = 73;
const Q24: i64 = 1 << 24;
const CUTS: &[&str] = &[
    "before_model_invocation",
    "after_model_result",
    "before_journal_append",
    "during_journal_frame_write",
    "after_journal_write_before_sync",
    "after_journal_sync",
    "after_full_receipt_durability",
    "before_witness_append",
    "during_witness_append",
    "after_witness_sync_before_response",
    "after_response_before_caller_acknowledgement",
    "during_journal_rollover",
    "during_witness_rollover",
];
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

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = FIXTURE.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-v2-process-cuts-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self(root)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn id(label: &str) -> StableId {
    checked(StableId::new(label))
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: digest("process-scope"),
        objective_digest: digest("process-objective"),
    }
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: digest(&format!("process-checkpoint-{sequence}")),
    }
}

fn store_context() -> NeuronGenerationStoreContextV2 {
    NeuronGenerationStoreContextV2 {
        generation: checked(Generation::new(9)),
        scope: scope(),
        runtime_config_digest: digest("process-config"),
        body_bundle_digest: digest("process-body"),
        max_records: 8,
        max_pending_witness: 8,
        max_checkpoint_bytes: 4096,
        max_full_receipt_bytes: 4096,
        max_file_bytes: 1024 * 1024,
        max_startup_replay_bytes: 1024 * 1024,
    }
}

fn witness_context(max_records: usize) -> NeuronWitnessContextV2 {
    NeuronWitnessContextV2 {
        generation: checked(Generation::new(9)),
        scope: scope(),
        key_epoch: 3,
        deletion_epoch: 5,
        max_records,
    }
}

fn operation_key() -> NeuronOperationKeyV2 {
    NeuronOperationKeyV2 {
        tick_id: id("process-tick-1"),
        input_semantic_digest: digest("process-input-1"),
    }
}

fn commit_value(model_result: &[u8]) -> NeuronGenerationCommitV2 {
    NeuronGenerationCommitV2 {
        key: operation_key(),
        config_semantic_digest: digest("process-config"),
        body_bundle_digest: digest("process-body"),
        model_semantic_digest: digest("process-model-semantic"),
        model_observation_digest: Digest32::of_parts(&[
            b"hepta.neuron.process-model-result.v1",
            model_result,
        ]),
        expected_anchor: None,
        next_anchor: anchor(1),
        checkpoint_bytes: b"process-canonical-checkpoint-1".to_vec(),
        full_receipt_bytes: b"process-full-receipt-1".to_vec(),
        disposition: NeuronCommitDispositionV1::CommittedReady,
    }
}

fn store_path(root: &Path) -> PathBuf {
    root.join("generation.hptngs02")
}

fn witness_path(root: &Path) -> PathBuf {
    root.join("witness.hptnwv02")
}

fn open_store(root: &Path) -> FileNeuronGenerationStoreV2 {
    let path = store_path(root);
    if path.exists() {
        checked(FileNeuronGenerationStoreV2::open_existing(
            &path,
            store_context(),
        ))
    } else {
        checked(FileNeuronGenerationStoreV2::create(
            &path,
            store_context(),
        ))
    }
}

fn open_witness(root: &Path) -> FileNeuronWitnessStoreV2 {
    let path = witness_path(root);
    if path.exists() {
        checked(FileNeuronWitnessStoreV2::open_existing(
            &path,
            witness_context(8),
        ))
    } else {
        checked(FileNeuronWitnessStoreV2::create(
            &path,
            witness_context(8),
        ))
    }
}

fn sync_parent(path: &Path) {
    let parent = match path.parent() {
        Some(value) => value,
        None => panic!("missing parent"),
    };
    let directory = checked(File::open(parent));
    checked(directory.sync_all());
}

fn write_durable(path: &Path, bytes: &[u8]) {
    let mut file = checked(
        OpenOptions::new()
            .write(true)
            .create(true)
            .truncate(true)
            .open(path),
    );
    checked(file.write_all(bytes));
    checked(file.sync_all());
    sync_parent(path);
}

fn durable_model_result(root: &Path) -> Vec<u8> {
    let result_path = root.join("model-result");
    if result_path.exists() {
        return checked(fs::read(result_path));
    }
    let calls_path = root.join("model-calls");
    let mut calls = checked(
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(&calls_path),
    );
    checked(calls.write_all(b"physical-call\n"));
    checked(calls.sync_all());
    sync_parent(&calls_path);
    let result = b"durable-inference-result-v1".to_vec();
    let mut result_file = checked(
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&result_path),
    );
    checked(result_file.write_all(&result));
    checked(result_file.sync_all());
    sync_parent(&result_path);
    result
}

fn cut_now(point: &str) {
    if std::env::var("HEPTA_NEURON_V2_CRASH_CUT").is_ok_and(|value| value == point) {
        std::process::exit(EXIT_CODE);
    }
}

fn reconcile_witness(
    store: &mut FileNeuronGenerationStoreV2,
    witness: &mut FileNeuronWitnessStoreV2,
) {
    let Some(pending) = checked(store.pending_witness()) else {
        return;
    };
    let current = checked(witness.current());
    if current == pending.expected_anchor {
        checked(witness.compare_and_swap(pending.expected_anchor, pending.next_anchor));
    } else if current != Some(pending.next_anchor) {
        panic!("witness frontier diverged");
    }
    checked(store.acknowledge_witness(&pending.key, pending.next_anchor));
}

fn execute_or_recover(root: &Path, allow_process_cut: bool) -> Vec<u8> {
    let mut store = open_store(root);
    let mut witness = open_witness(root);
    let key = operation_key();
    let output = match checked(store.admit_operation(&key, None, 128, 128)) {
        NeuronGenerationAdmissionV2::Historical(record) => record.full_receipt_bytes,
        NeuronGenerationAdmissionV2::New => {
            if allow_process_cut {
                cut_now("before_model_invocation");
            }
            let model_result = durable_model_result(root);
            if allow_process_cut {
                cut_now("after_model_result");
                cut_now("before_journal_append");
                let cut = checked(std::env::var("HEPTA_NEURON_V2_CRASH_CUT"));
                match cut.as_str() {
                    "during_journal_frame_write" => {
                        store.fail_next_append(GenerationStoreFailpointV2::DuringFrameWrite);
                    }
                    "after_journal_write_before_sync" => {
                        store.fail_next_append(
                            GenerationStoreFailpointV2::AfterFrameWriteBeforeSync,
                        );
                    }
                    "after_journal_sync" => {
                        store.fail_next_append(GenerationStoreFailpointV2::AfterFrameSync);
                    }
                    _ => {}
                }
            }
            let committed = store.commit_result(commit_value(&model_result));
            if allow_process_cut
                && matches!(
                    std::env::var("HEPTA_NEURON_V2_CRASH_CUT").as_deref(),
                    Ok("during_journal_frame_write")
                        | Ok("after_journal_write_before_sync")
                        | Ok("after_journal_sync")
                )
            {
                assert_eq!(committed, Err(GenerationStoreError::Indeterminate));
                std::process::exit(EXIT_CODE);
            }
            let output = match checked(committed) {
                NeuronGenerationCommitResultV2::Committed(record)
                | NeuronGenerationCommitResultV2::Duplicate(record) => record.full_receipt_bytes,
            };
            if allow_process_cut {
                cut_now("after_full_receipt_durability");
            }
            output
        }
    };
    reconcile_witness(&mut store, &mut witness);
    let response = root.join("response");
    write_durable(&response, &output);
    if allow_process_cut {
        cut_now("after_response_before_caller_acknowledgement");
    }
    write_durable(&root.join("caller-ack"), digest_bytes(&output).as_array());
    output
}

fn digest_bytes(bytes: &[u8]) -> Digest32 {
    Digest32::of_parts(&[b"hepta.neuron.caller-ack.v1", bytes])
}

fn sparse_config() -> SparseConfig {
    SparseConfig {
        model_digest: digest("rollover-model"),
        normalization_digest: digest("rollover-normalization"),
        generation: checked(Generation::new(9)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q24 / 2,
        inhibition_gain_q24: Q24,
        inhibition: Vec::new(),
        activity_decay_q24: 0,
        target_activity_q24: Q24 / 8,
        threshold_rate_q24: Q24 / 8,
        threshold_min_q24: -Q24,
        threshold_max_q24: Q24,
        eligibility_decay_q24: Q24 / 2,
    }
}

fn sparse_tick() -> SparseTick {
    SparseTick {
        scope_digest: scope().scope_digest,
        objective_digest: scope().objective_digest,
        ndu_digest: digest("rollover-ndu"),
        body_digest: digest("rollover-body"),
        input_digest: digest("rollover-input"),
        sequence: 1,
        monotonic_micros: 1_000,
        drive_q24: vec![Q24, Q24 / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    }
}

fn create_file(path: &Path) -> File {
    checked(
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path),
    )
}

fn open_rw(path: &Path) -> File {
    checked(OpenOptions::new().read(true).write(true).open(path))
}

fn journal_rollover_child(root: &Path) -> ! {
    let root_path = root.join("journal-root");
    let successor_path = root.join("journal-successor");
    let mut journal = checked(SparseJournal::open(
        create_file(&root_path),
        sparse_config(),
        scope(),
        1,
    ));
    checked(journal.commit(Digest32::ZERO, &sparse_tick()));
    write_durable(&root.join("active-journal"), b"journal-root");
    let _successor = checked(journal.start_successor(create_file(&successor_path), 1));
    std::process::exit(EXIT_CODE);
}

fn witness_rollover_child(root: &Path) -> ! {
    let root_path = root.join("rollover-witness-root");
    let successor_path = root.join("rollover-witness-successor");
    let mut witness = checked(FileNeuronWitnessStoreV2::create(
        &root_path,
        witness_context(1),
    ));
    checked(witness.compare_and_swap(None, anchor(1)));
    write_durable(&root.join("active-witness"), b"rollover-witness-root");
    let _successor = checked(witness.start_successor(&successor_path, witness_context(2)));
    std::process::exit(EXIT_CODE);
}

fn inspect_before_recovery(root: &Path, cut: &str) {
    if cut == "during_journal_rollover" || cut == "during_witness_rollover" {
        return;
    }
    let store = open_store(root);
    let witness = open_witness(root);
    let record = checked(store.find_operation(&operation_key()));
    let record_expected = !matches!(
        cut,
        "before_model_invocation"
            | "after_model_result"
            | "before_journal_append"
            | "during_journal_frame_write"
    );
    assert_eq!(record.is_some(), record_expected, "cut={cut}");
    let witness_expected = matches!(
        cut,
        "after_witness_sync_before_response"
            | "after_response_before_caller_acknowledgement"
    );
    assert_eq!(
        checked(witness.current()),
        witness_expected.then_some(anchor(1)),
        "cut={cut}"
    );
    if cut == "during_journal_frame_write" {
        assert_eq!(checked(store.current_anchor()), None);
    }
}

fn verify_normal_recovery(root: &Path, cut: &str) {
    inspect_before_recovery(root, cut);
    let output = execute_or_recover(root, false);
    assert_eq!(output, b"process-full-receipt-1");

    let mut store = open_store(root);
    let witness = open_witness(root);
    assert_eq!(checked(store.current_anchor()), Some(anchor(1)));
    assert_eq!(checked(store.witnessed_anchor()), Some(anchor(1)));
    assert_eq!(checked(witness.current()), Some(anchor(1)));
    assert_eq!(checked(store.pending_witness()), None);
    assert_eq!(checked(fs::read(root.join("response"))), output);
    assert_eq!(
        checked(fs::read(root.join("caller-ack"))),
        digest_bytes(&output).as_array()
    );

    let record = present(checked(store.find_operation(&operation_key())));
    assert_eq!(record.full_receipt_bytes, output);
    assert!(matches!(
        checked(store.commit_result(commit_value(b"durable-inference-result-v1"))),
        NeuronGenerationCommitResultV2::Duplicate(_)
    ));
    let changed = NeuronOperationKeyV2 {
        tick_id: operation_key().tick_id,
        input_semantic_digest: digest("changed-process-input"),
    };
    assert_eq!(
        store.admit_operation(&changed, None, 128, 128),
        Err(GenerationStoreError::Conflict)
    );
    assert_eq!(
        checked(fs::read(root.join("model-calls"))),
        b"physical-call\n",
        "cut={cut}"
    );
}

fn verify_journal_rollover(root: &Path) {
    assert_eq!(
        checked(fs::read(root.join("active-journal"))),
        b"journal-root"
    );
    let root_journal = checked(SparseJournal::open(
        open_rw(&root.join("journal-root")),
        sparse_config(),
        scope(),
        1,
    ));
    let root_anchor = present(checked(root_journal.current_anchor()));
    assert_eq!(root_anchor.sequence, 1);
    let successor = checked(root_journal.recover_successor(
        open_rw(&root.join("journal-successor")),
        1,
        root_anchor,
    ));
    assert_eq!(checked(successor.current_anchor()), Some(root_anchor));
}

fn verify_witness_rollover(root: &Path) {
    assert_eq!(
        checked(fs::read(root.join("active-witness"))),
        b"rollover-witness-root"
    );
    let root_witness = checked(FileNeuronWitnessStoreV2::open_existing(
        &root.join("rollover-witness-root"),
        witness_context(1),
    ));
    assert_eq!(checked(root_witness.current()), Some(anchor(1)));
    let successor = checked(FileNeuronWitnessStoreV2::open_successor(
        &root.join("rollover-witness-successor"),
        witness_context(2),
        anchor(1),
    ));
    assert_eq!(checked(successor.current()), Some(anchor(1)));
}

#[test]
fn durable_process_crash_matrix_v2() {
    if let Some(root) = std::env::var_os("HEPTA_NEURON_V2_CRASH_ROOT") {
        let root = PathBuf::from(root);
        let cut = checked(std::env::var("HEPTA_NEURON_V2_CRASH_CUT"));
        match cut.as_str() {
            "during_journal_rollover" => journal_rollover_child(&root),
            "during_witness_rollover" => witness_rollover_child(&root),
            _ => {
                drop(execute_or_recover(&root, true));
                panic!("crash cut did not terminate child: {cut}");
            }
        }
    }

    for cut in CUTS {
        let fixture = Fixture::new();
        let mut child = checked(
            Command::new(checked(std::env::current_exe()))
                .arg("--exact")
                .arg("generation_store_v2_process_tests::durable_process_crash_matrix_v2")
                .arg("--nocapture")
                .env("HEPTA_NEURON_V2_CRASH_ROOT", &fixture.0)
                .env("HEPTA_NEURON_V2_CRASH_CUT", cut)
                .stdout(Stdio::null())
                .stderr(Stdio::inherit())
                .spawn(),
        );
        let started = Instant::now();
        let status = loop {
            if let Some(status) = checked(child.try_wait()) {
                break status;
            }
            if started.elapsed() > Duration::from_secs(30) {
                let _ = child.kill();
                let _ = child.wait();
                panic!("child did not reach crash cut: {cut}");
            }
            std::thread::sleep(Duration::from_millis(10));
        };
        assert_eq!(status.code(), Some(EXIT_CODE), "cut={cut}");
        match *cut {
            "during_journal_rollover" => verify_journal_rollover(&fixture.0),
            "during_witness_rollover" => verify_witness_rollover(&fixture.0),
            _ => verify_normal_recovery(&fixture.0, cut),
        }
    }
}

#[test]
fn generation_store_process_matrix_names_are_closed_world() {
    assert_eq!(CUTS.len(), 13);
    let unique = CUTS
        .iter()
        .copied()
        .collect::<std::collections::BTreeSet<_>>();
    assert_eq!(unique.len(), CUTS.len());
}

#[test]
fn rollover_fixture_rejects_changed_journal_context() {
    let fixture = Fixture::new();
    let root_path = fixture.0.join("journal-root");
    let journal = checked(SparseJournal::open(
        create_file(&root_path),
        sparse_config(),
        scope(),
        1,
    ));
    drop(journal);
    let mut changed = sparse_config();
    changed.threshold_rate_q24 += 1;
    assert_eq!(
        SparseJournal::open(open_rw(&root_path), changed, scope(), 1).err(),
        Some(JournalError::ContextMismatch)
    );
}
