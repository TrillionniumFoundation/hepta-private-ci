//! Real-file regressions for the production journal's historical frontier port.
//! These exercise the sealed product implementations, not a mock durability claim.

#![forbid(unsafe_code)]

use std::error::Error;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::DurableLearningJournal;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::DurableLedgerError;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LedgerAnchor;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerSegmentLimits;
use codex_hepta_learning_ledger::SegmentedLedger;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

static NEXT: AtomicU64 = AtomicU64::new(0);
type TestResult<T = ()> = Result<T, Box<dyn Error>>;

struct Files(PathBuf);

impl Files {
    fn new() -> TestResult<Self> {
        let path = std::env::temp_dir().join(format!(
            "hepta-journal-anchor-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed),
        ));
        fs::create_dir(&path)?;
        Ok(Self(path))
    }

    fn create(&self, name: &str) -> std::io::Result<File> {
        OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(self.0.join(name))
    }

    fn open(&self, name: &str) -> std::io::Result<File> {
        OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.0.join(name))
    }

    fn segmented(&self) -> TestResult<SegmentedLedger> {
        Ok(SegmentedLedger::create(
            self.create("owner")?,
            self.create("0")?,
            binding(),
            limits(),
        )?)
    }
}

impl Drop for Files {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn binding() -> Digest32 {
    Digest32::of_bytes(b"journal-anchor-regression-owner")
}

fn empty() -> LedgerAnchor {
    LedgerAnchor {
        sequence: 0,
        chain_digest: Digest32::ZERO,
    }
}

fn limits() -> LedgerSegmentLimits {
    LedgerSegmentLimits {
        records: 2,
        bytes: 4096,
    }
}

fn decision(number: u64) -> TestResult<LedgerEvent> {
    Ok(LedgerEvent::Decision(EpisodeDecision {
        record_id: StableId::new(format!("decision-{number}"))?,
        episode_id: StableId::new(format!("episode-{number}"))?,
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: StableId::new("policy")?,
        candidate_ids: vec![StableId::new("choice")?, StableId::new("abstain")?],
        selected_candidate_id: StableId::new("choice")?,
        selected_propensity: ProbabilityQ32::from_raw(1 << 31)?,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"complete-support"),
    }))
}

fn check_membership<J: DurableLearningJournal>(
    journal: &J,
    prefix: LedgerAnchor,
    head: LedgerAnchor,
) -> TestResult {
    assert!(journal.contains_anchor(empty())?);
    assert!(journal.contains_anchor(prefix)?);
    assert!(journal.contains_anchor(head)?);
    for absent in [
        LedgerAnchor {
            sequence: 0,
            chain_digest: prefix.chain_digest,
        },
        LedgerAnchor {
            sequence: prefix.sequence,
            chain_digest: Digest32::of_bytes(b"wrong-frontier"),
        },
        LedgerAnchor {
            sequence: head.sequence + 1,
            chain_digest: head.chain_digest,
        },
        LedgerAnchor {
            sequence: (1_u64 << 32) + prefix.sequence,
            chain_digest: prefix.chain_digest,
        },
        LedgerAnchor {
            sequence: u64::MAX,
            chain_digest: head.chain_digest,
        },
    ] {
        assert!(!journal.contains_anchor(absent)?);
    }
    assert_eq!(journal.anchor()?, head);
    Ok(())
}

#[test]
fn segmented_frontiers_survive_rotation_retry_and_recovery() -> TestResult {
    let files = Files::new()?;
    let mut journal = files.segmented()?;
    journal.append(Digest32::ZERO, decision(0)?)?;
    let prefix = journal.anchor()?;
    journal.rotate(files.create("1")?, prefix)?;
    journal.append(prefix.chain_digest, decision(1)?)?;
    let head = journal.anchor()?;
    check_membership(&journal, prefix, head)?;
    let minimum = journal.checkpoint()?;
    drop(journal);

    let mut recovered = SegmentedLedger::recover(
        files.open("owner")?,
        vec![files.open("0")?, files.open("1")?],
        binding(),
        limits(),
        minimum,
    )?;
    check_membership(&recovered, prefix, head)?;
    let retry = recovered.append(Digest32::ZERO, decision(0)?)?;
    assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(retry.chain_digest, prefix.chain_digest);
    assert_eq!(recovered.anchor()?, head);
    Ok(())
}

