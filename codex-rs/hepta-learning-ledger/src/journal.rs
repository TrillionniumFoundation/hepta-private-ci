//! The durable Decision append port used by existing learning consumers.
//!
//! Sealed to the actual durable journal implementations; a fixture cannot assert
//! durability by implementing this port. Hosts still authorize files,
//! observations and scope. Backend-specific recovery/index details are mapped
//! into the stable `DurableLedgerError` operational taxonomy at this boundary so
//! consumers do not branch on the selected storage profile.

use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
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

/// Stable append-only Decision port for real durable learning journals.
///
/// The trait intentionally exposes the common operational error vocabulary,
/// not each backend's storage implementation types. This lets a consumer move
/// from the bounded V1/V2 compatibility profiles to the long-horizon profile
/// without a consumer-side storage branch.
pub trait DurableLearningJournal: sealed::Journal {
    fn append(
        &mut self,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError>;
}

impl DurableLearningJournal for DurableLedger {
    fn append(
        &mut self,
        predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        DurableLedger::append(self, predecessor, event)
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
mod tests {
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
