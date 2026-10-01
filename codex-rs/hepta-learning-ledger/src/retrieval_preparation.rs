//! Bounded owner-native preparation reads for cognitive delivery correlation.
//!
//! This is a view of the sole product ledger, not a delivery event or training
//! grant. Reads borrow its replay-built index and require its durable witness
//! to be current; they never copy or replay the whole event history.

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use super::LedgerWriter;
use super::ProductionLedgerError;
use super::validate_witness_state;
use crate::AppendReceipt;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::RetrievalAssignmentFact;

impl LedgerWriter {
    /// Resolve one exact owner-issued append receipt, with current witness and
    /// activity checks. A host must independently bind the native request and
    /// context; the receipt does not grant delivery, retry or training access.
    pub fn read_current_retrieval_preparation(
        &self,
        sequence: LogicalSequence,
        event_digest: Digest32,
        chain_digest: Digest32,
        namespace_record_id: &StableId,
        namespace_episode_id: &StableId,
    ) -> Result<&LedgerRecord, ProductionLedgerError> {
        let position = usize::try_from(sequence.get() - 1)
            .map_err(|_| ProductionLedgerError::Binding("retrieval preparation sequence"))?;
        let record = self.backend.core()?.records().get(position).ok_or(
            ProductionLedgerError::Binding("retrieval preparation missing"),
        )?;
        if record.sequence != sequence
            || record.event_digest != event_digest
            || record.chain_digest != chain_digest
        {
            return Err(ProductionLedgerError::Binding(
                "retrieval preparation receipt mismatch",
            ));
        }
        let LedgerEvent::RetrievalAssignment(assignment) = &record.event else {
            return Err(ProductionLedgerError::Binding(
                "retrieval preparation event kind",
            ));
        };
        let identity = preparation_identity(
            self.backend.binding(),
            record.predecessor_chain_digest,
            sequence.get(),
            namespace_record_id,
            namespace_episode_id,
        );
        if assignment.record_id.as_str() != format!("retrieval-preparation:{identity}")
            || assignment.episode_id.as_str() != format!("retrieval-preparation-episode:{identity}")
        {
            return Err(ProductionLedgerError::Binding("retrieval preparation namespace"));
        }
        self.read_current_retrieval_assignment(&assignment.record_id, &assignment.episode_id)
    }

    /// Give one fresh read preparation an identity from this durable owner.
    ///
    /// RPC correlation IDs are local to a client, so they cannot identify a
    /// durable operation across connections. The host's supplied record and
    /// episode IDs are namespace material only; this method replaces them with
    /// a distinct preparation namespace bound to the next witnessed sequence.
    /// The exclusive writer holds issuance and commit together. This is a new
    /// observation, not an idempotent retry or proof of publication/delivery.
    /// Explicit stable-operation retries must use append_retrieval_assignment.
    pub fn append_retrieval_assignment_preparation(
        &mut self,
        mut assignment: RetrievalAssignmentFact,
    ) -> Result<AppendReceipt, ProductionLedgerError> {
        let core = self.backend.core()?;
        let frontier = self.backend.frontier()?;
        if validate_witness_state(core.records(), frontier, self.witness.frontier()?)? != 0 {
            return Err(ProductionLedgerError::WitnessLag);
        }
        let next_sequence =
            frontier
                .anchor
                .sequence
                .checked_add(1)
                .ok_or(ProductionLedgerError::Binding(
                    "retrieval preparation sequence exhausted",
                ))?;
        let identity = preparation_identity(
            self.backend.binding(),
            frontier.anchor.chain_digest,
            next_sequence,
            &assignment.record_id,
            &assignment.episode_id,
        );
        assignment.record_id = StableId::new(format!("retrieval-preparation:{identity}"))
            .map_err(|_| ProductionLedgerError::Binding("retrieval preparation record identity"))?;
        assignment.episode_id = StableId::new(format!("retrieval-preparation-episode:{identity}"))
            .map_err(|_| {
                ProductionLedgerError::Binding("retrieval preparation episode identity")
            })?;
        self.append_retrieval_assignment(frontier.anchor.chain_digest, assignment)
    }

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

fn preparation_identity(
    owner_binding: Digest32,
    predecessor_chain_digest: Digest32,
    sequence: u64,
    namespace_record_id: &StableId,
    namespace_episode_id: &StableId,
) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.retrieval-preparation-identity.v1".to_vec();
    bytes.extend_from_slice(owner_binding.as_array());
    bytes.extend_from_slice(predecessor_chain_digest.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    for id in [namespace_record_id, namespace_episode_id] {
        bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "retrieval_preparation_tests.rs"]
mod tests;
