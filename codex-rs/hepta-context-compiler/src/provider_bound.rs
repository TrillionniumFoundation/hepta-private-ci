//! Provider-bound context serialization and exact final-request tokenization.
//!
//! This module closes the two trust gaps that remain intentionally abstract in
//! `v2`: canonical byte coverage and a tokenizer attestation over the exact
//! provider request. Product hosts must still supply qualified provider framing
//! and tokenizer implementations; missing or mismatched identities fail closed.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::v2::CompiledContextV2;
use crate::v2::ContextAdmissionSnapshotV2;
use crate::v2::ContextAdmissionVerifierV2;
use crate::v2::ContextAttachmentV2;
use crate::v2::ContextCompilerV2Error;
use crate::v2::ContextDeliveryPreparationV2;
use crate::v2::ContextModelProfileV2;
use crate::v2::ContextRealizedItemV2;
use crate::v2::ContextRoleV2;
use crate::v2::ContextSerializerV2;
use crate::v2::ExactTokenizerV2;
use crate::v2::MAX_CONTEXT_ITEM_BYTES_V2;
use crate::v2::MAX_CONTEXT_TOKENS_V2;
use crate::v2::MAX_SERIALIZED_PAYLOAD_BYTES_V2;
use crate::v2::SerializedContextV2;
use crate::v2::VerifiedAdmissionSnapshotV2;
use crate::v2::prepare_delivery_v2;
use crate::v2::record_serialization;
use crate::v2::verify_admission_snapshot_successor_v2;

const CANONICAL_CONTEXT_DOMAIN: &[u8] = b"hepta.context-canonical-payload.v2\0";
const CANONICAL_SERIALIZER_DOMAIN: &[u8] = b"hepta.context-canonical-serializer.v2\0";
const CANONICAL_COVERAGE_DOMAIN: &[u8] = b"hepta.context-canonical-coverage.v2\0";
const CANONICAL_SERIALIZATION_PROOF_DOMAIN: &[u8] =
    b"hepta.context-canonical-serialization-proof.v2\0";
const SNAPSHOT_SUCCESSOR_DOMAIN: &[u8] =
    b"hepta.context-verified-snapshot-successor.v2\0";
const PROVIDER_REQUEST_COVERAGE_DOMAIN: &[u8] =
    b"hepta.context-provider-request-coverage.v2\0";
const PROVIDER_TOKENIZER_IDENTITY_DOMAIN: &[u8] =
    b"hepta.context-provider-tokenizer-identity.v2\0";
const FINAL_REQUEST_TOKENIZATION_DOMAIN: &[u8] =
    b"hepta.context-final-request-tokenization.v2\0";

