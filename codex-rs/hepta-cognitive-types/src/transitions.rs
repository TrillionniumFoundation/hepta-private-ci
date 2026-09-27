//! Contextual checks against explicitly supplied, owner-authenticated pre-state.
//!
//! These routines prove a relation between values, not that the supplied
//! pre-state is the live head. The storage owner must perform them under its
//! existing authority check and transaction/fence; no second writer is created.

use codex_hepta_types::Digest32;

use crate::MemoryRecord;
use crate::RecordState;
use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;
use crate::contract::ValidateContractV1;
use crate::contract::Validated;
use crate::lane_c::CognitiveSnapshotKeyV1;
use crate::lane_c::MemoryWriteDisposition;
use crate::lane_c::MemoryWriteIntentV1;
use crate::lane_c::MemoryWriteOutcomeV1;
use crate::lane_c::MemoryWriteReceiptV1;

impl ValidateContractV1 for MemoryRecord {
    type Error = crate::Error;

    fn validate_contract_v1(&self) -> Result<(), Self::Error> {
        self.validate()
    }
}

impl Validated<MemoryRecord> {
    #[must_use]
    pub fn checked_record_digest(&self) -> Digest32 {
        self.as_inner().record_digest()
    }
}

/// Validate exactly one successor, never an arbitrary jump or another record.
/// Tombstones are terminal in this compatibility record protocol. A future
/// restore protocol must carry distinct, owner-authorized semantics. Memory
/// kind is revisioned content in the existing owner protocol, not an identity.
pub fn validate_record_transition_v1(
    previous: &Validated<MemoryRecord>,
    next: &Validated<MemoryRecord>,
) -> Result<(), ContractViolationV1> {
    if previous.record_id != next.record_id {
        return Err(ContractViolationV1::new(
            ContractErrorCodeV1::StateConflict,
            "recordId",
            "a revision cannot change its record identity",
        ));
    }
    if previous.revision.get().checked_add(1) != Some(next.revision.get())
        || next.predecessor_digest != Some(previous.checked_record_digest())
    {
        return Err(ContractViolationV1::new(
            ContractErrorCodeV1::DigestMismatch,
            "revision/predecessorDigest",
            "successor must reference the exact immediately preceding revision",
        ));
    }
    if previous.state == RecordState::Tombstone {
        return Err(ContractViolationV1::new(
            ContractErrorCodeV1::StateConflict,
            "state",
            "a terminal tombstone has no successor in this protocol",
        ));
    }
    Ok(())
}

/// Check receipt scope and monotonicity against the entire approved intent.
/// A receipt may observe independently advancing non-memory owners, so this
/// does not assume that all unrelated generations stay equal. It does require
/// an unchanged semantic execution profile and no frontier rollback.
pub fn validate_write_transition_v1(
    intent: &MemoryWriteIntentV1,
    receipt: &MemoryWriteReceiptV1,
) -> Result<(), ContractViolationV1> {
    receipt.validate_against_intent(intent).map_err(|error| error.violation())
}

// Constructors and integrity validation call this same non-recursive check.
// The expected snapshot is retained privately and is already digest-bound by
// the complete intent, so historical receipts remain self-validating.
pub(crate) fn validate_receipt_transition_v1(
    expected_snapshot: &CognitiveSnapshotKeyV1,
    observed_snapshot: &CognitiveSnapshotKeyV1,
    outcome: &MemoryWriteOutcomeV1,
) -> Result<(), ContractViolationV1> {
    let expected = &expected_snapshot.vector;
    let observed = &observed_snapshot.vector;
    if expected.scope_id != observed.scope_id || expected.purpose_id != observed.purpose_id {
        return Err(ContractViolationV1::new(
            ContractErrorCodeV1::StateConflict,
            "snapshot.scopeId/purposeId",
            "a write result cannot move to another scope or purpose",
        ));
    }
    // Rejection observes state; it does not commit or certify a transition.
    // A request naming a future frontier can legitimately be rejected.
    if matches!(outcome, MemoryWriteOutcomeV1::Rejected { .. }) {
        return Ok(());
    }
    if observed.memory_ledger_frontier < expected.memory_ledger_frontier
        || observed.knowledge_fact_frontier < expected.knowledge_fact_frontier
        || observed.tombstone_frontier < expected.tombstone_frontier
        || observed.source_ledger_frontier < expected.source_ledger_frontier
        || observed.knowledge_graph_generation < expected.knowledge_graph_generation
        || observed.compact_checkpoint_generation < expected.compact_checkpoint_generation
        || observed.prompt_registry_revision < expected.prompt_registry_revision
        || observed.authority_epoch < expected.authority_epoch
    {
        return Err(ContractViolationV1::new(
            ContractErrorCodeV1::StateConflict,
            "snapshot.frontiers",
            "a receipt cannot roll back an approved frontier",
        ));
    }
    if let MemoryWriteOutcomeV1::Committed { disposition, .. } = outcome {
        if observed.authority_epoch != expected.authority_epoch
            || observed.retrieval_profile_digest != expected.retrieval_profile_digest
            || observed.encoder_preprocessor_digest != expected.encoder_preprocessor_digest
            || observed.model_digest != expected.model_digest
            || observed.tokenizer_digest != expected.tokenizer_digest
            || observed.template_digest != expected.template_digest
            || observed.tool_schema_digest != expected.tool_schema_digest
        {
            return Err(ContractViolationV1::new(
                ContractErrorCodeV1::StateConflict,
                "snapshot.executionProfile",
                "committed receipt changed the authorized execution profile",
            ));
        }
        let valid_frontier = match disposition {
            MemoryWriteDisposition::Inserted => {
                observed.memory_ledger_frontier > expected.memory_ledger_frontier
            }
            MemoryWriteDisposition::Unchanged => {
                observed.memory_ledger_frontier == expected.memory_ledger_frontier
            }
        };
        if !valid_frontier {
            return Err(ContractViolationV1::new(
                ContractErrorCodeV1::StateConflict,
                "outcome.disposition/committedFrontier",
                "inserted must advance the memory frontier; unchanged must not",
            ));
        }
    }
    Ok(())
}
