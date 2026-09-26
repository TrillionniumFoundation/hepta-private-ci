//! Strict provider-bound prompt composition.
//!
//! This adapter turns an already validated prompt-registry compilation into a
//! construction-closed dispatch package. The provider host builds its final
//! request exactly once from the canonical context and the current delivery
//! preparation. That request is then byte-covered, tokenized with the qualified
//! provider/model tokenizer, and returned for direct submission. Reconstructing
//! a request after this function invalidates the proof package.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::CanonicalContextPayloadV2;
use codex_hepta_context_compiler::CanonicalSerializedContextProofV2;
use codex_hepta_context_compiler::ContextAdmissionSnapshotV2;
use codex_hepta_context_compiler::ContextAdmissionVerifierV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextDeliveryPreparationV2;
use codex_hepta_context_compiler::ContextRealizedItemV2;
use codex_hepta_context_compiler::ContextRoleV2;
use codex_hepta_context_compiler::ExactProviderRequestTokenizerV2;
use codex_hepta_context_compiler::ExactTokenizerV2;
use codex_hepta_context_compiler::FinalProviderRequestTokenizationV2;
use codex_hepta_context_compiler::ProviderBoundContextErrorV2;
use codex_hepta_context_compiler::ProviderRequestFramingPolicyV2;
use codex_hepta_context_compiler::ProviderRequestSegmentV2;
use codex_hepta_context_compiler::VerifiedAdmissionSnapshotSuccessorV2;
use codex_hepta_context_compiler::VerifiedAdmissionSnapshotV2;
use codex_hepta_context_compiler::VerifiedProviderRequestV2;
use codex_hepta_context_compiler::build_attachment;
use codex_hepta_context_compiler::prepare_delivery_from_successor_v2;
use codex_hepta_context_compiler::record_canonical_serialization_v2;
use codex_hepta_context_compiler::tokenize_verified_provider_request_v2;
use codex_hepta_context_compiler::verify_admission_snapshot_v2;
use codex_hepta_context_compiler::verify_provider_request_coverage_v2;
use codex_hepta_context_compiler::verify_typed_admission_snapshot_successor_v2;
use codex_hepta_prompt_registry::PromptRoleV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::PromptRegistryCompilationErrorV2;
use crate::PromptRegistryCompiledContextV2;

const PROVIDER_BOUND_PROMPT_DOMAIN: &[u8] = b"hepta.provider-bound-prompt.v2\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderRequestMaterializationV2 {
    pub exact_request_bytes: Vec<u8>,
    pub segments: Vec<ProviderRequestSegmentV2>,
    pub wire_semantic_digest: Digest32,
}

