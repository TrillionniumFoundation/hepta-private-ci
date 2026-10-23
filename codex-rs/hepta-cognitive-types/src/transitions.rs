//! Checked transitions for existing owner-local records and write receipts.
//!
//! These checks constrain the relationship between two already valid values.
//! They do not authenticate an owner, authorize a mutation, or change V1 bytes.

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

pub fn validate_record_transition_v1(
    predecessor: &Validated<MemoryRecord>,
    successor: &Validated<MemoryRecord>,
) -> Result<(), ContractViolationV1> {
    if predecessor.record_id != successor.record_id {
        return Err(conflict(
            "recordId",
            "record identity cannot change across a revision",
        ));
    }
    if predecessor.state == RecordState::Tombstone {
        return Err(conflict("state", "a tombstone cannot be resurrected"));
    }
    if predecessor.revision.get().checked_add(1) != Some(successor.revision.get()) {
        return Err(conflict(
            "revision",
            "successor must have the exact next revision",
        ));
    }
    if successor.predecessor_digest != Some(predecessor.checked_record_digest()) {
        return Err(ContractViolationV1::new(
            ContractErrorCodeV1::DigestMismatch,
            "predecessorDigest",
            "successor does not bind the exact predecessor",
        ));
    }
    // Kind is revisioned content, not identity; legitimate reclassification is
    // permitted by this structural check and remains subject to owner policy.
    Ok(())
}

pub fn validate_write_transition_v1(
    intent: &MemoryWriteIntentV1,
    receipt: &MemoryWriteReceiptV1,
) -> Result<(), ContractViolationV1> {
    receipt
        .validate_against_intent(intent)
        .map_err(|error| error.violation())
}

pub(crate) fn validate_receipt_transition_v1(
    expected: &CognitiveSnapshotKeyV1,
    observed: &CognitiveSnapshotKeyV1,
    outcome: &MemoryWriteOutcomeV1,
) -> Result<(), ContractViolationV1> {
    let before = &expected.vector;
    let after = &observed.vector;
    if before.scope_id != after.scope_id {
        return Err(conflict(
            "snapshot.scopeId",
            "a write result cannot substitute the scope",
        ));
    }
    if before.purpose_id != after.purpose_id {
        return Err(conflict(
            "snapshot.purposeId",
            "a write result cannot substitute the purpose",
        ));
    }
    let MemoryWriteOutcomeV1::Committed { disposition, .. } = outcome else {
        // A rejected request may contain a future/stale expected snapshot. Its
        // observed state is not a successful mutation and need not advance it.
        return Ok(());
    };
    for (field, previous, next) in [
        (
            "snapshot.memoryLedgerFrontier",
            before.memory_ledger_frontier,
            after.memory_ledger_frontier,
        ),
        (
            "snapshot.knowledgeFactFrontier",
            before.knowledge_fact_frontier,
            after.knowledge_fact_frontier,
        ),
        (
            "snapshot.tombstoneFrontier",
            before.tombstone_frontier,
            after.tombstone_frontier,
        ),
        (
            "snapshot.sourceLedgerFrontier",
            before.source_ledger_frontier,
            after.source_ledger_frontier,
        ),
        (
            "snapshot.knowledgeGraphGeneration",
            before.knowledge_graph_generation.get(),
            after.knowledge_graph_generation.get(),
        ),
        (
            "snapshot.compactCheckpointGeneration",
            before.compact_checkpoint_generation.get(),
            after.compact_checkpoint_generation.get(),
        ),
        (
            "snapshot.promptRegistryRevision",
            before.prompt_registry_revision.get(),
            after.prompt_registry_revision.get(),
        ),
        (
            "snapshot.authorityEpoch",
            before.authority_epoch,
            after.authority_epoch,
        ),
    ] {
        if next < previous {
            return Err(conflict(
                field,
                "a committed write cannot regress an observed frontier",
            ));
        }
    }
    if before.authority_epoch != after.authority_epoch {
        return Err(conflict(
            "snapshot.authorityEpoch",
            "a commit cannot silently change authority epoch",
        ));
    }
    for (field, previous, next) in [
        (
            "snapshot.retrievalProfileDigest",
            before.retrieval_profile_digest,
            after.retrieval_profile_digest,
        ),
        (
            "snapshot.encoderPreprocessorDigest",
            before.encoder_preprocessor_digest,
            after.encoder_preprocessor_digest,
        ),
        (
            "snapshot.modelDigest",
            before.model_digest,
            after.model_digest,
        ),
        (
            "snapshot.tokenizerDigest",
            before.tokenizer_digest,
            after.tokenizer_digest,
        ),
        (
            "snapshot.templateDigest",
            before.template_digest,
            after.template_digest,
        ),
        (
            "snapshot.toolSchemaDigest",
            before.tool_schema_digest,
            after.tool_schema_digest,
        ),
    ] {
        if previous != next {
            return Err(conflict(
                field,
                "a commit cannot silently change its interpretation profile",
            ));
        }
    }
    let frontier_valid = match disposition {
        MemoryWriteDisposition::Inserted => {
            after.memory_ledger_frontier > before.memory_ledger_frontier
        }
        MemoryWriteDisposition::Unchanged => {
            after.memory_ledger_frontier == before.memory_ledger_frontier
        }
    };
    if !frontier_valid {
        return Err(conflict(
            "snapshot.memoryLedgerFrontier",
            "frontier does not match the write disposition",
        ));
    }
    Ok(())
}

