use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-witness-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        checked(
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(root.join("witness")),
        );
        Self(root)
    }

    fn path(&self) -> PathBuf {
        self.0.join("witness")
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

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: Digest32::of_bytes(b"subject"),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

fn generation() -> Generation {
    checked(Generation::new(1))
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: Digest32::of_bytes(format!("checkpoint-{sequence}").as_bytes()),
    }
}

#[test]
fn witness_history_survives_reopen_and_fences_stale_cas() {
    let fixture = Fixture::new();
    {
        let mut store = checked(FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        ));
        checked(store.compare_and_swap(None, anchor(1)));
        checked(store.compare_and_swap(Some(anchor(1)), anchor(2)));
        assert_eq!(checked(store.current()), Some(anchor(2)));
    }
    let mut reopened = checked(FileAnchorWitnessStore::open(
        fixture.file(),
        scope(),
        generation(),
        /*max_records*/ 8,
    ));
    assert_eq!(checked(reopened.current()), Some(anchor(2)));
    assert_eq!(
        reopened.compare_and_swap(Some(anchor(1)), anchor(2)),
        Err(WitnessStoreError::Conflict)
    );
    assert_eq!(checked(reopened.current()), Some(anchor(2)));
}

#[test]
fn wrong_scope_generation_and_corruption_never_reinitialize_history() {
    let fixture = Fixture::new();
    {
        let mut store = checked(FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        ));
        checked(store.compare_and_swap(None, anchor(1)));
    }
    let original = checked(fs::read(fixture.path()));
    let mut changed_scope = scope();
    changed_scope.scope_digest = Digest32::of_bytes(b"other-subject");
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            changed_scope,
            generation(),
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::ContextMismatch)
    );
    assert_eq!(checked(fs::read(fixture.path())), original);

    let generation_two = checked(Generation::new(2));
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation_two,
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::ContextMismatch)
    );
    let mut corrupt = original.clone();
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    checked(fs::write(fixture.path(), &corrupt));
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::Corrupt)
    );
    assert_eq!(checked(fs::read(fixture.path())), corrupt);
}

#[test]
fn witness_capacity_and_independent_writer_are_bounded() {
    let fixture = Fixture::new();
    let mut store = checked(FileAnchorWitnessStore::open(
        fixture.file(),
        scope(),
        generation(),
        /*max_records*/ 1,
    ));
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 1,
        )
        .err(),
        Some(WitnessStoreError::Busy)
    );
    checked(store.compare_and_swap(None, anchor(1)));
    assert_eq!(
        store.compare_and_swap(Some(anchor(1)), anchor(2)),
        Err(WitnessStoreError::Capacity)
    );
}
