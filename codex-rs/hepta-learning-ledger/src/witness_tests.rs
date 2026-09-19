use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-anchor-witness-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&root).expect("create fixture");
        OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(root.join("witness"))
            .expect("create witness");
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
fn witness_reopens_exact_acknowledged_frontier_and_rejects_regression() {
    let fixture = Fixture::new();
    let binding = digest("witness-binding");
    let first = LedgerAnchor {
        sequence: 1,
        chain_digest: digest("chain-1"),
    };
    let second = LedgerAnchor {
        sequence: 2,
        chain_digest: digest("chain-2"),
    };

    {
        let mut witness = DurableAnchorWitness::create(fixture.file(), binding).expect("create");
        witness.publish(first).expect("first");
        witness.publish(first).expect("idempotent");
        witness.publish(second).expect("second");
        assert_eq!(witness.current().expect("current"), Some(second));
        assert_eq!(
            witness.publish(first),
            Err(AnchorWitnessError::Regression)
        );
    }

    let recovered = DurableAnchorWitness::recover(fixture.file(), binding).expect("recover");
    assert_eq!(recovered.current().expect("current"), Some(second));
}

#[test]
fn witness_binding_mismatch_fails_closed() {
    let fixture = Fixture::new();
    {
        let _witness =
            DurableAnchorWitness::create(fixture.file(), digest("binding-a")).expect("create");
    }
    assert_eq!(
        DurableAnchorWitness::recover(fixture.file(), digest("binding-b"))
            .err()
            .expect("must reject"),
        AnchorWitnessError::Corrupt
    );
}
