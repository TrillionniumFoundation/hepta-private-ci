use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

const Q: i64 = 1 << 24;
static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"model"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(/*value*/ 1)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: Digest32::of_bytes(b"anchor-run"),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

fn tick(sequence: u64) -> SparseTick {
    SparseTick {
        scope_digest: scope().scope_digest,
        objective_digest: scope().objective_digest,
        ndu_digest: Digest32::of_bytes(b"ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(b"features"),
        sequence,
        monotonic_micros: sequence * 1000,
        drive_q24: vec![Q, Q / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    }
}

struct Fixture {
    root: PathBuf,
    first: SparseSignalReceipt,
    second: SparseSignalReceipt,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root =
            std::env::temp_dir().join(format!("hepta-anchor-{}-{serial}", std::process::id()));
        checked(fs::create_dir(&root));
        let file = checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(root.join("journal")),
        );
        let mut journal = checked(SparseJournal::open(
            file,
            config(),
            scope(),
            /*max_records*/ 16,
        ));
        let first = checked(journal.commit(Digest32::ZERO, &tick(1)));
        let second = checked(journal.commit(first.checkpoint_after, &tick(2)));
        Self {
            root,
            first,
            second,
        }
    }

    fn path(&self) -> PathBuf {
        self.root.join("journal")
    }

    fn open(&self, anchor: JournalAnchor) -> Result<SparseJournal, JournalError> {
        let file = checked(OpenOptions::new().read(true).write(true).open(self.path()));
        SparseJournal::open_anchored(file, config(), scope(), /*max_records*/ 16, anchor)
    }

    fn anchor(&self) -> JournalAnchor {
        JournalAnchor {
            sequence: 2,
            checkpoint_digest: self.second.checkpoint_after,
        }
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn anchored_reopen_preserves_the_exact_receipt_and_all_bytes() {
    let fixture = Fixture::new();
    let before = checked(fs::read(fixture.path()));
    let mut reopened = checked(fixture.open(fixture.anchor()));
    assert_eq!(
        checked(reopened.commit(fixture.first.checkpoint_after, &tick(2))),
        fixture.second
    );
    drop(reopened);
    assert_eq!(checked(fs::read(fixture.path())), before);
}

#[test]
fn lost_complete_acknowledged_frame_is_rejected_without_repair() {
    let fixture = Fixture::new();
    let full = checked(fs::read(fixture.path()));
    let prefix = &full[..HEADER + 304 + 16 * config().width];
    checked(fs::write(fixture.path(), prefix));
    assert_eq!(
        fixture.open(fixture.anchor()).err(),
        Some(JournalError::AcknowledgedHistoryMissing)
    );
    assert_eq!(checked(fs::read(fixture.path())), prefix);
}

#[test]
fn empty_replacement_is_not_initialized_when_history_was_acknowledged() {
    let fixture = Fixture::new();
    checked(fs::write(fixture.path(), b""));
    assert_eq!(
        fixture.open(fixture.anchor()).err(),
        Some(JournalError::AcknowledgedHistoryMissing)
    );
    assert_eq!(checked(fs::metadata(fixture.path())).len(), 0);
}

#[test]
fn every_partial_acknowledged_frame_is_preserved_as_failure_evidence() {
    let fixture = Fixture::new();
    let full = checked(fs::read(fixture.path()));
    let frame = 304 + 16 * config().width;
    for tail in 1..frame {
        let damaged = &full[..HEADER + frame + tail];
        checked(fs::write(fixture.path(), damaged));
        assert_eq!(
            fixture.open(fixture.anchor()).err(),
            Some(JournalError::AcknowledgedHistoryMissing)
        );
        assert_eq!(checked(fs::read(fixture.path())), damaged);
    }
}

#[test]
fn wrong_anchor_does_not_truncate_an_unacknowledged_tail() {
    let fixture = Fixture::new();
    let mut bytes = checked(fs::read(fixture.path()));
    bytes.extend_from_slice(b"incomplete-next-frame");
    checked(fs::write(fixture.path(), &bytes));
    let mut wrong = fixture.anchor();
    wrong.checkpoint_digest = Digest32::of_bytes(b"different-acknowledged-history");
    assert_ne!(wrong, fixture.anchor());
    assert_eq!(
        fixture.open(wrong).err(),
        Some(JournalError::AnchorMismatch)
    );
    assert_eq!(checked(fs::read(fixture.path())), bytes);
}

#[test]
fn earlier_anchor_accepts_later_complete_frames_and_repairs_only_the_tail() {
    let fixture = Fixture::new();
    let complete = checked(fs::read(fixture.path()));
    let mut interrupted = complete.clone();
    interrupted.extend_from_slice(b"partial-third-frame");
    checked(fs::write(fixture.path(), interrupted));
    let anchor = JournalAnchor {
        sequence: 1,
        checkpoint_digest: fixture.first.checkpoint_after,
    };
    let mut recovered = checked(fixture.open(anchor));
    assert_eq!(
        checked(recovered.current()).map(SparseCheckpoint::digest),
        Some(fixture.second.checkpoint_after)
    );
    assert_eq!(
        checked(recovered.commit(fixture.first.checkpoint_after, &tick(2))),
        fixture.second
    );
    drop(recovered);
    assert_eq!(checked(fs::read(fixture.path())), complete);
}

#[test]
fn fully_rehashed_alternate_history_cannot_satisfy_the_trusted_anchor() {
    let fixture = Fixture::new();
    let full = checked(fs::read(fixture.path()));
    let mut alternate = full[..HEADER].to_vec();
    let mut changed = tick(1);
    changed.drive_q24[0] -= 1;
    let (state, first) = checked(sparse_tick(&config(), &changed, /*previous*/ None));
    let (_, second) = checked(sparse_tick(&config(), &tick(2), Some(&state)));
    alternate.extend_from_slice(&encode_frame(&changed, &first));
    alternate.extend_from_slice(&encode_frame(&tick(2), &second));
    assert_ne!(second.checkpoint_after, fixture.second.checkpoint_after);
    checked(fs::write(fixture.path(), &alternate));
    assert_eq!(
        fixture.open(fixture.anchor()).err(),
        Some(JournalError::AnchorMismatch)
    );
    assert_eq!(checked(fs::read(fixture.path())), alternate);
}

#[test]
fn malformed_anchor_rejects_before_file_mutation() {
    let fixture = Fixture::new();
    let original = checked(fs::read(fixture.path()));
    for sequence in [0, 17, u64::MAX] {
        let anchor = JournalAnchor {
            sequence,
            ..fixture.anchor()
        };
        assert_eq!(
            fixture.open(anchor).err(),
            Some(JournalError::InvalidAnchor)
        );
    }
    let anchor = JournalAnchor {
        checkpoint_digest: Digest32::ZERO,
        ..fixture.anchor()
    };
    assert_eq!(
        fixture.open(anchor).err(),
        Some(JournalError::InvalidAnchor)
    );
    assert_eq!(checked(fs::read(fixture.path())), original);
}

#[test]
fn matching_anchor_does_not_hide_corruption_in_a_later_full_frame() {
    let fixture = Fixture::new();
    let mut corrupt = checked(fs::read(fixture.path()));
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    checked(fs::write(fixture.path(), &corrupt));
    let anchor = JournalAnchor {
        sequence: 1,
        checkpoint_digest: fixture.first.checkpoint_after,
    };
    assert_eq!(fixture.open(anchor).err(), Some(JournalError::Corrupt));
    assert_eq!(checked(fs::read(fixture.path())), corrupt);
}
