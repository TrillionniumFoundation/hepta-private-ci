use super::*;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::CandidateSetCompleteness;
use crate::DurableLedger;
use crate::EpisodeDecision;
use crate::LedgerRecovery;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value.to_owned()))
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"witnessed-learning-store")
}

fn decision() -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id("decision-1"),
        episode_id: id("episode-1"),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: must(ProbabilityQ32::from_raw(1 << 31)),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"support"),
    })
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-witnessed-journal-{}-{serial}",
            std::process::id()
        ));
        must(fs::create_dir(&root));
        for name in ["ledger", "witness"] {
            must(
                OpenOptions::new()
                    .create_new(true)
                    .write(true)
                    .open(root.join(name)),
            );
        }
        Self { root }
    }

    fn file(&self, name: &str) -> File {
        must(
            OpenOptions::new()
                .read(true)
                .write(true)
                .open(self.root.join(name)),
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn witnessed_append_persists_anchor_before_success() {
    let fixture = Fixture::new();
    let journal = must(DurableLedger::create(fixture.file("ledger"), binding(), 16));
    let witness = must(LedgerWitnessStore::create(fixture.file("witness"), binding()));
    let mut guarded = must(WitnessedLearningJournal::new(journal, witness));

    let receipt = must(guarded.append(Digest32::ZERO, decision()));
    assert_eq!(
        guarded.witness_anchor(),
        Some(LedgerAnchor {
            sequence: receipt.sequence.get(),
            chain_digest: receipt.chain_digest,
        })
    );
}

#[test]
fn exact_retry_repairs_one_committed_frame_ahead_of_witness() {
    let fixture = Fixture::new();
    let committed = {
        let mut journal = must(DurableLedger::create(fixture.file("ledger"), binding(), 16));
        must(journal.append(Digest32::ZERO, decision()))
    };
    let recovered = must(DurableLedger::recover(
        fixture.file("ledger"),
        binding(),
        16,
        LedgerRecovery::Unacknowledged,
    ));
    let witness = must(LedgerWitnessStore::create(fixture.file("witness"), binding()));
    let mut guarded = must(WitnessedLearningJournal::new(recovered, witness));

    let retry = must(guarded.append(Digest32::ZERO, decision()));
    assert_eq!(retry.chain_digest, committed.chain_digest);
    assert_eq!(retry.sequence, committed.sequence);
    assert_eq!(
        guarded.witness_anchor(),
        Some(LedgerAnchor {
            sequence: committed.sequence.get(),
            chain_digest: committed.chain_digest,
        })
    );
}
