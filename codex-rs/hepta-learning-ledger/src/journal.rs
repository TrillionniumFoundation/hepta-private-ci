//! The durable Decision append port used by existing qualification consumers.
//! Sealed to the two actual journals; a fixture cannot assert durability by
//! implementing this port. Product callers cannot append arbitrary LedgerEvent
//! values through this public port. Hosts still authorize files and scope.

#[cfg(feature = "qualification-legacy-write")]
use codex_hepta_types::Digest32;

#[cfg(feature = "qualification-legacy-write")]
use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
#[cfg(feature = "qualification-legacy-write")]
use crate::EpisodeDecision;
use crate::LedgerAnchor;
#[cfg(feature = "qualification-legacy-write")]
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::SegmentedLedger;

mod sealed {
    pub trait Journal {}
    impl Journal for super::DurableLedger {}
    impl Journal for super::SegmentedLedger {}
}

/// Sealed read access to the durable owner, with explicit legacy qualification writes.
pub trait DurableLearningJournal: sealed::Journal {
    /// Compatibility/qualification path. Absent from default/product builds.
    #[cfg(feature = "qualification-legacy-write")]
    fn append_decision(
        &mut self,
        expected_predecessor: Digest32,
        decision: EpisodeDecision,
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

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        DurableLedger::snapshot(self)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        let snapshot = DurableLedger::snapshot(self)?;
        Ok(LedgerAnchor {
            sequence: u64::try_from(snapshot.records().len())
                .map_err(|_| DurableLedgerError::Capacity)?,
            chain_digest: snapshot.head_digest,
        })
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

    fn snapshot(&self) -> Result<LedgerSnapshot, DurableLedgerError> {
        SegmentedLedger::snapshot(self)
    }

    fn anchor(&self) -> Result<LedgerAnchor, DurableLedgerError> {
        SegmentedLedger::anchor(self)
    }
}
