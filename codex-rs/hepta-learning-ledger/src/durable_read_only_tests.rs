use super::*;
use std::error::Error;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;
use crate::LedgerWitnessStore;
use crate::OutcomeFinality;
use crate::OutcomeObservation;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;

static NEXT: AtomicU64 = AtomicU64::new(0);
const LIMIT: usize = 8;

struct Fixture {
    root: PathBuf,
    binding: Digest32,
}

impl Fixture {
    fn new() -> TestResult<Self> {
        let sequence = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-ledger-readonly-{}-{sequence}",
            std::process::id()
        ));
        fs::create_dir(&root)?;
        for name in ["ledger", "witness"] {
            OpenOptions::new()
                .create_new(true)
                .read(true)
                .write(true)
                .open(root.join(name))?;
        }
        Ok(Self {
            root,
            binding: Digest32::of_bytes(b"readonly-data-component-fixture"),
        })
    }

    fn writable(&self, name: &str) -> io::Result<File> {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join(name))
    }

    fn readonly(&self, name: &str) -> io::Result<File> {
        File::open(self.root.join(name))
    }

    fn observe(&self) -> Result<ReadOnlyLedgerViewV1, DurableLedgerError> {
        ReadOnlyLedgerViewV1::observe_closed(
            self.readonly("ledger")?,
            self.readonly("witness")?,
            self.binding,
            LIMIT,
        )
    }

    fn reopen(&self, cut: LedgerReadOnlyCutV1) -> Result<ReadOnlyLedgerViewV1, DurableLedgerError> {
        ReadOnlyLedgerViewV1::open_at_retained_cut(
            self.readonly("ledger")?,
            self.readonly("witness")?,
            self.binding,
            LIMIT,
            cut,
        )
    }

    fn populate(&self) -> TestResult<LedgerSnapshot> {
        // These canonical legacy events exercise the data parser, not the
        // production signed Decision/Outcome or any historical learning grant.
        let mut ledger = DurableLedger::create(self.writable("ledger")?, self.binding, LIMIT)?;
        let mut witness = LedgerWitnessStore::create(self.writable("witness")?, self.binding)?;
        let mut frontier = LedgerWitnessFrontier::empty();
        for event in events()? {
            let receipt = ledger.append(frontier.anchor.chain_digest, event)?;
            let next = LedgerWitnessFrontier {
                anchor: LedgerAnchor {
                    sequence: receipt.sequence.get(),
                    chain_digest: receipt.chain_digest,
                },
                segment: None,
                sealed: false,
            };
            frontier = witness.advance(frontier, next)?;
        }
        Ok(ledger.snapshot()?)
    }

    fn bytes(&self, name: &str) -> io::Result<Vec<u8>> {
        fs::read(self.root.join(name))
    }

    fn replace_bytes(&self, name: &str, bytes: &[u8]) -> io::Result<()> {
        // Deliberately bypass advisory locks to model physical corruption and
        // restoration. The readonly component must never perform this repair.
        let mut file = self.writable(name)?;
        file.write_all(bytes)?;
        file.set_len(bytes.len() as u64)?;
        file.sync_all()
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn events() -> TestResult<Vec<LedgerEvent>> {
    Ok(vec![
        LedgerEvent::Decision(EpisodeDecision {
            record_id: StableId::new("decision")?,
            episode_id: StableId::new("episode")?,
            objective_digest: Digest32::of_bytes(b"objective"),
            policy_id: StableId::new("policy")?,
            candidate_ids: vec![StableId::new("choice")?, StableId::new("abstain")?],
            selected_candidate_id: StableId::new("choice")?,
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: Digest32::of_bytes(b"decision support"),
        }),
        LedgerEvent::Outcome(OutcomeObservation {
            record_id: StableId::new("observation")?,
            outcome_id: StableId::new("outcome")?,
            episode_id: StableId::new("episode")?,
            observer_id: StableId::new("observer")?,
            value: FixedQ32::ONE,
            finality: OutcomeFinality::Terminal,
            support_digest: Digest32::of_bytes(b"outcome support"),
        }),
    ])
}

#[test]
fn ledger_readonly_replays_real_files_after_owners_drop_and_reopens_exact_cut() -> TestResult {
    let fixture = Fixture::new()?;
    let snapshot = fixture.populate()?;
    let before = (fixture.bytes("ledger")?, fixture.bytes("witness")?);
    let view = fixture.observe()?;
    let observed = view.observe()?;
    assert_eq!(observed.snapshot, snapshot);
    drop(view);
    let reopened = fixture.reopen(observed.cut)?;
    assert_eq!(reopened.observe()?, observed);
    assert_eq!(
        (fixture.bytes("ledger")?, fixture.bytes("witness")?),
        before
    );
    Ok(())
}

#[test]
fn ledger_readonly_rejects_writable_descriptors_and_each_live_writer() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.populate()?;
    assert!(matches!(
        ReadOnlyLedgerViewV1::observe_closed(
            fixture.writable("ledger")?,
            fixture.readonly("witness")?,
            fixture.binding,
            LIMIT,
        ),
        Err(DurableLedgerError::Io(io::ErrorKind::PermissionDenied))
    ));
    assert!(matches!(
        ReadOnlyLedgerViewV1::observe_closed(
            fixture.readonly("ledger")?,
            fixture.writable("witness")?,
            fixture.binding,
            LIMIT,
        ),
        Err(DurableLedgerError::Io(io::ErrorKind::PermissionDenied))
    ));
    let observation = fixture.observe()?.observe()?;
    let writer = DurableLedger::recover(
        fixture.writable("ledger")?,
        fixture.binding,
        LIMIT,
        LedgerRecovery::Acknowledged(observation.cut.frontier.anchor),
    )?;
    assert!(matches!(fixture.observe(), Err(DurableLedgerError::Busy)));
    drop(writer);
    let witness = LedgerWitnessStore::recover(fixture.writable("witness")?, fixture.binding)?;
    assert!(matches!(fixture.observe(), Err(DurableLedgerError::Busy)));
    drop(witness);
    assert_eq!(fixture.reopen(observation.cut)?.observe()?, observation);
    Ok(())
}