#[test]
fn single_file_frontiers_are_exact_and_reads_preserve_the_head() -> TestResult {
    let files = Files::new()?;
    let mut journal = DurableLedger::create(files.create("journal")?, binding(), 8)?;
    journal.append(Digest32::ZERO, decision(0)?)?;
    let prefix = journal.anchor()?;
    journal.append(prefix.chain_digest, decision(1)?)?;
    check_membership(&journal, prefix, journal.anchor()?)
}

#[test]
fn rejected_rotation_preserves_frontier_and_accepts_the_next_write() -> TestResult {
    let files = Files::new()?;
    let mut journal = files.segmented()?;
    journal.append(Digest32::ZERO, decision(0)?)?;
    let prefix = journal.anchor()?;
    assert_eq!(
        journal.rotate(files.create("rejected")?, empty()),
        Err(DurableLedgerError::AnchorMismatch)
    );
    check_membership(&journal, prefix, prefix)?;
    journal.append(prefix.chain_digest, decision(1)?)?;
    assert_eq!(journal.anchor()?.sequence, prefix.sequence + 1);
    Ok(())
}

// Fault injection uses independently opened Unix file handles. It deliberately
// violates the cooperative writer contract to make the owner observe corruption.
#[cfg(unix)]
fn change_file_length(file: &File) -> std::io::Result<()> {
    file.set_len(file.metadata()?.len() + 1)?;
    file.sync_all()
}

#[cfg(unix)]
#[test]
fn poisoned_segmented_journal_cannot_certify_even_the_empty_frontier() -> TestResult {
    let files = Files::new()?;
    let mut journal = files.segmented()?;
    journal.append(Digest32::ZERO, decision(0)?)?;
    let prefix = journal.anchor()?;
    change_file_length(&files.open("0")?)?;
    assert_eq!(
        journal.append(prefix.chain_digest, decision(1)?),
        Err(DurableLedgerError::Corrupt)
    );
    for anchor in [empty(), prefix] {
        assert_eq!(
            DurableLearningJournal::contains_anchor(&journal, anchor),
            Err(DurableLedgerError::Poisoned)
        );
        assert_eq!(
            journal.contains_anchor(anchor),
            Err(DurableLedgerError::Poisoned)
        );
    }
    Ok(())
}

#[cfg(unix)]
#[test]
fn poisoned_single_file_journal_cannot_certify_even_the_empty_frontier() -> TestResult {
    let files = Files::new()?;
    let mut journal = DurableLedger::create(files.create("journal")?, binding(), 8)?;
    journal.append(Digest32::ZERO, decision(0)?)?;
    let prefix = journal.anchor()?;
    change_file_length(&files.open("journal")?)?;
    assert_eq!(
        journal.append(prefix.chain_digest, decision(1)?),
        Err(DurableLedgerError::Corrupt)
    );
    for anchor in [empty(), prefix] {
        assert_eq!(
            journal.contains_anchor(anchor),
            Err(DurableLedgerError::Poisoned)
        );
    }
    Ok(())
}

#[cfg(unix)]
mod long_horizon {
    use super::*;
    use codex_hepta_learning_ledger::LongHorizonLedgerErrorV1;
    use codex_hepta_learning_ledger::LongHorizonSegmentedLedgerV1;

    fn create(files: &Files) -> TestResult<LongHorizonSegmentedLedgerV1> {
        Ok(LongHorizonSegmentedLedgerV1::create(
            files.create("owner")?,
            files.create("0")?,
            files.0.join("index"),
            binding(),
            limits(),
            16,
        )?)
    }

