use super::*;
use std::fs;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;
use crate::Revocation;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("inspection fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"inspection-fixture-scope-purpose-generation")
}

fn decision(suffix: &str) -> LedgerEvent {
    LedgerEvent::Decision(EpisodeDecision {
        record_id: id(&format!("decision-{suffix}")),
        episode_id: id(&format!("episode-{suffix}")),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy"),
        candidate_ids: vec![id("choice"), id("abstain")],
        selected_candidate_id: id("choice"),
        selected_propensity: must(ProbabilityQ32::from_raw(/*raw*/ 1 << 31)),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"complete-candidates"),
    })
}

fn anchor(snapshot: &LedgerSnapshot) -> LedgerAnchor {
    LedgerAnchor {
        sequence: snapshot.records().len() as u64,
        chain_digest: snapshot.head_digest,
    }
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-readonly-ledger-{}-{serial}",
            std::process::id()
        ));
        must(fs::create_dir(&root));
        Self { root }
    }

    fn path(&self) -> PathBuf {
        self.root.join("ledger")
    }

    fn seed(&self, events: Vec<LedgerEvent>) -> LedgerSnapshot {
        let file = must(
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(self.path()),
        );
        let mut ledger = must(DurableLedger::create(
            file,
            binding(),
            /*max_records*/ 16,
        ));
        let mut head = Digest32::ZERO;
        for event in events {
            head = must(ledger.append(head, event)).chain_digest;
        }
        must(ledger.snapshot())
    }

    fn inspect(&self, witness: LedgerAnchor) -> Result<LedgerSnapshot, DurableLedgerError> {
        inspect_ledger(
            must(File::open(self.path())),
            binding(),
            /*max_records*/ 16,
            witness,
        )
    }

    fn recover(&self, witness: LedgerAnchor) -> Result<DurableLedger, DurableLedgerError> {
        let file = must(OpenOptions::new().read(true).write(true).open(self.path()));
        DurableLedger::recover(
            file,
            binding(),
            /*max_records*/ 16,
            LedgerRecovery::Acknowledged(witness),
        )
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn os_readonly_inspection_matches_writer_and_preserves_bytes() {
    let fixture = Fixture::new();
    let expected = fixture.seed(vec![decision("one"), decision("two")]);
    let bytes = must(fs::read(fixture.path()));
    assert_eq!(must(fixture.inspect(anchor(&expected))), expected);
    assert_eq!(must(fs::read(fixture.path())), bytes);
    let recovered = must(fixture.recover(anchor(&expected)));
    assert_eq!(must(recovered.snapshot()), expected);
}

#[test]
fn reader_coexists_with_shared_lock_but_does_not_unlock_another_reader() {
    let fixture = Fixture::new();
    let expected = fixture.seed(vec![decision("one")]);
    let shared = must(File::open(fixture.path()));
    must(shared.try_lock_shared());
    assert_eq!(must(fixture.inspect(anchor(&expected))), expected);
    assert_eq!(
        fixture.recover(anchor(&expected)).err(),
        Some(DurableLedgerError::Busy)
    );
    must(shared.unlock());
    let recovered = must(fixture.recover(anchor(&expected)));
    assert_eq!(
        fixture.inspect(anchor(&expected)),
        Err(DurableLedgerError::Busy)
    );
    assert_eq!(must(recovered.snapshot()), expected);
}

#[test]
fn partial_tail_is_never_repaired_by_reader() {
    let fixture = Fixture::new();
    let expected = fixture.seed(vec![decision("one")]);
    let original = must(fs::read(fixture.path()));
    {
        let mut file = must(OpenOptions::new().append(true).open(fixture.path()));
        must(file.write_all(&[0, 0, 0]));
        must(file.sync_all());
    }
    let partial = must(fs::read(fixture.path()));
    assert_eq!(
        fixture.inspect(anchor(&expected)),
        Err(DurableLedgerError::IncompleteTail)
    );
    assert_eq!(must(fs::read(fixture.path())), partial);
    drop(must(fixture.recover(anchor(&expected))));
    assert_eq!(must(fs::read(fixture.path())), original);
    assert_eq!(must(fixture.inspect(anchor(&expected))), expected);
}

#[test]
fn complete_suffix_needs_current_witness_and_never_returns_old_prefix() {
    let fixture = Fixture::new();
    let first = fixture.seed(vec![decision("one")]);
    let mut writer = must(fixture.recover(anchor(&first)));
    must(writer.append(first.head_digest, decision("two")));
    let second = must(writer.snapshot());
    drop(writer);
    let bytes = must(fs::read(fixture.path()));
    assert_eq!(
        fixture.inspect(anchor(&first)),
        Err(DurableLedgerError::UnwitnessedTail)
    );
    assert_eq!(must(fixture.inspect(anchor(&second))), second);
    assert_eq!(must(fs::read(fixture.path())), bytes);
}

#[test]
fn missing_and_mismatched_acknowledged_history_never_mutate_file() {
    let fixture = Fixture::new();
    let expected = fixture.seed(vec![decision("one")]);
    let bytes = must(fs::read(fixture.path()));
    let mut missing = anchor(&expected);
    missing.sequence += 1;
    assert_eq!(
        fixture.inspect(missing),
        Err(DurableLedgerError::AcknowledgedHistoryMissing)
    );
    let mut mismatch = anchor(&expected);
    mismatch.chain_digest = Digest32::of_bytes(b"wrong-chain");
    assert_eq!(
        fixture.inspect(mismatch),
        Err(DurableLedgerError::AnchorMismatch)
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
    assert_eq!(must(fixture.inspect(anchor(&expected))), expected);
}

#[test]
fn corrupted_complete_frame_and_invalid_domains_are_rejected() {
    let fixture = Fixture::new();
    let expected = fixture.seed(vec![decision("one")]);
    let mut invalid = anchor(&expected);
    invalid.sequence = 0;
    assert_eq!(
        fixture.inspect(invalid),
        Err(DurableLedgerError::InvalidAnchor)
    );
    assert_eq!(
        inspect_ledger(
            must(File::open(fixture.path())),
            Digest32::ZERO,
            /*max_records*/ 16,
            anchor(&expected),
        ),
        Err(DurableLedgerError::InvalidBinding)
    );
    assert_eq!(
        inspect_ledger(
            must(File::open(fixture.path())),
            binding(),
            /*max_records*/ 0,
            anchor(&expected),
        ),
        Err(DurableLedgerError::InvalidLimit)
    );
    let mut bytes = must(fs::read(fixture.path()));
    let last = bytes.len() - 1;
    bytes[last] ^= 1;
    must(fs::write(fixture.path(), &bytes));
    assert_eq!(
        fixture.inspect(anchor(&expected)),
        Err(DurableLedgerError::Corrupt)
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
}

#[test]
fn current_revocations_survive_readonly_projection() {
    let fixture = Fixture::new();
    let revoke = LedgerEvent::Revocation(Revocation {
        record_id: id("revoke-one"),
        target_record_id: id("decision-one"),
        authority_id: id("privacy-owner"),
        reason_digest: Digest32::of_bytes(b"authorized-deletion-fixture"),
    });
    let expected = fixture.seed(vec![decision("one"), decision("two"), revoke]);
    let inspected = must(fixture.inspect(anchor(&expected)));
    assert_eq!(inspected, expected);
    let core = must(LearningLedger::from_snapshot(inspected));
    let active = core.active_records();
    assert_eq!(active.len(), 2);
    assert!(active.iter().all(|record| !matches!(
        &record.event,
        LedgerEvent::Decision(value) if value.record_id == id("decision-one")
    )));
}

#[cfg(target_os = "linux")]
#[test]
fn rejection_releases_own_lock_even_with_transient_duplicate() {
    let fixture = Fixture::new();
    let expected = fixture.seed(vec![decision("one")]);
    let file = must(File::open(fixture.path()));
    // Test-only model of a transient inherited open description, never a caller API.
    let transient = must(file.try_clone());
    let mut wrong = anchor(&expected);
    wrong.chain_digest = Digest32::of_bytes(b"wrong-chain");
    assert_eq!(
        inspect_ledger(file, binding(), /*max_records*/ 16, wrong),
        Err(DurableLedgerError::AnchorMismatch)
    );
    let writer = must(fixture.recover(anchor(&expected)));
    drop(transient);
    assert_eq!(
        fixture.inspect(anchor(&expected)),
        Err(DurableLedgerError::Busy)
    );
    assert_eq!(must(writer.snapshot()), expected);
}