#[test]
fn ledger_readonly_corruption_then_byte_restoration_stays_poisoned_for_each_file() -> TestResult {
    for name in ["ledger", "witness"] {
        let fixture = Fixture::new()?;
        fixture.populate()?;
        let original = fixture.bytes(name)?;
        let view = fixture.observe()?;
        let mut damaged = original.clone();
        damaged[HEADER] ^= 1;
        fixture.replace_bytes(name, &damaged)?;
        assert!(view.observe().is_err());
        fixture.replace_bytes(name, &original)?;
        assert_eq!(fixture.bytes(name)?, original);
        assert_eq!(view.observe(), Err(DurableLedgerError::Poisoned));
    }
    Ok(())
}

#[test]
fn ledger_readonly_never_repairs_partial_tails_or_initializes_missing_headers() -> TestResult {
    let empty = Fixture::new()?;
    assert!(matches!(
        empty.observe(),
        Err(DurableLedgerError::MissingHeader)
    ));
    assert_eq!(
        (empty.bytes("ledger")?, empty.bytes("witness")?),
        (vec![], vec![])
    );
    for name in ["ledger", "witness"] {
        let fixture = Fixture::new()?;
        fixture.populate()?;
        let mut bytes = fixture.bytes(name)?;
        bytes.push(1);
        fixture.replace_bytes(name, &bytes)?;
        assert!(matches!(
            fixture.observe(),
            Err(DurableLedgerError::IncompleteTail)
        ));
        assert_eq!(fixture.bytes(name)?, bytes);
    }
    Ok(())
}

#[test]
fn ledger_readonly_rejects_witness_lag_instead_of_owner_recovery() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.populate()?;
    let mut witness = fixture.bytes("witness")?;
    witness.truncate(72 + 88);
    fixture.replace_bytes("witness", &witness)?;
    assert!(matches!(
        fixture.observe(),
        Err(DurableLedgerError::UnwitnessedTail)
    ));
    assert_eq!(fixture.bytes("witness")?, witness);
    Ok(())
}

#[test]
fn ledger_readonly_rejects_joint_rollback_against_the_external_exact_cut() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.populate()?;
    let observed = fixture.observe()?.observe()?;
    let ledger = fixture.bytes("ledger")?;
    let size = u32::from_be_bytes(ledger[72..76].try_into()?) as usize;
    fixture.replace_bytes("ledger", &ledger[..72 + FRAME_OVERHEAD + size])?;
    let witness = fixture.bytes("witness")?;
    fixture.replace_bytes("witness", &witness[..72 + 88])?;
    assert!(matches!(
        fixture.reopen(observed.cut),
        Err(DurableLedgerError::AnchorMismatch)
    ));
    // Discarding the external cut would only obtain a different data view. The
    // original Root admission must never authorize that recapture as recovery.
    Ok(())
}

#[test]
fn ledger_readonly_rejects_segmented_or_sealed_frontiers() -> TestResult {
    for frontier_kind in [(Some(0), false), (None, true)] {
        let fixture = Fixture::new()?;
        let mut ledger =
            DurableLedger::create(fixture.writable("ledger")?, fixture.binding, LIMIT)?;
        let mut witness =
            LedgerWitnessStore::create(fixture.writable("witness")?, fixture.binding)?;
        let event = events()?.remove(0);
        let receipt = ledger.append(Digest32::ZERO, event)?;
        witness.advance(
            LedgerWitnessFrontier::empty(),
            LedgerWitnessFrontier {
                anchor: LedgerAnchor {
                    sequence: receipt.sequence.get(),
                    chain_digest: receipt.chain_digest,
                },
                segment: frontier_kind.0,
                sealed: frontier_kind.1,
            },
        )?;
        drop((ledger, witness));
        assert!(matches!(
            fixture.observe(),
            Err(DurableLedgerError::InvalidAnchor)
        ));
    }
    Ok(())
}

#[test]
fn ledger_readonly_rejects_aliased_or_unlinked_original_files() -> TestResult {
    let fixture = Fixture::new()?;
    fixture.populate()?;
    assert!(matches!(
        ReadOnlyLedgerViewV1::observe_closed(
            fixture.readonly("ledger")?,
            fixture.readonly("ledger")?,
            fixture.binding,
            LIMIT,
        ),
        Err(DurableLedgerError::BindingMismatch)
    ));
    let view = fixture.observe()?;
    fs::remove_file(fixture.root.join("ledger"))?;
    assert!(view.observe().is_err());
    assert_eq!(view.observe(), Err(DurableLedgerError::Poisoned));
    Ok(())
}
