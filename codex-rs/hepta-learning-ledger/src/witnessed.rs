//! Witnessed durable append: storage commit first, independent witness second,
//! caller acknowledgement last.

use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::AppendReceipt;
use crate::DurableLearningJournal;
use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerWitnessStore;
use crate::WitnessStoreError;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WitnessedAppendError {
    Journal(DurableLedgerError),
    /// The ledger may already contain the event. Retry the exact same identity,
    /// predecessor and semantics after recovering the witness; never mint a new id.
    CommittedButUnwitnessed {
        receipt: AppendReceipt,
        witness_error: WitnessStoreError,
    },
}

impl fmt::Display for WitnessedAppendError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for WitnessedAppendError {}

impl From<DurableLedgerError> for WitnessedAppendError {
    fn from(value: DurableLedgerError) -> Self {
        Self::Journal(value)
    }
}

/// The production acknowledgement boundary for durable learning facts.
///
/// `append` never returns success until the independent witness has durably
/// retained the exact sequence and chain digest produced by the journal.
pub struct WitnessedLearningJournal<J: DurableLearningJournal> {
    journal: J,
    witness: LedgerWitnessStore,
}

impl<J: DurableLearningJournal> WitnessedLearningJournal<J> {
    pub fn new(journal: J, witness: LedgerWitnessStore) -> Result<Self, WitnessedAppendError> {
        let journal_anchor = journal.anchor()?;
        match witness.latest() {
            None if journal_anchor.sequence <= 1 => {}
            Some(anchor) if anchor == journal_anchor => {}
            Some(anchor)
                if journal_anchor.sequence == anchor.sequence + 1
                    && journal.contains_anchor(anchor)? =>
            {
                // Exactly one complete journal frame may be ahead after a crash
                // between journal sync and witness sync. The original operation
                // must be replayed before any later append can be acknowledged.
            }
            _ => return Err(WitnessedAppendError::Journal(DurableLedgerError::AnchorMismatch)),
        }
        Ok(Self { journal, witness })
    }

    pub fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, WitnessedAppendError> {
        let receipt = self.journal.append(expected_predecessor, event)?;
        let anchor = LedgerAnchor {
            sequence: receipt.sequence.get(),
            chain_digest: receipt.chain_digest,
        };
        if let Err(witness_error) = self.witness.persist(anchor) {
            return Err(WitnessedAppendError::CommittedButUnwitnessed {
                receipt,
                witness_error,
            });
        }
        Ok(receipt)
    }

    pub fn anchor(&self) -> Result<LedgerAnchor, WitnessedAppendError> {
        self.journal.anchor().map_err(Into::into)
    }

    #[must_use]
    pub fn witness_anchor(&self) -> Option<LedgerAnchor> {
        self.witness.latest()
    }

    pub fn into_parts(self) -> (J, LedgerWitnessStore) {
        (self.journal, self.witness)
    }
}

#[cfg(test)]
#[path = "witnessed_tests.rs"]
mod tests;
