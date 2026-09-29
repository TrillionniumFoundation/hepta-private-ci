//! Bounded owner-native preparation reads for cognitive delivery correlation.
//!
//! This is a view of the sole product ledger, not a delivery event or training
//! grant. Reads borrow its replay-built index and require its durable witness
//! to be current; they never copy or replay the whole event history.

use codex_hepta_types::StableId;

use super::LedgerWriter;
use super::ProductionLedgerError;
use super::validate_witness_state;
use crate::LedgerEvent;
use crate::LedgerRecord;

impl LedgerWriter {
    /// Read one current, non-revoked assignment from this existing owner.
    ///
    /// The host must separately authenticate the requesting consumer and join
    /// the exact context to an independently observed native dispatch/turn. The
    /// legacy `context_exposed` field by itself proves neither socket delivery
    /// nor model use. The borrow prevents mutation through this writer while
    /// the host checks the other owner; it grants no future-use authority.
    pub fn read_current_retrieval_assignment(
        &self,
        record_id: &StableId,
        episode_id: &StableId,
    ) -> Result<&LedgerRecord, ProductionLedgerError> {
        let core = self.backend.core()?;
        let lag = validate_witness_state(
            core.records(),
            self.backend.frontier()?,
            self.witness.frontier()?,
        )?;
        if lag != 0 {
            return Err(ProductionLedgerError::WitnessLag);
        }
        let record = core
            .active_record_by_id(record_id)?
            .ok_or(ProductionLedgerError::Binding(
                "retrieval assignment missing or inactive",
            ))?;
        match &record.event {
            LedgerEvent::RetrievalAssignment(value)
                if &value.record_id == record_id && &value.episode_id == episode_id =>
            {
                Ok(record)
            }
            _ => Err(ProductionLedgerError::Binding(
                "retrieval assignment identity or kind",
            )),
        }
    }
}

#[cfg(test)]
#[path = "retrieval_preparation_tests.rs"]
mod tests;
