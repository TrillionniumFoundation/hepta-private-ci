//! Provider-final-request proof chain for context compiler V2.
//!
//! This module closes the boundary between the canonical context bundle and the
//! exact provider request bytes. The context bundle is serialized by a
//! compiler-owned canonical serializer with a complete segment map. The final
//! provider request is tokenized only after its exact canonical wire body is
//! available. A typed admission-snapshot successor is required before the
//! provider-bound preparation can be minted.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CompiledContextV2;
use crate::ContextAdmissionSnapshotV2;
use crate::ContextAdmissionVerifierV2;
use crate::ContextAttachmentV2;
use crate::ContextCompilerV2Error;
use crate::ContextDeliveryPreparationV2;
use crate::ContextModelProfileV2;
use crate::ContextRealizedItemV2;
use crate::ContextRoleV2;
use crate::ContextSerializerV2;
use crate::ExactTokenizerV2;
use crate::SerializedContextV2;
use crate::VerifiedAdmissionSnapshotV2;
use crate::prepare_delivery_v2;
use crate::record_serialization;
use crate::verify_admission_snapshot_successor_v2;

pub const MAX_PROVIDER_FINAL_REQUEST_BYTES_V2: usize = 32 * 1024 * 1024;
pub const MAX_CANONICAL_CONTEXT_SEGMENTS_V2: usize = 8_193;
pub const MAX_PROVIDER_REQUEST_SEGMENTS_V2: usize = 16_384;
pub const MAX_PROVIDER_ID_BYTES_V2: usize = 256;
pub const MAX_PROVIDER_MODEL_BYTES_V2: usize = 512;

const CANONICAL_CONTEXT_DOMAIN: &[u8] = b"hepta.context-canonical-bundle.v2";
const CANONICAL_CONTEXT_COVERAGE_DOMAIN: &[u8] =
    b"hepta.context-canonical-bundle-coverage.v2";
const TOKENIZER_IDENTITY_DOMAIN: &[u8] = b"hepta.provider-tokenizer-identity.v2";
const FINAL_REQUEST_TOKENIZATION_DOMAIN: &[u8] =
    b"hepta.provider-final-request-tokenization.v2";
const FINAL_REQUEST_SEGMENT_MAP_DOMAIN: &[u8] = b"hepta.provider-request-segment-map.v2";
const FINAL_REQUEST_PROOF_DOMAIN: &[u8] = b"hepta.provider-final-request-proof.v2";
const PROVIDER_BOUND_PREPARATION_DOMAIN: &[u8] =
    b"hepta.context-provider-bound-preparation.v2";
const PROVIDER_BOUND_RECEIPT_DOMAIN: &[u8] = b"hepta.context-provider-bound-receipt.v2";
const PROVIDER_BOUND_PREPARATION_RECORD_DOMAIN: &[u8] =
    b"hepta.context-provider-bound-preparation-record.v2";
const TYPED_SUCCESSOR_DOMAIN: &[u8] = b"hepta.context-typed-snapshot-successor.v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExactTokenizerIdentityV2 {
    provider_id: String,
    model: String,
    tokenizer_version: String,
    tokenizer_binary_digest: Digest32,
    vocabulary_digest: Digest32,
    normalization_policy_digest: Digest32,
    identity_digest: Digest32,
}

impl ExactTokenizerIdentityV2 {
    pub fn new(
        provider_id: impl Into<String>,
        model: impl Into<String>,
        tokenizer_version: impl Into<String>,
        tokenizer_binary_digest: Digest32,
        vocabulary_digest: Digest32,
        normalization_policy_digest: Digest32,
    ) -> Result<Self, ProviderRequestProofErrorV2> {
        let mut identity = Self {
            provider_id: provider_id.into(),
            model: model.into(),
            tokenizer_version: tokenizer_version.into(),
            tokenizer_binary_digest,
            vocabulary_digest,
            normalization_policy_digest,
            identity_digest: Digest32::ZERO,
        };
        identity.validate_shape()?;
        identity.identity_digest = identity.compute_digest();
        Ok(identity)
    }

    pub fn validate(&self) -> Result<(), ProviderRequestProofErrorV2> {
        self.validate_shape()?;
        if self.identity_digest != self.compute_digest() {
            return Err(ProviderRequestProofErrorV2::DigestMismatch(
                "tokenizer_identity",
            ));
        }
        Ok(())
    }

