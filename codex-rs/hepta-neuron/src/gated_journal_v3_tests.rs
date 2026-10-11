use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::gated_sparse_v3::TemporalGateV3;
use crate::population_v2::ActivationPopulationV2;
use crate::population_v2::PopulationSparseConfigV2;
use crate::population_v2::TemporalProjectionEdgeV2;
use codex_hepta_types::Generation;

const Q: i64 = 1 << 24;
static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("V3 shadow fixture failed: {error:?}"))
}

fn config() -> GatedSparseConfigV3 {
    GatedSparseConfigV3 {
        base: PopulationSparseConfigV2 {
            model_digest: Digest32::of_bytes(b"selected-training-artifact"),
            normalization_digest: Digest32::of_bytes(b"selected-normalization"),
            generation: checked(Generation::new(31)),
            temporal_width: 2,
            activation_width: 6,
            global_top_k: 1,
            temporal_decay_q24: Q / 2,
            projection: (0..6)
                .map(|target_activation| TemporalProjectionEdgeV2 {
                    source_temporal: target_activation % 2,
                    target_activation,
                    weight_q24: Q / 2,
                })
                .collect(),
            inhibition_gain_q24: Q / 2,
            inhibition: Vec::new(),
            populations: vec![
                ActivationPopulationV2 {
                    start: 0,
                    len: 3,
                    top_k: 1,
                },
                ActivationPopulationV2 {
                    start: 3,
                    len: 3,
                    top_k: 1,
                },
            ],
            activity_decay_q24: Q / 2,
            target_activity_q24: Q / 2,
            threshold_rate_q24: Q / 16,
            threshold_min_q24: -Q,
            threshold_max_q24: Q,
            eligibility_decay_q24: Q / 2,
        },
        gates: vec![
            TemporalGateV3 {
                bias_q24: Q / 2,
                input_gain_q24: Q / 4,
                change_gain_q24: Q / 4,
            };
            2
        ],
    }
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: Digest32::of_bytes(b"shadow-scope"),
        objective_digest: Digest32::of_bytes(b"shadow-objective"),
    }
}

