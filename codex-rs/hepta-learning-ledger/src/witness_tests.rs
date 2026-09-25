use super::*;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn binding() -> Digest32 {
    digest("production-ledger-witness-binding")
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-learning-witness-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root).unwrap();
        File::create(root.join("witness")).unwrap();
        Self { root }
    }

    fn file(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("witness"))
            .unwrap()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn witness_advances_monotonically_and_recovers_exact_frontier() {
    let fixture = Fixture::new();
    let mut store = LedgerWitnessStore::create(fixture.file(), binding()).unwrap();
    let empty = LedgerWitnessFrontier::empty();
    let one = LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: 1,
            chain_digest: digest("chain-1"),
        },
        segment: None,
        sealed: false,
    };
    assert_eq!(store.advance(empty, one).unwrap(), one);
    assert_eq!(store.frontier().unwrap(), one);
    drop(store);

    let mut recovered = LedgerWitnessStore::recover(fixture.file(), binding()).unwrap();
    assert_eq!(recovered.frontier().unwrap(), one);
    let two = LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: 2,
            chain_digest: digest("chain-2"),
        },
        segment: None,
        sealed: false,
    };
    assert_eq!(recovered.advance(one, two).unwrap(), two);
}

#[test]
fn witness_rejects_skips_and_binding_mismatch() {
    let fixture = Fixture::new();
    let mut store = LedgerWitnessStore::create(fixture.file(), binding()).unwrap();
    let skipped = LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: 2,
            chain_digest: digest("chain-2"),
        },
        segment: None,
        sealed: false,
    };
    assert_eq!(
        store.advance(LedgerWitnessFrontier::empty(), skipped),
        Err(DurableLedgerError::InvalidAnchor)
    );
    drop(store);
    assert!(matches!(
        LedgerWitnessStore::recover(fixture.file(), digest("other-binding")),
        Err(DurableLedgerError::BindingMismatch)
    ));
}
