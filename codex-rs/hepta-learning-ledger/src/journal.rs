//! The durable Decision append port used by existing learning consumers.
//! Sealed to the two actual journals; a fixture cannot assert durability by
//! implementing this port. Hosts still authorize files, observations and scope.

use crate::AppendReceipt;
use crate::DurableLedger;
use crate::DurableLedgerError;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::SegmentedLedger;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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

    /// Verify that the supplied predecessor is the exact durable Decision that
    /// authorized a later terminal Outcome/Credit closure.
    ///
    /// This intentionally exposes no general record-reading surface. The
    /// implementation proves chain identity, event identity, run identity and
    /// episode identity inside the sealed ledger owner before a caller may
    /// append terminal facts.
    fn verify_decision_predecessor(
        &self,
        expected_chain_digest: Digest32,
        expected_event_digest: Digest32,
        run_id: &StableId,
        episode_id: &StableId,
    ) -> Result<(), DurableLedgerError>;
}

impl DurableLearningJournal for DurableLedger {
    fn append(
        &mut self,
        predecessor: Digest32,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, DurableLedgerError> {
        DurableLedger::append(self, predecessor, event)
    }

    fn verify_decision_predecessor(
        &self,
        expected_chain_digest: Digest32,
        expected_event_digest: Digest32,
        run_id: &StableId,
        episode_id: &StableId,
    ) -> Result<(), DurableLedgerError> {
        verify_decision_record(
            self.records()?,
            expected_chain_digest,
            expected_event_digest,
            run_id,
            episode_id,
        )
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

    fn verify_decision_predecessor(
        &self,
        expected_chain_digest: Digest32,
        expected_event_digest: Digest32,
        run_id: &StableId,
        episode_id: &StableId,
    ) -> Result<(), DurableLedgerError> {
        let snapshot = self.snapshot()?;
        verify_decision_record(
            snapshot.records(),
            expected_chain_digest,
            expected_event_digest,
            run_id,
            episode_id,
        )
    }
}

fn verify_decision_record(
    records: &[LedgerRecord],
    expected_chain_digest: Digest32,
    expected_event_digest: Digest32,
    run_id: &StableId,
    episode_id: &StableId,
) -> Result<(), DurableLedgerError> {
    if expected_chain_digest.is_zero() || expected_event_digest.is_zero() {
        return Err(DurableLedgerError::Conflict);
    }
    let record = records
        .iter()
        .find(|record| record.chain_digest == expected_chain_digest)
        .ok_or(DurableLedgerError::Conflict)?;
    if record.event_digest != expected_event_digest {
        return Err(DurableLedgerError::Conflict);
    }
    match &record.event {
        LedgerEvent::Decision(decision)
            if &decision.record_id == run_id && &decision.episode_id == episode_id =>
        {
            Ok(())
        }
        _ => Err(DurableLedgerError::Conflict),
    }
}
