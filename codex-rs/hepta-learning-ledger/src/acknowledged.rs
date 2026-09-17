//! Witness-gated durable learning journal.
//!
//! A caller receives a successful append only after both the causal journal and
//! the independently retained acknowledgement witness are synchronized. The raw
//! `DurableLearningJournal` remains available for explicit recovery/maintenance;
//! product-facing consumers should depend on `AcknowledgedLearningJournal`.

use codex_hepta_types::Digest32;

use crate::AppendReceipt;
use crate::DurableLearningJournal;
use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::LedgerWitnessStore;

/// Owns the only journal handle exposed to an acknowledged consumer together
/// with the independent durable witness that gates acknowledgement.
pub struct WitnessedLearningLedger<J: DurableLearningJournal> {
    journal: J,
    witness: LedgerWitnessStore,
    poisoned: bool,
}

impl<J: DurableLearningJournal> WitnessedLearningLedger<J> {
    /// Attach a recovered or newly created journal to its independent witness.
    ///
    /// A non-empty journal may never be promoted from an empty witness. If a
    /// non-empty witness is a valid prefix of a longer canonical journal, the
    /// suffix is treated as a lost-acknowledgement tail and the witness is
    /// advanced to the recovered journal head before the consumer is exposed.
    pub fn attach(
        journal: J,
        mut witness: LedgerWitnessStore,
    ) -> Result<Self, DurableLedgerError> {
        let journal_anchor = journal.anchor()?;
        let witness_anchor = witness.current_anchor();
        let snapshot = journal.snapshot()?;

        if witness_anchor.sequence == 0 {
            if journal_anchor.sequence != 0 || !journal_anchor.chain_digest.is_zero() {
                return Err(DurableLedgerError::AcknowledgedHistoryMissing);
            }
        } else {
            if witness_anchor.sequence > journal_anchor.sequence {
                return Err(DurableLedgerError::AcknowledgedHistoryMissing);
            }
            let index = usize::try_from(witness_anchor.sequence - 1)
                .map_err(|_| DurableLedgerError::InvalidAnchor)?;
            let record = snapshot
                .records()
                .get(index)
                .ok_or(DurableLedgerError::AcknowledgedHistoryMissing)?;
            if record.chain_digest != witness_anchor.chain_digest {
                return Err(DurableLedgerError::AnchorMismatch);
            }
        }

        if witness_anchor != journal_anchor {
            witness.advance(witness_anchor, journal_anchor)?;
        }

        Ok(Self {
            journal,
            witness,
            poisoned: false,
        })
    }

    /// Append one canonical event and advance the external witness to the actual
    /// journal head before returning success. Historical idempotent replays do
    /// not move the witness backward.
    pub fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        self.ready()?;
        let witness_before = self.require_aligned_head()?;
        let receipt = match self.journal.append(expected_predecessor, event) {
            Ok(receipt) => receipt,
            Err(error) => {
                self.poison_if_indeterminate(&error);
                return Err(error);
            }
        };
        self.advance_witness_from(witness_before)?;
        Ok(receipt)
    }

    /// Commit one ordered journal batch and witness its terminal head before
    /// returning any successful batch receipt.
    pub fn append_batch(
        &mut self,
        expected_predecessor: Digest32,
        events: Vec<LedgerEvent>,
    ) -> Result<Vec<AppendReceipt>, DurableLedgerError> {
        self.ready()?;
        let witness_before = self.require_aligned_head()?;
        let receipts = match self.journal.append_batch(expected_predecessor, events) {
            Ok(receipts) => receipts,
            Err(error) => {
                self.poison_if_indeterminate(&error);
                return Err(error);
            }
        };
        self.advance_witness_from(witness_before)?;
        Ok(receipts)
    }

    pub fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        self.ready()?;
        let journal = self.journal.anchor()?;
        let witness = self.witness.current_anchor();
        if journal != witness {
            return Err(DurableLedgerError::AnchorMismatch);
        }
        Ok(journal)
    }

    pub fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        self.ready()?;
        self.anchor()?;
        self.journal.snapshot()
    }

    #[must_use]
    pub const fn witness_anchor(&self) -> LedgerAnchor {
        self.witness.current_anchor()
    }

    fn require_aligned_head(&mut self) -> Result<LedgerAnchor, DurableLedgerError> {
        let journal = self.journal.anchor()?;
        let witness = self.witness.current_anchor();
        if journal != witness {
            self.poisoned = true;
            return Err(DurableLedgerError::AnchorMismatch);
        }
        Ok(witness)
    }

    fn advance_witness_from(
        &mut self,
        witness_before: LedgerAnchor,
    ) -> Result<(), DurableLedgerError> {
        let journal_after = match self.journal.anchor() {
            Ok(anchor) => anchor,
            Err(error) => {
                self.poisoned = true;
                return Err(error);
            }
        };
        if journal_after != witness_before
            && let Err(error) = self.witness.advance(witness_before, journal_after)
        {
            self.poisoned = true;
            return Err(error);
        }
        Ok(())
    }

    fn poison_if_indeterminate(&mut self, error: &DurableLedgerError) {
        if matches!(
            error,
            DurableLedgerError::Indeterminate | DurableLedgerError::Poisoned
        ) {
            self.poisoned = true;
        }
    }

    fn ready(&self) -> Result<(), DurableLedgerError> {
        if self.poisoned {
            Err(DurableLedgerError::Poisoned)
        } else {
            Ok(())
        }
    }
}

