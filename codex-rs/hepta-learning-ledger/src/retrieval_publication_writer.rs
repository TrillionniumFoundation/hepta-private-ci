//! Typed two-stage ports on the existing witnessed product writer. The host
//! owns the actual Unix write observation; the ledger owns identity and linkage.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AppendReceipt;
use crate::LedgerEvent;
use crate::LedgerWriter;
use crate::ProductionLedgerError;
use crate::RetrievalAssignmentIntentV2;
use crate::RetrievalPublicationConfirmedV2;
use crate::RetrievalPublicationProjectionV2;

impl LedgerWriter {
    pub fn append_retrieval_assignment_intent(
        &mut self,
        expected_predecessor: Digest32,
        intent: RetrievalAssignmentIntentV2,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        self.commit(
            expected_predecessor,
            LedgerEvent::RetrievalAssignmentIntentV2(intent),
        )
    }

    /// Success acknowledges a durable intent and independently synced witness,
    /// allowing the host to start writing the exact frame. It proves no exposure.
    pub fn append_retrieval_assignment_intent_current(
        &mut self,
        intent: RetrievalAssignmentIntentV2,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        self.append_current_event(LedgerEvent::RetrievalAssignmentIntentV2(intent))
    }

    pub fn append_retrieval_publication_confirmed(
        &mut self,
        expected_predecessor: Digest32,
        confirmation: RetrievalPublicationConfirmedV2,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        self.commit(
            expected_predecessor,
            LedgerEvent::RetrievalPublicationConfirmedV2(confirmation),
        )
    }

    /// Host-owned full-write observation only. Exact historical linkage is
    /// required even if the intent was withdrawn after the physical write.
    pub fn append_retrieval_publication_confirmed_current(
        &mut self,
        confirmation: RetrievalPublicationConfirmedV2,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        self.append_current_event(LedgerEvent::RetrievalPublicationConfirmedV2(confirmation))
    }

    pub fn retrieval_publication(
        &self,
        assignment_record_id: &StableId,
    ) -> Result<Option<RetrievalPublicationProjectionV2>, ProductionLedgerError> {
        let core = self.ledger_core()?;
        let Some(mut projection) = core.retrieval_publication(assignment_record_id)? else {
            return Ok(None);
        };
        // A complete ledger suffix may precede its independent witness after an
        // interrupted commit. Preserve the observed history, withhold eligibility
        // until the exact confirmation retry advances that witness.
        if let Some(digest) = projection.confirmation_event_digest {
            let witnessed = self.witness_frontier()?.anchor.sequence;
            projection.ledger_lineage_active &= core
                .active_record_by_digest(&digest)?
                .is_some_and(|record| record.sequence.get() <= witnessed);
        }
        Ok(Some(projection))
    }
}
