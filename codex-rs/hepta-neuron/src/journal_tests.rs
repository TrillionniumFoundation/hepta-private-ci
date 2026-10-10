use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::AuthorityPosture;
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

// Read through the owning handle: Windows enforces the exclusive byte-range
// lock against independently opened readers too. Preserve the append cursor.
fn journal_bytes(journal: &mut SparseJournal) -> Vec<u8> {
    let position = checked(journal.file.stream_position());
    checked(journal.file.seek(SeekFrom::Start(0)));
    let mut bytes = Vec::new();
    checked(journal.file.read_to_end(&mut bytes));
    checked(journal.file.seek(SeekFrom::Start(position)));
    bytes
}

struct Fixture(PathBuf);
impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root =
            std::env::temp_dir().join(format!("hepta-journal-{}-{serial}", std::process::id()));
        checked(fs::create_dir(&root));
        let fixture = Self(root);
        checked(
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(fixture.path()),
        );
        fixture
    }

    fn path(&self) -> PathBuf {
        self.0.join("checkpoint.journal")
    }

    fn file(&self) -> File {
        checked(OpenOptions::new().read(true).write(true).open(self.path()))
    }

    fn open(&self) -> SparseJournal {
        checked(SparseJournal::open(
            self.file(),
            config(),
            scope(),
            /*max_records*/ 16,
        ))
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn config() -> SparseConfig {
    let generation = 1;
    SparseConfig {
        model_digest: Digest32::of_bytes(b"model"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(generation)),
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
        scope_digest: Digest32::of_bytes(b"run/principal"),
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

#[test]
fn committed_checkpoint_and_receipt_survive_reopen() {
    let fixture = Fixture::new();
    let receipt = {
        let mut journal = fixture.open();
        checked(journal.commit(Digest32::ZERO, &tick(1)))
    };
    // Independent integer/SHA256 oracle for this complete first committed file.
    assert_eq!(
        receipt.checkpoint_after.to_string(),
        "c38b12275a0b6e93855931c7da4d3af3c79ba0d5c8dc74151a3c53210b6677b3"
    );
    let committed_bytes = checked(fs::read(fixture.path()));
    assert_eq!(committed_bytes.len(), 520);
    assert_eq!(
        Digest32::of_bytes(&committed_bytes).to_string(),
        "a4f3f20a33961d665b9aedd9c154e32163bf45d46de15cb64404929e611a3b44"
    );
    let mut reopened = fixture.open();
    assert_eq!(
        checked(reopened.current()).map(SparseCheckpoint::digest),
        Some(receipt.checkpoint_after)
    );
    assert_eq!(checked(reopened.commit(Digest32::ZERO, &tick(1))), receipt);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert!(receipt.requires_calibration);
}

#[test]
fn equal_retry_after_later_commit_does_not_append() {
    let fixture = Fixture::new();
    let mut journal = fixture.open();
    let first = checked(journal.commit(Digest32::ZERO, &tick(1)));
    let second = checked(journal.commit(first.checkpoint_after, &tick(2)));
    let before = journal_bytes(&mut journal);
    assert_eq!(checked(journal.commit(Digest32::ZERO, &tick(1))), first);
    assert_eq!(journal_bytes(&mut journal), before);
    assert_eq!(
        checked(journal.current()).map(SparseCheckpoint::digest),
        Some(second.checkpoint_after)
    );
}

#[test]
fn complete_unacknowledged_frame_is_reconciled_on_reopen() {
    let fixture = Fixture::new();
    drop(fixture.open());
    let (_, expected) = checked(sparse_tick(&config(), &tick(1), /*previous*/ None));
    let mut writer = fixture.file();
    checked(writer.seek(SeekFrom::End(0)));
    checked(writer.write_all(&encode_frame(&tick(1), &expected)));
    // Simulate a writer that exits before acknowledging or syncing a full frame.
    drop(writer);
    let before = checked(fs::read(fixture.path()));
    let mut recovered = fixture.open();
    assert_eq!(
        checked(recovered.commit(Digest32::ZERO, &tick(1))),
        expected
    );
    drop(recovered);
    assert_eq!(checked(fs::read(fixture.path())), before);
}

#[test]
fn changed_retry_and_stale_compare_and_swap_do_not_mutate_file() {
    let fixture = Fixture::new();
    let mut journal = fixture.open();
    checked(journal.commit(Digest32::ZERO, &tick(1)));
    let before = journal_bytes(&mut journal);
    let mut changed = tick(1);
    changed.drive_q24[0] -= 1;
    assert_eq!(
        journal.commit(Digest32::ZERO, &changed),
        Err(JournalError::Conflict)
    );
    assert_eq!(
        journal.commit(Digest32::ZERO, &tick(2)),
        Err(JournalError::Conflict)
    );
    assert_eq!(journal_bytes(&mut journal), before);
}

#[test]
fn independent_writer_is_fenced_and_lock_releases_on_drop() {
    let fixture = Fixture::new();
    let first = fixture.open();
    assert_eq!(
        SparseJournal::open(fixture.file(), config(), scope(), /*max_records*/ 16).err(),
        Some(JournalError::Busy)
    );
    drop(first);
    let second = fixture.open();
    assert_eq!(checked(second.current()), None);
}

#[test]
fn every_partial_frame_boundary_recovers_only_the_predecessor() {
    let fixture = Fixture::new();
    let (first, second) = {
        let mut journal = fixture.open();
        let first = checked(journal.commit(Digest32::ZERO, &tick(1)));
        let second = checked(journal.commit(first.checkpoint_after, &tick(2)));
        (first, second)
    };
    let full = checked(fs::read(fixture.path()));
    let frame = (full.len() - HEADER) / 2;
    for tail in 0..=frame {
        checked(fs::write(fixture.path(), &full[..HEADER + frame + tail]));
        let recovered = fixture.open();
        let expected = if tail == frame {
            second.checkpoint_after
        } else {
            first.checkpoint_after
        };
        assert_eq!(
            checked(recovered.current()).map(SparseCheckpoint::digest),
            Some(expected)
        );
        let count = if tail == frame { 2 } else { 1 };
        assert_eq!(
            checked(fs::metadata(fixture.path())).len(),
            (HEADER + count * frame) as u64
        );
    }
}

#[test]
fn complete_corruption_is_rejected_without_truncation() {
    let fixture = Fixture::new();
    checked(fixture.open().commit(Digest32::ZERO, &tick(1)));
    let original = checked(fs::read(fixture.path()));
    for offset in [0, 12, HEADER - 1, HEADER, original.len() - 1] {
        let mut bytes = original.clone();
        bytes[offset] ^= 1;
        checked(fs::write(fixture.path(), &bytes));
        assert_eq!(
            SparseJournal::open(fixture.file(), config(), scope(), /*max_records*/ 16).err(),
            Some(JournalError::Corrupt)
        );
        assert_eq!(checked(fs::read(fixture.path())), bytes);
    }
}

#[test]
fn valid_frame_checksum_cannot_hide_invalid_checkpoint_chain() {
    let fixture = Fixture::new();
    checked(fixture.open().commit(Digest32::ZERO, &tick(1)));
    let mut bytes = checked(fs::read(fixture.path()));
    let tick_length = 176 + 16 * config().width;
    bytes[HEADER + tick_length] = 1;
    let end = bytes.len() - 32;
    let digest = Digest32::of_bytes(&bytes[HEADER..end]);
    bytes[end..].copy_from_slice(digest.as_array());
    checked(fs::write(fixture.path(), &bytes));
    assert_eq!(
        SparseJournal::open(fixture.file(), config(), scope(), /*max_records*/ 16).err(),
        Some(JournalError::Corrupt)
    );
}

#[test]
fn wrong_generation_and_scope_do_not_reinitialize_journal() {
    let fixture = Fixture::new();
    checked(fixture.open().commit(Digest32::ZERO, &tick(1)));
    let before = checked(fs::read(fixture.path()));
    let mut other = config();
    let generation = 2;
    other.generation = checked(Generation::new(generation));
    assert_eq!(
        SparseJournal::open(fixture.file(), other, scope(), /*max_records*/ 16).err(),
        Some(JournalError::ContextMismatch)
    );
    let mut other = scope();
    other.scope_digest = Digest32::of_bytes(b"other-run");
    assert_eq!(
        SparseJournal::open(fixture.file(), config(), other, /*max_records*/ 16).err(),
        Some(JournalError::ContextMismatch)
    );
    assert_eq!(checked(fs::read(fixture.path())), before);
}

#[test]
fn invalid_tick_and_record_cap_do_not_append() {
    let fixture = Fixture::new();
    let mut journal = checked(SparseJournal::open(
        fixture.file(),
        config(),
        scope(),
        /*max_records*/ 1,
    ));
    let mut bad = tick(1);
    bad.drive_q24.push(0);
    assert_eq!(
        journal.commit(Digest32::ZERO, &bad),
        Err(JournalError::Mechanism(SparseError::InvalidInput))
    );
    let first = checked(journal.commit(Digest32::ZERO, &tick(1)));
    assert_eq!(
        journal.commit(first.checkpoint_after, &tick(2)),
        Err(JournalError::Capacity)
    );
    assert_eq!(checked(journal.commit(Digest32::ZERO, &tick(1))), first);
}

#[test]
fn incomplete_header_and_excess_file_size_are_not_repaired() {
    let fixture = Fixture::new();
    checked(fs::write(fixture.path(), b"HPT"));
    assert_eq!(
        SparseJournal::open(fixture.file(), config(), scope(), /*max_records*/ 16).err(),
        Some(JournalError::Corrupt)
    );
    checked(fs::write(fixture.path(), b""));
    drop(fixture.open());
    checked(fixture.file().set_len(100_000_000));
    assert_eq!(
        SparseJournal::open(fixture.file(), config(), scope(), /*max_records*/ 16).err(),
        Some(JournalError::Capacity)
    );
}

#[cfg(unix)]
#[test]
fn write_error_requires_reopen_and_reconciliation() {
    let fixture = Fixture::new();
    drop(fixture.open());
    let read_only = checked(File::open(fixture.path()));
    let mut journal = checked(SparseJournal::open(
        read_only,
        config(),
        scope(),
        /*max_records*/ 16,
    ));
    assert_eq!(
        journal.commit(Digest32::ZERO, &tick(1)),
        Err(JournalError::Indeterminate)
    );
    assert_eq!(
        journal.commit(Digest32::ZERO, &tick(1)),
        Err(JournalError::Poisoned)
    );
    assert_eq!(journal.current().err(), Some(JournalError::Poisoned));
    drop(journal);
    assert_eq!(checked(fixture.open().current()), None);
}

#[test]
fn process_exit_without_destructors_releases_lock_and_keeps_committed_frame() {
    let fixture = Fixture::new();
    let status = checked(
        std::process::Command::new(checked(std::env::current_exe()))
            .args([
                "--exact",
                "journal::tests::child_process_commit_and_exit",
                "--nocapture",
            ])
            .env("HEPTA_JOURNAL_TEST_CHILD", fixture.path())
            .status(),
    );
    assert!(status.success());
    let mut recovered = fixture.open();
    assert!(checked(recovered.current()).is_some());
    let replay = checked(recovered.commit(Digest32::ZERO, &tick(1)));
    assert_eq!(
        checked(recovered.current()).map(SparseCheckpoint::digest),
        Some(replay.checkpoint_after)
    );
}

#[test]
fn child_process_commit_and_exit() {
    if let Some(path) = std::env::var_os("HEPTA_JOURNAL_TEST_CHILD") {
        let file = checked(OpenOptions::new().read(true).write(true).open(path));
        let mut journal = checked(SparseJournal::open(
            file,
            config(),
            scope(),
            /*max_records*/ 16,
        ));
        checked(journal.commit(Digest32::ZERO, &tick(1)));
        std::process::exit(0);
    }
}

#[cfg(target_os = "linux")]
#[test]
fn owner_drop_releases_lock_with_a_transient_duplicate_alive() {
    let fixture = Fixture::new();
    let mut journal = fixture.open();
    let receipt = checked(journal.commit(Digest32::ZERO, &tick(1)));
    // Simulate the shared open description temporarily retained during fork.
    // This is not permission for an application to share writable handles.
    let transient = checked(journal.file.try_clone());
    assert_eq!(
        SparseJournal::open(fixture.file(), config(), scope(), /*max_records*/ 16).err(),
        Some(JournalError::Busy)
    );
    drop(journal);
    let mut reopened = fixture.open();
    assert_eq!(checked(reopened.commit(Digest32::ZERO, &tick(1))), receipt);
    drop(transient);
    assert_eq!(
        SparseJournal::open(fixture.file(), config(), scope(), /*max_records*/ 16).err(),
        Some(JournalError::Busy)
    );
}

#[cfg(target_os = "linux")]
#[test]
fn failed_recovery_releases_acquired_lock_before_journal_exists() {
    let fixture = Fixture::new();
    let receipt = checked(fixture.open().commit(Digest32::ZERO, &tick(1)));
    let original = checked(fs::read(fixture.path()));
    for bytes in [Vec::new(), b"broken".to_vec(), {
        let mut bad = original;
        bad[0] ^= 1;
        bad
    }] {
        checked(fs::write(fixture.path(), &bytes));
        let file = fixture.file();
        let transient = checked(file.try_clone());
        let anchor = JournalAnchor {
            sequence: 1,
            checkpoint_digest: receipt.checkpoint_after,
        };
        let first =
            SparseJournal::open_anchored(file, config(), scope(), /*max_records*/ 16, anchor).err();
        assert!(matches!(
            first,
            Some(JournalError::AcknowledgedHistoryMissing | JournalError::Corrupt)
        ));
        assert_eq!(
            SparseJournal::open_anchored(
                fixture.file(),
                config(),
                scope(),
                /*max_records*/ 16,
                anchor
            )
            .err(),
            first
        );
        drop(transient);
        assert_eq!(checked(fs::read(fixture.path())), bytes);
    }
}