mod sealed {
    pub trait Acknowledged {}

    impl<J: super::DurableLearningJournal> Acknowledged for super::WitnessedLearningLedger<J> {}
}

/// Consumer port that cannot be implemented by a fixture or raw journal. The
/// only implementation is `WitnessedLearningLedger`, which synchronizes the
/// independent witness before acknowledging an append.
pub trait AcknowledgedLearningJournal: sealed::Acknowledged {
    fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError>;

    fn append_batch(
        &mut self,
        expected_predecessor: Digest32,
        events: Vec<LedgerEvent>,
    ) -> Result<Vec<AppendReceipt>, DurableLedgerError>;

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError>;

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError>;
}

impl<J: DurableLearningJournal> AcknowledgedLearningJournal for WitnessedLearningLedger<J> {
    fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        WitnessedLearningLedger::append(self, expected_predecessor, event)
    }

    fn append_batch(
        &mut self,
        expected_predecessor: Digest32,
        events: Vec<LedgerEvent>,
    ) -> Result<Vec<AppendReceipt>, DurableLedgerError> {
        WitnessedLearningLedger::append_batch(self, expected_predecessor, events)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        WitnessedLearningLedger::anchor(self)
    }

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        WitnessedLearningLedger::snapshot(self)
    }
}

