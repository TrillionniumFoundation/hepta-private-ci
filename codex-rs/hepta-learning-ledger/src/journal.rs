//! The durable Decision append port used by existing learning consumers.
//! Sealed to the actual journal implementations; a fixture cannot assert durability by
//! implementing this port. Hosts still authorize files, observations and scope.

use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LongHorizonLedgerErrorV1;
use crate::LongHorizonSegmentedLedgerV1;
use crate::PersistentIndexErrorV1;
use crate::PersistentIndexedLedgerErrorV1;
use crate::SegmentedLedger;
use codex_hepta_types::Digest32;

mod sealed {
    pub trait Journal {}
    impl Journal for super::DurableLedger {}
    impl Journal for super::SegmentedLedger {}
    impl Journal for super::LongHorizonSegmentedLedgerV1 {}
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

impl DurableLearningJournal for LongHorizonSegmentedLedgerV1 {
    fn append(
        &mut self,
        predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        LongHorizonSegmentedLedgerV1::append(self, predecessor, event)
            .map_err(map_long_horizon_error)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        LongHorizonSegmentedLedgerV1::checkpoint(self)
            .map(|checkpoint| checkpoint.head_anchor)
            .map_err(map_long_horizon_error)
    }

    fn contains_anchor(&self, anchor: LedgerAnchor) -> Result<bool, DurableLedgerError> {
        LongHorizonSegmentedLedgerV1::contains_anchor(self, anchor)
            .map_err(map_long_horizon_error)
    }
}

fn map_long_horizon_error(error: LongHorizonLedgerErrorV1) -> DurableLedgerError {
    match error {
        LongHorizonLedgerErrorV1::Durable(error) => error,
        LongHorizonLedgerErrorV1::Index(error) => map_persistent_ledger_error(error),
        LongHorizonLedgerErrorV1::InvalidCheckpoint => DurableLedgerError::InvalidAnchor,
        LongHorizonLedgerErrorV1::CatalogCorrupt => DurableLedgerError::Corrupt,
        LongHorizonLedgerErrorV1::Poisoned => DurableLedgerError::Poisoned,
    }
}

fn map_persistent_ledger_error(error: PersistentIndexedLedgerErrorV1) -> DurableLedgerError {
    match error {
        PersistentIndexedLedgerErrorV1::Index(error) => map_persistent_index_error(error),
        PersistentIndexedLedgerErrorV1::Semantic(error) => DurableLedgerError::Semantic(error),
        PersistentIndexedLedgerErrorV1::Poisoned => DurableLedgerError::Poisoned,
        PersistentIndexedLedgerErrorV1::AnchorMismatch => DurableLedgerError::AnchorMismatch,
    }
}

fn map_persistent_index_error(error: PersistentIndexErrorV1) -> DurableLedgerError {
    match error {
        PersistentIndexErrorV1::InvalidCacheLimit => DurableLedgerError::InvalidLimit,
        PersistentIndexErrorV1::InvalidAnchor => DurableLedgerError::InvalidAnchor,
        PersistentIndexErrorV1::Corrupt | PersistentIndexErrorV1::HashCollision => {
            DurableLedgerError::Corrupt
        }
        PersistentIndexErrorV1::ValueTooLarge => DurableLedgerError::Capacity,
        PersistentIndexErrorV1::Io(kind) => DurableLedgerError::Io(kind),
    }
}

#[cfg(test)]
mod long_horizon_journal_tests {
    use super::*;

    #[test]
    fn long_horizon_error_mapping_preserves_operational_meaning() {
        assert_eq!(
            map_long_horizon_error(LongHorizonLedgerErrorV1::Durable(
                DurableLedgerError::Conflict,
            )),
            DurableLedgerError::Conflict
        );
        assert_eq!(
            map_long_horizon_error(LongHorizonLedgerErrorV1::Index(
                PersistentIndexedLedgerErrorV1::Index(PersistentIndexErrorV1::HashCollision),
            )),
            DurableLedgerError::Corrupt
        );
        assert_eq!(
            map_long_horizon_error(LongHorizonLedgerErrorV1::Poisoned),
            DurableLedgerError::Poisoned
        );
    }
}
