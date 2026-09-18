use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;

const Q: i64 = 1 << 24;
static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("fixture failed: {error:?}"))
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-managed-neuron-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        for name in ["journal", "witness"] {
            checked(
                OpenOptions::new()
                    .read(true)
                    .write(true)
                    .create_new(true)
                    .open(root.join(name)),
            );
        }
        Self(root)
    }

    fn file(&self, name: &str) -> File {
        checked(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(self.0.join(name)),
        )
    }

    fn open(&self, config: SparseConfig) -> ManagedSparseJournal {
        checked(ManagedSparseJournal::open(
            self.file("journal"),
            self.file("witness"),
            config,
            scope(),
            16,
        ))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn config(generation: u64) -> SparseConfig {
    SparseConfig {
        model_digest: Digest32::of_bytes(b"model"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(generation)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

fn tick(sequence: u64, generation: u64) -> SparseTick {
    SparseTick {
        scope_digest: scope().scope_digest,
        objective_digest: scope().objective_digest,
        ndu_digest: Digest32::of_bytes(b"ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(format!("input:{generation}:{sequence}").as_bytes()),
        sequence,
        monotonic_micros: generation * 100_000 + sequence * 1_000,
        drive_q24: vec![Q, Q / 2, 0, 0, 0],
        prediction_q24: vec![0; 5],
    }
}

#[test]
fn managed_commit_durably_advances_journal_and_independent_witness() {
    let fixture = Fixture::new();
    let first = {
        let mut host = fixture.open(config(1));
        checked(host.commit(Digest32::ZERO, &tick(1, 1)))
    };
    let reopened = fixture.open(config(1));
    assert_eq!(
        checked(reopened.acknowledged()),
        Some(JournalAnchor {
            sequence: 1,
            checkpoint_digest: first.checkpoint_after,
        })
    );
    assert_eq!(
        checked(reopened.current()).map(SparseCheckpoint::digest),
        Some(first.checkpoint_after)
    );
}

#[test]
fn generation_rollover_seed_preserves_temporal_state() {
    let fixture = Fixture::new();
    let (old_state, old_config) = {
        let cfg = config(1);
        let mut host = fixture.open(cfg.clone());
        let receipt = checked(host.commit(Digest32::ZERO, &tick(1, 1)));
        let state = checked(host.current())
            .cloned()
            .unwrap_or_else(|| panic!("missing committed state"));
        assert_eq!(state.digest(), receipt.checkpoint_after);
        (state, cfg)
    };

    let next_config = config(2);
    let seed = checked(crate::rollover_seed(
        &old_state,
        &old_config,
        &next_config,
    ));
    assert_eq!(seed.sequence(), 0);
    assert_eq!(seed.temporal_q24(), old_state.temporal_q24());

    let next_root = Fixture::new();
    let mut host = checked(ManagedSparseJournal::open_seeded(
        next_root.file("journal"),
        next_root.file("witness"),
        next_config,
        scope(),
        16,
        seed.clone(),
    ));
    let receipt = checked(host.commit(seed.digest(), &tick(1, 2)));
    assert_eq!(receipt.checkpoint_before, seed.digest());
}
