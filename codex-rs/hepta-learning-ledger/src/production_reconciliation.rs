//! Historical acknowledgement recovery through the existing production writer.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::LedgerWriter;
use super::ProductionLedgerError;
use crate::AppendReceipt;
use crate::LedgerEvent;

/// Exact identity of a previously committed authenticated Decision or Outcome.
/// This reference grants no append, execution, or current-use authority. The
/// writer resolves every field against its own recovered canonical history.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CommittedLearningAppendV1 {
    pub ledger_binding: Digest32,
    pub record_id: StableId,
    pub event_digest: Digest32,
    pub predecessor_chain_digest: Digest32,
}

impl LedgerWriter {
    /// Recover an acknowledgement without renewing expired signing authority.
    /// Only an existing authenticated Decision/Outcome can be reconciled; no
    /// event body is accepted and a missing record never becomes a new append.
    /// The ordinary commit path retains poison, predecessor and witness checks,
    /// including exact-tail-only recovery when the witness is one record late.
    /// A receipt proves historical durability, not that the record is still
    /// active: correction, revocation and current-use checks remain unchanged.
    pub fn reconcile_committed_append(
        &mut self,
        expected: &CommittedLearningAppendV1,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        if expected.ledger_binding != self.backend.binding() {
            return Err(ProductionLedgerError::Binding("committed append ledger"));
        }
        let record = self
            .backend
            .core()?
            .record_by_id(&expected.record_id)?
            .ok_or(ProductionLedgerError::Binding("committed append missing"))?;
        if record.event_digest != expected.event_digest
            || record.predecessor_chain_digest != expected.predecessor_chain_digest
            || !matches!(
                &record.event,
                LedgerEvent::AuthenticatedDecisionV2(_) | LedgerEvent::AuthenticatedOutcomeV2(_)
            )
        {
            return Err(ProductionLedgerError::Binding("committed append identity"));
        }
        let event = record.event.clone();
        self.commit(expected.predecessor_chain_digest, event)
    }
}

#[cfg(test)]
#[path = "production_reconciliation_tests.rs"]
mod tests;
