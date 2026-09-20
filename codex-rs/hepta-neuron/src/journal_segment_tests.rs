use super::*;

use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

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

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-segments-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        for name in ["root", "successor"] {
            checked(
                OpenOptions::new()
                    .write(true)
                    .create_new(true)
                    .open(root.join(name)),
            );
        }
        Self { root }
    }

    fn file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(self.root.join(name)),
        )
    }

    fn bytes(&self, name: &str) -> Vec<u8> {
        checked(fs::read(self.root.join(name)))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn config() -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"model"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
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
        scope_digest: Digest32::of_bytes(b"segment-subject"),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

fn tick(sequence: u64) -> SparseTick {
    SparseTick {
        scope_digest: scope().scope_digest,
        objective_digest: scope().objective_digest,
        ndu_digest: Digest32::of_bytes(b"ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(format!("feature-{sequence}").as_bytes()),
        sequence,
        monotonic_micros: sequence * 1_000,
        drive_q24: vec![Q, Q / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    }
}

#[test]
fn successor_segment_preserves_state_and_allows_exact_retry() {
    let fixture = Fixture::new();
    let mut root = checked(SparseJournal::open(
        fixture.file("root"),
        config(),
        scope(),
        /*max_records*/ 2,
    ));
    let first = checked(root.commit(Digest32::ZERO, &tick(1)));
    let second = checked(root.commit(first.checkpoint_after, &tick(2)));
    assert_eq!(checked(root.remaining_capacity()), 0);

    let mut successor = checked(root.start_successor(fixture.file("successor"), /*max_records*/ 2));
    let third = checked(successor.commit(second.checkpoint_after, &tick(3)));
    let fourth = checked(successor.commit(third.checkpoint_after, &tick(4)));
    let before = fixture.bytes("successor");
    assert_eq!(
        checked(successor.commit(second.checkpoint_after, &tick(3))),
        third
    );
    assert_eq!(fixture.bytes("successor"), before);
    assert_eq!(
        successor.commit(fourth.checkpoint_after, &tick(5)),
        Err(JournalError::Capacity)
    );
}

#[test]
fn successor_reopen_requires_exact_predecessor_seed_and_acknowledged_suffix() {
    let fixture = Fixture::new();
    let final_anchor = {
        let mut root = checked(SparseJournal::open(
            fixture.file("root"),
            config(),
            scope(),
            /*max_records*/ 2,
        ));
        let first = checked(root.commit(Digest32::ZERO, &tick(1)));
        let second = checked(root.commit(first.checkpoint_after, &tick(2)));
        let mut successor =
            checked(root.start_successor(fixture.file("successor"), /*max_records*/ 2));
        let third = checked(successor.commit(second.checkpoint_after, &tick(3)));
        let fourth = checked(successor.commit(third.checkpoint_after, &tick(4)));
        JournalAnchor {
            sequence: 4,
            checkpoint_digest: fourth.checkpoint_after,
        }
    };

    let root = checked(SparseJournal::open(
        fixture.file("root"),
        config(),
        scope(),
        /*max_records*/ 2,
    ));
    let recovered = checked(root.recover_successor(
        fixture.file("successor"),
        /*max_records*/ 2,
        final_anchor,
    ));
    assert_eq!(
        checked(recovered.current()).map(SparseCheckpoint::digest),
        Some(final_anchor.checkpoint_digest)
    );

    let mut wrong_config = config();
    wrong_config.threshold_rate_q24 += 1;
    let seed = checked(root.current()).expect("root seed");
    assert_eq!(
        SparseJournal::open_successor(
            fixture.file("successor"),
            wrong_config,
            scope(),
            /*max_records*/ 2,
            seed,
        )
        .err(),
        Some(JournalError::ContextMismatch)
    );
}

#[test]
fn missing_acknowledged_successor_frame_is_rejected_without_repair() {
    let fixture = Fixture::new();
    let anchor = {
        let mut root = checked(SparseJournal::open(
            fixture.file("root"),
            config(),
            scope(),
            /*max_records*/ 2,
        ));
        let first = checked(root.commit(Digest32::ZERO, &tick(1)));
        let second = checked(root.commit(first.checkpoint_after, &tick(2)));
        let mut successor =
            checked(root.start_successor(fixture.file("successor"), /*max_records*/ 2));
        let third = checked(successor.commit(second.checkpoint_after, &tick(3)));
        let fourth = checked(successor.commit(third.checkpoint_after, &tick(4)));
        JournalAnchor {
            sequence: 4,
            checkpoint_digest: fourth.checkpoint_after,
        }
    };

    let full = fixture.bytes("successor");
    let frame_len = 304 + 16 * config().width;
    let truncated = full[..SUCCESSOR_HEADER + frame_len].to_vec();
    checked(fs::write(fixture.root.join("successor"), &truncated));

    let root = checked(SparseJournal::open(
        fixture.file("root"),
        config(),
        scope(),
        /*max_records*/ 2,
    ));
    assert_eq!(
        root.recover_successor(fixture.file("successor"), /*max_records*/ 2, anchor,)
            .err(),
        Some(JournalError::AcknowledgedHistoryMissing)
    );
    assert_eq!(fixture.bytes("successor"), truncated);
}
