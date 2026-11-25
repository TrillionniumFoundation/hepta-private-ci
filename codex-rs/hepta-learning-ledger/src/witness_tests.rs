use super::*;
use pretty_assertions::assert_eq;
use std::cell::Cell;
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

fn recovered_frontier() -> LedgerWitnessFrontier {
    LedgerWitnessFrontier {
        anchor: LedgerAnchor {
            sequence: 1,
            chain_digest: digest("complete-frame-before-sync"),
        },
        segment: None,
        sealed: false,
    }
}

fn fixture_with_complete_unsynced_frame() -> Fixture {
    let fixture = Fixture::new();
    drop(LedgerWitnessStore::create(fixture.file(), binding()).unwrap());
    let status = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "witness::tests::complete_unsynced_frame_child",
            "--ignored",
            "--nocapture",
        ])
        .env(
            "HEPTA_TEST_WITNESS_UNSYNCED_PATH",
            fixture.root.join("witness"),
        )
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(73));
    fixture
}

#[test]
#[ignore = "launched only by the witness recovery process-exit regression"]
fn complete_unsynced_frame_child() {
    let path = std::env::var_os("HEPTA_TEST_WITNESS_UNSYNCED_PATH").unwrap();
    let mut file = OpenOptions::new().append(true).open(path).unwrap();
    file.write_all(&encode_frontier(recovered_frontier()).unwrap())
        .unwrap();
    // Deliberately exit after a complete write without requesting a durability
    // barrier. This models process interruption, not a physical power failure.
    std::process::exit(/*code*/ 73);
}

#[test]
fn complete_unsynced_frame_is_synced_before_recovery_publishes_frontier() {
    let fixture = fixture_with_complete_unsynced_frame();
    let before = fs::read(fixture.root.join("witness")).unwrap();
    let sync_calls = Cell::new(/*value*/ 0);
    let recovered = LedgerWitnessStore::recover_with_sync(fixture.file(), binding(), |file| {
        sync_calls.set(sync_calls.get() + 1);
        assert_eq!(file.metadata().unwrap().len(), (HEADER + FRAME) as u64);
        file.sync_all()
    })
    .unwrap();
    assert_eq!(sync_calls.get(), 1);
    assert_eq!(recovered.frontier().unwrap(), recovered_frontier());
    drop(recovered);
    assert_eq!(fs::read(fixture.root.join("witness")).unwrap(), before);
}

#[test]
fn complete_unsynced_frame_sync_failure_refuses_recovery_and_releases_lock() {
    let fixture = fixture_with_complete_unsynced_frame();
    let before = fs::read(fixture.root.join("witness")).unwrap();
    let sync_calls = Cell::new(/*value*/ 0);
    let result = LedgerWitnessStore::recover_with_sync(fixture.file(), binding(), |file| {
        sync_calls.set(sync_calls.get() + 1);
        assert_eq!(file.metadata().unwrap().len(), (HEADER + FRAME) as u64);
        Err(io::Error::other("injected recovery sync failure"))
    });
    assert_eq!(sync_calls.get(), 1);
    assert!(matches!(result, Err(DurableLedgerError::Indeterminate)));
    assert_eq!(fs::read(fixture.root.join("witness")).unwrap(), before);

    // No witness owner escaped the failed barrier. A new exclusive recovery
    // can perform the real sync and only then expose the exact frontier.
    let recovered = LedgerWitnessStore::recover(fixture.file(), binding()).unwrap();
    assert_eq!(recovered.frontier().unwrap(), recovered_frontier());
}

#[test]
fn incomplete_tail_is_truncated_before_recovery_sync_failure_is_reported() {
    let fixture = fixture_with_complete_unsynced_frame();
    let expected = fs::read(fixture.root.join("witness")).unwrap();
    let mut file = OpenOptions::new()
        .append(true)
        .open(fixture.root.join("witness"))
        .unwrap();
    file.write_all(&[0; 11]).unwrap();
    drop(file);
    let sync_calls = Cell::new(/*value*/ 0);
    let result = LedgerWitnessStore::recover_with_sync(fixture.file(), binding(), |file| {
        sync_calls.set(sync_calls.get() + 1);
        assert_eq!(file.metadata().unwrap().len(), (HEADER + FRAME) as u64);
        Err(io::Error::other("injected repaired-tail sync failure"))
    });
    assert_eq!(sync_calls.get(), 1);
    assert!(matches!(result, Err(DurableLedgerError::Indeterminate)));
    assert_eq!(fs::read(fixture.root.join("witness")).unwrap(), expected);
    let recovered = LedgerWitnessStore::recover(fixture.file(), binding()).unwrap();
    assert_eq!(recovered.frontier().unwrap(), recovered_frontier());
}

#[test]
fn complete_corruption_is_rejected_before_any_recovery_sync_or_truncation() {
    let fixture = Fixture::new();
    drop(LedgerWitnessStore::create(fixture.file(), binding()).unwrap());
    let mut corrupt = encode_frontier(recovered_frontier()).unwrap();
    corrupt[FRAME - 1] ^= 1;
    let mut file = OpenOptions::new()
        .append(true)
        .open(fixture.root.join("witness"))
        .unwrap();
    file.write_all(&corrupt).unwrap();
    drop(file);
    let before = fs::read(fixture.root.join("witness")).unwrap();
    let sync_calls = Cell::new(/*value*/ 0);
    let result = LedgerWitnessStore::recover_with_sync(fixture.file(), binding(), |_| {
        sync_calls.set(sync_calls.get() + 1);
        Ok(())
    });
    assert!(matches!(result, Err(DurableLedgerError::Corrupt)));
    assert_eq!(sync_calls.get(), 0);
    assert_eq!(fs::read(fixture.root.join("witness")).unwrap(), before);
}
