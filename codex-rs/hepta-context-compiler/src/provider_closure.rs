//! Provider-bound V2 closure for the exact physical request.
//!
//! The legacy V2 compiler proves the selected context bundle. This module
//! closes the two remaining type-level gaps without granting dispatch
//! authority:
//!
//! * a delivery preparation consumes a typed, monotone admission-snapshot
//!   successor rather than an independently verified snapshot; and
//! * the exact canonical provider request bytes are tokenized only after final
//!   request construction and are bound to provider/model/tokenizer identity,
//!   a complete byte-segment map, and the provider wire-semantic digest.

use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ContextAdmissionSnapshotV2;
use crate::ContextAdmissionVerifierV2;
use crate::ContextAttachmentV2;
use crate::ContextCompilerV2Error;
use crate::ContextDeliveryPreparationV2;
use crate::ContextModelProfileV2;
use crate::SerializedContextV2;
use crate::VerifiedAdmissionSnapshotV2;
use crate::prepare_delivery_v2;
use crate::verify_admission_snapshot_successor_v2;

const SNAPSHOT_SUCCESSOR_DOMAIN: &[u8] =
    b"hepta.context-verified-admission-snapshot-successor.v2";
const TOKENIZER_IDENTITY_DOMAIN: &[u8] = b"hepta.context-final-request-tokenizer-identity.v2";
const TOKENIZATION_RECEIPT_DOMAIN: &[u8] =
    b"hepta.context-final-request-tokenization-receipt.v2";
const SEGMENT_MAP_DOMAIN: &[u8] = b"hepta.context-final-request-segment-map.v2";
const FINAL_REQUEST_PROOF_DOMAIN: &[u8] = b"hepta.context-final-provider-request-proof.v2";

pub const MAX_FINAL_PROVIDER_REQUEST_BYTES_V2: usize = 32 * 1024 * 1024;
pub const MAX_FINAL_PROVIDER_REQUEST_SEGMENTS_V2: usize = 3;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderClosureErrorV2 {
    Core(ContextCompilerV2Error),
    EmptyDigest(&'static str),
    SnapshotPredecessorMismatch,
    InvalidTokenizerIdentity,
    TokenizerFailed(String),
    InvalidTokenCount,
    FinalRequestEmpty,
    FinalRequestTooLarge,
    ContextPayloadNotUtf8,
    ContextPayloadMissing,
    ContextPayloadAmbiguous,
    SegmentCoverageInvalid,
    Arithmetic,
}

impl fmt::Display for ProviderClosureErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ProviderClosureErrorV2 {}

impl From<ContextCompilerV2Error> for ProviderClosureErrorV2 {
    fn from(value: ContextCompilerV2Error) -> Self {
        Self::Core(value)
    }
}

/// Construction-closed evidence that a fresh snapshot is the exact monotone
/// successor of the snapshot bound into the attachment.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAdmissionSnapshotSuccessorV2 {
    predecessor_snapshot_digest: Digest32,
    verified_snapshot: VerifiedAdmissionSnapshotV2,
    successor_digest: Digest32,
}

impl VerifiedAdmissionSnapshotSuccessorV2 {
    #[must_use]
    pub const fn predecessor_snapshot_digest(&self) -> Digest32 {
        self.predecessor_snapshot_digest
    }

    #[must_use]
    pub const fn successor_snapshot_digest(&self) -> Digest32 {
        self.verified_snapshot.snapshot_digest()
    }

    #[must_use]
    pub const fn successor_digest(&self) -> Digest32 {
        self.successor_digest
    }

    #[must_use]
    pub const fn verified_snapshot(&self) -> &VerifiedAdmissionSnapshotV2 {
        &self.verified_snapshot
    }

