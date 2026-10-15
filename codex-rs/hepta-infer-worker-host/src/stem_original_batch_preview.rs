//! Non-authorizing typed Stem -> ORIGINAL signed Neuron batch request bridge.
//!
//! This adapter does not load weights, issue a FinalUse grant, bind the real
//! Control/CNS owner, enqueue, or dispatch. It transforms one already bounded
//! Stem feature reference into the *existing* NeuronFeatureRequest and the
//! *existing* batched_neuron::neuron_batch_final_use_binding_v1.
//!
//! Only the original OriginalEvidenceBoundNeuronWorkerV1 may actually enqueue
//! the separately signed request after current Control/CNS and Evidence checks.

use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_infer_core::SharedStemQ24BufferV1;
use codex_hepta_infer_core::StemAccessContextV1;
use codex_hepta_infer_core::StemFeatureRefV1;
use codex_hepta_infer_core::StemHeadBindingV1;
use codex_hepta_infer_core::microbatch::MicrobatchKeyV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::batched_neuron::neuron_batch_final_use_binding_v1;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::WorkerRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;

/// Data-only preview. No grant, signed nonce, queue slot, Evidence receipt,
/// original-Control authentication or physical backend effect is implied.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedStemOriginalBatchPreviewV1 {
    pub model_id: String,
    pub request: NeuronFeatureRequest,
    pub exact_final_use_binding: FinalUseBinding,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StemOriginalBatchPreviewErrorV1 {
    InvalidIdentity,
    InvalidScopeFence,
    InvalidGeneration,
    InvalidLease,
    InvalidSource,
    InvalidHead,
    PayloadMismatch,
    OriginalBatchBinding,
}

impl std::fmt::Display for StemOriginalBatchPreviewErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for StemOriginalBatchPreviewErrorV1 {}

/// Bind ONE prospective Head to the existing original signed batch protocol.
///
/// An independently authenticated inference.control owner must supply the
/// selected source, access claims, physical batch key and WorkerRequest. This
/// pure helper can validate their consistency but CANNOT authenticate them.
///
/// Do not "repair" a missing or stale payload/lease digest. The caller must
/// separately obtain an original-owner signed FinalUse grant matching the
/// returned exact binding, then use the real Evidence-bound Worker.
pub fn prepare_stem_original_batch_preview_v1(
    worker_id: &str,
    source: &StemFeatureRefV1,
    access: &StemAccessContextV1,
    head: &StemHeadBindingV1,
    shared: &SharedStemQ24BufferV1,
    key: &MicrobatchKeyV1,
    authorization: &WorkerRequest,
) -> Result<PreparedStemOriginalBatchPreviewV1, StemOriginalBatchPreviewErrorV1> {
    use StemOriginalBatchPreviewErrorV1 as Denied;

    if worker_id.is_empty()
        || authorization.request_id.as_str() != head.request_id.as_str()
        || authorization.request_id.is_empty()
        || authorization.reservation_id.is_empty()
        || authorization.maximum_tokens == 0
        || authorization.maximum_tokens > authorization.reservation_maximum_tokens
        || authorization.cancelled
    {
        return Err(Denied::InvalidIdentity);
    }
    if key.scope_id != source.scope_id
        || key.route_fence == 0
        || source.scope_id != access.scope_id
        || source.principal_id != access.principal_id
    {
        return Err(Denied::InvalidScopeFence);
    }
    if key.generation != source.stem_generation
        || source.stem_generation != access.stem_generation
        || key.authority_epoch == 0
        || key.authority_epoch != source.authority_epoch
        || source.authority_epoch != access.authority_epoch
    {
        return Err(Denied::InvalidGeneration);
    }
    if access.revocation_observed
        || access.now_ms >= source.lease_expires_at_ms
        || access.now_ms >= authorization.deadline_ms
        || authorization.deadline_ms > source.lease_expires_at_ms
    {
        return Err(Denied::InvalidLease);
    }
    if authorization.model_digest != key.model_digest.to_string()
        || authorization.reservation_model_digest != authorization.model_digest
    {
        return Err(Denied::InvalidHead);
    }

    // The typed immutable view is checked against the CURRENT caller access
    // before producing the one necessary legacy owned V1 request. The second
    // refresh prevents a different caller-supplied source descriptor being
    // substituted for the immutable buffer's private source.
    let view = shared
        .borrow_for_head(access, head)
        .map_err(|_| Denied::InvalidSource)?;
    if view.authority().grants_any() {
        return Err(Denied::InvalidSource);
    }
    let bound = view
        .materialize_owned_after_refresh(source, access, head)
        .map_err(|_| Denied::InvalidSource)?;
    if bound.authority.grants_any() {
        return Err(Denied::InvalidSource);
    }

    let source_input_digest = Digest32::of_parts(&[
        b"hepta.infer-worker.scoped-stem-input.v1",
        source.input_digest.as_array(),
        bound.feature_ref_digest.as_array(),
    ]);
    let request = NeuronFeatureRequest {
        authorization: authorization.clone(),
        encoder_digest: bound.request.encoder_digest.to_string(),
        head_digest: bound.request.head_digest.to_string(),
        weights_digest: bound.request.weights_digest.to_string(),
        input_digest: source_input_digest.to_string(),
        feature_vector_q24: bound.request.feature_vector_q24,
        expected_output_width: bound.request.expected_output_width,
    };

    // A matching payload declaration is mandatory. No encoder/Head/request
    // digest is silently rewritten to persuade the original signer to grant
    // an effect. The immutable shared Arc remains owned by its original
    // buffer; one Vec materialization is required by the V1 queue ABI.
    let actual = canonical_neuron_feature_payload_digest(&request);
    if actual != authorization.payload_digest || actual != authorization.lease_payload_digest {
        return Err(Denied::PayloadMismatch);
    }
    let exact_final_use_binding = neuron_batch_final_use_binding_v1(worker_id, key, &request)
        .map_err(|_| Denied::OriginalBatchBinding)?;

    Ok(PreparedStemOriginalBatchPreviewV1 {
        model_id: head.head_model_id.to_string(),
        request,
        exact_final_use_binding,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "stem_original_batch_preview_tests.rs"]
mod tests;