    fn check_frontiers<J: DurableLearningJournal>(
        journal: &J,
        prefix: LedgerAnchor,
        head: LedgerAnchor,
    ) -> TestResult {
        for anchor in [empty(), prefix, head] {
            assert!(journal.contains_anchor(anchor)?);
        }
        assert_eq!(journal.anchor()?, head);
        Ok(())
    }

    #[test]
    fn observed_corruption_requires_checkpointed_recovery_not_same_handle_retry() -> TestResult {
        let files = Files::new()?;
        let mut journal = create(&files)?;
        journal.append(Digest32::ZERO, decision(0)?)?;
        let minimum = journal.checkpoint()?;
        let prefix = minimum.head_anchor;
        let length = files.open("0")?.metadata()?.len();
        change_file_length(&files.open("0")?)?;
        assert!(matches!(
            journal.append(prefix.chain_digest, decision(1)?),
            Err(LongHorizonLedgerErrorV1::Durable(DurableLedgerError::Corrupt))
        ));
        assert!(matches!(
            journal.checkpoint(),
            Err(LongHorizonLedgerErrorV1::Poisoned)
        ));
        assert!(matches!(
            journal.metrics(),
            Err(LongHorizonLedgerErrorV1::Poisoned)
        ));
        for anchor in [empty(), prefix] {
            assert_eq!(
                DurableLearningJournal::contains_anchor(&journal, anchor),
                Err(DurableLedgerError::Poisoned)
            );
        }
        // Even exact idempotent replay cannot turn this failed handle into a
        // healthy one. Restoring bytes is not a substitute for authenticated recovery.
        assert_eq!(
            DurableLearningJournal::append(&mut journal, Digest32::ZERO, decision(0)?),
            Err(DurableLedgerError::Poisoned)
        );
        let repair = files.open("0")?;
        repair.set_len(length)?;
        repair.sync_all()?;
        drop(repair);
        assert_eq!(
            DurableLearningJournal::anchor(&journal),
            Err(DurableLedgerError::Poisoned)
        );
        drop(journal);

        let mut recovered = LongHorizonSegmentedLedgerV1::recover(
            files.open("owner")?,
            files.open("0")?,
            files.0.join("index"),
            binding(),
            limits(),
            16,
            minimum,
        )?;
        check_frontiers(&recovered, prefix, prefix)?;
        let retry = recovered.append(Digest32::ZERO, decision(0)?)?;
        assert_eq!(retry.disposition, AppendDisposition::IdempotentReplay);
        assert_eq!(retry.chain_digest, prefix.chain_digest);
        recovered.append(prefix.chain_digest, decision(1)?)?;
        assert_eq!(recovered.checkpoint()?.head_anchor.sequence, 2);
        Ok(())
    }

    #[test]
    fn semantic_conflict_and_capacity_preserve_a_usable_owner() -> TestResult {
        let files = Files::new()?;
        let mut journal = create(&files)?;
        journal.append(Digest32::ZERO, decision(0)?)?;
        let prefix = journal.checkpoint()?.head_anchor;
        assert!(matches!(
            journal.append(Digest32::ZERO, decision(1)?),
            Err(LongHorizonLedgerErrorV1::Durable(DurableLedgerError::Conflict))
        ));
        check_frontiers(&journal, prefix, prefix)?;
        journal.append(prefix.chain_digest, decision(1)?)?;
        let head = journal.checkpoint()?.head_anchor;
        assert!(matches!(
            journal.append(head.chain_digest, decision(2)?),
            Err(LongHorizonLedgerErrorV1::Durable(DurableLedgerError::Capacity))
        ));
        check_frontiers(&journal, prefix, head)?;
        journal.rotate(files.create("1")?, head)?;
        journal.append(head.chain_digest, decision(2)?)?;
        let next = journal.checkpoint()?;
        assert_eq!(next.head_anchor.sequence, 3);
        assert_eq!(next.archived_anchor, head);
        assert_eq!(journal.metrics()?.retained_payload_records, 1);
        check_frontiers(&journal, prefix, next.head_anchor)?;
        Ok(())
    }
}
