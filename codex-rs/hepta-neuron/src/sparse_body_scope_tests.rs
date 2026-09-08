use super::*;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use crate::JournalError;
use crate::JournalScope;
use crate::SparseJournal;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"body-scope-model"),
        normalization_digest: Digest32::of_bytes(b"body-scope-normalization"),
        generation: checked(Generation::new(1)),
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
        scope_digest: Digest32::of_bytes(b"body-scope-run"),
        objective_digest: Digest32::of_bytes(b"body-scope-objective"),
    }
}

fn tick(sequence: u64) -> SparseTick {
    SparseTick {
        scope_digest: scope().scope_digest,
        objective_digest: scope().objective_digest,
        ndu_digest: Digest32::of_bytes(b"body-scope-ndu"),
        body_digest: Digest32::of_bytes(b"body-scope-body"),
        input_digest: Digest32::of_bytes(b"body-scope-input"),
        sequence,
        monotonic_micros: sequence * 1000,
        drive_q24: vec![Q, 0, 0, 0, 0],
        prediction_q24: vec![0; 5],
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-body-scope-{}-{serial}",
            std::process::id()
        ));
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
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
fn successor_rejects_body_scope_drift() {
    let config = config();
    let (previous, _) = checked(sparse_tick(&config, &tick(1), None));
    let mut successor = tick(2);
    successor.body_digest = Digest32::of_bytes(b"different-body");
    assert_eq!(
        sparse_tick(&config, &successor, Some(&previous)),
        Err(SparseError::ScopeDrift)
    );
}

#[test]
fn reopened_checkpoint_retains_body_scope_and_rejects_before_write() {
    let fixture = Fixture::new();
    let first = {
        let mut journal = checked(SparseJournal::open(fixture.file(), config(), scope(), 4));
        checked(journal.commit(Digest32::ZERO, &tick(1)))
    };
    let before = checked(fs::read(fixture.path()));
    let mut reopened = checked(SparseJournal::open(fixture.file(), config(), scope(), 4));
    let mut successor = tick(2);
    successor.body_digest = Digest32::of_bytes(b"different-body-after-reopen");
    assert_eq!(
        reopened.commit(first.checkpoint_after, &successor),
        Err(JournalError::Mechanism(SparseError::ScopeDrift))
    );
    assert_eq!(checked(fs::read(fixture.path())), before);
    assert_eq!(
        checked(reopened.current()).map(SparseCheckpoint::digest),
        Some(first.checkpoint_after)
    );
}
