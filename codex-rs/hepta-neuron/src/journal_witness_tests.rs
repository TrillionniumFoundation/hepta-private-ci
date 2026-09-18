use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;

use crate::SparseCheckpoint;
use crate::sparse_tick;

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
    let seed = checked(crate::rollover_seed(&old_state, &old_config, &next_config));
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

#[test]
fn managed_reopen_refuses_committed_journal_when_witness_is_missing() {
    let fixture = Fixture::new();
    let receipt = {
        let mut journal = checked(SparseJournal::open(
            fixture.file("journal"),
            config(1),
            scope(),
            16,
        ));
        checked(journal.commit(Digest32::ZERO, &tick(1, 1)))
    };
    assert!(!receipt.checkpoint_after.is_zero());
    assert!(checked(fs::metadata(fixture.0.join("journal"))).len() > HEADER as u64);
    assert_eq!(
        ManagedSparseJournal::open(
            fixture.file("journal"),
            fixture.file("witness"),
            config(1),
            scope(),
            16,
        )
        .err(),
        Some(WitnessError::AcknowledgedHistoryMissing)
    );
}

#[test]
fn seeded_journal_reopens_with_seeded_magic_and_witness() {
    let old_config = config(1);
    let (old_state, _) = checked(sparse_tick(&old_config, &tick(1, 1), None));
    let next_config = config(2);
    let seed = checked(crate::rollover_seed(&old_state, &old_config, &next_config));
    let fixture = Fixture::new();
    let receipt = {
        let mut host = checked(ManagedSparseJournal::open_seeded(
            fixture.file("journal"),
            fixture.file("witness"),
            next_config.clone(),
            scope(),
            16,
            seed.clone(),
        ));
        checked(host.commit(seed.digest(), &tick(1, 2)))
    };
    let reopened = checked(ManagedSparseJournal::open_seeded(
        fixture.file("journal"),
        fixture.file("witness"),
        next_config,
        scope(),
        16,
        seed,
    ));
    assert_eq!(
        checked(reopened.current()).map(SparseCheckpoint::digest),
        Some(receipt.checkpoint_after)
    );
}

#[test]
fn reopen_reconciles_complete_journal_suffix_into_witness_before_new_commit() {
    let fixture = Fixture::new();
    let (first, second) = {
        let mut host = fixture.open(config(1));
        let first = checked(host.commit(Digest32::ZERO, &tick(1, 1)));
        drop(host);

        let mut journal = checked(SparseJournal::open_anchored(
            fixture.file("journal"),
            config(1),
            scope(),
            16,
            JournalAnchor {
                sequence: 1,
                checkpoint_digest: first.checkpoint_after,
            },
        ));
        let second = checked(journal.commit(first.checkpoint_after, &tick(2, 1)));
        (first, second)
    };
    assert_ne!(first.checkpoint_after, second.checkpoint_after);

    let mut reopened = fixture.open(config(1));
    assert_eq!(
        checked(reopened.acknowledged()),
        Some(JournalAnchor {
            sequence: 2,
            checkpoint_digest: second.checkpoint_after,
        })
    );
    let third = checked(reopened.commit(second.checkpoint_after, &tick(3, 1)));
    assert_eq!(
        checked(reopened.acknowledged()),
        Some(JournalAnchor {
            sequence: 3,
            checkpoint_digest: third.checkpoint_after,
        })
    );
}

#[test]
fn managed_old_retry_is_idempotent_after_later_witnesses_exist() {
    let fixture = Fixture::new();
    let mut host = fixture.open(config(1));
    let first = checked(host.commit(Digest32::ZERO, &tick(1, 1)));
    let second = checked(host.commit(first.checkpoint_after, &tick(2, 1)));
    assert_eq!(checked(host.commit(Digest32::ZERO, &tick(1, 1))), first);
    assert_eq!(
        checked(host.acknowledged()),
        Some(JournalAnchor {
            sequence: 2,
            checkpoint_digest: second.checkpoint_after,
        })
    );
}

#[test]
fn same_generation_segment_seed_preserves_global_sequence_and_state() {
    let first_root = Fixture::new();
    let cfg = config(1);
    let state = {
        let mut host = first_root.open(cfg.clone());
        let first = checked(host.commit(Digest32::ZERO, &tick(1, 1)));
        checked(host.commit(first.checkpoint_after, &tick(2, 1)));
        checked(host.current())
            .cloned()
            .unwrap_or_else(|| panic!("missing segment state"))
    };
    assert_eq!(state.sequence(), 2);
    let seed = checked(crate::segment_seed(&state, &cfg));

    let second_root = Fixture::new();
    let receipt = {
        let mut host = checked(ManagedSparseJournal::open_seeded(
            second_root.file("journal"),
            second_root.file("witness"),
            cfg.clone(),
            scope(),
            16,
            seed.clone(),
        ));
        checked(host.commit(seed.digest(), &tick(3, 1)))
    };
    assert_eq!(receipt.checkpoint_before, seed.digest());

    let reopened = checked(ManagedSparseJournal::open_seeded(
        second_root.file("journal"),
        second_root.file("witness"),
        cfg,
        scope(),
        16,
        seed,
    ));
    let current =
        checked(reopened.current()).unwrap_or_else(|| panic!("missing reopened segment state"));
    assert_eq!(current.sequence(), 3);
    assert_eq!(current.digest(), receipt.checkpoint_after);
}
