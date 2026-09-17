use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn anchor(sequence: u64) -> LedgerAnchor {
    LedgerAnchor {
        sequence,
        chain_digest: digest(&format!("chain-{sequence}")),
    }
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
        fs::create_dir(&root).expect("create witness fixture");
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(root.join("witness"))
            .expect("create witness file");
        Self { root }
    }

    fn file(&self) -> File {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("witness"))
            .expect("open witness")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn witness_is_append_only_idempotent_and_recoverable() {
    let fixture = Fixture::new();
    let binding = digest("witness-binding");
    let mut witness =
        FileLearningWitnessStore::create(fixture.file(), binding).expect("create witness");
    let first = witness.persist(anchor(1)).expect("persist first");
    assert_eq!(first.disposition, WitnessDisposition::Appended);
    let replay = witness.persist(anchor(1)).expect("replay first");
    assert_eq!(replay.disposition, WitnessDisposition::IdempotentReplay);
    let second = witness.persist(anchor(2)).expect("persist second");
    assert_eq!(second.anchor.sequence, 2);
    let expected_digest = second.witness_digest;
    drop(witness);

    let recovered =
        FileLearningWitnessStore::recover(fixture.file(), binding).expect("recover witness");
    assert_eq!(recovered.current_anchor(), anchor(2));
    assert_eq!(recovered.witness_digest(), expected_digest);
}

#[test]
fn witness_rejects_gap_regression_and_binding_drift() {
    let fixture = Fixture::new();
    let binding = digest("witness-binding");
    let mut witness =
        FileLearningWitnessStore::create(fixture.file(), binding).expect("create witness");
    assert_eq!(
        witness.persist(anchor(2)),
        Err(LearningWitnessError::Gap)
    );
    witness.persist(anchor(1)).expect("persist first");
    assert_eq!(
        witness.persist(LedgerAnchor {
            sequence: 1,
            chain_digest: digest("other-chain"),
        }),
        Err(LearningWitnessError::Regression)
    );
    drop(witness);
    assert!(matches!(
        FileLearningWitnessStore::recover(fixture.file(), digest("wrong-binding")),
        Err(LearningWitnessError::BindingMismatch)
    ));
}

#[test]
fn incomplete_unacknowledged_witness_tail_is_trimmed() {
    let fixture = Fixture::new();
    let binding = digest("witness-binding");
    let mut witness =
        FileLearningWitnessStore::create(fixture.file(), binding).expect("create witness");
    witness.persist(anchor(1)).expect("persist first");
    drop(witness);

    let mut file = fixture.file();
    file.seek(SeekFrom::End(0)).expect("seek witness tail");
    file.write_all(b"partial").expect("write partial witness");
    file.sync_all().expect("sync partial witness");
    drop(file);

    let recovered =
        FileLearningWitnessStore::recover(fixture.file(), binding).expect("recover witness");
    assert_eq!(recovered.current_anchor(), anchor(1));
    assert_eq!(
        recovered.file.metadata().expect("metadata").len(),
        (HEADER + FRAME) as u64
    );
}