pub const MAX_PROVIDER_REQUEST_SEGMENTS_V2: usize = 8_192;
pub const MAX_PROVIDER_REQUEST_BYTES_V2: usize = 32 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderBoundContextErrorV2 {
    Context(ContextCompilerV2Error),
    EmptyDigest(&'static str),
    InvalidCanonicalItem(String),
    DuplicateCanonicalItem(String),
    CanonicalCoverageMismatch,
    SegmentLimitExceeded,
    EmptyProviderRequest,
    ProviderRequestTooLarge,
    SegmentOutOfBounds,
    SegmentGapOrOverlap,
    SegmentDigestMismatch,
    CanonicalContextSegmentMissing,
    DuplicateCanonicalContextSegment,
    CanonicalContextSegmentMismatch,
    FramingRejected(String),
    SnapshotSuccessorMismatch,
    TokenizerIdentityMismatch,
    TokenizerFailure(String),
    InvalidFinalTokenCount,
    FinalTokenBudgetExceeded {
        token_count: u64,
        token_limit: u64,
    },
    AuthorityGranted,
    Arithmetic,
}

impl From<ContextCompilerV2Error> for ProviderBoundContextErrorV2 {
    fn from(error: ContextCompilerV2Error) -> Self {
        Self::Context(error)
    }
}

impl fmt::Display for ProviderBoundContextErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProviderBoundContextErrorV2 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalContextSegmentKindV2 {
    Envelope,
    ItemHeader,
    SelectedItem,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextSegmentV2 {
    kind: CanonicalContextSegmentKindV2,
    item_id: Option<StableId>,
    role: Option<ContextRoleV2>,
    content_digest: Option<Digest32>,
    start_offset: u64,
    end_offset: u64,
    segment_digest: Digest32,
}

impl CanonicalContextSegmentV2 {
    #[must_use]
    pub const fn kind(&self) -> CanonicalContextSegmentKindV2 {
        self.kind
    }

    #[must_use]
    pub fn item_id(&self) -> Option<&StableId> {
        self.item_id.as_ref()
    }

    #[must_use]
    pub const fn role(&self) -> Option<ContextRoleV2> {
        self.role
    }

    #[must_use]
    pub const fn content_digest(&self) -> Option<Digest32> {
        self.content_digest
    }

    #[must_use]
    pub const fn start_offset(&self) -> u64 {
        self.start_offset
    }

    #[must_use]
    pub const fn end_offset(&self) -> u64 {
        self.end_offset
    }

    #[must_use]
    pub const fn segment_digest(&self) -> Digest32 {
        self.segment_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextCoverageV2 {
    payload_digest: Digest32,
    selected_item_ids: Vec<StableId>,
    segments: Vec<CanonicalContextSegmentV2>,
    coverage_digest: Digest32,
    authority: AuthorityPosture,
}

impl CanonicalContextCoverageV2 {
    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 {
        self.payload_digest
    }

    #[must_use]
    pub fn selected_item_ids(&self) -> &[StableId] {
        &self.selected_item_ids
    }

    #[must_use]
    pub fn segments(&self) -> &[CanonicalContextSegmentV2] {
        &self.segments
    }

    #[must_use]
    pub const fn coverage_digest(&self) -> Digest32 {
        self.coverage_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(
        &self,
        payload: &[u8],
        items: &[ContextRealizedItemV2],
    ) -> Result<(), ProviderBoundContextErrorV2> {
        if self.authority.grants_any() {
            return Err(ProviderBoundContextErrorV2::AuthorityGranted);
        }
        let expected = encode_canonical_context(items)?;
        if payload != expected.payload
            || self.payload_digest != expected.coverage.payload_digest
            || self.selected_item_ids != expected.coverage.selected_item_ids
            || self.segments != expected.coverage.segments
            || self.coverage_digest != expected.coverage.coverage_digest
        {
            return Err(ProviderBoundContextErrorV2::CanonicalCoverageMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextPayloadV2 {
    payload: Vec<u8>,
    coverage: CanonicalContextCoverageV2,
}

impl CanonicalContextPayloadV2 {
    #[must_use]
    pub fn payload(&self) -> &[u8] {
        &self.payload
    }

    #[must_use]
    pub const fn coverage(&self) -> &CanonicalContextCoverageV2 {
        &self.coverage
    }

    pub fn validate(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<(), ProviderBoundContextErrorV2> {
        self.coverage.validate(&self.payload, items)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextSerializerV2 {
    serializer_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
}

impl CanonicalContextSerializerV2 {
    pub fn for_profile(
        profile: &ContextModelProfileV2,
    ) -> Result<Self, ProviderBoundContextErrorV2> {
        profile.validate()?;
        let expected = canonical_context_serializer_digest(
            profile.template_digest,
            profile.tool_schema_digest,
        );
        if profile.serializer_digest != expected {
            return Err(ProviderBoundContextErrorV2::CanonicalCoverageMismatch);
        }
        Ok(Self {
            serializer_digest: expected,
            template_digest: profile.template_digest,
            tool_schema_digest: profile.tool_schema_digest,
        })
    }

    pub fn serialize_with_coverage(
        &self,
        items: &[ContextRealizedItemV2],
    ) -> Result<CanonicalContextPayloadV2, ProviderBoundContextErrorV2> {
        encode_canonical_context(items)
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
        self.serialize_with_coverage(items)
            .map(|value| value.payload)
            .map_err(|_| ContextCompilerV2Error::SerializationMismatch)
    }
}

#[must_use]
pub fn canonical_context_serializer_digest(
    template_digest: Digest32,
    tool_schema_digest: Digest32,
) -> Digest32 {
    let mut bytes = CANONICAL_SERIALIZER_DOMAIN.to_vec();
    bytes.extend_from_slice(template_digest.as_array());
    bytes.extend_from_slice(tool_schema_digest.as_array());
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalSerializedContextProofV2 {
    serialized_context: SerializedContextV2,
    canonical_payload: CanonicalContextPayloadV2,
    proof_digest: Digest32,
    authority: AuthorityPosture,
}

impl CanonicalSerializedContextProofV2 {
    #[must_use]
    pub const fn serialized_context(&self) -> &SerializedContextV2 {
        &self.serialized_context
    }

    #[must_use]
    pub const fn canonical_payload(&self) -> &CanonicalContextPayloadV2 {
        &self.canonical_payload
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }

    pub fn validate_for(
        &self,
        compiled: &CompiledContextV2,
        profile: &ContextModelProfileV2,
        items: &[ContextRealizedItemV2],
    ) -> Result<(), ProviderBoundContextErrorV2> {
        if self.authority.grants_any() {
            return Err(ProviderBoundContextErrorV2::AuthorityGranted);
        }
        self.serialized_context.validate_for(compiled, profile)?;
        self.canonical_payload.validate(items)?;
        if self.serialized_context.payload() != self.canonical_payload.payload()
            || self.proof_digest != self.compute_digest()
        {
            return Err(ProviderBoundContextErrorV2::CanonicalCoverageMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = CANONICAL_SERIALIZATION_PROOF_DOMAIN.to_vec();
        bytes.extend_from_slice(
            self.serialized_context
                .receipt()
                .receipt_digest()
                .as_array(),
        );
        bytes.extend_from_slice(self.canonical_payload.coverage.coverage_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

pub fn record_canonical_serialization_v2(
    compiled: &CompiledContextV2,
    profile: &ContextModelProfileV2,
    serialization_id: StableId,
    realizations: Vec<ContextRealizedItemV2>,
    tokenizer: &impl ExactTokenizerV2,
) -> Result<CanonicalSerializedContextProofV2, ProviderBoundContextErrorV2> {
    let serializer = CanonicalContextSerializerV2::for_profile(profile)?;
    let canonical_payload = serializer.serialize_with_coverage(&realizations)?;
    let serialized_context = record_serialization(
        compiled,
        profile,
        serialization_id,
        realizations.clone(),
        &serializer,
        tokenizer,
    )?;
    let mut proof = CanonicalSerializedContextProofV2 {
        serialized_context,
        canonical_payload,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_digest();
    proof.validate_for(compiled, profile, &realizations)?;
    Ok(proof)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAdmissionSnapshotSuccessorV2 {
    predecessor_snapshot_digest: Digest32,
    current_snapshot: VerifiedAdmissionSnapshotV2,
    chain_digest: Digest32,
    authority: AuthorityPosture,
}

impl VerifiedAdmissionSnapshotSuccessorV2 {
    #[must_use]
    pub const fn predecessor_snapshot_digest(&self) -> Digest32 {
        self.predecessor_snapshot_digest
    }

    #[must_use]
    pub const fn current_snapshot(&self) -> &VerifiedAdmissionSnapshotV2 {
        &self.current_snapshot
    }

    #[must_use]
    pub const fn chain_digest(&self) -> Digest32 {
        self.chain_digest
    }

    pub fn validate(
        &self,
        predecessor: &VerifiedAdmissionSnapshotV2,
    ) -> Result<(), ProviderBoundContextErrorV2> {
        if self.authority.grants_any() {
            return Err(ProviderBoundContextErrorV2::AuthorityGranted);
        }
        if self.predecessor_snapshot_digest != predecessor.snapshot_digest()
            || self.chain_digest != self.compute_digest()
        {
            return Err(ProviderBoundContextErrorV2::SnapshotSuccessorMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = SNAPSHOT_SUCCESSOR_DOMAIN.to_vec();
        bytes.extend_from_slice(self.predecessor_snapshot_digest.as_array());
        bytes.extend_from_slice(self.current_snapshot.snapshot_digest().as_array());
        bytes.extend_from_slice(self.current_snapshot.verification_digest().as_array());
        Digest32::of_bytes(&bytes)
    }
}

pub fn verify_typed_admission_snapshot_successor_v2(
    snapshot: ContextAdmissionSnapshotV2,
    predecessor: &VerifiedAdmissionSnapshotV2,
    verifier: &impl ContextAdmissionVerifierV2,
) -> Result<VerifiedAdmissionSnapshotSuccessorV2, ProviderBoundContextErrorV2> {
    let current_snapshot =
        verify_admission_snapshot_successor_v2(snapshot, predecessor, verifier)?;
    let mut successor = VerifiedAdmissionSnapshotSuccessorV2 {
        predecessor_snapshot_digest: predecessor.snapshot_digest(),
        current_snapshot,
        chain_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    successor.chain_digest = successor.compute_digest();
    successor.validate(predecessor)?;
    Ok(successor)
}

pub fn prepare_delivery_from_successor_v2(
    compiled: &CompiledContextV2,
    serialization: &SerializedContextV2,
    attachment: &ContextAttachmentV2,
    profile: &ContextModelProfileV2,
    successor: &VerifiedAdmissionSnapshotSuccessorV2,
    preparation_id: StableId,
) -> Result<ContextDeliveryPreparationV2, ProviderBoundContextErrorV2> {
    if attachment.admission_snapshot_digest() != successor.predecessor_snapshot_digest {
        return Err(ProviderBoundContextErrorV2::SnapshotSuccessorMismatch);
    }
    prepare_delivery_v2(
        compiled,
        serialization,
        attachment,
        profile,
        successor.current_snapshot(),
        preparation_id,
    )
    .map_err(ProviderBoundContextErrorV2::from)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderRequestSegmentKindV2 {
    CanonicalContext,
    TypedFraming { framing_kind: StableId },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderRequestSegmentV2 {
    pub kind: ProviderRequestSegmentKindV2,
    pub start_offset: u64,
    pub end_offset: u64,
    pub segment_digest: Digest32,
}

impl ProviderRequestSegmentV2 {
    pub fn from_bytes(
        kind: ProviderRequestSegmentKindV2,
        start_offset: u64,
        end_offset: u64,
        bytes: &[u8],
    ) -> Result<Self, ProviderBoundContextErrorV2> {
        let start = usize::try_from(start_offset)
            .map_err(|_| ProviderBoundContextErrorV2::SegmentOutOfBounds)?;
        let end = usize::try_from(end_offset)
            .map_err(|_| ProviderBoundContextErrorV2::SegmentOutOfBounds)?;
        let segment = bytes
            .get(start..end)
            .ok_or(ProviderBoundContextErrorV2::SegmentOutOfBounds)?;
        if segment.is_empty() {
            return Err(ProviderBoundContextErrorV2::SegmentOutOfBounds);
        }
        Ok(Self {
            kind,
            start_offset,
            end_offset,
            segment_digest: Digest32::of_bytes(segment),
        })
    }
}

pub trait ProviderRequestFramingPolicyV2 {
    fn policy_digest(&self) -> Digest32;

    fn permits(&self, framing_kind: &StableId, bytes: &[u8]) -> bool;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedProviderRequestV2 {
    bytes: Vec<u8>,
    request_digest: Digest32,
    canonical_context_payload_digest: Digest32,
    framing_policy_digest: Digest32,
    segments: Vec<ProviderRequestSegmentV2>,
    coverage_digest: Digest32,
    authority: AuthorityPosture,
}

impl VerifiedProviderRequestV2 {
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    #[must_use]
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    #[must_use]
    pub const fn canonical_context_payload_digest(&self) -> Digest32 {
        self.canonical_context_payload_digest
    }

    #[must_use]
    pub const fn framing_policy_digest(&self) -> Digest32 {
        self.framing_policy_digest
    }

    #[must_use]
    pub fn segments(&self) -> &[ProviderRequestSegmentV2] {
        &self.segments
    }

    #[must_use]
    pub const fn coverage_digest(&self) -> Digest32 {
        self.coverage_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(
        &self,
        canonical_context: &CanonicalContextPayloadV2,
        framing_policy: &impl ProviderRequestFramingPolicyV2,
    ) -> Result<(), ProviderBoundContextErrorV2> {
        let verified = verify_provider_request_coverage_v2(
            canonical_context,
            self.bytes.clone(),
            self.segments.clone(),
            framing_policy,
        )?;
        if &verified != self {
            return Err(ProviderBoundContextErrorV2::CanonicalCoverageMismatch);
        }
        Ok(())
    }

    fn compute_coverage_digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_REQUEST_COVERAGE_DOMAIN.to_vec();
        bytes.extend_from_slice(self.request_digest.as_array());
        bytes.extend_from_slice(self.canonical_context_payload_digest.as_array());
        bytes.extend_from_slice(self.framing_policy_digest.as_array());
        push_len(&mut bytes, self.segments.len());
        for segment in &self.segments {
            match &segment.kind {
                ProviderRequestSegmentKindV2::CanonicalContext => bytes.push(0),
                ProviderRequestSegmentKindV2::TypedFraming { framing_kind } => {
                    bytes.push(1);
                    push_id(&mut bytes, framing_kind);
                }
            }
            push_u64(&mut bytes, segment.start_offset);
            push_u64(&mut bytes, segment.end_offset);
            bytes.extend_from_slice(segment.segment_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

pub fn verify_provider_request_coverage_v2(
    canonical_context: &CanonicalContextPayloadV2,
    bytes: Vec<u8>,
    segments: Vec<ProviderRequestSegmentV2>,
    framing_policy: &impl ProviderRequestFramingPolicyV2,
) -> Result<VerifiedProviderRequestV2, ProviderBoundContextErrorV2> {
    if bytes.is_empty() {
        return Err(ProviderBoundContextErrorV2::EmptyProviderRequest);
    }
    if bytes.len() > MAX_PROVIDER_REQUEST_BYTES_V2 {
        return Err(ProviderBoundContextErrorV2::ProviderRequestTooLarge);
    }
    if segments.is_empty() || segments.len() > MAX_PROVIDER_REQUEST_SEGMENTS_V2 {
        return Err(ProviderBoundContextErrorV2::SegmentLimitExceeded);
    }
    let framing_policy_digest = framing_policy.policy_digest();
    ensure_digest("provider_request_framing_policy", framing_policy_digest)?;

    let mut cursor = 0_usize;
    let mut canonical_context_seen = false;
    for segment in &segments {
        let start = usize::try_from(segment.start_offset)
            .map_err(|_| ProviderBoundContextErrorV2::SegmentOutOfBounds)?;
        let end = usize::try_from(segment.end_offset)
            .map_err(|_| ProviderBoundContextErrorV2::SegmentOutOfBounds)?;
        if start != cursor || start >= end || end > bytes.len() {
            return Err(ProviderBoundContextErrorV2::SegmentGapOrOverlap);
        }
        let segment_bytes = bytes
            .get(start..end)
            .ok_or(ProviderBoundContextErrorV2::SegmentOutOfBounds)?;
        if Digest32::of_bytes(segment_bytes) != segment.segment_digest {
            return Err(ProviderBoundContextErrorV2::SegmentDigestMismatch);
        }
        match &segment.kind {
            ProviderRequestSegmentKindV2::CanonicalContext => {
                if canonical_context_seen {
                    return Err(
                        ProviderBoundContextErrorV2::DuplicateCanonicalContextSegment,
                    );
                }
                if segment_bytes != canonical_context.payload() {
                    return Err(ProviderBoundContextErrorV2::CanonicalContextSegmentMismatch);
                }
                canonical_context_seen = true;
            }
            ProviderRequestSegmentKindV2::TypedFraming { framing_kind } => {
                if !framing_policy.permits(framing_kind, segment_bytes) {
                    return Err(ProviderBoundContextErrorV2::FramingRejected(
                        framing_kind.to_string(),
                    ));
                }
            }
        }
        cursor = end;
    }
    if cursor != bytes.len() {
        return Err(ProviderBoundContextErrorV2::SegmentGapOrOverlap);
    }
    if !canonical_context_seen {
        return Err(ProviderBoundContextErrorV2::CanonicalContextSegmentMissing);
    }

    let mut verified = VerifiedProviderRequestV2 {
        request_digest: Digest32::of_bytes(&bytes),
        canonical_context_payload_digest: canonical_context.coverage.payload_digest,
        framing_policy_digest,
        bytes,
        segments,
        coverage_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    verified.coverage_digest = verified.compute_coverage_digest();
    Ok(verified)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderTokenizerIdentityV2 {
    pub provider_id_digest: Digest32,
    pub provider_model_digest: Digest32,
    pub tokenizer_binary_digest: Digest32,
    pub tokenizer_version_digest: Digest32,
    pub vocabulary_digest: Digest32,
    pub normalization_policy_digest: Digest32,
}

impl ProviderTokenizerIdentityV2 {
    pub fn validate(&self) -> Result<(), ProviderBoundContextErrorV2> {
        for (name, digest) in [
            ("provider_id", self.provider_id_digest),
            ("provider_model", self.provider_model_digest),
            ("tokenizer_binary", self.tokenizer_binary_digest),
            ("tokenizer_version", self.tokenizer_version_digest),
            ("tokenizer_vocabulary", self.vocabulary_digest),
            (
                "tokenizer_normalization_policy",
                self.normalization_policy_digest,
            ),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_TOKENIZER_IDENTITY_DOMAIN.to_vec();
        for digest in [
            self.provider_id_digest,
            self.provider_model_digest,
            self.tokenizer_binary_digest,
            self.tokenizer_version_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

pub trait ExactProviderRequestTokenizerV2 {
    fn identity(&self) -> ProviderTokenizerIdentityV2;

    fn count_tokens(
        &self,
        exact_provider_request: &[u8],
    ) -> Result<u64, ProviderBoundContextErrorV2>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalProviderRequestTokenizationV2 {
    request_digest: Digest32,
    wire_semantic_digest: Digest32,
    provider_request_coverage_digest: Digest32,
    model_profile_digest: Digest32,
    tokenizer_identity: ProviderTokenizerIdentityV2,
    token_count: u64,
    request_bytes: u64,
    attestation_digest: Digest32,
    authority: AuthorityPosture,
}

impl FinalProviderRequestTokenizationV2 {
    #[must_use]
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    #[must_use]
    pub const fn wire_semantic_digest(&self) -> Digest32 {
        self.wire_semantic_digest
    }

    #[must_use]
    pub const fn provider_request_coverage_digest(&self) -> Digest32 {
        self.provider_request_coverage_digest
    }

    #[must_use]
    pub const fn model_profile_digest(&self) -> Digest32 {
        self.model_profile_digest
    }

    #[must_use]
    pub const fn tokenizer_identity(&self) -> &ProviderTokenizerIdentityV2 {
        &self.tokenizer_identity
    }

    #[must_use]
    pub const fn token_count(&self) -> u64 {
        self.token_count
    }

    #[must_use]
    pub const fn request_bytes(&self) -> u64 {
        self.request_bytes
    }

    #[must_use]
    pub const fn attestation_digest(&self) -> Digest32 {
        self.attestation_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        profile: &ContextModelProfileV2,
        request: &VerifiedProviderRequestV2,
    ) -> Result<(), ProviderBoundContextErrorV2> {
        profile.validate()?;
        self.tokenizer_identity.validate()?;
        if self.authority.grants_any() {
            return Err(ProviderBoundContextErrorV2::AuthorityGranted);
        }
        if self.request_digest != request.request_digest
            || self.provider_request_coverage_digest != request.coverage_digest
            || self.model_profile_digest != profile.digest()
            || self.tokenizer_identity.provider_id_digest != profile.provider_id_digest
            || self.tokenizer_identity.provider_model_digest != profile.provider_model_digest
            || self.tokenizer_identity.digest() != profile.tokenizer_digest
            || self.request_bytes != u64::try_from(request.bytes.len()).unwrap_or(u64::MAX)
        {
            return Err(ProviderBoundContextErrorV2::TokenizerIdentityMismatch);
        }
        ensure_digest("provider_wire_semantics", self.wire_semantic_digest)?;
        if self.token_count == 0 || self.token_count > MAX_CONTEXT_TOKENS_V2 {
            return Err(ProviderBoundContextErrorV2::InvalidFinalTokenCount);
        }
        if self.token_count > profile.maximum_context_tokens {
            return Err(ProviderBoundContextErrorV2::FinalTokenBudgetExceeded {
                token_count: self.token_count,
                token_limit: profile.maximum_context_tokens,
            });
        }
        if self.attestation_digest != self.compute_digest() {
            return Err(ProviderBoundContextErrorV2::TokenizerIdentityMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = FINAL_REQUEST_TOKENIZATION_DOMAIN.to_vec();
        bytes.extend_from_slice(self.request_digest.as_array());
        bytes.extend_from_slice(self.wire_semantic_digest.as_array());
        bytes.extend_from_slice(self.provider_request_coverage_digest.as_array());
        bytes.extend_from_slice(self.model_profile_digest.as_array());
        bytes.extend_from_slice(self.tokenizer_identity.digest().as_array());
        push_u64(&mut bytes, self.token_count);
        push_u64(&mut bytes, self.request_bytes);
        Digest32::of_bytes(&bytes)
    }
}

pub fn tokenize_verified_provider_request_v2(
    profile: &ContextModelProfileV2,
    request: &VerifiedProviderRequestV2,
    wire_semantic_digest: Digest32,
    tokenizer: &impl ExactProviderRequestTokenizerV2,
) -> Result<FinalProviderRequestTokenizationV2, ProviderBoundContextErrorV2> {
    profile.validate()?;
    ensure_digest("provider_wire_semantics", wire_semantic_digest)?;
    let identity = tokenizer.identity();
    identity.validate()?;
    if identity.provider_id_digest != profile.provider_id_digest
        || identity.provider_model_digest != profile.provider_model_digest
        || identity.digest() != profile.tokenizer_digest
    {
        return Err(ProviderBoundContextErrorV2::TokenizerIdentityMismatch);
    }
    let token_count = tokenizer.count_tokens(request.bytes())?;
    if token_count == 0 || token_count > MAX_CONTEXT_TOKENS_V2 {
        return Err(ProviderBoundContextErrorV2::InvalidFinalTokenCount);
    }
    if token_count > profile.maximum_context_tokens {
        return Err(ProviderBoundContextErrorV2::FinalTokenBudgetExceeded {
            token_count,
            token_limit: profile.maximum_context_tokens,
        });
    }
    let mut tokenization = FinalProviderRequestTokenizationV2 {
        request_digest: request.request_digest,
        wire_semantic_digest,
        provider_request_coverage_digest: request.coverage_digest,
        model_profile_digest: profile.digest(),
        tokenizer_identity: identity,
        token_count,
        request_bytes: u64::try_from(request.bytes.len()).unwrap_or(u64::MAX),
        attestation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    tokenization.attestation_digest = tokenization.compute_digest();
    tokenization.validate_for(profile, request)?;
    Ok(tokenization)
}

fn encode_canonical_context(
    items: &[ContextRealizedItemV2],
) -> Result<CanonicalContextPayloadV2, ProviderBoundContextErrorV2> {
    if items.is_empty() {
        return Err(ProviderBoundContextErrorV2::InvalidCanonicalItem(
            "empty_context".to_string(),
        ));
    }
    let mut seen = BTreeSet::new();
    let mut payload = CANONICAL_CONTEXT_DOMAIN.to_vec();
    push_len(&mut payload, items.len());
    let envelope_end = payload.len();
    let mut segments = vec![canonical_segment(
        CanonicalContextSegmentKindV2::Envelope,
        None,
        None,
        None,
        0,
        envelope_end,
        &payload,
    )?];

    for item in items {
        if item.content.is_empty() || item.content.len() > MAX_CONTEXT_ITEM_BYTES_V2 {
            return Err(ProviderBoundContextErrorV2::InvalidCanonicalItem(
                item.item_id.to_string(),
            ));
        }
        if !seen.insert(item.item_id.clone()) {
            return Err(ProviderBoundContextErrorV2::DuplicateCanonicalItem(
                item.item_id.to_string(),
            ));
        }
        let header_start = payload.len();
        push_id(&mut payload, &item.item_id);
        payload.push(role_code(item.role));
        push_len(&mut payload, item.content.len());
        let content_digest = Digest32::of_bytes(&item.content);
        payload.extend_from_slice(content_digest.as_array());
        let header_end = payload.len();
        segments.push(canonical_segment(
            CanonicalContextSegmentKindV2::ItemHeader,
            Some(item.item_id.clone()),
            Some(item.role),
            Some(content_digest),
            header_start,
            header_end,
            &payload,
        )?);

        let content_start = payload.len();
        payload.extend_from_slice(&item.content);
        let content_end = payload.len();
        segments.push(canonical_segment(
            CanonicalContextSegmentKindV2::SelectedItem,
            Some(item.item_id.clone()),
            Some(item.role),
            Some(content_digest),
            content_start,
            content_end,
            &payload,
        )?);
        if payload.len() > MAX_SERIALIZED_PAYLOAD_BYTES_V2 {
            return Err(ProviderBoundContextErrorV2::Context(
                ContextCompilerV2Error::SerializedPayloadTooLarge,
            ));
        }
    }

    let selected_item_ids = items.iter().map(|item| item.item_id.clone()).collect();
    let payload_digest = Digest32::of_bytes(&payload);
    let mut coverage = CanonicalContextCoverageV2 {
        payload_digest,
        selected_item_ids,
        segments,
        coverage_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    coverage.coverage_digest = compute_canonical_coverage_digest(&coverage);
    Ok(CanonicalContextPayloadV2 { payload, coverage })
}

#[allow(clippy::too_many_arguments)]
fn canonical_segment(
    kind: CanonicalContextSegmentKindV2,
    item_id: Option<StableId>,
    role: Option<ContextRoleV2>,
    content_digest: Option<Digest32>,
    start: usize,
    end: usize,
    payload: &[u8],
) -> Result<CanonicalContextSegmentV2, ProviderBoundContextErrorV2> {
    let segment = payload
        .get(start..end)
        .ok_or(ProviderBoundContextErrorV2::CanonicalCoverageMismatch)?;
    if segment.is_empty() {
        return Err(ProviderBoundContextErrorV2::CanonicalCoverageMismatch);
    }
    Ok(CanonicalContextSegmentV2 {
        kind,
        item_id,
        role,
        content_digest,
        start_offset: u64::try_from(start)
            .map_err(|_| ProviderBoundContextErrorV2::Arithmetic)?,
        end_offset: u64::try_from(end)
            .map_err(|_| ProviderBoundContextErrorV2::Arithmetic)?,
        segment_digest: Digest32::of_bytes(segment),
    })
}

fn compute_canonical_coverage_digest(coverage: &CanonicalContextCoverageV2) -> Digest32 {
    let mut bytes = CANONICAL_COVERAGE_DOMAIN.to_vec();
    bytes.extend_from_slice(coverage.payload_digest.as_array());
    push_len(&mut bytes, coverage.selected_item_ids.len());
    for item_id in &coverage.selected_item_ids {
        push_id(&mut bytes, item_id);
    }
    push_len(&mut bytes, coverage.segments.len());
    for segment in &coverage.segments {
        bytes.push(match segment.kind {
            CanonicalContextSegmentKindV2::Envelope => 0,
            CanonicalContextSegmentKindV2::ItemHeader => 1,
            CanonicalContextSegmentKindV2::SelectedItem => 2,
        });
        match &segment.item_id {
            Some(item_id) => {
                bytes.push(1);
                push_id(&mut bytes, item_id);
            }
            None => bytes.push(0),
        }
        match segment.role {
            Some(role) => {
                bytes.push(1);
                bytes.push(role_code(role));
            }
            None => bytes.push(0),
        }
        match segment.content_digest {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
        push_u64(&mut bytes, segment.start_offset);
        push_u64(&mut bytes, segment.end_offset);
        bytes.extend_from_slice(segment.segment_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), ProviderBoundContextErrorV2> {
    if digest.is_zero() {
        return Err(ProviderBoundContextErrorV2::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

#[cfg(test)]
#[path = "provider_bound_tests.rs"]
mod tests;
