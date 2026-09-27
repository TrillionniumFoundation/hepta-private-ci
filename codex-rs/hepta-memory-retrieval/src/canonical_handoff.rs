//! Compare the existing retrieval adapter with independently received canonical wire.
//! This does not replace the generation-bound owner or grant product authority.

use codex_hepta_cognitive_types::contract::ContractErrorCodeV1;
use codex_hepta_cognitive_types::contract::ContractViolationV1;
use codex_hepta_cognitive_types::contract::Validated;
use codex_hepta_cognitive_types::handoff::CanonicalHandoffV1;
use codex_hepta_cognitive_types::handoff::ConsumerHandoffContextV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1 as CanonicalRecallPacketV1;

use crate::CanonicalRecallShadowContextV1;
use crate::RecallPacketV1;
use crate::adapt_generation_bound_recall_to_canonical_shadow_v1;

/// Derive expected canonical output from the actual legacy adapter. The input
/// context must be supplied by the authenticated owner. Operation/source/snapshot
/// substitution fails before comparing or releasing a payload. Callers retain
/// mismatch receipts for metrics and call `require_match` before cutover use.
pub fn compare_canonical_recall_handoff_v1(
    legacy: &RecallPacketV1,
    projection: CanonicalRecallShadowContextV1,
    context: Validated<ConsumerHandoffContextV1>,
    canonical_wire: &[u8],
) -> Result<CanonicalHandoffV1<CanonicalRecallPacketV1>, ContractViolationV1> {
    if context.consumer != "memory.retrieval"
        || context.legacy_digest != legacy.packet_digest
        || context.source_digest != legacy.candidate_union_digest
        || context.snapshot.vector_digest != legacy.generation_vector_digest
    {
        return Err(ContractViolationV1::new(
            ContractErrorCodeV1::DigestMismatch,
            "handoff.consumer/source/snapshot/legacy",
            "handoff does not identify this native retrieval result",
        ));
    }
    let expected = adapt_generation_bound_recall_to_canonical_shadow_v1(legacy, projection)
        .map_err(|error| ContractViolationV1::new(
            ContractErrorCodeV1::StateConflict,
            "legacyProjection",
            error.to_string(),
        ))?;
    let expected = Validated::new(expected).map_err(|error| error.violation())?;
    CanonicalHandoffV1::compare(context, &expected, canonical_wire)
}