fn tick(sequence: u64) -> PopulationSparseTickV2 {
    PopulationSparseTickV2 {
        scope_digest: scope().scope_digest,
        objective_digest: scope().objective_digest,
        ndu_digest: Digest32::of_bytes(b"frozen-ndu-shadow"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(format!("features-{sequence}").as_bytes()),
        sequence,
        monotonic_micros: sequence * 100,
        temporal_drive_q24: vec![
            Q,
            if sequence.is_multiple_of(2) {
                -Q / 2
            } else {
                Q / 2
            },
        ],
        prediction_q24: vec![0; 6],
    }
}

struct Fixture {
    root: PathBuf,
    file: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-gated-v3-journal-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        let file = root.join("shadow-v3");
        Self { root, file }
    }

    fn create(&self) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(&self.file),
        )
    }

    fn reopen(&self) -> File {
        checked(OpenOptions::new().read(true).write(true).open(&self.file))
    }

    fn open_anchored(
        &self,
        anchor: JournalAnchor,
    ) -> Result<GatedSparseJournalV3, GatedJournalErrorV3> {
        GatedSparseJournalV3::open_anchored(self.reopen(), config(), scope(), 16, anchor)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn committed_fixture() -> (
    Fixture,
    JournalAnchor,
    JournalAnchor,
    GatedSparseSignalReceiptV3,
) {
    let fixture = Fixture::new();
    let mut journal = checked(GatedSparseJournalV3::open(
        fixture.create(),
        config(),
        scope(),
        16,
    ));
    let first = checked(journal.commit(Digest32::ZERO, &tick(1)));
    let second = checked(journal.commit(first.checkpoint_after, &tick(2)));
    let third = checked(journal.commit(second.checkpoint_after, &tick(3)));
    let ack2 = JournalAnchor {
        sequence: 2,
        checkpoint_digest: second.checkpoint_after,
    };
    let ack3 = checked(journal.current_anchor()).expect("three committed ticks");
    assert_eq!(ack3.sequence, 3);
    drop(journal);
    (fixture, ack2, ack3, third)
}

#[test]
fn exact_recovery_and_old_retry_preserve_committed_bytes() {
    let (fixture, ack2, ack3, third) = committed_fixture();
    let before = checked(fs::read(&fixture.file));
    let mut journal = checked(fixture.open_anchored(ack2));
    assert_eq!(checked(journal.current_anchor()), Some(ack3));
    assert!(checked(journal.contains_anchor(ack2)));
    assert_eq!(
        checked(journal.commit(ack2.checkpoint_digest, &tick(3))),
        third
    );
    assert_eq!(
        checked(journal.current()).unwrap().digest(),
        ack3.checkpoint_digest
    );
    drop(journal);
    assert_eq!(checked(fs::read(&fixture.file)), before);
}

#[test]
fn loss_of_acknowledged_prefix_or_empty_replacement_is_rejected() {
    let (fixture, _, ack3, _) = committed_fixture();
    let bytes = checked(fs::read(&fixture.file));
    let first_frame = frame_length(&config());
    checked(fs::write(
        &fixture.file,
        &bytes[..HEADER_BYTES + first_frame * 2],
    ));
    assert_eq!(
        fixture.open_anchored(ack3).err(),
        Some(GatedJournalErrorV3::AcknowledgedHistoryMissing)
    );
    assert_eq!(
        checked(fs::read(&fixture.file)).as_slice(),
        &bytes[..HEADER_BYTES + first_frame * 2]
    );
    checked(fs::write(&fixture.file, b""));
    assert_eq!(
        fixture.open_anchored(ack3).err(),
        Some(GatedJournalErrorV3::AcknowledgedHistoryMissing)
    );
}

#[test]
fn corrupt_complete_frames_fail_without_truncation() {
    let (fixture, _, ack3, _) = committed_fixture();
    let mut bytes = checked(fs::read(&fixture.file));
    bytes[HEADER_BYTES + 15] ^= 1;
    checked(fs::write(&fixture.file, &bytes));
    assert_eq!(
        fixture.open_anchored(ack3).err(),
        Some(GatedJournalErrorV3::Corrupt)
    );
    assert_eq!(checked(fs::read(&fixture.file)), bytes);
}

#[test]
fn incomplete_unacknowledged_tail_is_repaired_after_valid_anchor() {
    let (fixture, _, ack3, _) = committed_fixture();
    let before = checked(fs::read(&fixture.file));
    let mut full = before.clone();
    full.extend_from_slice(&[0x12; 40]);
    checked(fs::write(&fixture.file, full));
    let journal = checked(fixture.open_anchored(ack3));
    assert_eq!(checked(journal.current_anchor()), Some(ack3));
    drop(journal);
    assert_eq!(checked(fs::read(&fixture.file)), before);
}

#[test]
fn config_generation_drift_and_v1_header_are_rejected() {
    let (fixture, _, anchor, _) = committed_fixture();
    // Nonempty history without a separately held witness MUST be fenced
    // before config/header validation, rather than silently reopened.
    assert_eq!(
        GatedSparseJournalV3::open(fixture.reopen(), config(), scope(), 16).err(),
        Some(GatedJournalErrorV3::ExistingJournalRequiresAnchor)
    );
    let mut changed = config();
    changed.gates[0].bias_q24 += 1;
    assert_eq!(
        GatedSparseJournalV3::open_anchored(fixture.reopen(), changed, scope(), 16, anchor).err(),
        Some(GatedJournalErrorV3::Corrupt)
    );
    changed = config();
    changed.base.generation = checked(Generation::new(32));
    assert_eq!(
        GatedSparseJournalV3::open_anchored(fixture.reopen(), changed, scope(), 16, anchor).err(),
        Some(GatedJournalErrorV3::Corrupt)
    );
    let old = checked(fs::read(&fixture.file));
    assert_eq!(&old[..8], MAGIC);
    checked(fs::write(&fixture.file, b"HPTNSJ01"));
    assert_eq!(
        GatedSparseJournalV3::open_anchored(fixture.reopen(), config(), scope(), 16, anchor).err(),
        Some(GatedJournalErrorV3::Corrupt)
    );
}

#[test]
fn conflicting_retries_and_missing_sequences_cannot_write() {
    let fixture = Fixture::new();
    let mut journal = checked(GatedSparseJournalV3::open(
        fixture.create(),
        config(),
        scope(),
        16,
    ));
    let first = checked(journal.commit(Digest32::ZERO, &tick(1)));
    let before = checked(fs::read(&fixture.file));
    let mut altered = tick(1);
    altered.temporal_drive_q24[0] = -Q;
    assert_eq!(
        journal.commit(Digest32::ZERO, &altered).err(),
        Some(GatedJournalErrorV3::Conflict)
    );
    assert_eq!(
        journal.commit(first.checkpoint_after, &tick(3)).err(),
        Some(GatedJournalErrorV3::Mechanism(
            GatedSparseErrorV3::Mechanism(crate::population_v2::PopulationSparseError::Sequence)
        ))
    );
    assert_eq!(checked(fs::read(&fixture.file)), before);
}

#[test]
fn external_witness_is_required_to_detect_full_valid_suffix_loss() {
    let (fixture, ack2, ack3, _) = committed_fixture();
    let len = checked(fs::metadata(&fixture.file)).len();
    let f = fixture.reopen();
    checked(f.set_len(len - frame_length(&config()) as u64));
    drop(f);
    assert_eq!(
        GatedSparseJournalV3::open(fixture.reopen(), config(), scope(), 16).err(),
        Some(GatedJournalErrorV3::ExistingJournalRequiresAnchor)
    );
    let weaker = checked(fixture.open_anchored(ack2));
    assert_eq!(checked(weaker.current_anchor()), Some(ack2));
    drop(weaker);
    assert_eq!(
        fixture.open_anchored(ack3).err(),
        Some(GatedJournalErrorV3::AcknowledgedHistoryMissing)
    );
}

#[test]
fn rejects_external_scope_and_bad_capacity_without_writes() {
    let fixture = Fixture::new();
    let mut journal = checked(GatedSparseJournalV3::open(
        fixture.create(),
        config(),
        scope(),
        1,
    ));
    let first = checked(journal.commit(Digest32::ZERO, &tick(1)));
    assert_eq!(
        journal.commit(first.checkpoint_after, &tick(2)).err(),
        Some(GatedJournalErrorV3::Capacity)
    );
    let mut wrong = tick(2);
    wrong.scope_digest = Digest32::of_bytes(b"cross-scope");
    assert_eq!(
        journal.commit(first.checkpoint_after, &wrong).err(),
        Some(GatedJournalErrorV3::ContextMismatch)
    );
    assert_eq!(checked(journal.remaining_capacity()), 0);
    drop(journal);
    assert_eq!(
        GatedSparseJournalV3::open(fixture.reopen(), config(), scope(), 0).err(),
        Some(GatedJournalErrorV3::InvalidLimit)
    );
}

#[test]
fn bounded_digest_only_history_reconstructs_exact_old_receipt_after_later_ticks() {
    let fixture = Fixture::new();
    let mut journal = checked(GatedSparseJournalV3::open(
        fixture.create(),
        config(),
        scope(),
        1_024,
    ));
    let mut predecessor = Digest32::ZERO;
    let mut original_receipt = None;
    for sequence in 1..=256 {
        let receipt = checked(journal.commit(predecessor, &tick(sequence)));
        if sequence == 2 {
            original_receipt = Some(receipt.clone());
        }
        predecessor = receipt.checkpoint_after;
    }
    assert_eq!(checked(journal.remaining_capacity()), 1_024 - 256);
    assert_eq!(
        checked(journal.retained_history_digest_bytes()),
        256 * std::mem::size_of::<Digest32>()
    );
    let before = checked(fs::read(&fixture.file));
    let earliest = checked(journal.commit(Digest32::ZERO, &tick(1)));
    let second = checked(journal.commit(earliest.checkpoint_after, &tick(2)));
    assert_eq!(Some(second), original_receipt);
    assert_eq!(
        checked(journal.current_anchor())
            .expect("latest anchor")
            .checkpoint_digest,
        predecessor
    );
    assert_eq!(checked(fs::read(&fixture.file)), before);
    drop(journal);
}

#[test]
fn historical_idempotent_read_refuses_corrupted_frame_and_poisoned_owner() {
    let (fixture, _ack2, ack3, _) = committed_fixture();
    let mut journal = checked(fixture.open_anchored(ack3));
    let mut bytes = checked(fs::read(&fixture.file));
    bytes[HEADER_BYTES + 16] ^= 1;
    checked(fs::write(&fixture.file, &bytes));
    assert_eq!(
        journal.commit(Digest32::ZERO, &tick(1)).err(),
        Some(GatedJournalErrorV3::Corrupt),
    );
    assert_eq!(
        journal.retained_history_digest_bytes().err(),
        Some(GatedJournalErrorV3::Poisoned),
    );
    assert_eq!(
        journal.commit(ack3.checkpoint_digest, &tick(4)).err(),
        Some(GatedJournalErrorV3::Poisoned),
    );
    drop(journal);
    assert_eq!(
        fixture.open_anchored(ack3).err(),
        Some(GatedJournalErrorV3::Corrupt),
    );
}

#[test]
fn v3_child_commit_then_hard_exit() {
    // Helper invoked by the dedicated parent recovery test. In ordinary
    // test enumeration it does nothing, so it cannot commit to production.
    let Ok(path) = std::env::var("HEPTA_V3_SHADOW_JOURNAL_CHILD") else {
        return;
    };
    let file = checked(OpenOptions::new().read(true).write(true).open(path));
    let anchor = JournalAnchor {
        sequence: 1,
        checkpoint_digest: {
            // Independent host witness is given as 64 lowercase hex in the
            // child environment; never reconstructed from journal contents.
            let raw = std::env::var("HEPTA_V3_SHADOW_JOURNAL_ANCHOR")
                .expect("child needs an independently supplied anchor");
            raw.parse::<Digest32>()
                .expect("valid independently supplied anchor")
        },
    };
    let mut journal = checked(GatedSparseJournalV3::open_anchored(
        file,
        config(),
        scope(),
        16,
        anchor,
    ));
    let second = checked(journal.commit(anchor.checkpoint_digest, &tick(2)));
    assert_eq!(second.checkpoint_before, anchor.checkpoint_digest);
    assert_eq!(checked(journal.current_anchor()).unwrap().sequence, 2);
    // Deliberately bypass Rust destructors. The completed sync_data is the
    // durability boundary; this is NOT physical power loss certification.
    std::process::exit(0);
}

#[test]
fn independent_anchor_recovers_synced_child_commit_after_process_exit() {
    let fixture = Fixture::new();
    let mut journal = checked(GatedSparseJournalV3::open(
        fixture.create(),
        config(),
        scope(),
        16,
    ));
    let first = checked(journal.commit(Digest32::ZERO, &tick(1)));
    let anchor = checked(journal.current_anchor()).expect("first committed tick");
    assert_eq!(anchor.checkpoint_digest, first.checkpoint_after);
    drop(journal);

    let output = checked(
        std::process::Command::new(checked(std::env::current_exe()))
            .arg("--nocapture")
            .arg("v3_child_commit_then_hard_exit")
            .env("HEPTA_V3_SHADOW_JOURNAL_CHILD", &fixture.file)
            .env(
                "HEPTA_V3_SHADOW_JOURNAL_ANCHOR",
                anchor.checkpoint_digest.to_string(),
            )
            .output(),
    );
    assert!(
        output.status.success(),
        "child failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let reopened = checked(fixture.open_anchored(anchor));
    let recovered = checked(reopened.current_anchor()).expect("recovered second tick");
    assert_eq!(recovered.sequence, 2);
    assert_ne!(recovered.checkpoint_digest, anchor.checkpoint_digest);
    assert!(checked(reopened.contains_anchor(anchor)));
    drop(reopened);
    // Existing nonempty V3 history still cannot reopen unanchored.
    assert_eq!(
        GatedSparseJournalV3::open(fixture.reopen(), config(), scope(), 16).err(),
        Some(GatedJournalErrorV3::ExistingJournalRequiresAnchor)
    );
}