    pub fn validate(
        &self,
        predecessor: &VerifiedAdmissionSnapshotV2,
    ) -> Result<(), ProviderClosureErrorV2> {
        if self.predecessor_snapshot_digest.is_zero()
            || self.verified_snapshot.snapshot_digest().is_zero()
            || self.successor_digest.is_zero()
            || self.predecessor_snapshot_digest != predecessor.snapshot_digest()
            || self.verified_snapshot.observed_unix_ms() < predecessor.observed_unix_ms()
            || self.verified_snapshot.revocation_epoch() < predecessor.revocation_epoch()
            || self.successor_digest != self.compute_digest()
        {
            return Err(ProviderClosureErrorV2::SnapshotPredecessorMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = SNAPSHOT_SUCCESSOR_DOMAIN.to_vec();
        push_digest(&mut bytes, self.predecessor_snapshot_digest);
        push_digest(&mut bytes, self.verified_snapshot.snapshot_digest());
        push_digest(&mut bytes, self.verified_snapshot.verification_digest());
        push_u64(&mut bytes, self.verified_snapshot.observed_unix_ms());
        push_u64(&mut bytes, self.verified_snapshot.revocation_epoch());
        Digest32::of_bytes(&bytes)
    }
}

pub fn verify_admission_snapshot_successor_typed_v2(
    snapshot: ContextAdmissionSnapshotV2,
    predecessor: &VerifiedAdmissionSnapshotV2,
    verifier: &impl ContextAdmissionVerifierV2,
) -> Result<VerifiedAdmissionSnapshotSuccessorV2, ProviderClosureErrorV2> {
    let verified_snapshot =
        verify_admission_snapshot_successor_v2(snapshot, predecessor, verifier)?;
    let mut successor = VerifiedAdmissionSnapshotSuccessorV2 {
        predecessor_snapshot_digest: predecessor.snapshot_digest(),
        verified_snapshot,
        successor_digest: Digest32::ZERO,
    };
    successor.successor_digest = successor.compute_digest();
    successor.validate(predecessor)?;
    Ok(successor)
}

/// The only preferred V2 send-preparation entrypoint. It makes snapshot
/// lineage a type-level requirement and rejects a successor of any snapshot
/// other than the one already bound into the attachment.
pub fn prepare_delivery_from_successor_v2(
    compiled: &crate::CompiledContextV2,
    serialization: &SerializedContextV2,
    attachment: &ContextAttachmentV2,
    profile: &ContextModelProfileV2,
    successor: &VerifiedAdmissionSnapshotSuccessorV2,
    preparation_id: StableId,
) -> Result<ContextDeliveryPreparationV2, ProviderClosureErrorV2> {
    if successor.predecessor_snapshot_digest() != attachment.admission_snapshot_digest() {
        return Err(ProviderClosureErrorV2::SnapshotPredecessorMismatch);
    }
    Ok(prepare_delivery_v2(
        compiled,
        serialization,
        attachment,
        profile,
        successor.verified_snapshot(),
        preparation_id,
    )?)
}

/// Identity of the exact tokenizer executable and vocabulary used on the
/// complete canonical provider request. `declared_tokenizer_digest` is the
/// tokenizer identity admitted by the context model profile; the remaining
/// digests make the concrete runtime implementation reproducible.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalRequestTokenizerIdentityV2 {
    provider_id_digest: Digest32,
    provider_model_digest: Digest32,
    declared_tokenizer_digest: Digest32,
    tokenizer_binary_digest: Digest32,
    tokenizer_version_digest: Digest32,
    vocabulary_digest: Digest32,
    normalization_policy_digest: Digest32,
    identity_digest: Digest32,
}

impl FinalRequestTokenizerIdentityV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        provider_id_digest: Digest32,
        provider_model_digest: Digest32,
        declared_tokenizer_digest: Digest32,
        tokenizer_binary_digest: Digest32,
        tokenizer_version_digest: Digest32,
        vocabulary_digest: Digest32,
        normalization_policy_digest: Digest32,
    ) -> Result<Self, ProviderClosureErrorV2> {
        let mut identity = Self {
            provider_id_digest,
            provider_model_digest,
            declared_tokenizer_digest,
            tokenizer_binary_digest,
            tokenizer_version_digest,
            vocabulary_digest,
            normalization_policy_digest,
            identity_digest: Digest32::ZERO,
        };
        identity.identity_digest = identity.compute_digest();
        identity.validate_shape()?;
        Ok(identity)
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
    pub const fn declared_tokenizer_digest(&self) -> Digest32 {
        self.declared_tokenizer_digest
    }

    #[must_use]
    pub const fn tokenizer_binary_digest(&self) -> Digest32 {
        self.tokenizer_binary_digest
    }

    #[must_use]
    pub const fn tokenizer_version_digest(&self) -> Digest32 {
        self.tokenizer_version_digest
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
    pub const fn identity_digest(&self) -> Digest32 {
        self.identity_digest
    }

    pub fn validate_for(
        &self,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ProviderClosureErrorV2> {
        self.validate_shape()?;
        if self.provider_id_digest != profile.provider_id_digest
            || self.provider_model_digest != profile.provider_model_digest
            || self.declared_tokenizer_digest != profile.tokenizer_digest
        {
            return Err(ProviderClosureErrorV2::InvalidTokenizerIdentity);
        }
        Ok(())
    }

    fn validate_shape(&self) -> Result<(), ProviderClosureErrorV2> {
        for (name, digest) in [
            ("provider_id", self.provider_id_digest),
            ("provider_model", self.provider_model_digest),
            ("declared_tokenizer", self.declared_tokenizer_digest),
            ("tokenizer_binary", self.tokenizer_binary_digest),
            ("tokenizer_version", self.tokenizer_version_digest),
            ("tokenizer_vocabulary", self.vocabulary_digest),
            ("tokenizer_normalization", self.normalization_policy_digest),
            ("tokenizer_identity", self.identity_digest),
        ] {
            if digest.is_zero() {
                return Err(ProviderClosureErrorV2::EmptyDigest(name));
            }
        }
        if self.identity_digest != self.compute_digest() {
            return Err(ProviderClosureErrorV2::InvalidTokenizerIdentity);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = TOKENIZER_IDENTITY_DOMAIN.to_vec();
        for digest in [
            self.provider_id_digest,
            self.provider_model_digest,
            self.declared_tokenizer_digest,
            self.tokenizer_binary_digest,
            self.tokenizer_version_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        Digest32::of_bytes(&bytes)
    }
}

pub trait ExactFinalRequestTokenizerV2: Send + Sync {
    fn identity(&self) -> &FinalRequestTokenizerIdentityV2;

    /// Count the model-input tokens represented by this exact canonical
    /// provider request. Implementations must parse provider semantics rather
    /// than use byte/character estimates.
    fn count_final_request_tokens(&self, canonical_request: &[u8]) -> Result<u64, String>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FinalRequestSegmentKindV2 {
    TypedProviderFraming,
    CanonicalContextBundle,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalRequestSegmentV2 {
    kind: FinalRequestSegmentKindV2,
    start_offset: u64,
    end_offset: u64,
    wire_bytes_digest: Digest32,
    source_payload_digest: Option<Digest32>,
}

impl FinalRequestSegmentV2 {
    #[must_use]
    pub const fn kind(&self) -> FinalRequestSegmentKindV2 {
        self.kind
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
    pub const fn wire_bytes_digest(&self) -> Digest32 {
        self.wire_bytes_digest
    }

    #[must_use]
    pub const fn source_payload_digest(&self) -> Option<Digest32> {
        self.source_payload_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalRequestTokenizationReceiptV2 {
    request_digest: Digest32,
    tokenizer_identity: FinalRequestTokenizerIdentityV2,
    token_count: u64,
    receipt_digest: Digest32,
}

impl FinalRequestTokenizationReceiptV2 {
    #[must_use]
    pub const fn request_digest(&self) -> Digest32 {
        self.request_digest
    }

    #[must_use]
    pub const fn tokenizer_identity(&self) -> &FinalRequestTokenizerIdentityV2 {
        &self.tokenizer_identity
    }

    #[must_use]
    pub const fn token_count(&self) -> u64 {
        self.token_count
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = TOKENIZATION_RECEIPT_DOMAIN.to_vec();
        push_digest(&mut bytes, self.request_digest);
        push_digest(&mut bytes, self.tokenizer_identity.identity_digest());
        push_u64(&mut bytes, self.token_count);
        Digest32::of_bytes(&bytes)
    }
}

/// Construction-closed proof for the exact bytes passed to the HTTP transport
/// before compression or signing.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FinalProviderRequestProofV2 {
    preparation_digest: Digest32,
    context_payload_digest: Digest32,
    provider_request_digest: Digest32,
    provider_wire_semantic_digest: Digest32,
    request_bytes: u64,
    segments: Vec<FinalRequestSegmentV2>,
    segment_map_digest: Digest32,
    tokenization: FinalRequestTokenizationReceiptV2,
    proof_digest: Digest32,
    authority: AuthorityPosture,
}

impl FinalProviderRequestProofV2 {
    #[must_use]
    pub const fn preparation_digest(&self) -> Digest32 {
        self.preparation_digest
    }

    #[must_use]
    pub const fn context_payload_digest(&self) -> Digest32 {
        self.context_payload_digest
    }

    #[must_use]
    pub const fn provider_request_digest(&self) -> Digest32 {
        self.provider_request_digest
    }

    #[must_use]
    pub const fn provider_wire_semantic_digest(&self) -> Digest32 {
        self.provider_wire_semantic_digest
    }

    #[must_use]
    pub const fn request_bytes(&self) -> u64 {
        self.request_bytes
    }

    #[must_use]
    pub fn segments(&self) -> &[FinalRequestSegmentV2] {
        &self.segments
    }

    #[must_use]
    pub const fn segment_map_digest(&self) -> Digest32 {
        self.segment_map_digest
    }

    #[must_use]
    pub const fn tokenization(&self) -> &FinalRequestTokenizationReceiptV2 {
        &self.tokenization
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate_for(
        &self,
        preparation: &ContextDeliveryPreparationV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ProviderClosureErrorV2> {
        self.tokenization.tokenizer_identity.validate_for(profile)?;
        if self.preparation_digest != preparation.preparation_digest()
            || self.context_payload_digest != preparation.payload_digest()
            || self.provider_request_digest.is_zero()
            || self.provider_wire_semantic_digest.is_zero()
            || self.request_bytes == 0
            || self.request_bytes
                > u64::try_from(MAX_FINAL_PROVIDER_REQUEST_BYTES_V2).unwrap_or(u64::MAX)
            || self.segments.is_empty()
            || self.segments.len() > MAX_FINAL_PROVIDER_REQUEST_SEGMENTS_V2
            || self.segment_map_digest != compute_segment_map_digest(&self.segments)
            || self.tokenization.request_digest != self.provider_request_digest
            || self.tokenization.token_count == 0
            || self.tokenization.token_count > profile.maximum_context_tokens
            || self.tokenization.receipt_digest != self.tokenization.compute_digest()
            || self.authority.grants_any()
            || self.proof_digest != self.compute_digest()
        {
            return Err(ProviderClosureErrorV2::SegmentCoverageInvalid);
        }
        validate_segment_coverage(&self.segments, self.request_bytes)?;
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = FINAL_REQUEST_PROOF_DOMAIN.to_vec();
        for digest in [
            self.preparation_digest,
            self.context_payload_digest,
            self.provider_request_digest,
            self.provider_wire_semantic_digest,
            self.segment_map_digest,
            self.tokenization.receipt_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.request_bytes);
        Digest32::of_bytes(&bytes)
    }
}

#[allow(clippy::too_many_arguments)]
pub fn prove_final_provider_request_v2(
    preparation: &ContextDeliveryPreparationV2,
    attachment: &ContextAttachmentV2,
    serialization: &SerializedContextV2,
    profile: &ContextModelProfileV2,
    provider_wire_semantic_digest: Digest32,
    canonical_request: &[u8],
    tokenizer: &impl ExactFinalRequestTokenizerV2,
) -> Result<FinalProviderRequestProofV2, ProviderClosureErrorV2> {
    preparation.validate_for(attachment, serialization, profile)?;
    if canonical_request.is_empty() {
        return Err(ProviderClosureErrorV2::FinalRequestEmpty);
    }
    if canonical_request.len() > MAX_FINAL_PROVIDER_REQUEST_BYTES_V2 {
        return Err(ProviderClosureErrorV2::FinalRequestTooLarge);
    }
    if provider_wire_semantic_digest.is_zero() {
        return Err(ProviderClosureErrorV2::EmptyDigest(
            "provider_wire_semantic",
        ));
    }
    tokenizer.identity().validate_for(profile)?;

    let payload_text = std::str::from_utf8(serialization.payload())
        .map_err(|_| ProviderClosureErrorV2::ContextPayloadNotUtf8)?;
    let encoded_payload = serde_json::to_string(payload_text)
        .map_err(|_| ProviderClosureErrorV2::ContextPayloadNotUtf8)?;
    let encoded_payload = encoded_payload
        .as_bytes()
        .get(1..encoded_payload.len().saturating_sub(1))
        .ok_or(ProviderClosureErrorV2::ContextPayloadNotUtf8)?;
    let segments = build_segment_map(
        canonical_request,
        encoded_payload,
        preparation.payload_digest(),
    )?;

    let provider_request_digest = Digest32::of_bytes(canonical_request);
    let token_count = tokenizer
        .count_final_request_tokens(canonical_request)
        .map_err(ProviderClosureErrorV2::TokenizerFailed)?;
    if token_count == 0 || token_count > profile.maximum_context_tokens {
        return Err(ProviderClosureErrorV2::InvalidTokenCount);
    }
    let mut tokenization = FinalRequestTokenizationReceiptV2 {
        request_digest: provider_request_digest,
        tokenizer_identity: tokenizer.identity().clone(),
        token_count,
        receipt_digest: Digest32::ZERO,
    };
    tokenization.receipt_digest = tokenization.compute_digest();

    let segment_map_digest = compute_segment_map_digest(&segments);
    let mut proof = FinalProviderRequestProofV2 {
        preparation_digest: preparation.preparation_digest(),
        context_payload_digest: preparation.payload_digest(),
        provider_request_digest,
        provider_wire_semantic_digest,
        request_bytes: u64::try_from(canonical_request.len())
            .map_err(|_| ProviderClosureErrorV2::Arithmetic)?,
        segments,
        segment_map_digest,
        tokenization,
        proof_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    proof.proof_digest = proof.compute_digest();
    proof.validate_for(preparation, profile)?;
    Ok(proof)
}

fn build_segment_map(
    request: &[u8],
    encoded_payload: &[u8],
    source_payload_digest: Digest32,
) -> Result<Vec<FinalRequestSegmentV2>, ProviderClosureErrorV2> {
    if encoded_payload.is_empty() {
        return Err(ProviderClosureErrorV2::ContextPayloadMissing);
    }
    let matches = request
        .windows(encoded_payload.len())
        .enumerate()
        .filter_map(|(offset, window)| (window == encoded_payload).then_some(offset))
        .collect::<Vec<_>>();
    let [start] = matches.as_slice() else {
        return if matches.is_empty() {
            Err(ProviderClosureErrorV2::ContextPayloadMissing)
        } else {
            Err(ProviderClosureErrorV2::ContextPayloadAmbiguous)
        };
    };
    let end = start
        .checked_add(encoded_payload.len())
        .ok_or(ProviderClosureErrorV2::Arithmetic)?;
    let mut segments = Vec::with_capacity(MAX_FINAL_PROVIDER_REQUEST_SEGMENTS_V2);
    if *start > 0 {
        segments.push(segment(
            FinalRequestSegmentKindV2::TypedProviderFraming,
            0,
            *start,
            &request[..*start],
            None,
        )?);
    }
    segments.push(segment(
        FinalRequestSegmentKindV2::CanonicalContextBundle,
        *start,
        end,
        &request[*start..end],
        Some(source_payload_digest),
    )?);
    if end < request.len() {
        segments.push(segment(
            FinalRequestSegmentKindV2::TypedProviderFraming,
            end,
            request.len(),
            &request[end..],
            None,
        )?);
    }
    validate_segment_coverage(
        &segments,
        u64::try_from(request.len()).map_err(|_| ProviderClosureErrorV2::Arithmetic)?,
    )?;
    Ok(segments)
}

fn segment(
    kind: FinalRequestSegmentKindV2,
    start: usize,
    end: usize,
    bytes: &[u8],
    source_payload_digest: Option<Digest32>,
) -> Result<FinalRequestSegmentV2, ProviderClosureErrorV2> {
    if start >= end || bytes.is_empty() {
        return Err(ProviderClosureErrorV2::SegmentCoverageInvalid);
    }
    Ok(FinalRequestSegmentV2 {
        kind,
        start_offset: u64::try_from(start).map_err(|_| ProviderClosureErrorV2::Arithmetic)?,
        end_offset: u64::try_from(end).map_err(|_| ProviderClosureErrorV2::Arithmetic)?,
        wire_bytes_digest: Digest32::of_bytes(bytes),
        source_payload_digest,
    })
}

fn validate_segment_coverage(
    segments: &[FinalRequestSegmentV2],
    request_bytes: u64,
) -> Result<(), ProviderClosureErrorV2> {
    let mut cursor = 0_u64;
    let mut context_segments = 0_usize;
    for segment in segments {
        if segment.start_offset != cursor
            || segment.start_offset >= segment.end_offset
            || segment.end_offset > request_bytes
            || segment.wire_bytes_digest.is_zero()
        {
            return Err(ProviderClosureErrorV2::SegmentCoverageInvalid);
        }
        match segment.kind {
            FinalRequestSegmentKindV2::TypedProviderFraming => {
                if segment.source_payload_digest.is_some() {
                    return Err(ProviderClosureErrorV2::SegmentCoverageInvalid);
                }
            }
            FinalRequestSegmentKindV2::CanonicalContextBundle => {
                context_segments = context_segments
                    .checked_add(1)
                    .ok_or(ProviderClosureErrorV2::Arithmetic)?;
                if segment.source_payload_digest.is_none() {
                    return Err(ProviderClosureErrorV2::SegmentCoverageInvalid);
                }
            }
        }
        cursor = segment.end_offset;
    }
    if cursor != request_bytes || context_segments != 1 {
        return Err(ProviderClosureErrorV2::SegmentCoverageInvalid);
    }
    Ok(())
}

fn compute_segment_map_digest(segments: &[FinalRequestSegmentV2]) -> Digest32 {
    let mut bytes = SEGMENT_MAP_DOMAIN.to_vec();
    push_u64(
        &mut bytes,
        u64::try_from(segments.len()).unwrap_or(u64::MAX),
    );
    for segment in segments {
        bytes.push(match segment.kind {
            FinalRequestSegmentKindV2::TypedProviderFraming => 0,
            FinalRequestSegmentKindV2::CanonicalContextBundle => 1,
        });
        push_u64(&mut bytes, segment.start_offset);
        push_u64(&mut bytes, segment.end_offset);
        push_digest(&mut bytes, segment.wire_bytes_digest);
        match segment.source_payload_digest {
            Some(digest) => {
                bytes.push(1);
                push_digest(&mut bytes, digest);
            }
            None => bytes.push(0),
        }
    }
    Digest32::of_bytes(&bytes)
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &str) -> Digest32 {
        Digest32::of_bytes(label.as_bytes())
    }

    #[test]
    fn segment_map_covers_unicode_and_control_escaping_exactly() {
        let payload = "政策\ncontrol:\u{0001} emoji:🧪";
        let encoded = serde_json::to_string(payload).expect("encode");
        let encoded = &encoded.as_bytes()[1..encoded.len() - 1];
        let mut request = br#"{"model":"m","instructions":"prefix\n"#.to_vec();
        request.extend_from_slice(encoded);
        request.extend_from_slice(br#"\nsuffix","input":[]}"#);
        let segments = build_segment_map(&request, encoded, digest("payload")).expect("proof");
        assert_eq!(segments.len(), 3);
        assert_eq!(
            segments[1].kind(),
            FinalRequestSegmentKindV2::CanonicalContextBundle
        );
        assert_eq!(segments[0].start_offset(), 0);
        assert_eq!(segments.last().expect("last").end_offset(), request.len() as u64);
    }

    #[test]
    fn adversarial_duplicate_payload_is_rejected() {
        let payload = b"same";
        let request = b"before same middle same after";
        assert_eq!(
            build_segment_map(request, payload, digest("payload")),
            Err(ProviderClosureErrorV2::ContextPayloadAmbiguous)
        );
    }

    #[test]
    fn large_request_has_bounded_three_segment_proof() {
        let payload = b"context-bundle";
        let mut request = vec![b'a'; 1024 * 1024];
        request.extend_from_slice(payload);
        request.extend(std::iter::repeat_n(b'z', 1024 * 1024));
        let segments = build_segment_map(&request, payload, digest("payload")).expect("proof");
        assert_eq!(segments.len(), MAX_FINAL_PROVIDER_REQUEST_SEGMENTS_V2);
        validate_segment_coverage(&segments, request.len() as u64).expect("coverage");
    }
}
