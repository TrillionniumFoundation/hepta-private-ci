//! Provider-bound context delivery closure.
//!
//! This module adds the strict V2 path that the compatibility API deliberately
//! could not prove on its own:
//!
//! * compiler-owned canonical context serialization;
//! * an exhaustive byte/segment identity map;
//! * a typed admission-snapshot successor for final-use revalidation;
//! * exact tokenization of the frozen provider request;
//! * a provider receipt that is bound to the same wire-semantic digest.
//!
//! The raw final provider request is accepted only by the exact-tokenizer seam.
//! Receipts retain digests and counts, never prompt bytes.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::ProviderInvocationReceipt;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompiledContextV2;
use crate::ContextAdmissionSnapshotV2;
use crate::ContextAdmissionVerifierV2;
use crate::ContextAttachmentV2;
use crate::ContextCompilerV2Error;
use crate::ContextDeliveryPreparationV2;
use crate::ContextDeliveryReceiptV2;
use crate::ContextModelProfileV2;
use crate::ContextProviderDeliveryVerifierV2;
use crate::ContextRealizedItemV2;
use crate::ContextRoleV2;
use crate::ContextSerializerV2;
use crate::ExactTokenizerV2;
use crate::SerializedContextV2;
use crate::VerifiedAdmissionSnapshotV2;
use crate::observe_delivery;
use crate::prepare_delivery_v2;
use crate::record_serialization;
use crate::verify_admission_snapshot_successor_v2;

const CANONICAL_CONTEXT_FORMAT_DOMAIN: &[u8] = b"hepta.context-canonical-bundle.v2";
const CANONICAL_SEGMENT_MAP_DOMAIN: &[u8] = b"hepta.context-canonical-segment-map.v2";
const CANONICAL_BUNDLE_DOMAIN: &[u8] = b"hepta.context-canonical-bundle-receipt.v2";
const SNAPSHOT_SUCCESSOR_DOMAIN: &[u8] = b"hepta.context-snapshot-successor.v2";
const TOKENIZER_DESCRIPTOR_DOMAIN: &[u8] = b"hepta.provider-tokenizer-descriptor.v2";
const FINAL_REQUEST_TOKENIZATION_DOMAIN: &[u8] =
    b"hepta.provider-final-request-tokenization.v2";
const PROVIDER_BOUND_PREPARATION_DOMAIN: &[u8] =
    b"hepta.context-provider-bound-preparation.v2";
const PROVIDER_BOUND_DELIVERY_DOMAIN: &[u8] = b"hepta.context-provider-bound-delivery.v2";

