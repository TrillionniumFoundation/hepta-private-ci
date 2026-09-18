use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"independent-witness-binding")
}

fn anchor(sequence: u64, label: &[u8]) -> LedgerAnchor {
    LedgerAnchor {
        sequence,
        chain_digest: Digest32::of_bytes(label),
    }
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-ledger-witness-{}-{serial}",
            std::process::id()
        ));
        must(fs::create_dir(&root));
        must(
            OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(root.join("witness")),
        );
        Self { root }
    }

    fn file(&self) -> File {
        must(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(self.root.join("witness")),
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn witness_persists_exact_monotonic_frontier_and_reopens() {
    let fixture = Fixture::new();
    let first = anchor(1, b"one");
    let second = anchor(2, b"two");

    {
        let mut store = must(LedgerWitnessStore::create(fixture.file(), binding()));
        assert_eq!(store.latest(), None);
        must(store.persist(first));
        must(store.persist(first));
        must(store.persist(second));
        assert_eq!(store.latest(), Some(second));
    }

    let reopened = must(LedgerWitnessStore::recover(fixture.file(), binding()));
    assert_eq!(reopened.latest(), Some(second));
    assert_eq!(reopened.binding(), binding());
}

#[test]
fn witness_rejects_gap_and_same_sequence_digest_drift() {
    let fixture = Fixture::new();
    let first = anchor(1, b"one");
    let mut store = must(LedgerWitnessStore::create(fixture.file(), binding()));
    must(store.persist(first));

    assert_eq!(
        store.persist(anchor(3, b"three")),
        Err(WitnessStoreError::Gap)
    );
    assert_eq!(
        store.persist(anchor(1, b"changed")),
        Err(WitnessStoreError::Conflict)
    );
}
