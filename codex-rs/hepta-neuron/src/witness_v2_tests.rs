use super::*;
use pretty_assertions::assert_eq;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static FIXTURE: AtomicU64 = AtomicU64::new(1);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = FIXTURE.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-witness-v2-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        Self(root)
    }

    fn root(&self) -> PathBuf {
        self.0.join("witness-root")
    }

    fn successor(&self) -> PathBuf {
        self.0.join("witness-successor")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn context(max_records: usize) -> NeuronWitnessContextV2 {
    NeuronWitnessContextV2 {
        generation: checked(Generation::new(2)),
        scope: JournalScope {
            scope_digest: Digest32::of_bytes(b"subject"),
            objective_digest: Digest32::of_bytes(b"objective"),
        },
        key_epoch: 4,
        deletion_epoch: 7,
        max_records,
    }
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: Digest32::of_bytes(format!("checkpoint-{sequence}").as_bytes()),
    }
}

#[test]
fn torn_tail_is_removed_and_acknowledged_frontier_survives() {
    let fixture = Fixture::new();
    {
        let mut witness = checked(FileNeuronWitnessStoreV2::create(
            &fixture.root(),
            context(8),
        ));
        checked(witness.compare_and_swap(None, anchor(1)));
    }
    let stable_length = checked(fs::metadata(fixture.root())).len();
    let mut file = checked(OpenOptions::new().append(true).open(fixture.root()));
    checked(file.write_all(&[1_u8; RECORD_BYTES / 2]));
    checked(file.sync_all());
    drop(file);

    let reopened = checked(FileNeuronWitnessStoreV2::open_existing(
        &fixture.root(),
        context(8),
    ));
    assert_eq!(checked(reopened.current()), Some(anchor(1)));
    assert_eq!(checked(fs::metadata(fixture.root())).len(), stable_length);
}

#[test]
fn complete_corruption_fails_closed() {
    let fixture = Fixture::new();
    {
        let mut witness = checked(FileNeuronWitnessStoreV2::create(
            &fixture.root(),
            context(8),
        ));
        checked(witness.compare_and_swap(None, anchor(1)));
    }
    let mut bytes = checked(fs::read(fixture.root()));
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    checked(fs::write(fixture.root(), bytes));
    assert_eq!(
        FileNeuronWitnessStoreV2::open_existing(&fixture.root(), context(8)).err(),
        Some(WitnessStoreError::Corrupt)
    );
}

#[test]
fn successor_binds_seed_and_monotonic_epochs() {
    let fixture = Fixture::new();
    let seed = {
        let mut root = checked(FileNeuronWitnessStoreV2::create(
            &fixture.root(),
            context(1),
        ));
        checked(root.compare_and_swap(None, anchor(1)));
        match checked(root.current()) {
            Some(value) => value,
            None => panic!("missing root anchor"),
        }
    };
    let mut next_context = context(2);
    next_context.key_epoch += 1;
    next_context.deletion_epoch += 1;
    {
        let mut successor = checked(FileNeuronWitnessStoreV2::create_successor(
            &fixture.successor(),
            next_context.clone(),
            seed,
        ));
        assert_eq!(successor.segment_seed(), Some(seed));
        assert_eq!(successor.key_epoch(), 5);
        assert_eq!(successor.deletion_epoch(), 8);
        checked(successor.compare_and_swap(Some(seed), anchor(2)));
    }
    let reopened = checked(FileNeuronWitnessStoreV2::open_successor(
        &fixture.successor(),
        next_context,
        seed,
    ));
    assert_eq!(checked(reopened.current()), Some(anchor(2)));
}

#[test]
fn context_epoch_rollback_is_rejected() {
    let fixture = Fixture::new();
    {
        let _witness = checked(FileNeuronWitnessStoreV2::create(
            &fixture.root(),
            context(2),
        ));
    }
    let mut rollback = context(2);
    rollback.deletion_epoch -= 1;
    assert_eq!(
        FileNeuronWitnessStoreV2::open_existing(&fixture.root(), rollback).err(),
        Some(WitnessStoreError::ContextMismatch)
    );
}
