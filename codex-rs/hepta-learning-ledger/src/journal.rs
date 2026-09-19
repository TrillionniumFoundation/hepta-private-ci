//! The durable Decision append port used by existing qualification consumers.
//! Sealed to the two actual journals; a fixture cannot assert durability by
//! implementing this port. Product callers cannot append arbitrary LedgerEvent
//! values through this public port. Hosts still authorize files and scope.

use codex_hepta_types::Digest32;

use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
#[cfg(feature = "qualification-legacy-write")]
use crate::EpisodeDecision;
use crate::LedgerAnchor;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::SegmentedLedger;

mod sealed {
    pub trait Journal {}
    impl Journal for super::DurableLedger {}
    impl Journal for super::SegmentedLedger {}
}

/// Capability used only by this crate's authenticated production facade.
/// The type is public solely because it appears in a public sealed-trait method;
/// its private field and crate-private constructor prevent safe external callers
/// from obtaining a value.
#[doc(hidden)]
pub struct ProductionAppendPermit {
    _private: (),
}

impl ProductionAppendPermit {
    pub(crate) const fn new() -> Self {
        Self { _private: () }
    }
}

pub trait DurableLearningJournal: sealed::Journal {
    /// Compatibility/qualification path. Absent from default/product builds.
    #[cfg(feature = "qualification-legacy-write")]
    fn append_decision(
        &mut self,
        expected_predecessor: Digest32,
        decision: EpisodeDecision,
    ) -> Result<AppendReceipt, DurableLedgerError>;

    /// Arbitrary durable facts require the crate-owned production permit.
    #[doc(hidden)]
    fn append_production(
        &mut self,
        _permit: ProductionAppendPermit,
        expected_predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError>;

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError>;

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError>;
}

impl DurableLearningJournal for DurableLedger {
    #[cfg(feature = "qualification-legacy-write")]
    fn append_decision(
        &mut self,
        predecessor: Digest32,
        decision: EpisodeDecision,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        DurableLedger::append(self, predecessor, LedgerEvent::Decision(decision))
    }

    fn append_production(
        &mut self,
        _permit: ProductionAppendPermit,
        predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        DurableLedger::append(self, predecessor, event)
    }

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        DurableLedger::snapshot(self)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        DurableLedger::anchor(self)
    }
}

impl DurableLearningJournal for SegmentedLedger {
    #[cfg(feature = "qualification-legacy-write")]
    fn append_decision(
        &mut self,
        predecessor: Digest32,
        decision: EpisodeDecision,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        SegmentedLedger::append(self, predecessor, LedgerEvent::Decision(decision))
    }

    fn append_production(
        &mut self,
        _permit: ProductionAppendPermit,
        predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        SegmentedLedger::append(self, predecessor, event)
    }

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        SegmentedLedger::snapshot(self)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        SegmentedLedger::anchor(self)
    }
}