fn conflict(field: &'static str, message: &'static str) -> ContractViolationV1 {
    ContractViolationV1::new(ContractErrorCodeV1::StateConflict, field, message)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lane_c::LaneCGenerationVectorV1;
    use crate::lane_c::MemoryWriteRejectionCodeV1;
    use codex_hepta_types::Generation;
    use codex_hepta_types::Revision;
    use codex_hepta_types::StableId;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("fixture id")
    }
    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }
    fn snapshot(frontier: u64) -> CognitiveSnapshotKeyV1 {
        CognitiveSnapshotKeyV1::new(LaneCGenerationVectorV1 {
            scope_id: id("scope:transition"),
            purpose_id: id("purpose:transition"),
            memory_ledger_frontier: frontier,
            knowledge_fact_frontier: 5,
            tombstone_frontier: 3,
            source_ledger_frontier: 9,
            knowledge_graph_generation: Generation::new(3).expect("generation"),
            compact_checkpoint_generation: Generation::new(2).expect("generation"),
            prompt_registry_revision: Revision::new(4).expect("revision"),
            retrieval_profile_digest: digest("retrieval"),
            encoder_preprocessor_digest: digest("encoder"),
            authority_epoch: 11,
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
        })
        .expect("snapshot")
    }
    fn intent() -> MemoryWriteIntentV1 {
        MemoryWriteIntentV1::new(
            id("intent:transition"),
            digest("candidate"),
            snapshot(7),
            digest("fence"),
            digest("authorization"),
        )
        .expect("intent")
    }
    fn committed(
        after: CognitiveSnapshotKeyV1,
        disposition: MemoryWriteDisposition,
    ) -> Result<MemoryWriteReceiptV1, crate::lane_c::LaneCContractError> {
        let frontier = after.vector.memory_ledger_frontier;
        MemoryWriteReceiptV1::committed(
            &intent(),
            after,
            id("record:transition"),
            digest("record"),
            frontier,
            disposition,
        )
    }

    #[test]
    fn receipt_construction_enforces_inserted_and_unchanged_frontiers() {
        committed(snapshot(8), MemoryWriteDisposition::Inserted).expect("insert advances");
        committed(snapshot(7), MemoryWriteDisposition::Unchanged).expect("unchanged stays");
        assert!(committed(snapshot(7), MemoryWriteDisposition::Inserted).is_err());
        assert!(committed(snapshot(6), MemoryWriteDisposition::Inserted).is_err());
        assert!(committed(snapshot(8), MemoryWriteDisposition::Unchanged).is_err());
    }

    #[test]
    fn receipt_rejects_scope_purpose_and_profile_substitution() {
        for index in 0..9 {
            let mut vector = snapshot(8).vector;
            match index {
                0 => vector.scope_id = id("scope:other"),
                1 => vector.purpose_id = id("purpose:other"),
                2 => vector.authority_epoch += 1,
                3 => vector.retrieval_profile_digest = digest("other"),
                4 => vector.encoder_preprocessor_digest = digest("other"),
                5 => vector.model_digest = digest("other"),
                6 => vector.tokenizer_digest = digest("other"),
                7 => vector.template_digest = digest("other"),
                _ => vector.tool_schema_digest = digest("other"),
            }
            let after =
                CognitiveSnapshotKeyV1::new(vector).expect("internally valid substituted snapshot");
            assert!(
                committed(after, MemoryWriteDisposition::Inserted).is_err(),
                "substitution {index}"
            );
        }
    }

    #[test]
    fn receipt_rejects_every_committed_frontier_regression() {
        for index in 0..8 {
            let mut vector = snapshot(8).vector;
            match index {
                0 => vector.memory_ledger_frontier = 6,
                1 => vector.knowledge_fact_frontier -= 1,
                2 => vector.tombstone_frontier -= 1,
                3 => vector.source_ledger_frontier -= 1,
                4 => vector.knowledge_graph_generation = Generation::new(2).expect("generation"),
                5 => vector.compact_checkpoint_generation = Generation::new(1).expect("generation"),
                6 => vector.prompt_registry_revision = Revision::new(3).expect("revision"),
                _ => vector.authority_epoch -= 1,
            }
            let after =
                CognitiveSnapshotKeyV1::new(vector).expect("internally valid regressed snapshot");
            assert!(
                committed(after, MemoryWriteDisposition::Inserted).is_err(),
                "regression {index}"
            );
        }
    }

    #[test]
    fn rejected_future_request_keeps_observed_state_without_fabricating_a_commit() {
        let receipt = MemoryWriteReceiptV1::rejected(
            &intent(),
            snapshot(6),
            MemoryWriteRejectionCodeV1::SnapshotStale,
            digest("denied"),
        )
        .expect("future request rejection");
        assert!(receipt.record_id().is_none());
        validate_write_transition_v1(&intent(), &receipt).expect("valid rejection");
        let mut wrong = snapshot(6).vector;
        wrong.scope_id = id("scope:other");
        assert!(
            MemoryWriteReceiptV1::rejected(
                &intent(),
                CognitiveSnapshotKeyV1::new(wrong).expect("snapshot"),
                MemoryWriteRejectionCodeV1::SnapshotStale,
                digest("denied")
            )
            .is_err()
        );
    }
}