/// Qualified provider request constructor.
///
/// The returned bytes are the only bytes that may be submitted. The builder
/// must identify every byte either as the canonical context segment or as an
/// approved typed framing segment.
pub trait ProviderRequestBuilderV2 {
    fn build_provider_request(
        &self,
        canonical_context: &CanonicalContextPayloadV2,
        preparation: &ContextDeliveryPreparationV2,
    ) -> Result<ProviderRequestMaterializationV2, String>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundPromptPrepareRequestV2 {
    pub serialization_id: StableId,
    pub attachment_id: StableId,
    pub preparation_id: StableId,
    pub attachment_snapshot: ContextAdmissionSnapshotV2,
    pub pre_dispatch_snapshot: ContextAdmissionSnapshotV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedProviderBoundPromptV2 {
    realizations: Vec<ContextRealizedItemV2>,
    canonical_serialization: CanonicalSerializedContextProofV2,
    attachment_snapshot: VerifiedAdmissionSnapshotV2,
    attachment: ContextAttachmentV2,
    snapshot_successor: VerifiedAdmissionSnapshotSuccessorV2,
    preparation: ContextDeliveryPreparationV2,
    provider_request: VerifiedProviderRequestV2,
    final_tokenization: FinalProviderRequestTokenizationV2,
    bundle_digest: Digest32,
    authority: AuthorityPosture,
}

impl PreparedProviderBoundPromptV2 {
    #[must_use]
    pub fn canonical_serialization(&self) -> &CanonicalSerializedContextProofV2 {
        &self.canonical_serialization
    }

    #[must_use]
    pub const fn attachment(&self) -> &ContextAttachmentV2 {
        &self.attachment
    }

    #[must_use]
    pub const fn snapshot_successor(&self) -> &VerifiedAdmissionSnapshotSuccessorV2 {
        &self.snapshot_successor
    }

    #[must_use]
    pub const fn preparation(&self) -> &ContextDeliveryPreparationV2 {
        &self.preparation
    }

    /// Exact provider request bytes that the host must submit without rebuild.
    #[must_use]
    pub const fn provider_request(&self) -> &VerifiedProviderRequestV2 {
        &self.provider_request
    }

    #[must_use]
    pub const fn final_tokenization(&self) -> &FinalProviderRequestTokenizationV2 {
        &self.final_tokenization
    }

    #[must_use]
    pub const fn bundle_digest(&self) -> Digest32 {
        self.bundle_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        source: &PromptRegistryCompiledContextV2,
        framing_policy: &impl ProviderRequestFramingPolicyV2,
    ) -> Result<(), ProviderBoundPromptErrorV2> {
        source
            .validate()
            .map_err(ProviderBoundPromptErrorV2::Source)?;
        self.canonical_serialization.validate_for(
            &source.compiled,
            &source.model_profile,
            &self.realizations,
        )?;
        self.attachment.validate_for(
            &source.compiled,
            self.canonical_serialization.serialized_context(),
            &source.model_profile,
        )?;
        self.snapshot_successor
            .validate(&self.attachment_snapshot)?;
        self.preparation.validate_for(
            &self.attachment,
            self.canonical_serialization.serialized_context(),
            &source.model_profile,
        )?;
        self.provider_request.validate(
            self.canonical_serialization.canonical_payload(),
            framing_policy,
        )?;
        self.final_tokenization
            .validate_for(&source.model_profile, &self.provider_request)?;
        if self.authority.grants_any()
            || self.bundle_digest.is_zero()
            || self.bundle_digest != self.compute_bundle_digest(source)
        {
            return Err(ProviderBoundPromptErrorV2::Integrity);
        }
        Ok(())
    }

    fn compute_bundle_digest(&self, source: &PromptRegistryCompiledContextV2) -> Digest32 {
        let mut bytes = PROVIDER_BOUND_PROMPT_DOMAIN.to_vec();
        for digest in [
            source.delivery_set_digest,
            source.compiled.receipt().receipt_digest(),
            self.canonical_serialization.proof_digest(),
            self.attachment_snapshot.verification_digest(),
            self.attachment.attachment_digest(),
            self.snapshot_successor.chain_digest(),
            self.preparation.preparation_digest(),
            self.provider_request.coverage_digest(),
            self.final_tokenization.attestation_digest(),
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Debug)]
pub enum ProviderBoundPromptErrorV2 {
    Source(PromptRegistryCompilationErrorV2),
    Context(ContextCompilerV2Error),
    ProviderBound(ProviderBoundContextErrorV2),
    RequestBuilder(String),
    Integrity,
}

impl From<ContextCompilerV2Error> for ProviderBoundPromptErrorV2 {
    fn from(error: ContextCompilerV2Error) -> Self {
        Self::Context(error)
    }
}

impl From<ProviderBoundContextErrorV2> for ProviderBoundPromptErrorV2 {
    fn from(error: ProviderBoundContextErrorV2) -> Self {
        Self::ProviderBound(error)
    }
}

impl fmt::Display for ProviderBoundPromptErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProviderBoundPromptErrorV2 {}

/// Compose the strict V2 provider-bound path.
///
/// Candidate token costs used during registry selection are only a bounded
/// preselection signal. This function reserializes the selected source bytes
/// canonically and invokes the qualified tokenizer over both the canonical
/// context and the exact final provider request.
#[allow(clippy::too_many_arguments)]
pub fn prepare_provider_bound_prompt_v2(
    source: &PromptRegistryCompiledContextV2,
    request: ProviderBoundPromptPrepareRequestV2,
    admission_verifier: &impl ContextAdmissionVerifierV2,
    request_builder: &impl ProviderRequestBuilderV2,
    framing_policy: &impl ProviderRequestFramingPolicyV2,
    exact_tokenizer: &impl ExactProviderRequestTokenizerV2,
) -> Result<PreparedProviderBoundPromptV2, ProviderBoundPromptErrorV2> {
    source
        .validate()
        .map_err(ProviderBoundPromptErrorV2::Source)?;
    let realizations = source_realizations(source)?;
    let context_tokenizer = ProviderTokenizerAsContext {
        inner: exact_tokenizer,
    };
    let canonical_serialization = record_canonical_serialization_v2(
        &source.compiled,
        &source.model_profile,
        request.serialization_id,
        realizations.clone(),
        &context_tokenizer,
    )?;

    let attachment_snapshot =
        verify_admission_snapshot_v2(request.attachment_snapshot, admission_verifier)?;
    let attachment = build_attachment(
        &source.compiled,
        canonical_serialization.serialized_context(),
        &source.model_profile,
        &attachment_snapshot,
        request.attachment_id,
    )?;
    let snapshot_successor = verify_typed_admission_snapshot_successor_v2(
        request.pre_dispatch_snapshot,
        &attachment_snapshot,
        admission_verifier,
    )?;
    let preparation = prepare_delivery_from_successor_v2(
        &source.compiled,
        canonical_serialization.serialized_context(),
        &attachment,
        &source.model_profile,
        &snapshot_successor,
        request.preparation_id,
    )?;

    let materialized = request_builder
        .build_provider_request(canonical_serialization.canonical_payload(), &preparation)
        .map_err(ProviderBoundPromptErrorV2::RequestBuilder)?;
    let provider_request = verify_provider_request_coverage_v2(
        canonical_serialization.canonical_payload(),
        materialized.exact_request_bytes,
        materialized.segments,
        framing_policy,
    )?;
    let final_tokenization = tokenize_verified_provider_request_v2(
        &source.model_profile,
        &provider_request,
        materialized.wire_semantic_digest,
        exact_tokenizer,
    )?;

    let mut output = PreparedProviderBoundPromptV2 {
        realizations,
        canonical_serialization,
        attachment_snapshot,
        attachment,
        snapshot_successor,
        preparation,
        provider_request,
        final_tokenization,
        bundle_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    output.bundle_digest = output.compute_bundle_digest(source);
    output.validate_for(source, framing_policy)?;
    Ok(output)
}

fn source_realizations(
    source: &PromptRegistryCompiledContextV2,
) -> Result<Vec<ContextRealizedItemV2>, ProviderBoundPromptErrorV2> {
    let selected = source.compiled.receipt().selected_item_ids();
    if selected.len() != source.selected_deliveries.len() {
        return Err(ProviderBoundPromptErrorV2::Integrity);
    }
    selected
        .iter()
        .zip(&source.selected_deliveries)
        .map(|(item_id, delivery)| {
            if item_id != &delivery.binding.realization_id {
                return Err(ProviderBoundPromptErrorV2::Integrity);
            }
            let role = match delivery.binding.role {
                PromptRoleV2::ToolSchemaFragment => ContextRoleV2::Schema,
                PromptRoleV2::SystemInstruction
                | PromptRoleV2::DeveloperInstruction
                | PromptRoleV2::UserTemplate => ContextRoleV2::TrustedInstruction,
            };
            Ok(ContextRealizedItemV2 {
                item_id: item_id.clone(),
                role,
                content: delivery.payload.clone(),
            })
        })
        .collect()
}

struct ProviderTokenizerAsContext<'a, T> {
    inner: &'a T,
}

impl<T> ExactTokenizerV2 for ProviderTokenizerAsContext<'_, T>
where
    T: ExactProviderRequestTokenizerV2,
{
    fn tokenizer_digest(&self) -> Digest32 {
        self.inner.identity().digest()
    }

    fn count_tokens(&self, bytes: &[u8]) -> Result<u64, ContextCompilerV2Error> {
        self.inner
            .count_tokens(bytes)
            .map_err(|_| ContextCompilerV2Error::InvalidSerializedTokenCount)
    }
}

#[cfg(test)]
#[path = "provider_bound_prompt_tests.rs"]
mod tests;