    fn validate_shape(&self) -> Result<(), ProviderRequestProofErrorV2> {
        validate_bounded_text(
            "provider_id",
            &self.provider_id,
            MAX_PROVIDER_ID_BYTES_V2,
        )?;
        validate_bounded_text("model", &self.model, MAX_PROVIDER_MODEL_BYTES_V2)?;
        validate_bounded_text("tokenizer_version", &self.tokenizer_version, 512)?;
        for (name, digest) in [
            ("tokenizer_binary", self.tokenizer_binary_digest),
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
    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    #[must_use]
    pub fn model(&self) -> &str {
        &self.model
    }

    #[must_use]
    pub fn tokenizer_version(&self) -> &str {
        &self.tokenizer_version
    }

    #[must_use]
    pub const fn tokenizer_binary_digest(&self) -> Digest32 {
        self.tokenizer_binary_digest
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

    #[must_use]
    fn compute_digest(&self) -> Digest32 {
        let mut bytes = TOKENIZER_IDENTITY_DOMAIN.to_vec();
        push_text(&mut bytes, &self.provider_id);
        push_text(&mut bytes, &self.model);
        push_text(&mut bytes, &self.tokenizer_version);
        push_digest(&mut bytes, self.tokenizer_binary_digest);
        push_digest(&mut bytes, self.vocabulary_digest);
        push_digest(&mut bytes, self.normalization_policy_digest);
        Digest32::of_bytes(&bytes)
    }
}

pub trait ExactProviderRequestTokenizerV2: Send + Sync {
    fn identity(&self) -> Result<ExactTokenizerIdentityV2, ProviderRequestProofErrorV2>;

    fn count_final_request_tokens(
        &self,
        final_request: &[u8],
    ) -> Result<u64, ProviderRequestProofErrorV2>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderFinalRequestTokenizationV2 {
    tokenizer_identity: ExactTokenizerIdentityV2,
    final_request_digest: Digest32,
    final_request_bytes: u64,
    token_count: u64,
    receipt_digest: Digest32,
}

impl ProviderFinalRequestTokenizationV2 {
    pub fn from_exact_bytes(
        final_request: &[u8],
        tokenizer: &impl ExactProviderRequestTokenizerV2,
    ) -> Result<Self, ProviderRequestProofErrorV2> {
        validate_final_request_bytes(final_request)?;
        let tokenizer_identity = tokenizer.identity()?;
        tokenizer_identity.validate()?;
        let token_count = tokenizer.count_final_request_tokens(final_request)?;
        if token_count == 0 || token_count > 4_000_000 {
            return Err(ProviderRequestProofErrorV2::InvalidTokenCount);
        }
        let mut receipt = Self {
            tokenizer_identity,
            final_request_digest: Digest32::of_bytes(final_request),
            final_request_bytes: u64::try_from(final_request.len())
                .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?,
            token_count,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.compute_digest();
        receipt.validate_for(final_request)?;
        Ok(receipt)
    }

    pub fn validate_for(
        &self,
        final_request: &[u8],
    ) -> Result<(), ProviderRequestProofErrorV2> {
        validate_final_request_bytes(final_request)?;
        self.tokenizer_identity.validate()?;
        if self.final_request_digest != Digest32::of_bytes(final_request)
            || self.final_request_bytes
                != u64::try_from(final_request.len())
                    .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?
        {
            return Err(ProviderRequestProofErrorV2::FinalRequestMismatch);
        }
        if self.token_count == 0 || self.token_count > 4_000_000 {
            return Err(ProviderRequestProofErrorV2::InvalidTokenCount);
        }
        if self.receipt_digest != self.compute_digest() {
            return Err(ProviderRequestProofErrorV2::DigestMismatch(
                "final_request_tokenization",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub const fn final_request_digest(&self) -> Digest32 {
        self.final_request_digest
    }

    #[must_use]
    pub const fn token_count(&self) -> u64 {
        self.token_count
    }

    #[must_use]
    pub const fn final_request_bytes(&self) -> u64 {
        self.final_request_bytes
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn tokenizer_identity(&self) -> &ExactTokenizerIdentityV2 {
        &self.tokenizer_identity
    }

    #[must_use]
    fn compute_digest(&self) -> Digest32 {
        let mut bytes = FINAL_REQUEST_TOKENIZATION_DOMAIN.to_vec();
        push_digest(&mut bytes, self.tokenizer_identity.identity_digest());
        push_digest(&mut bytes, self.final_request_digest);
        push_u64(&mut bytes, self.final_request_bytes);
        push_u64(&mut bytes, self.token_count);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CanonicalContextSegmentKindV2 {
    Framing { framing_type: StableId },
    SelectedItem {
        item_id: StableId,
        role: ContextRoleV2,
        content_digest: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalContextSegmentV2 {
    offset: u64,
    length: u64,
    encoded_digest: Digest32,
    kind: CanonicalContextSegmentKindV2,
}

impl CanonicalContextSegmentV2 {
    #[must_use]
    pub const fn offset(&self) -> u64 {
        self.offset
    }

    #[must_use]
    pub const fn length(&self) -> u64 {
        self.length
    }

    #[must_use]
    pub const fn encoded_digest(&self) -> Digest32 {
        self.encoded_digest
    }

    #[must_use]
    pub const fn kind(&self) -> &CanonicalContextSegmentKindV2 {
        &self.kind
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalSerializedContextV2 {
    serialized_context: SerializedContextV2,
    segments: Vec<CanonicalContextSegmentV2>,
    coverage_digest: Digest32,
}

impl CanonicalSerializedContextV2 {
    pub fn validate_for(
        &self,
        compiled: &CompiledContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ProviderRequestProofErrorV2> {
        self.serialized_context
            .validate_for(compiled, profile)
            .map_err(ProviderRequestProofErrorV2::Context)?;
        validate_canonical_segments(
            self.serialized_context.payload(),
            self.segments.as_slice(),
            compiled.receipt().selected_item_ids(),
        )?;
        if self.coverage_digest != compute_canonical_coverage_digest(&self.segments) {
            return Err(ProviderRequestProofErrorV2::DigestMismatch(
                "canonical_context_coverage",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub const fn serialized_context(&self) -> &SerializedContextV2 {
        &self.serialized_context
    }

    #[must_use]
    pub fn into_serialized_context(self) -> SerializedContextV2 {
        self.serialized_context
    }

    #[must_use]
    pub fn segments(&self) -> &[CanonicalContextSegmentV2] {
        &self.segments
    }

    #[must_use]
    pub const fn coverage_digest(&self) -> Digest32 {
        self.coverage_digest
    }
}

pub fn record_canonical_serialization_v2(
    compiled: &CompiledContextV2,
    profile: &ContextModelProfileV2,
    serialization_id: StableId,
    realizations: Vec<ContextRealizedItemV2>,
    tokenizer: &impl ExactTokenizerV2,
) -> Result<CanonicalSerializedContextV2, ProviderRequestProofErrorV2> {
    let by_id = realizations
        .into_iter()
        .map(|item| (item.item_id.clone(), item))
        .collect::<BTreeMap<_, _>>();
    if by_id.len() != compiled.receipt().selected_item_ids().len() {
        return Err(ProviderRequestProofErrorV2::SelectedSetMismatch);
    }
    let ordered_realizations = compiled
        .receipt()
        .selected_item_ids()
        .iter()
        .map(|item_id| {
            by_id
                .get(item_id)
                .cloned()
                .ok_or(ProviderRequestProofErrorV2::SelectedSetMismatch)
        })
        .collect::<Result<Vec<_>, _>>()?;
    let (payload, segments) = build_canonical_context_bundle(&ordered_realizations)?;
    let serializer = CanonicalContextSerializerV2 {
        serializer_digest: profile.serializer_digest,
        template_digest: profile.template_digest,
        tool_schema_digest: profile.tool_schema_digest,
        payload,
    };
    let serialized_context = record_serialization(
        compiled,
        profile,
        serialization_id,
        ordered_realizations,
        &serializer,
        tokenizer,
    )
    .map_err(ProviderRequestProofErrorV2::Context)?;
    validate_canonical_segments(
        serialized_context.payload(),
        segments.as_slice(),
        compiled.receipt().selected_item_ids(),
    )?;
    let output = CanonicalSerializedContextV2 {
        serialized_context,
        coverage_digest: compute_canonical_coverage_digest(&segments),
        segments,
    };
    output.validate_for(compiled, profile)?;
    Ok(output)
}

#[derive(Debug)]
struct CanonicalContextSerializerV2 {
    serializer_digest: Digest32,
    template_digest: Digest32,
    tool_schema_digest: Digest32,
    payload: Vec<u8>,
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
        _items: &[ContextRealizedItemV2],
    ) -> Result<Vec<u8>, ContextCompilerV2Error> {
        Ok(self.payload.clone())
    }
}

fn build_canonical_context_bundle(
    realizations: &[ContextRealizedItemV2],
) -> Result<(Vec<u8>, Vec<CanonicalContextSegmentV2>), ProviderRequestProofErrorV2> {
    let mut payload = Vec::new();
    let mut segments = Vec::new();
    append_framing_segment(
        &mut payload,
        &mut segments,
        StableId::new("context-bundle-header")
            .map_err(|_| ProviderRequestProofErrorV2::InvalidSegment)?,
        |bytes| {
            bytes.extend_from_slice(CANONICAL_CONTEXT_DOMAIN);
            push_u64(bytes, u64::try_from(realizations.len()).unwrap_or(u64::MAX));
        },
    )?;
    for realization in realizations {
        append_framing_segment(
            &mut payload,
            &mut segments,
            StableId::new("context-item-header")
                .map_err(|_| ProviderRequestProofErrorV2::InvalidSegment)?,
            |bytes| {
                push_text(bytes, realization.item_id.as_str());
                bytes.push(role_code(realization.role));
                push_u64(
                    bytes,
                    u64::try_from(realization.content.len()).unwrap_or(u64::MAX),
                );
            },
        )?;
        let offset = u64::try_from(payload.len())
            .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?;
        payload.extend_from_slice(&realization.content);
        let length = u64::try_from(realization.content.len())
            .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?;
        segments.push(CanonicalContextSegmentV2 {
            offset,
            length,
            encoded_digest: Digest32::of_bytes(&realization.content),
            kind: CanonicalContextSegmentKindV2::SelectedItem {
                item_id: realization.item_id.clone(),
                role: realization.role,
                content_digest: Digest32::of_bytes(&realization.content),
            },
        });
    }
    if segments.len() > MAX_CANONICAL_CONTEXT_SEGMENTS_V2 {
        return Err(ProviderRequestProofErrorV2::SegmentLimitExceeded);
    }
    Ok((payload, segments))
}

fn append_framing_segment(
    payload: &mut Vec<u8>,
    segments: &mut Vec<CanonicalContextSegmentV2>,
    framing_type: StableId,
    append: impl FnOnce(&mut Vec<u8>),
) -> Result<(), ProviderRequestProofErrorV2> {
    let start = payload.len();
    append(payload);
    let bytes = payload
        .get(start..)
        .ok_or(ProviderRequestProofErrorV2::Arithmetic)?;
    if bytes.is_empty() {
        return Err(ProviderRequestProofErrorV2::InvalidSegment);
    }
    segments.push(CanonicalContextSegmentV2 {
        offset: u64::try_from(start).map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?,
        length: u64::try_from(bytes.len())
            .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?,
        encoded_digest: Digest32::of_bytes(bytes),
        kind: CanonicalContextSegmentKindV2::Framing { framing_type },
    });
    Ok(())
}

fn validate_canonical_segments(
    payload: &[u8],
    segments: &[CanonicalContextSegmentV2],
    selected_item_ids: &[StableId],
) -> Result<(), ProviderRequestProofErrorV2> {
    if payload.is_empty()
        || segments.is_empty()
        || segments.len() > MAX_CANONICAL_CONTEXT_SEGMENTS_V2
    {
        return Err(ProviderRequestProofErrorV2::InvalidSegmentMap);
    }
    let mut expected_offset = 0_u64;
    let mut selected = Vec::new();
    for segment in segments {
        if segment.offset != expected_offset || segment.length == 0 {
            return Err(ProviderRequestProofErrorV2::IncompleteSegmentCoverage);
        }
        let end = segment
            .offset
            .checked_add(segment.length)
            .ok_or(ProviderRequestProofErrorV2::Arithmetic)?;
        let start = usize::try_from(segment.offset)
            .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?;
        let end_usize =
            usize::try_from(end).map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?;
        let bytes = payload
            .get(start..end_usize)
            .ok_or(ProviderRequestProofErrorV2::IncompleteSegmentCoverage)?;
        if Digest32::of_bytes(bytes) != segment.encoded_digest {
            return Err(ProviderRequestProofErrorV2::DigestMismatch(
                "canonical_context_segment",
            ));
        }
        match &segment.kind {
            CanonicalContextSegmentKindV2::Framing { framing_type } => {
                if framing_type.as_str().is_empty() {
                    return Err(ProviderRequestProofErrorV2::InvalidSegment);
                }
            }
            CanonicalContextSegmentKindV2::SelectedItem {
                item_id,
                content_digest,
                ..
            } => {
                if *content_digest != segment.encoded_digest {
                    return Err(ProviderRequestProofErrorV2::DigestMismatch(
                        "selected_context_segment",
                    ));
                }
                selected.push(item_id.clone());
            }
        }
        expected_offset = end;
    }
    if expected_offset
        != u64::try_from(payload.len()).map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?
    {
        return Err(ProviderRequestProofErrorV2::IncompleteSegmentCoverage);
    }
    if selected != selected_item_ids {
        return Err(ProviderRequestProofErrorV2::SelectedSetMismatch);
    }
    Ok(())
}

fn compute_canonical_coverage_digest(segments: &[CanonicalContextSegmentV2]) -> Digest32 {
    let mut bytes = CANONICAL_CONTEXT_COVERAGE_DOMAIN.to_vec();
    push_u64(&mut bytes, u64::try_from(segments.len()).unwrap_or(u64::MAX));
    for segment in segments {
        push_u64(&mut bytes, segment.offset);
        push_u64(&mut bytes, segment.length);
        push_digest(&mut bytes, segment.encoded_digest);
        match &segment.kind {
            CanonicalContextSegmentKindV2::Framing { framing_type } => {
                bytes.push(0);
                push_text(&mut bytes, framing_type.as_str());
            }
            CanonicalContextSegmentKindV2::SelectedItem {
                item_id,
                role,
                content_digest,
            } => {
                bytes.push(1);
                push_text(&mut bytes, item_id.as_str());
                bytes.push(role_code(*role));
                push_digest(&mut bytes, *content_digest);
            }
        }
    }
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAdmissionSnapshotSuccessorV2 {
    snapshot: VerifiedAdmissionSnapshotV2,
    predecessor_snapshot_digest: Digest32,
    successor_witness_digest: Digest32,
}

impl VerifiedAdmissionSnapshotSuccessorV2 {
    #[must_use]
    pub const fn snapshot(&self) -> &VerifiedAdmissionSnapshotV2 {
        &self.snapshot
    }

    #[must_use]
    pub const fn predecessor_snapshot_digest(&self) -> Digest32 {
        self.predecessor_snapshot_digest
    }

    #[must_use]
    pub const fn successor_witness_digest(&self) -> Digest32 {
        self.successor_witness_digest
    }

    pub fn validate_for(
        &self,
        predecessor: &VerifiedAdmissionSnapshotV2,
    ) -> Result<(), ProviderRequestProofErrorV2> {
        if self.predecessor_snapshot_digest != predecessor.snapshot_digest() {
            return Err(ProviderRequestProofErrorV2::SnapshotPredecessorMismatch);
        }
        let expected = compute_successor_witness_digest(
            self.predecessor_snapshot_digest,
            self.snapshot.snapshot_digest(),
            self.snapshot.verification_digest(),
        );
        if self.successor_witness_digest != expected {
            return Err(ProviderRequestProofErrorV2::DigestMismatch(
                "typed_snapshot_successor",
            ));
        }
        Ok(())
    }
}

pub fn verify_typed_admission_snapshot_successor_v2(
    successor: ContextAdmissionSnapshotV2,
    predecessor: &VerifiedAdmissionSnapshotV2,
    verifier: &impl ContextAdmissionVerifierV2,
) -> Result<VerifiedAdmissionSnapshotSuccessorV2, ProviderRequestProofErrorV2> {
    let snapshot = verify_admission_snapshot_successor_v2(successor, predecessor, verifier)
        .map_err(ProviderRequestProofErrorV2::Context)?;
    let predecessor_snapshot_digest = predecessor.snapshot_digest();
    let successor_witness_digest = compute_successor_witness_digest(
        predecessor_snapshot_digest,
        snapshot.snapshot_digest(),
        snapshot.verification_digest(),
    );
    let typed = VerifiedAdmissionSnapshotSuccessorV2 {
        snapshot,
        predecessor_snapshot_digest,
        successor_witness_digest,
    };
    typed.validate_for(predecessor)?;
    Ok(typed)
}

fn compute_successor_witness_digest(
    predecessor: Digest32,
    successor: Digest32,
    verification: Digest32,
) -> Digest32 {
    let mut bytes = TYPED_SUCCESSOR_DOMAIN.to_vec();
    push_digest(&mut bytes, predecessor);
    push_digest(&mut bytes, successor);
    push_digest(&mut bytes, verification);
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderRequestSegmentKindV2 {
    SelectedContextItem {
        item_id: StableId,
        source_content_digest: Digest32,
    },
    TypedFraming {
        framing_type: StableId,
        framing_policy_digest: Digest32,
    },
    HostCanonicalMaterial {
        material_type: StableId,
        semantic_digest: Digest32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderRequestSegmentV2 {
    pub offset: u64,
    pub length: u64,
    pub encoded_digest: Digest32,
    pub kind: ProviderRequestSegmentKindV2,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderRequestSegmentMapV2 {
    segments: Vec<ProviderRequestSegmentV2>,
    selected_item_ids: Vec<StableId>,
    map_digest: Digest32,
}

impl ProviderRequestSegmentMapV2 {
    pub fn verify(
        final_request: &[u8],
        mut segments: Vec<ProviderRequestSegmentV2>,
        expected_selected_items: &BTreeMap<StableId, Digest32>,
    ) -> Result<Self, ProviderRequestProofErrorV2> {
        validate_final_request_bytes(final_request)?;
        if segments.is_empty() || segments.len() > MAX_PROVIDER_REQUEST_SEGMENTS_V2 {
            return Err(ProviderRequestProofErrorV2::SegmentLimitExceeded);
        }
        segments.sort_by_key(|segment| segment.offset);
        let mut expected_offset = 0_u64;
        let mut selected = BTreeMap::new();
        for segment in &segments {
            if segment.offset != expected_offset || segment.length == 0 {
                return Err(ProviderRequestProofErrorV2::IncompleteSegmentCoverage);
            }
            let end = segment
                .offset
                .checked_add(segment.length)
                .ok_or(ProviderRequestProofErrorV2::Arithmetic)?;
            let start = usize::try_from(segment.offset)
                .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?;
            let end_usize =
                usize::try_from(end).map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?;
            let bytes = final_request
                .get(start..end_usize)
                .ok_or(ProviderRequestProofErrorV2::IncompleteSegmentCoverage)?;
            if Digest32::of_bytes(bytes) != segment.encoded_digest {
                return Err(ProviderRequestProofErrorV2::DigestMismatch(
                    "provider_request_segment",
                ));
            }
            match &segment.kind {
                ProviderRequestSegmentKindV2::SelectedContextItem {
                    item_id,
                    source_content_digest,
                } => {
                    let expected = expected_selected_items
                        .get(item_id)
                        .ok_or(ProviderRequestProofErrorV2::SelectedSetMismatch)?;
                    if expected != source_content_digest
                        || selected
                            .insert(item_id.clone(), *source_content_digest)
                            .is_some()
                    {
                        return Err(ProviderRequestProofErrorV2::SelectedSetMismatch);
                    }
                }
                ProviderRequestSegmentKindV2::TypedFraming {
                    framing_type,
                    framing_policy_digest,
                } => {
                    if framing_type.as_str().is_empty() || framing_policy_digest.is_zero() {
                        return Err(ProviderRequestProofErrorV2::InvalidSegment);
                    }
                }
                ProviderRequestSegmentKindV2::HostCanonicalMaterial {
                    material_type,
                    semantic_digest,
                } => {
                    if material_type.as_str().is_empty() || semantic_digest.is_zero() {
                        return Err(ProviderRequestProofErrorV2::InvalidSegment);
                    }
                }
            }
            expected_offset = end;
        }
        if expected_offset
            != u64::try_from(final_request.len())
                .map_err(|_| ProviderRequestProofErrorV2::Arithmetic)?
            || selected != *expected_selected_items
        {
            return Err(ProviderRequestProofErrorV2::IncompleteSegmentCoverage);
        }
        let selected_item_ids = selected.keys().cloned().collect::<Vec<_>>();
        let map_digest = compute_provider_segment_map_digest(&segments, &selected_item_ids);
        Ok(Self {
            segments,
            selected_item_ids,
            map_digest,
        })
    }

    #[must_use]
    pub fn segments(&self) -> &[ProviderRequestSegmentV2] {
        &self.segments
    }

    #[must_use]
    pub fn selected_item_ids(&self) -> &[StableId] {
        &self.selected_item_ids
    }

    #[must_use]
    pub const fn map_digest(&self) -> Digest32 {
        self.map_digest
    }
}

fn compute_provider_segment_map_digest(
    segments: &[ProviderRequestSegmentV2],
    selected_item_ids: &[StableId],
) -> Digest32 {
    let mut bytes = FINAL_REQUEST_SEGMENT_MAP_DOMAIN.to_vec();
    push_u64(&mut bytes, u64::try_from(segments.len()).unwrap_or(u64::MAX));
    for segment in segments {
        push_u64(&mut bytes, segment.offset);
        push_u64(&mut bytes, segment.length);
        push_digest(&mut bytes, segment.encoded_digest);
        match &segment.kind {
            ProviderRequestSegmentKindV2::SelectedContextItem {
                item_id,
                source_content_digest,
            } => {
                bytes.push(0);
                push_text(&mut bytes, item_id.as_str());
                push_digest(&mut bytes, *source_content_digest);
            }
            ProviderRequestSegmentKindV2::TypedFraming {
                framing_type,
                framing_policy_digest,
            } => {
                bytes.push(1);
                push_text(&mut bytes, framing_type.as_str());
                push_digest(&mut bytes, *framing_policy_digest);
            }
            ProviderRequestSegmentKindV2::HostCanonicalMaterial {
                material_type,
                semantic_digest,
            } => {
                bytes.push(2);
                push_text(&mut bytes, material_type.as_str());
                push_digest(&mut bytes, *semantic_digest);
            }
        }
    }
    push_ids(&mut bytes, selected_item_ids);
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderFinalRequestProofV2 {
    proof_id: StableId,
    context_attachment_digest: Digest32,
    canonical_context_payload_digest: Digest32,
    canonical_context_coverage_digest: Digest32,
    wire_semantic_digest: Digest32,
    segment_map: ProviderRequestSegmentMapV2,
    tokenization: ProviderFinalRequestTokenizationV2,
    prepared_at_unix_ms: u64,
    proof_digest: Digest32,
    authority: AuthorityPosture,
}

impl ProviderFinalRequestProofV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn from_exact_request(
        proof_id: StableId,
        context_attachment_digest: Digest32,
        canonical_context_payload_digest: Digest32,
        canonical_context_coverage_digest: Digest32,
        wire_semantic_digest: Digest32,
        final_request: &[u8],
        segments: Vec<ProviderRequestSegmentV2>,
        expected_selected_items: &BTreeMap<StableId, Digest32>,
        tokenizer: &impl ExactProviderRequestTokenizerV2,
        prepared_at_unix_ms: u64,
    ) -> Result<Self, ProviderRequestProofErrorV2> {
        for (name, digest) in [
            ("context_attachment", context_attachment_digest),
            ("canonical_context_payload", canonical_context_payload_digest),
            (
                "canonical_context_coverage",
                canonical_context_coverage_digest,
            ),
            ("provider_wire_semantic", wire_semantic_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if prepared_at_unix_ms == 0 {
            return Err(ProviderRequestProofErrorV2::InvalidTime);
        }
        let segment_map =
            ProviderRequestSegmentMapV2::verify(final_request, segments, expected_selected_items)?;
        let tokenization =
            ProviderFinalRequestTokenizationV2::from_exact_bytes(final_request, tokenizer)?;
        let mut proof = Self {
            proof_id,
            context_attachment_digest,
            canonical_context_payload_digest,
            canonical_context_coverage_digest,
            wire_semantic_digest,
            segment_map,
            tokenization,
            prepared_at_unix_ms,
            proof_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        proof.proof_digest = proof.compute_digest();
        proof.validate_for(final_request)?;
        Ok(proof)
    }

    pub fn validate_for(
        &self,
        final_request: &[u8],
    ) -> Result<(), ProviderRequestProofErrorV2> {
        self.tokenization.validate_for(final_request)?;
        for (name, digest) in [
            ("context_attachment", self.context_attachment_digest),
            (
                "canonical_context_payload",
                self.canonical_context_payload_digest,
            ),
            (
                "canonical_context_coverage",
                self.canonical_context_coverage_digest,
            ),
            ("provider_wire_semantic", self.wire_semantic_digest),
            ("provider_request_segment_map", self.segment_map.map_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.prepared_at_unix_ms == 0 || self.authority.grants_any() {
            return Err(ProviderRequestProofErrorV2::InvalidProof);
        }
        if self.proof_digest != self.compute_digest() {
            return Err(ProviderRequestProofErrorV2::DigestMismatch(
                "provider_final_request_proof",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub const fn proof_digest(&self) -> Digest32 {
        self.proof_digest
    }

    #[must_use]
    pub const fn final_request_digest(&self) -> Digest32 {
        self.tokenization.final_request_digest()
    }

    #[must_use]
    pub const fn wire_semantic_digest(&self) -> Digest32 {
        self.wire_semantic_digest
    }

    #[must_use]
    pub const fn tokenization(&self) -> &ProviderFinalRequestTokenizationV2 {
        &self.tokenization
    }

    #[must_use]
    pub const fn segment_map(&self) -> &ProviderRequestSegmentMapV2 {
        &self.segment_map
    }

    #[must_use]
    pub const fn context_attachment_digest(&self) -> Digest32 {
        self.context_attachment_digest
    }

    #[must_use]
    pub const fn canonical_context_payload_digest(&self) -> Digest32 {
        self.canonical_context_payload_digest
    }

    #[must_use]
    pub const fn canonical_context_coverage_digest(&self) -> Digest32 {
        self.canonical_context_coverage_digest
    }

    #[must_use]
    pub const fn prepared_at_unix_ms(&self) -> u64 {
        self.prepared_at_unix_ms
    }

    #[must_use]
    fn compute_digest(&self) -> Digest32 {
        let mut bytes = FINAL_REQUEST_PROOF_DOMAIN.to_vec();
        push_text(&mut bytes, self.proof_id.as_str());
        for digest in [
            self.context_attachment_digest,
            self.canonical_context_payload_digest,
            self.canonical_context_coverage_digest,
            self.wire_semantic_digest,
            self.segment_map.map_digest,
            self.tokenization.receipt_digest(),
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.prepared_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundDeliveryPreparationV2 {
    context_preparation: ContextDeliveryPreparationV2,
    final_request_proof: ProviderFinalRequestProofV2,
    snapshot_successor_witness_digest: Digest32,
    preparation_digest: Digest32,
    authority: AuthorityPosture,
}

impl ProviderBoundDeliveryPreparationV2 {
    pub fn validate_for(
        &self,
        attachment: &ContextAttachmentV2,
        serialization: &SerializedContextV2,
        profile: &ContextModelProfileV2,
    ) -> Result<(), ProviderRequestProofErrorV2> {
        self.context_preparation
            .validate_for(attachment, serialization, profile)
            .map_err(ProviderRequestProofErrorV2::Context)?;
        if self.final_request_proof.context_attachment_digest
            != attachment.attachment_digest()
            || self.final_request_proof.canonical_context_payload_digest
                != serialization.receipt().payload_digest()
            || self.authority.grants_any()
            || self.snapshot_successor_witness_digest.is_zero()
            || self.preparation_digest != self.compute_digest()
        {
            return Err(ProviderRequestProofErrorV2::PreparationMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub const fn context_preparation(&self) -> &ContextDeliveryPreparationV2 {
        &self.context_preparation
    }

    #[must_use]
    pub const fn final_request_proof(&self) -> &ProviderFinalRequestProofV2 {
        &self.final_request_proof
    }

    #[must_use]
    pub const fn preparation_digest(&self) -> Digest32 {
        self.preparation_digest
    }

    #[must_use]
    pub const fn snapshot_successor_witness_digest(&self) -> Digest32 {
        self.snapshot_successor_witness_digest
    }

    #[must_use]
    pub fn to_record(&self) -> ProviderBoundDeliveryPreparationRecordV2 {
        ProviderBoundDeliveryPreparationRecordV2::from_preparation(self)
    }

    #[must_use]
    fn compute_digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_BOUND_PREPARATION_DOMAIN.to_vec();
        push_digest(&mut bytes, self.context_preparation.preparation_digest());
        push_digest(&mut bytes, self.final_request_proof.proof_digest());
        push_digest(&mut bytes, self.snapshot_successor_witness_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[allow(clippy::too_many_arguments)]
pub fn prepare_provider_bound_delivery_v2(
    compiled: &CompiledContextV2,
    serialization: &SerializedContextV2,
    attachment: &ContextAttachmentV2,
    profile: &ContextModelProfileV2,
    snapshot_successor: &VerifiedAdmissionSnapshotSuccessorV2,
    final_request_proof: ProviderFinalRequestProofV2,
    preparation_id: StableId,
) -> Result<ProviderBoundDeliveryPreparationV2, ProviderRequestProofErrorV2> {
    if final_request_proof.context_attachment_digest != attachment.attachment_digest()
        || final_request_proof.canonical_context_payload_digest
            != serialization.receipt().payload_digest()
    {
        return Err(ProviderRequestProofErrorV2::PreparationMismatch);
    }
    let context_preparation = prepare_delivery_v2(
        compiled,
        serialization,
        attachment,
        profile,
        snapshot_successor.snapshot(),
        preparation_id,
    )
    .map_err(ProviderRequestProofErrorV2::Context)?;
    let mut preparation = ProviderBoundDeliveryPreparationV2 {
        context_preparation,
        final_request_proof,
        snapshot_successor_witness_digest: snapshot_successor.successor_witness_digest(),
        preparation_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    preparation.preparation_digest = preparation.compute_digest();
    preparation.validate_for(attachment, serialization, profile)?;
    Ok(preparation)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundDeliveryPreparationRecordV2 {
    pub provider_id: String,
    pub model: String,
    pub tokenizer_version: String,
    pub preparation_digest: Digest32,
    pub context_preparation_digest: Digest32,
    pub final_request_proof_digest: Digest32,
    pub final_request_digest: Digest32,
    pub wire_semantic_digest: Digest32,
    pub segment_map_digest: Digest32,
    pub tokenizer_identity_digest: Digest32,
    pub tokenizer_binary_digest: Digest32,
    pub vocabulary_digest: Digest32,
    pub normalization_policy_digest: Digest32,
    pub final_request_bytes: u64,
    pub token_count: u64,
    pub prepared_at_unix_ms: u64,
    pub snapshot_successor_witness_digest: Digest32,
    pub record_digest: Digest32,
}

impl ProviderBoundDeliveryPreparationRecordV2 {
    #[must_use]
    pub fn from_preparation(preparation: &ProviderBoundDeliveryPreparationV2) -> Self {
        let proof = preparation.final_request_proof();
        let tokenization = proof.tokenization();
        let identity = tokenization.tokenizer_identity();
        let mut record = Self {
            provider_id: identity.provider_id().to_owned(),
            model: identity.model().to_owned(),
            tokenizer_version: identity.tokenizer_version().to_owned(),
            preparation_digest: preparation.preparation_digest(),
            context_preparation_digest: preparation.context_preparation().preparation_digest(),
            final_request_proof_digest: proof.proof_digest(),
            final_request_digest: proof.final_request_digest(),
            wire_semantic_digest: proof.wire_semantic_digest(),
            segment_map_digest: proof.segment_map().map_digest(),
            tokenizer_identity_digest: identity.identity_digest(),
            tokenizer_binary_digest: identity.tokenizer_binary_digest(),
            vocabulary_digest: identity.vocabulary_digest(),
            normalization_policy_digest: identity.normalization_policy_digest(),
            final_request_bytes: tokenization.final_request_bytes(),
            token_count: tokenization.token_count(),
            prepared_at_unix_ms: proof.prepared_at_unix_ms(),
            snapshot_successor_witness_digest: preparation
                .snapshot_successor_witness_digest(),
            record_digest: Digest32::ZERO,
        };
        record.record_digest = record.compute_digest();
        record
    }

    pub fn validate(&self) -> Result<(), ProviderRequestProofErrorV2> {
        validate_bounded_text("provider_id", &self.provider_id, MAX_PROVIDER_ID_BYTES_V2)?;
        validate_bounded_text("model", &self.model, MAX_PROVIDER_MODEL_BYTES_V2)?;
        validate_bounded_text("tokenizer_version", &self.tokenizer_version, 512)?;
        for (name, digest) in [
            ("provider_bound_preparation", self.preparation_digest),
            ("context_preparation", self.context_preparation_digest),
            ("provider_final_request_proof", self.final_request_proof_digest),
            ("provider_final_request", self.final_request_digest),
            ("provider_wire_semantic", self.wire_semantic_digest),
            ("provider_request_segment_map", self.segment_map_digest),
            ("tokenizer_identity", self.tokenizer_identity_digest),
            ("tokenizer_binary", self.tokenizer_binary_digest),
            ("tokenizer_vocabulary", self.vocabulary_digest),
            (
                "tokenizer_normalization_policy",
                self.normalization_policy_digest,
            ),
            (
                "snapshot_successor_witness",
                self.snapshot_successor_witness_digest,
            ),
            ("provider_bound_preparation_record", self.record_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.final_request_bytes == 0
            || self.final_request_bytes
                > u64::try_from(MAX_PROVIDER_FINAL_REQUEST_BYTES_V2).unwrap_or(u64::MAX)
            || self.token_count == 0
            || self.token_count > 4_000_000
            || self.prepared_at_unix_ms == 0
        {
            return Err(ProviderRequestProofErrorV2::InvalidProof);
        }
        if self.record_digest != self.compute_digest() {
            return Err(ProviderRequestProofErrorV2::DigestMismatch(
                "provider_bound_preparation_record",
            ));
        }
        Ok(())
    }

    #[must_use]
    fn compute_digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_BOUND_PREPARATION_RECORD_DOMAIN.to_vec();
        push_text(&mut bytes, &self.provider_id);
        push_text(&mut bytes, &self.model);
        push_text(&mut bytes, &self.tokenizer_version);
        for digest in [
            self.preparation_digest,
            self.context_preparation_digest,
            self.final_request_proof_digest,
            self.final_request_digest,
            self.wire_semantic_digest,
            self.segment_map_digest,
            self.tokenizer_identity_digest,
            self.tokenizer_binary_digest,
            self.vocabulary_digest,
            self.normalization_policy_digest,
            self.snapshot_successor_witness_digest,
        ] {
            push_digest(&mut bytes, digest);
        }
        push_u64(&mut bytes, self.final_request_bytes);
        push_u64(&mut bytes, self.token_count);
        push_u64(&mut bytes, self.prepared_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderBoundTerminalV2 {
    Completed { terminal_evidence_digest: Digest32 },
    Rejected {
        reason_digest: Digest32,
        terminal_evidence_digest: Digest32,
    },
    NotDispatched { reason_digest: Digest32 },
    Indeterminate {
        reason_digest: Digest32,
        terminal_evidence_digest: Option<Digest32>,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundDeliveryReceiptV2 {
    preparation_digest: Digest32,
    final_request_digest: Digest32,
    provider_attempt_id: StableId,
    request_binding_id: StableId,
    terminal: ProviderBoundTerminalV2,
    observed_at_unix_ms: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ProviderBoundDeliveryReceiptV2 {
    pub fn observe(
        preparation: &ProviderBoundDeliveryPreparationV2,
        provider_attempt_id: StableId,
        request_binding_id: StableId,
        terminal: ProviderBoundTerminalV2,
        observed_at_unix_ms: u64,
    ) -> Result<Self, ProviderRequestProofErrorV2> {
        Self::observe_record(
            &preparation.to_record(),
            provider_attempt_id,
            request_binding_id,
            terminal,
            observed_at_unix_ms,
        )
    }

    pub fn observe_record(
        preparation: &ProviderBoundDeliveryPreparationRecordV2,
        provider_attempt_id: StableId,
        request_binding_id: StableId,
        terminal: ProviderBoundTerminalV2,
        observed_at_unix_ms: u64,
    ) -> Result<Self, ProviderRequestProofErrorV2> {
        preparation.validate()?;
        if observed_at_unix_ms == 0
            || observed_at_unix_ms < preparation.prepared_at_unix_ms
        {
            return Err(ProviderRequestProofErrorV2::InvalidTime);
        }
        validate_terminal(&terminal)?;
        let mut receipt = Self {
            preparation_digest: preparation.preparation_digest,
            final_request_digest: preparation.final_request_digest,
            provider_attempt_id,
            request_binding_id,
            terminal,
            observed_at_unix_ms,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.receipt_digest = receipt.compute_digest();
        receipt.validate_for_record(preparation)?;
        Ok(receipt)
    }

    pub fn validate_for(
        &self,
        preparation: &ProviderBoundDeliveryPreparationV2,
    ) -> Result<(), ProviderRequestProofErrorV2> {
        self.validate_for_record(&preparation.to_record())
    }

    pub fn validate_for_record(
        &self,
        preparation: &ProviderBoundDeliveryPreparationRecordV2,
    ) -> Result<(), ProviderRequestProofErrorV2> {
        preparation.validate()?;
        if self.preparation_digest != preparation.preparation_digest
            || self.final_request_digest != preparation.final_request_digest
            || self.observed_at_unix_ms < preparation.prepared_at_unix_ms
            || self.authority.grants_any()
        {
            return Err(ProviderRequestProofErrorV2::ReceiptMismatch);
        }
        validate_terminal(&self.terminal)?;
        if self.receipt_digest != self.compute_digest() {
            return Err(ProviderRequestProofErrorV2::DigestMismatch(
                "provider_bound_delivery_receipt",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn preparation_digest(&self) -> Digest32 {
        self.preparation_digest
    }

    #[must_use]
    pub const fn final_request_digest(&self) -> Digest32 {
        self.final_request_digest
    }

    #[must_use]
    pub const fn provider_attempt_id(&self) -> &StableId {
        &self.provider_attempt_id
    }

    #[must_use]
    pub const fn request_binding_id(&self) -> &StableId {
        &self.request_binding_id
    }

    #[must_use]
    pub const fn observed_at_unix_ms(&self) -> u64 {
        self.observed_at_unix_ms
    }

    #[must_use]
    pub const fn terminal(&self) -> &ProviderBoundTerminalV2 {
        &self.terminal
    }

    #[must_use]
    fn compute_digest(&self) -> Digest32 {
        let mut bytes = PROVIDER_BOUND_RECEIPT_DOMAIN.to_vec();
        push_digest(&mut bytes, self.preparation_digest);
        push_digest(&mut bytes, self.final_request_digest);
        push_text(&mut bytes, self.provider_attempt_id.as_str());
        push_text(&mut bytes, self.request_binding_id.as_str());
        match &self.terminal {
            ProviderBoundTerminalV2::Completed {
                terminal_evidence_digest,
            } => {
                bytes.push(0);
                push_digest(&mut bytes, *terminal_evidence_digest);
            }
            ProviderBoundTerminalV2::Rejected {
                reason_digest,
                terminal_evidence_digest,
            } => {
                bytes.push(1);
                push_digest(&mut bytes, *reason_digest);
                push_digest(&mut bytes, *terminal_evidence_digest);
            }
            ProviderBoundTerminalV2::NotDispatched { reason_digest } => {
                bytes.push(2);
                push_digest(&mut bytes, *reason_digest);
            }
            ProviderBoundTerminalV2::Indeterminate {
                reason_digest,
                terminal_evidence_digest,
            } => {
                bytes.push(3);
                push_digest(&mut bytes, *reason_digest);
                match terminal_evidence_digest {
                    Some(digest) => {
                        bytes.push(1);
                        push_digest(&mut bytes, *digest);
                    }
                    None => bytes.push(0),
                }
            }
        }
        push_u64(&mut bytes, self.observed_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

fn validate_terminal(terminal: &ProviderBoundTerminalV2) -> Result<(), ProviderRequestProofErrorV2> {
    match terminal {
        ProviderBoundTerminalV2::Completed {
            terminal_evidence_digest,
        } => ensure_digest("provider_terminal_evidence", *terminal_evidence_digest),
        ProviderBoundTerminalV2::Rejected {
            reason_digest,
            terminal_evidence_digest,
        } => {
            ensure_digest("provider_rejection_reason", *reason_digest)?;
            ensure_digest("provider_terminal_evidence", *terminal_evidence_digest)
        }
        ProviderBoundTerminalV2::NotDispatched { reason_digest } => {
            ensure_digest("provider_not_dispatched_reason", *reason_digest)
        }
        ProviderBoundTerminalV2::Indeterminate {
            reason_digest,
            terminal_evidence_digest,
        } => {
            ensure_digest("provider_indeterminate_reason", *reason_digest)?;
            if let Some(digest) = terminal_evidence_digest {
                ensure_digest("provider_terminal_evidence", *digest)?;
            }
            Ok(())
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProviderRequestProofErrorV2 {
    Context(ContextCompilerV2Error),
    EmptyDigest(&'static str),
    InvalidText(&'static str),
    FinalRequestTooLarge,
    EmptyFinalRequest,
    InvalidTokenCount,
    InvalidSegment,
    InvalidSegmentMap,
    SegmentLimitExceeded,
    IncompleteSegmentCoverage,
    SelectedSetMismatch,
    SnapshotPredecessorMismatch,
    FinalRequestMismatch,
    PreparationMismatch,
    ReceiptMismatch,
    InvalidProof,
    InvalidTime,
    DigestMismatch(&'static str),
    Arithmetic,
    Tokenizer(String),
}

impl fmt::Display for ProviderRequestProofErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProviderRequestProofErrorV2 {}

impl From<ContextCompilerV2Error> for ProviderRequestProofErrorV2 {
    fn from(error: ContextCompilerV2Error) -> Self {
        Self::Context(error)
    }
}

fn validate_final_request_bytes(bytes: &[u8]) -> Result<(), ProviderRequestProofErrorV2> {
    if bytes.is_empty() {
        return Err(ProviderRequestProofErrorV2::EmptyFinalRequest);
    }
    if bytes.len() > MAX_PROVIDER_FINAL_REQUEST_BYTES_V2 {
        return Err(ProviderRequestProofErrorV2::FinalRequestTooLarge);
    }
    Ok(())
}

fn validate_bounded_text(
    field: &'static str,
    value: &str,
    max_bytes: usize,
) -> Result<(), ProviderRequestProofErrorV2> {
    if value.is_empty() || value.len() > max_bytes || value.chars().any(char::is_control) {
        return Err(ProviderRequestProofErrorV2::InvalidText(field));
    }
    Ok(())
}

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), ProviderRequestProofErrorV2> {
    if digest.is_zero() {
        return Err(ProviderRequestProofErrorV2::EmptyDigest(name));
    }
    Ok(())
}

const fn role_code(role: ContextRoleV2) -> u8 {
    match role {
        ContextRoleV2::TrustedInstruction => 0,
        ContextRoleV2::Schema => 1,
        ContextRoleV2::UntrustedEvidence => 2,
    }
}

fn push_digest(bytes: &mut Vec<u8>, digest: Digest32) {
    bytes.extend_from_slice(digest.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    push_u64(bytes, u64::try_from(value.len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(value.as_bytes());
}

fn push_ids(bytes: &mut Vec<u8>, ids: &[StableId]) {
    push_u64(bytes, u64::try_from(ids.len()).unwrap_or(u64::MAX));
    for id in ids {
        push_text(bytes, id.as_str());
    }
}

#[cfg(test)]
#[path = "provider_request_tests.rs"]
mod tests;
