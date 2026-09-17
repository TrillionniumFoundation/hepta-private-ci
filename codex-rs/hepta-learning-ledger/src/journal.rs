//! The durable Decision append port used by existing learning consumers.
//! Sealed to the two actual journals; a fixture cannot assert durability by
//! implementing this port. Hosts still authorize files, observations and scope.

use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::LedgerEvent;
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

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError>;

    fn contains_anchor(&self, anchor: LedgerAnchor) -> Result<bool, DurableLedgerError>;
}

impl DurableLearningJournal for DurableLedger {
    fn append(
        &mut self,
        predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        DurableLedger::append(self, predecessor, event)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        let records = self.records()?;
        Ok(records.last().map_or(
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

    fn contains_anchor(&self, anchor: LedgerAnchor) -> Result<bool, DurableLedgerError> {
        if anchor.sequence == 0 {
            return Ok(anchor.chain_digest.is_zero());
        }
        let records = self.records()?;
        Ok(records
            .get((anchor.sequence - 1) as usize)
            .is_some_and(|record| record.chain_digest == anchor.chain_digest))
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

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        SegmentedLedger::anchor(self)
    }

    fn contains_anchor(&self, anchor: LedgerAnchor) -> Result<bool, DurableLedgerError> {
        if anchor.sequence == 0 {
            return Ok(anchor.chain_digest.is_zero());
        }
        let snapshot = SegmentedLedger::snapshot(self)?;
        Ok(snapshot
            .records()
            .get((anchor.sequence - 1) as usize)
            .is_some_and(|record| record.chain_digest == anchor.chain_digest))
    }
}