#[cfg(test)]
mod tests {
    use std::fs::File;
    use std::fs::OpenOptions;
    use std::path::Path;
    use std::path::PathBuf;
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_types::ProbabilityQ32;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::CandidateSetCompleteness;
    use crate::DurableLedger;
    use crate::EpisodeDecision;
    use crate::LedgerRecovery;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid test id")
    }

    fn file(root: &Path, name: &str, create_new: bool) -> File {
        let mut options = OpenOptions::new();
        options.read(true).write(true);
        if create_new {
            options.create_new(true);
        }
        options.open(root.join(name)).expect("open test file")
    }

    fn temp_root(label: &str) -> PathBuf {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock after epoch")
            .as_nanos();
        let root = std::env::temp_dir().join(format!(
            "hepta-learning-ack-{label}-{}-{nanos}",
            std::process::id()
        ));
        std::fs::create_dir(&root).expect("create test root");
        root
    }

    fn decision(record: &str, episode: &str) -> LedgerEvent {
        LedgerEvent::Decision(EpisodeDecision {
            record_id: id(record),
            episode_id: id(episode),
            objective_digest: digest("objective"),
            policy_id: id("policy"),
            candidate_ids: vec![id("abstain"), id("candidate")],
            selected_candidate_id: id("candidate"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompleteness::Complete,
            support_digest: digest("support"),
        })
    }

    #[test]
    fn acknowledged_append_persists_witness_before_success() {
        let root = temp_root("append");
        let binding = digest("ledger-binding");
        let witness_binding = digest("witness-binding");
        let journal = DurableLedger::create(file(&root, "ledger", true), binding, 16)
            .expect("create ledger");
        let witness = LedgerWitnessStore::create(
            file(&root, "witness", true),
            witness_binding,
        )
        .expect("create witness");
        let mut acknowledged =
            WitnessedLearningLedger::attach(journal, witness).expect("attach witness");

        let receipt = acknowledged
            .append(Digest32::ZERO, decision("record-1", "episode-1"))
            .expect("append acknowledged event");
        assert_eq!(acknowledged.witness_anchor().sequence, receipt.sequence.get());
        assert_eq!(
            acknowledged.witness_anchor().chain_digest,
            receipt.chain_digest
        );
        drop(acknowledged);

        let recovered = LedgerWitnessStore::recover(
            file(&root, "witness", false),
            witness_binding,
        )
        .expect("recover witness");
        assert_eq!(recovered.current_anchor().chain_digest, receipt.chain_digest);
        drop(recovered);
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn acknowledged_batch_witnesses_only_the_terminal_head() {
        let root = temp_root("batch");
        let binding = digest("ledger-binding");
        let witness_binding = digest("witness-binding");
        let journal = DurableLedger::create(file(&root, "ledger", true), binding, 16)
            .expect("create ledger");
        let witness = LedgerWitnessStore::create(
            file(&root, "witness", true),
            witness_binding,
        )
        .expect("create witness");
        let mut acknowledged =
            WitnessedLearningLedger::attach(journal, witness).expect("attach witness");
        let receipts = acknowledged
            .append_batch(
                Digest32::ZERO,
                vec![
                    decision("record-1", "episode-1"),
                    decision("record-2", "episode-2"),
                ],
            )
            .expect("append acknowledged batch");
        let terminal = receipts.last().expect("terminal receipt");
        assert_eq!(acknowledged.witness_anchor().sequence, terminal.sequence.get());
        assert_eq!(acknowledged.witness_anchor().chain_digest, terminal.chain_digest);
        drop(acknowledged);
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn nonempty_journal_cannot_be_promoted_from_empty_witness() {
        let root = temp_root("empty-witness");
        let binding = digest("ledger-binding");
        let witness_binding = digest("witness-binding");
        let mut journal = DurableLedger::create(file(&root, "ledger", true), binding, 16)
            .expect("create ledger");
        journal
            .append(Digest32::ZERO, decision("record-1", "episode-1"))
            .expect("append raw fixture event");
        let witness = LedgerWitnessStore::create(
            file(&root, "witness", true),
            witness_binding,
        )
        .expect("create witness");
        assert!(matches!(
            WitnessedLearningLedger::attach(journal, witness),
            Err(DurableLedgerError::AcknowledgedHistoryMissing)
        ));
        std::fs::remove_dir_all(root).expect("remove test root");
    }

    #[test]
    fn witnessed_prefix_reconciles_a_valid_lost_acknowledgement_tail() {
        let root = temp_root("reconcile");
        let binding = digest("ledger-binding");
        let witness_binding = digest("witness-binding");
        let journal = DurableLedger::create(file(&root, "ledger", true), binding, 16)
            .expect("create ledger");
        let witness = LedgerWitnessStore::create(
            file(&root, "witness", true),
            witness_binding,
        )
        .expect("create witness");
        let mut acknowledged =
            WitnessedLearningLedger::attach(journal, witness).expect("attach witness");
        let first = acknowledged
            .append(Digest32::ZERO, decision("record-1", "episode-1"))
            .expect("append first");
        drop(acknowledged);

        let anchor = LedgerAnchor {
            sequence: first.sequence.get(),
            chain_digest: first.chain_digest,
        };
        let mut recovered = DurableLedger::recover(
            file(&root, "ledger", false),
            binding,
            16,
            LedgerRecovery::Acknowledged(anchor),
        )
        .expect("recover ledger");
        let second = recovered
            .append(first.chain_digest, decision("record-2", "episode-2"))
            .expect("append unwitnessed complete tail");
        drop(recovered);

        let recovered = DurableLedger::recover(
            file(&root, "ledger", false),
            binding,
            16,
            LedgerRecovery::Acknowledged(anchor),
        )
        .expect("recover preserved tail");
        let witness = LedgerWitnessStore::recover(
            file(&root, "witness", false),
            witness_binding,
        )
        .expect("recover witness");
        let reconciled =
            WitnessedLearningLedger::attach(recovered, witness).expect("reconcile suffix");
        assert_eq!(reconciled.witness_anchor().sequence, second.sequence.get());
        assert_eq!(reconciled.witness_anchor().chain_digest, second.chain_digest);
        drop(reconciled);
        std::fs::remove_dir_all(root).expect("remove test root");
    }
}
