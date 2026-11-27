//! Native request preparation from the existing V2 context owner receipts.

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextDeliveryPreparationV2;
use codex_hepta_context_compiler::ContextModelProfileV2;
use codex_hepta_context_compiler::SerializedContextV2;
use codex_hepta_context_compiler::VerifiedAdmissionSnapshotV2;
use codex_hepta_context_compiler::prepare_delivery_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::Error;
use crate::ModelRequest;
use crate::Result;

/// Already-owned compilation artifacts plus a fresh, verified admission view.
/// The source owner supplies the admitted objective. This adapter never opens a
/// store, invents an admission verifier, or changes compaction policy.
pub struct NativeContextInputV2<'a> {
    pub objective_digest: Digest32,
    pub compiled: &'a CompiledContextV2,
    pub serialized: &'a SerializedContextV2,
    pub attachment: &'a ContextAttachmentV2,
    pub model_profile: &'a ContextModelProfileV2,
    pub current_snapshot: &'a VerifiedAdmissionSnapshotV2,
}

pub struct PreparedNativeContextV2 {
    pub request: ModelRequest,
    /// Must be bound into the existing provider invocation receipt. This is a
    /// context safety witness and grants no model/provider/effect authority.
    pub preparation: ContextDeliveryPreparationV2,
}

/// Revalidate current admission and retain the exact owner-serialized bytes.
/// Call after the owning context compiler has prepared/recompiled a frame; an
/// unresolved request must continue using its previously frozen frame.
pub fn prepare_native_context_v2(
    request_id: StableId,
    maximum_output_tokens: u64,
    input: NativeContextInputV2<'_>,
) -> Result<PreparedNativeContextV2> {
    if input.objective_digest.is_zero()
        || input.compiled.receipt().objective_digest() != input.objective_digest
    {
        return Err(Error::Contract("context objective"));
    }
    let preparation = prepare_delivery_v2(
        input.compiled,
        input.serialized,
        input.attachment,
        input.model_profile,
        input.current_snapshot,
        request_id.clone(),
    )
    .map_err(|_| Error::Contract("context delivery preparation"))?;
    let input_tokens = input.serialized.receipt().serialized_token_count();
    if maximum_output_tokens == 0
        || input_tokens
            .checked_add(maximum_output_tokens)
            .is_none_or(|v| v > input.model_profile.maximum_context_tokens)
    {
        return Err(Error::Limit("model context including output reservation"));
    }
    let payload = std::str::from_utf8(input.serialized.payload())
        .map_err(|_| Error::Contract("native context UTF-8"))?;
    Ok(PreparedNativeContextV2 {
        request: ModelRequest {
            request_id,
            payload: payload.into(),
            context_digest: input.serialized.receipt().payload_digest(),
            input_tokens,
            maximum_output_tokens,
        },
        preparation,
    })
}
