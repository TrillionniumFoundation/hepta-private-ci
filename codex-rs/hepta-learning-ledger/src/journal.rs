//! The durable append port used by learning consumers.
//! Raw journals remain sealed to the two actual persistence implementations;
//! witness-gated consumers use `AcknowledgedLearningJournal` instead of this
//! low-level maintenance surface. Hosts still authorize files, observations and
//! scope.

use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::SegmentedLedger;
use codex_hepta_types::Digest32;

mod sealed {
    pub trait Journal {}
    impl Journal for super::DurableLedger {}
    impl Journal for super::SegmentedLedger {}
}

pub trait DurableLearningJournal: sealed::Journal {
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

impl DurableLearningJournal for DurableLedger {
    fn append(
        &mut self,
        predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        DurableLedger::append(self, predecessor, event)
    }

    fn append_batch(
        &mut self,
        predecessor: Digest32,
        events: Vec<LedgerEvent>,
    ) -> Result<Vec<AppendReceipt>, DurableLedgerError> {
        DurableLedger::append_batch(self, predecessor, events)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        let snapshot = DurableLedger::snapshot(self)?;
        Ok(snapshot.records().last().map_or(
            LedgerAnchor {
                sequence: 0,
                chain_digest: Digest32::ZERO,
            },
            |record| LedgerAnchor {
                sequence: record.sequence.get(),
                chain_digest: record.chain_digest,
            },
        ))
    }

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        DurableLedger::snapshot(self)
    }
}

impl DurableLearningJournal for SegmentedLedger {
    fn append(
        &mut self,
        predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        SegmentedLedger::append(self, predecessor, event)
    }

    fn append_batch(
        &mut self,
        predecessor: Digest32,
        events: Vec<LedgerEvent>,
    ) -> Result<Vec<AppendReceipt>, DurableLedgerError> {
        SegmentedLedger::append_batch(self, predecessor, events)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        SegmentedLedger::anchor(self)
    }

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        SegmentedLedger::snapshot(self)
    }
}
