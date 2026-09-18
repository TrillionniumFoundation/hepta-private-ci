//! The durable append/snapshot port used by learning consumers. Sealed to the
//! two actual journals; a fixture cannot assert durability by implementing this
//! port. Production callers should use `LedgerWriter`, not call this port directly.

use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
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

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        SegmentedLedger::snapshot(self)
    }
}