pub const MAX_PROVIDER_FINAL_REQUEST_BYTES_V2: usize = 64 * 1024 * 1024;
pub const MAX_TOKENIZER_VERSION_BYTES_V2: usize = 256;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalContextFramingV2 {
    Domain,
    ItemCount,
    ItemIdLength,
    ItemId,
    ItemRole,
    ItemContentDigest,
    ItemContentLength,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalContextSegmentKindV2 {
    TypedFraming(CanonicalContextFramingV2),
    SelectedItem {
        item_id: StableId,
        role: ContextRoleV2,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextSegmentV2 {
    pub kind: CanonicalContextSegmentKindV2,
    pub offset: u64,
    pub length: u64,
    pub content_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextSerializerV2 {
    serializer_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
}

impl CanonicalContextSerializerV2 {
    #[must_use]
    pub fn for_profile(profile: &ContextModelProfileV2) -> Self {
        Self {
            serializer_digest: profile.serializer_digest,
            template_digest: profile.template_digest,
            tool_schema_digest: profile.tool_schema_digest,
        }
    }

    #[must_use]
    pub fn format_digest() -> Digest32 {
        Digest32::of_bytes(CANONICAL_CONTEXT_FORMAT_DOMAIN)
    }
}

impl ContextSerializerV2 for CanonicalContextSerializerV2 {
    fn serializer_digest(&self) -> Digest32 {
        self.serializer_digest
    }

    fn template_digest(&self) -> Digest32 {
        self.template_digest
    }

    fn tool_schema_digest(&self) -> Digest32 {
        self.tool_schema_digest
    }

    fn serialize(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<Vec<u8>, ContextCompilerV2Error> {
        encode_canonical_context(items).map(|(payload, _)| payload)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextBundleV2 {
    serialized: SerializedContextV2,
    segments: Vec<CanonicalContextSegmentV2>,
    segment_map_digest: Digest32,
    bundle_digest: Digest32,
    authority: AuthorityPosture,
}

impl CanonicalContextBundleV2 {
    #[must_use]
    pub const fn serialized(&self) -> &SerializedContextV2 {
        &self.serialized
    }

    #[must_use]
    pub fn payload(&self) -> &[u8] {
        self.serialized.payload()
    }

    #[must_use]
    pub fn segments(&self) -> &[CanonicalContextSegmentV2] {
        &self.segments
    }

    #[must_use]
    pub const fn segment_map_digest(&self) -> Digest32 {
        self.segment_map_digest
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
        compiled: &CompiledContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ProviderBoundErrorV2> {
        self.serialized.validate_for(compiled, profile)?;
        ensure_nonzero("canonical segment map", self.segment_map_digest)?;
        ensure_nonzero("canonical bundle", self.bundle_digest)?;
        if self.authority.grants_any() {
            return Err(ProviderBoundErrorV2::AuthorityGranted);
        }
        validate_segment_coverage(self.serialized.payload(), &self.segments)?;
        validate_canonical_payload(compiled, self.serialized.payload(), &self.segments)?;
        if self.segment_map_digest != compute_segment_map_digest(&self.segments) {
            return Err(ProviderBoundErrorV2::DigestMismatch(
                "canonical segment map",
            ));
        }
        if self.bundle_digest != self.compute_bundle_digest() {
            return Err(ProviderBoundErrorV2::DigestMismatch("canonical bundle"));
        }
        Ok(())
    }

    fn compute_bundle_digest(&self) -> Digest32 {
        let mut bytes = CANONICAL_BUNDLE_DOMAIN.to_vec();
        push_digest(&mut bytes, CanonicalContextSerializerV2::format_digest());
        push_digest(&mut bytes, self.serialized.receipt().receipt_digest());
        push_digest(&mut bytes, self.serialized.receipt().payload_digest());
        push_digest(&mut bytes, self.segment_map_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub fn record_canonical_serialization_v2(
    compiled: &CompiledContextV2,
    profile: &ContextModelProfileV2,
    serialization_id: StableId,
    realizations: Vec<ContextRealizedItemV2>,
    tokenizer: &impl ExactTokenizerV2,
) -> Result<CanonicalContextBundleV2, ProviderBoundErrorV2> {
    let ordered = order_canonical_realizations(compiled, realizations)?;
    let (expected_payload, segments) = encode_canonical_context(&ordered)?;
    let serializer = CanonicalContextSerializerV2::for_profile(profile);
    let serialized = record_serialization(
        compiled,
        profile,
        serialization_id,
        ordered,
        &serializer,
        tokenizer,
    )?;
    if serialized.payload() != expected_payload.as_slice() {
        return Err(ProviderBoundErrorV2::CanonicalSerializerDrift);
    }
    let segment_map_digest = compute_segment_map_digest(&segments);
    let mut bundle = CanonicalContextBundleV2 {
        serialized,
        segments,
        segment_map_digest,
        bundle_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    bundle.bundle_digest = bundle.compute_bundle_digest();
    bundle.validate_for(compiled, profile)?;
    Ok(bundle)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAdmissionSnapshotSuccessorV2 {
    predecessor_snapshot_digest: Digest32,
    predecessor_verification_digest: Digest32,
    successor: VerifiedAdmissionSnapshotV2,
    transition_digest: Digest32,
}

impl VerifiedAdmissionSnapshotSuccessorV2 {
    #[must_use]
    pub const fn predecessor_snapshot_digest(&self) -> Digest32 {
        self.predecessor_snapshot_digest
    }

    #[must_use]
    pub const fn successor(&self) -> &VerifiedAdmissionSnapshotV2 {
        &self.successor
    }

    #[must_use]
    pub const fn transition_digest(&self) -> Digest32 {
        self.transition_digest
    }

    pub fn validate_for_predecessor(
        &self,
        predecessor: &VerifiedAdmissionSnapshotV2,
    ) -> Result<(), ProviderBoundErrorV2> {
        if self.predecessor_snapshot_digest != predecessor.snapshot_digest()
            || self.predecessor_verification_digest != predecessor.verification_digest()
        {
            return Err(ProviderBoundErrorV2::SnapshotPredecessorMismatch);
        }
        if self.transition_digest != self.compute_transition_digest() {
            return Err(ProviderBoundErrorV2::DigestMismatch(
                "snapshot successor transition",
            ));
        }
        Ok(())
    }

    fn compute_transition_digest(&self) -> Digest32 {
        let mut bytes = SNAPSHOT_SUCCESSOR_DOMAIN.to_vec();
        push_digest(&mut bytes, self.predecessor_snapshot_digest);
        push_digest(&mut bytes, self.predecessor_verification_digest);
        push_digest(&mut bytes, self.successor.snapshot_digest());
        push_digest(&mut bytes, self.successor.verification_digest());
        push_u64(&mut bytes, self.successor.observed_unix_ms());
        push_u64(&mut bytes, self.successor.revocation_epoch());
        Digest32::of_bytes(&bytes)
    }
}

pub fn verify_typed_admission_snapshot_successor_v2(
    snapshot: ContextAdmissionSnapshotV2,
    predecessor: &VerifiedAdmissionSnapshotV2,
    verifier: &impl ContextAdmissionVerifierV2,
) -> Result<VerifiedAdmissionSnapshotSuccessorV2, ProviderBoundErrorV2> {
    let successor =
        verify_admission_snapshot_successor_v2(snapshot, predecessor, verifier)?;
    let mut typed = VerifiedAdmissionSnapshotSuccessorV2 {
        predecessor_snapshot_digest: predecessor.snapshot_digest(),
        predecessor_verification_digest: predecessor.verification_digest(),
        successor,
        transition_digest: Digest32::ZERO,
    };
    typed.transition_digest = typed.compute_transition_digest();
    typed.validate_for_predecessor(predecessor)?;
    Ok(typed)
}

pub fn prepare_delivery_with_successor_v2(
    compiled: &CompiledContextV2,
    serialization: &SerializedContextV2,
    attachment: &ContextAttachmentV2,
    profile: &ContextModelProfileV2,
    successor: &VerifiedAdmissionSnapshotSuccessorV2,
    preparation_id: StableId,
) -> Result<ContextDeliveryPreparationV2, ProviderBoundErrorV2> {
    if successor.predecessor_snapshot_digest() != attachment.admission_snapshot_digest() {
        return Err(ProviderBoundErrorV2::SnapshotPredecessorMismatch);
    }
    Ok(prepare_delivery_v2(
        compiled,
        serialization,
        attachment,
        profile,
        successor.successor(),
        preparation_id,
    )?)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderTokenizerDescriptorV2 {
    provider_id_digest: Digest32,
    provider_model_digest: Digest32,
    tokenizer_binary_digest: Digest32,
    tokenizer_version: String,
    vocabulary_digest: Digest32,
    normalization_policy_digest: Digest32,
    descriptor_digest: Digest32,
}

impl ProviderTokenizerDescriptorV2 {
    pub fn new(
        provider_id_digest: Digest32,
        provider_model_digest: Digest32,
        tokenizer_binary_digest: Digest32,
        tokenizer_version: impl Into<String>,
        vocabulary_digest: Digest32,
        normalization_policy_digest: Digest32,
    ) -> Result<Self, ProviderBoundErrorV2> {
        let mut value = Self {
            provider_id_digest,
            provider_model_digest,
            tokenizer_binary_digest,
            tokenizer_version: tokenizer_version.into(),
            vocabulary_digest,
            normalization_policy_digest,
            descriptor_digest: Digest32::ZERO,
        };
        value.descriptor_digest = value.compute_descriptor_digest();
        value.validate()?;
        Ok(value)
    }

    #[must_use]
    pub const fn provider_id_digest(&self) -> Digest32 {
        self.provider_id_digest
    }

    #[must_use]
    pub const fn provider_model_digest(&self) -> Digest32 {
        self.provider_model_digest
    }

    #[must_use]
    pub const fn tokenizer_binary_digest(&self) -> Digest32 {
        self.tokenizer_binary_digest
    }

    #[must_use]
    pub fn tokenizer_version(&self) -> &str {
        &self.tokenizer_version
    }

    #[must_use]
    pub const fn vocabulary_digest(&self) -> Digest32 {
        self.vocabulary_digest
    }

    #[must_use]
    pub const fn normalization_policy_digest(&self) -> Digest32 {
        self.normalization_policy_digest
    }

    #[must_use]
    pub const fn descriptor_digest(&self) -> Digest32 {
        self.descriptor_digest
    }

    pub fn validate(&self) -> Result<(), ProviderBoundErrorV2> {
        for (name, digest) in [
            ("provider id", self.provider_id_digest),
            ("provider model", self.provider_model_digest),
            ("tokenizer binary", self.tokenizer_binary_digest),
            ("tokenizer vocabulary", self.vocabulary_digest),
            (
                "tokenizer normalization policy",
                self.normalization_policy_digest,
            ),
            ("tokenizer descriptor", self.descriptor_digest),
        ] {
            ensure_nonzero(name, digest)?;
        }
        if self.tokenizer_version.is_empty()
            || self.tokenizer_version.len() > MAX_TOKENIZER_VERSION_BYTES_V2
            || self.tokenizer_version.as_bytes().contains(&0)
        {
            return Err(ProviderBoundErrorV2::InvalidTokenizerVersion);
        }
        if self.descriptor_digest != self.compute_descriptor_digest() {
            return Err(ProviderBoundErrorV2::DigestMismatch(
                "tokenizer descriptor",
            ));
        }
        Ok(())
    }

    fn compute_descriptor_digest(&self) -> Digest32 {
        let mut bytes = TOKENIZER_DESCRIPTOR_DOMAIN.to_vec();
        push_digest(&mut bytes, self.provider_id_digest);
        push_digest(&mut bytes, self.provider_model_digest);
        push_digest(&mut bytes, self.tokenizer_binary_digest);
        push_text(&mut bytes, &self.tokenizer_version);
        push_digest(&mut bytes, self.vocabulary_digest);
        push_digest(&mut bytes, self.normalization_policy_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub trait ExactProviderRequestTokenizerV2 {
    fn descriptor(&self) -> &ProviderTokenizerDescriptorV2;

    fn count_tokens(
        &self,
        canonical_final_request: &[u8],
    ) -> Result<u64, ProviderBoundErrorV2>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderFinalRequestTokenizationV2 {
    descriptor: ProviderTokenizerDescriptorV2,
    final_request_digest: Digest32,
    provider_wire_semantic_sha256: Sha256Digest,
    final_request_bytes: u64,
    token_count: u64,
    receipt_digest: Digest32,
}

impl ProviderFinalRequestTokenizationV2 {
    #[must_use]
    pub const fn descriptor(&self) -> &ProviderTokenizerDescriptorV2 {
        &self.descriptor
    }

    #[must_use]
    pub const fn final_request_digest(&self) -> Digest32 {
        self.final_request_digest
    }

    #[must_use]
    pub fn provider_wire_semantic_sha256(&self) -> &Sha256Digest {
        &self.provider_wire_semantic_sha256
    }

    #[must_use]
    pub const fn final_request_bytes(&self) -> u64 {
        self.final_request_bytes
    }

    #[must_use]
    pub const fn token_count(&self) -> u64 {
        self.token_count
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    pub fn validate(&self, maximum_context_tokens: u64) -> Result<(), ProviderBoundErrorV2> {
        self.descriptor.validate()?;
        ensure_nonzero("final provider request", self.final_request_digest)?;
        ensure_nonzero("final request tokenization receipt", self.receipt_digest)?;
        if self.final_request_bytes == 0
            || self.final_request_bytes
                > u64::try_from(MAX_PROVIDER_FINAL_REQUEST_BYTES_V2).unwrap_or(u64::MAX)
        {
            return Err(ProviderBoundErrorV2::FinalRequestSizeInvalid);
        }
        if maximum_context_tokens == 0
            || self.token_count == 0
            || self.token_count > maximum_context_tokens
        {
            return Err(ProviderBoundErrorV2::FinalRequestTokenBudgetExceeded {
                token_count: self.token_count,
                token_budget: maximum_context_tokens,
            });
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ProviderBoundErrorV2::DigestMismatch(
                "final request tokenization receipt",
            ));
        }
        Ok(())
    }

    fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = FINAL_REQUEST_TOKENIZATION_DOMAIN.to_vec();
        push_digest(&mut bytes, self.descriptor.descriptor_digest());
        push_digest(&mut bytes, self.final_request_digest);
        push_text(&mut bytes, self.provider_wire_semantic_sha256.as_str());
        push_u64(&mut bytes, self.final_request_bytes);
        push_u64(&mut bytes, self.token_count);
        Digest32::of_bytes(&bytes)
    }
}

pub fn tokenize_provider_final_request_v2(
    canonical_final_request: &[u8],
    provider_wire_semantic_sha256: Sha256Digest,
    maximum_context_tokens: u64,
    tokenizer: &impl ExactProviderRequestTokenizerV2,
) -> Result<ProviderFinalRequestTokenizationV2, ProviderBoundErrorV2> {
    if canonical_final_request.is_empty()
        || canonical_final_request.len() > MAX_PROVIDER_FINAL_REQUEST_BYTES_V2
    {
        return Err(ProviderBoundErrorV2::FinalRequestSizeInvalid);
    }
    tokenizer.descriptor().validate()?;
    if provider_wire_semantic_sha256 != Sha256Digest::for_bytes(canonical_final_request) {
        return Err(ProviderBoundErrorV2::ProviderWireDigestMismatch);
    }
    let token_count = tokenizer.count_tokens(canonical_final_request)?;
    let mut receipt = ProviderFinalRequestTokenizationV2 {
        descriptor: tokenizer.descriptor().clone(),
        final_request_digest: Digest32::of_bytes(canonical_final_request),
        provider_wire_semantic_sha256,
        final_request_bytes: u64::try_from(canonical_final_request.len()).unwrap_or(u64::MAX),
        token_count,
        receipt_digest: Digest32::ZERO,
    };
    receipt.receipt_digest = receipt.compute_receipt_digest();
    receipt.validate(maximum_context_tokens)?;
    Ok(receipt)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundDeliveryPreparationV2 {
    preparation: ContextDeliveryPreparationV2,
    canonical_bundle_digest: Digest32,
    canonical_segment_map_digest: Digest32,
    prompt_fragments_digest: Digest32,
    final_request_tokenization: ProviderFinalRequestTokenizationV2,
    binding_digest: Digest32,
    authority: AuthorityPosture,
}

impl ProviderBoundDeliveryPreparationV2 {
    #[must_use]
    pub const fn preparation(&self) -> &ContextDeliveryPreparationV2 {
        &self.preparation
    }

    #[must_use]
    pub const fn canonical_bundle_digest(&self) -> Digest32 {
        self.canonical_bundle_digest
    }

    #[must_use]
    pub const fn canonical_segment_map_digest(&self) -> Digest32 {
        self.canonical_segment_map_digest
    }

    #[must_use]
    pub const fn prompt_fragments_digest(&self) -> Digest32 {
        self.prompt_fragments_digest
    }

    #[must_use]
    pub const fn final_request_tokenization(&self) -> &ProviderFinalRequestTokenizationV2 {
        &self.final_request_tokenization
    }

    #[must_use]
    pub const fn binding_digest(&self) -> Digest32 {
        self.binding_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        compiled: &CompiledContextV2,
        bundle: &CanonicalContextBundleV2,
        attachment: &ContextAttachmentV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ProviderBoundErrorV2> {
        bundle.validate_for(compiled, profile)?;
        self.preparation
            .validate_for(attachment, bundle.serialized(), profile)?;
        self.final_request_tokenization
            .validate(profile.maximum_context_tokens)?;
        for (name, digest) in [
            ("canonical bundle", self.canonical_bundle_digest),
            ("canonical segment map", self.canonical_segment_map_digest),
            ("prompt fragments", self.prompt_fragments_digest),
            ("provider-bound preparation", self.binding_digest),
        ] {
            ensure_nonzero(name, digest)?;
        }
        if self.canonical_bundle_digest != bundle.bundle_digest()
            || self.canonical_segment_map_digest != bundle.segment_map_digest()
            || self.preparation.payload_digest() != bundle.serialized().receipt().payload_digest()
            || self.final_request_tokenization.descriptor().provider_id_digest()
                != profile.provider_id_digest
            || self.final_request_tokenization.descriptor().provider_model_digest()
                != profile.provider_model_digest
        {
            return Err(ProviderBoundErrorV2::ProviderModelProfileMismatch);
        }
        if self.authority.grants_any() {
            return Err(ProviderBoundErrorV2::AuthorityGranted);
        }
        if self.binding_digest != self.compute_binding_digest() {
            return Err(ProviderBoundErrorV2::DigestMismatch(
                "provider-bound preparation",
            ));
        }
        Ok(())
    }

    fn compute_binding_digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_BOUND_PREPARATION_DOMAIN.to_vec();
        push_digest(&mut bytes, self.preparation.preparation_digest());
        push_digest(&mut bytes, self.canonical_bundle_digest);
        push_digest(&mut bytes, self.canonical_segment_map_digest);
        push_digest(&mut bytes, self.prompt_fragments_digest);
        push_digest(
            &mut bytes,
            self.final_request_tokenization.receipt_digest(),
        );
        push_digest(
            &mut bytes,
            self.final_request_tokenization.final_request_digest(),
        );
        push_text(
            &mut bytes,
            self.final_request_tokenization
                .provider_wire_semantic_sha256()
                .as_str(),
        );
        Digest32::of_bytes(&bytes)
    }
}

#[allow(clippy::too_many_arguments)]
pub fn prepare_provider_bound_delivery_v2(
    compiled: &CompiledContextV2,
    bundle: &CanonicalContextBundleV2,
    attachment: &ContextAttachmentV2,
    profile: &ContextModelProfileV2,
    successor: &VerifiedAdmissionSnapshotSuccessorV2,
    preparation_id: StableId,
    prompt_fragments_digest: Digest32,
    final_request_tokenization: ProviderFinalRequestTokenizationV2,
) -> Result<ProviderBoundDeliveryPreparationV2, ProviderBoundErrorV2> {
    ensure_nonzero("prompt fragments", prompt_fragments_digest)?;
    bundle.validate_for(compiled, profile)?;
    final_request_tokenization.validate(profile.maximum_context_tokens)?;
    if final_request_tokenization.descriptor().provider_id_digest()
        != profile.provider_id_digest
        || final_request_tokenization.descriptor().provider_model_digest()
            != profile.provider_model_digest
    {
        return Err(ProviderBoundErrorV2::ProviderModelProfileMismatch);
    }
    let preparation = prepare_delivery_with_successor_v2(
        compiled,
        bundle.serialized(),
        attachment,
        profile,
        successor,
        preparation_id,
    )?;
    let mut value = ProviderBoundDeliveryPreparationV2 {
        preparation,
        canonical_bundle_digest: bundle.bundle_digest(),
        canonical_segment_map_digest: bundle.segment_map_digest(),
        prompt_fragments_digest,
        final_request_tokenization,
        binding_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.binding_digest = value.compute_binding_digest();
    value.validate_for(compiled, bundle, attachment, profile)?;
    Ok(value)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundDeliveryReceiptV2 {
    delivery: ContextDeliveryReceiptV2,
    provider_bound_preparation_digest: Digest32,
    provider_wire_semantic_sha256: Sha256Digest,
    final_request_tokenization_receipt_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ProviderBoundDeliveryReceiptV2 {
    #[must_use]
    pub const fn delivery(&self) -> &ContextDeliveryReceiptV2 {
        &self.delivery
    }

    #[must_use]
    pub const fn provider_bound_preparation_digest(&self) -> Digest32 {
        self.provider_bound_preparation_digest
    }

    #[must_use]
    pub fn provider_wire_semantic_sha256(&self) -> &Sha256Digest {
        &self.provider_wire_semantic_sha256
    }

    #[must_use]
    pub const fn final_request_tokenization_receipt_digest(&self) -> Digest32 {
        self.final_request_tokenization_receipt_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        preparation: &ProviderBoundDeliveryPreparationV2,
        attachment: &ContextAttachmentV2,
        bundle: &CanonicalContextBundleV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ProviderBoundErrorV2> {
        self.delivery.validate_for(
            preparation.preparation(),
            attachment,
            bundle.serialized(),
            profile,
        )?;
        if self.provider_bound_preparation_digest != preparation.binding_digest()
            || &self.provider_wire_semantic_sha256
                != preparation
                    .final_request_tokenization()
                    .provider_wire_semantic_sha256()
            || self.final_request_tokenization_receipt_digest
                != preparation.final_request_tokenization().receipt_digest()
        {
            return Err(ProviderBoundErrorV2::DeliveryBindingMismatch);
        }
        if self.authority.grants_any() {
            return Err(ProviderBoundErrorV2::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(ProviderBoundErrorV2::DigestMismatch(
                "provider-bound delivery",
            ));
        }
        Ok(())
    }

    fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_BOUND_DELIVERY_DOMAIN.to_vec();
        push_digest(&mut bytes, self.delivery.receipt_digest());
        push_digest(&mut bytes, self.provider_bound_preparation_digest);
        push_text(&mut bytes, self.provider_wire_semantic_sha256.as_str());
        push_digest(
            &mut bytes,
            self.final_request_tokenization_receipt_digest,
        );
        Digest32::of_bytes(&bytes)
    }
}

#[allow(clippy::too_many_arguments)]
pub fn observe_provider_bound_delivery_v2(
    preparation: &ProviderBoundDeliveryPreparationV2,
    compiled: &CompiledContextV2,
    bundle: &CanonicalContextBundleV2,
    attachment: &ContextAttachmentV2,
    profile: &ContextModelProfileV2,
    delivery_id: StableId,
    provider_receipt: &ProviderInvocationReceipt,
    delivery_verifier: &impl ContextProviderDeliveryVerifierV2,
    observed_unix_ms: u64,
) -> Result<ProviderBoundDeliveryReceiptV2, ProviderBoundErrorV2> {
    preparation.validate_for(compiled, bundle, attachment, profile)?;
    if &provider_receipt.intent.binding.wire_semantic_sha256
        != preparation
            .final_request_tokenization()
            .provider_wire_semantic_sha256()
    {
        return Err(ProviderBoundErrorV2::ProviderWireDigestMismatch);
    }
    let delivery = observe_delivery(
        preparation.preparation(),
        attachment,
        bundle.serialized(),
        profile,
        delivery_id,
        provider_receipt,
        delivery_verifier,
        observed_unix_ms,
    )?;
    let mut value = ProviderBoundDeliveryReceiptV2 {
        delivery,
        provider_bound_preparation_digest: preparation.binding_digest(),
        provider_wire_semantic_sha256: preparation
            .final_request_tokenization()
            .provider_wire_semantic_sha256()
            .clone(),
        final_request_tokenization_receipt_digest: preparation
            .final_request_tokenization()
            .receipt_digest(),
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.receipt_digest = value.compute_receipt_digest();
    value.validate_for(preparation, attachment, bundle, profile)?;
    Ok(value)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderBoundErrorV2 {
    Context(ContextCompilerV2Error),
    EmptyDigest(&'static str),
    CanonicalSerializerDrift,
    InvalidSegmentMap(&'static str),
    SnapshotPredecessorMismatch,
    InvalidTokenizerVersion,
    FinalRequestSizeInvalid,
    FinalRequestTokenBudgetExceeded {
        token_count: u64,
        token_budget: u64,
    },
    ProviderWireDigestMismatch,
    ProviderModelProfileMismatch,
    DeliveryBindingMismatch,
    DigestMismatch(&'static str),
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for ProviderBoundErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProviderBoundErrorV2 {}

impl From<ContextCompilerV2Error> for ProviderBoundErrorV2 {
    fn from(value: ContextCompilerV2Error) -> Self {
        Self::Context(value)
    }
}

fn order_canonical_realizations(
    compiled: &CompiledContextV2,
    realizations: Vec<ContextRealizedItemV2>,
) -> Result<Vec<ContextRealizedItemV2>, ProviderBoundErrorV2> {
    if realizations.len() != compiled.selected_candidates().len() {
        return Err(ContextCompilerV2Error::RealizationSetMismatch.into());
    }
    let mut by_id = std::collections::BTreeMap::new();
    for realization in realizations {
        let item_id = realization.item_id.clone();
        if by_id.insert(item_id.clone(), realization).is_some() {
            return Err(ContextCompilerV2Error::DuplicateRealization(
                item_id.to_string(),
            )
            .into());
        }
    }
    let mut ordered = Vec::with_capacity(compiled.selected_candidates().len());
    for candidate in compiled.selected_candidates() {
        let Some(realization) = by_id.remove(&candidate.item_id) else {
            return Err(ContextCompilerV2Error::RealizationSetMismatch.into());
        };
        if realization.role != candidate.role {
            return Err(ContextCompilerV2Error::RealizedRoleMismatch(
                candidate.item_id.to_string(),
            )
            .into());
        }
        if Digest32::of_bytes(&realization.content) != candidate.content_digest {
            return Err(ContextCompilerV2Error::RealizedContentMismatch(
                candidate.item_id.to_string(),
            )
            .into());
        }
        ordered.push(realization);
    }
    if !by_id.is_empty() {
        return Err(ContextCompilerV2Error::RealizationSetMismatch.into());
    }
    Ok(ordered)
}

fn encode_canonical_context(
    items: &[ContextRealizedItemV2],
) -> Result<(Vec<u8>, Vec<CanonicalContextSegmentV2>), ContextCompilerV2Error> {
    let mut payload = Vec::new();
    let mut segments = Vec::new();
    push_segment(
        &mut payload,
        &mut segments,
        CANONICAL_CONTEXT_FORMAT_DOMAIN,
        CanonicalContextSegmentKindV2::TypedFraming(CanonicalContextFramingV2::Domain),
    );
    push_segment(
        &mut payload,
        &mut segments,
        &u64::try_from(items.len()).unwrap_or(u64::MAX).to_be_bytes(),
        CanonicalContextSegmentKindV2::TypedFraming(CanonicalContextFramingV2::ItemCount),
    );
    for item in items {
        if item.content.is_empty() {
            return Err(ContextCompilerV2Error::RealizedContentMismatch(
                item.item_id.to_string(),
            ));
        }
        let item_id = item.item_id.as_str().as_bytes();
        push_segment(
            &mut payload,
            &mut segments,
            &u64::try_from(item_id.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
            CanonicalContextSegmentKindV2::TypedFraming(
                CanonicalContextFramingV2::ItemIdLength,
            ),
        );
        push_segment(
            &mut payload,
            &mut segments,
            item_id,
            CanonicalContextSegmentKindV2::TypedFraming(CanonicalContextFramingV2::ItemId),
        );
        push_segment(
            &mut payload,
            &mut segments,
            &[canonical_role_code(item.role)],
            CanonicalContextSegmentKindV2::TypedFraming(CanonicalContextFramingV2::ItemRole),
        );
        let content_digest = Digest32::of_bytes(&item.content);
        push_segment(
            &mut payload,
            &mut segments,
            content_digest.as_array(),
            CanonicalContextSegmentKindV2::TypedFraming(
                CanonicalContextFramingV2::ItemContentDigest,
            ),
        );
        push_segment(
            &mut payload,
            &mut segments,
            &u64::try_from(item.content.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
            CanonicalContextSegmentKindV2::TypedFraming(
                CanonicalContextFramingV2::ItemContentLength,
            ),
        );
        push_segment(
            &mut payload,
            &mut segments,
            &item.content,
            CanonicalContextSegmentKindV2::SelectedItem {
                item_id: item.item_id.clone(),
                role: item.role,
            },
        );
    }
    Ok((payload, segments))
}

fn push_segment(
    payload: &mut Vec<u8>,
    segments: &mut Vec<CanonicalContextSegmentV2>,
    bytes: &[u8],
    kind: CanonicalContextSegmentKindV2,
) {
    let offset = u64::try_from(payload.len()).unwrap_or(u64::MAX);
    payload.extend_from_slice(bytes);
    segments.push(CanonicalContextSegmentV2 {
        kind,
        offset,
        length: u64::try_from(bytes.len()).unwrap_or(u64::MAX),
        content_digest: Digest32::of_bytes(bytes),
    });
}

fn validate_segment_coverage(
    payload: &[u8],
    segments: &[CanonicalContextSegmentV2],
) -> Result<(), ProviderBoundErrorV2> {
    if segments.is_empty() {
        return Err(ProviderBoundErrorV2::InvalidSegmentMap("empty"));
    }
    let mut cursor = 0_u64;
    for segment in segments {
        if segment.length == 0 || segment.offset != cursor {
            return Err(ProviderBoundErrorV2::InvalidSegmentMap(
                "gap, overlap, or zero-length segment",
            ));
        }
        let end = segment
            .offset
            .checked_add(segment.length)
            .ok_or(ProviderBoundErrorV2::Arithmetic)?;
        let start = usize::try_from(segment.offset)
            .map_err(|_| ProviderBoundErrorV2::Arithmetic)?;
        let end_usize =
            usize::try_from(end).map_err(|_| ProviderBoundErrorV2::Arithmetic)?;
        let Some(bytes) = payload.get(start..end_usize) else {
            return Err(ProviderBoundErrorV2::InvalidSegmentMap(
                "segment outside payload",
            ));
        };
        if segment.content_digest != Digest32::of_bytes(bytes) {
            return Err(ProviderBoundErrorV2::DigestMismatch("canonical segment"));
        }
        cursor = end;
    }
    if cursor != u64::try_from(payload.len()).unwrap_or(u64::MAX) {
        return Err(ProviderBoundErrorV2::InvalidSegmentMap(
            "incomplete payload coverage",
        ));
    }
    Ok(())
}

fn validate_canonical_payload(
    compiled: &CompiledContextV2,
    payload: &[u8],
    segments: &[CanonicalContextSegmentV2],
) -> Result<(), ProviderBoundErrorV2> {
    let mut segment_index = 0_usize;
    expect_framing(
        payload,
        segments,
        &mut segment_index,
        CanonicalContextFramingV2::Domain,
        CANONICAL_CONTEXT_FORMAT_DOMAIN,
    )?;
    expect_framing(
        payload,
        segments,
        &mut segment_index,
        CanonicalContextFramingV2::ItemCount,
        &u64::try_from(compiled.selected_candidates().len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    )?;
    for candidate in compiled.selected_candidates() {
        let item_id = candidate.item_id.as_str().as_bytes();
        expect_framing(
            payload,
            segments,
            &mut segment_index,
            CanonicalContextFramingV2::ItemIdLength,
            &u64::try_from(item_id.len())
                .unwrap_or(u64::MAX)
                .to_be_bytes(),
        )?;
        expect_framing(
            payload,
            segments,
            &mut segment_index,
            CanonicalContextFramingV2::ItemId,
            item_id,
        )?;
        expect_framing(
            payload,
            segments,
            &mut segment_index,
            CanonicalContextFramingV2::ItemRole,
            &[canonical_role_code(candidate.role)],
        )?;
        expect_framing(
            payload,
            segments,
            &mut segment_index,
            CanonicalContextFramingV2::ItemContentDigest,
            candidate.content_digest.as_array(),
        )?;
        let Some(content_segment) = segments.get(segment_index + 1) else {
            return Err(ProviderBoundErrorV2::InvalidSegmentMap(
                "missing selected item segment",
            ));
        };
        let content_length = content_segment.length;
        expect_framing(
            payload,
            segments,
            &mut segment_index,
            CanonicalContextFramingV2::ItemContentLength,
            &content_length.to_be_bytes(),
        )?;
        let Some(segment) = segments.get(segment_index) else {
            return Err(ProviderBoundErrorV2::InvalidSegmentMap(
                "missing selected item segment",
            ));
        };
        match &segment.kind {
            CanonicalContextSegmentKindV2::SelectedItem { item_id, role }
                if item_id == &candidate.item_id && *role == candidate.role => {}
            _ => {
                return Err(ProviderBoundErrorV2::InvalidSegmentMap(
                    "selected item identity mismatch",
                ));
            }
        }
        if segment.content_digest != candidate.content_digest {
            return Err(ProviderBoundErrorV2::DigestMismatch(
                "selected item content",
            ));
        }
        segment_index = segment_index
            .checked_add(1)
            .ok_or(ProviderBoundErrorV2::Arithmetic)?;
    }
    if segment_index != segments.len() {
        return Err(ProviderBoundErrorV2::InvalidSegmentMap(
            "unexpected trailing segments",
        ));
    }
    Ok(())
}

fn expect_framing(
    payload: &[u8],
    segments: &[CanonicalContextSegmentV2],
    segment_index: &mut usize,
    expected_kind: CanonicalContextFramingV2,
    expected_bytes: &[u8],
) -> Result<(), ProviderBoundErrorV2> {
    let Some(segment) = segments.get(*segment_index) else {
        return Err(ProviderBoundErrorV2::InvalidSegmentMap(
            "missing framing segment",
        ));
    };
    if segment.kind
        != CanonicalContextSegmentKindV2::TypedFraming(expected_kind)
        || segment.length != u64::try_from(expected_bytes.len()).unwrap_or(u64::MAX)
    {
        return Err(ProviderBoundErrorV2::InvalidSegmentMap(
            "framing kind or length mismatch",
        ));
    }
    let start =
        usize::try_from(segment.offset).map_err(|_| ProviderBoundErrorV2::Arithmetic)?;
    let end = start
        .checked_add(
            usize::try_from(segment.length).map_err(|_| ProviderBoundErrorV2::Arithmetic)?,
        )
        .ok_or(ProviderBoundErrorV2::Arithmetic)?;
    if payload.get(start..end) != Some(expected_bytes) {
        return Err(ProviderBoundErrorV2::InvalidSegmentMap(
            "framing bytes mismatch",
        ));
    }
    *segment_index = (*segment_index)
        .checked_add(1)
        .ok_or(ProviderBoundErrorV2::Arithmetic)?;
    Ok(())
}

fn compute_segment_map_digest(segments: &[CanonicalContextSegmentV2]) -> Digest32 {
    let mut bytes = CANONICAL_SEGMENT_MAP_DOMAIN.to_vec();
    push_u64(
        &mut bytes,
        u64::try_from(segments.len()).unwrap_or(u64::MAX),
    );
    for segment in segments {
        match &segment.kind {
            CanonicalContextSegmentKindV2::TypedFraming(kind) => {
                bytes.push(0);
                bytes.push(framing_code(*kind));
            }
            CanonicalContextSegmentKindV2::SelectedItem { item_id, role } => {
                bytes.push(1);
                push_id(&mut bytes, item_id);
                bytes.push(canonical_role_code(*role));
            }
        }
        push_u64(&mut bytes, segment.offset);
        push_u64(&mut bytes, segment.length);
        push_digest(&mut bytes, segment.content_digest);
    }
    Digest32::of_bytes(&bytes)
}

fn ensure_nonzero(
    name: &'static str,
    digest: Digest32,
) -> Result<(), ProviderBoundErrorV2> {
    if digest.is_zero() {
        return Err(ProviderBoundErrorV2::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_text(bytes, value.as_str());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    push_u64(bytes, u64::try_from(value.len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(value.as_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn canonical_role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

const fn framing_code(kind: CanonicalContextFramingV2) -> u8 {
    match kind {
        CanonicalContextFramingV2::Domain => 0,
        CanonicalContextFramingV2::ItemCount => 1,
        CanonicalContextFramingV2::ItemIdLength => 2,
        CanonicalContextFramingV2::ItemId => 3,
        CanonicalContextFramingV2::ItemRole => 4,
        CanonicalContextFramingV2::ItemContentDigest => 5,
        CanonicalContextFramingV2::ItemContentLength => 6,
    }
}

#[cfg(test)]
#[path = "provider_bound_tests.rs"]
mod tests;
