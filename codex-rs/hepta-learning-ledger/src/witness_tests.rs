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

impl LedgerWitnessStore {
    // This method exists only in the cfg(test) module. It changes no File or
    // lock and cannot replace the real ledger append/sync being exercised.
    pub(crate) fn fail_next_advance_write_for_test(&mut self) {
        self.fail_next_advance_write = true;
    }
}

#[test]
fn complete_unconfirmed_witness_frame_requires_successful_recovery_sync() {
    let fixture = Fixture::new();
    let mut store = LedgerWitnessStore::create(fixture.file(), binding()).unwrap();
    let one = LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: 1,
            chain_digest: digest("unconfirmed-chain"),
        },
        segment: None,
        sealed: false,
    };
    // Model the distinct window where a complete valid frame was written but
    // its sync never completed. No advance acknowledgement has been returned.
    store
        .file
        .write_all(&encode_frontier(one).unwrap())
        .unwrap();
    drop(store);

    let sync_attempted = std::cell::Cell::new(false);
    let recovered = LedgerWitnessStore::recover_with_sync(fixture.file(), binding(), |file| {
        sync_attempted.set(true);
        assert_eq!(file.metadata().unwrap().len(), (HEADER + FRAME) as u64);
        Err(std::io::Error::other("injected recovery sync failure"))
    });
    assert!(sync_attempted.get());
    assert!(matches!(recovered, Err(DurableLedgerError::Indeterminate)));

    // Failed synchronization exposes no owner and releases only its acquired
    // lock. A later real sync recovers the same frame without appending another.
    let recovered = LedgerWitnessStore::recover(fixture.file(), binding()).unwrap();
    assert_eq!(recovered.frontier(), Ok(one));
    assert_eq!(
        recovered.file.metadata().unwrap().len(),
        (HEADER + FRAME) as u64
    );
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
