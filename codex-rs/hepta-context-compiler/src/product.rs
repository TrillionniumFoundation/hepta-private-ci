//! Product-only hardening for the verified V2 context path.
//!
//! This module binds the otherwise digest-only model profile to concrete,
//! versioned provider artifacts and makes admission-snapshot ancestry a typed
//! value.  It intentionally contains no permissive defaults: a product host
//! must supply an independently authenticated admission verifier and an exact
//! tokenizer implementation.

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
use crate::build_attachment;
use crate::prepare_delivery_v2;
use crate::verify_admission_snapshot_successor_v2;
use crate::verify_admission_snapshot_v2;

const PRODUCT_PROFILE_DOMAIN: &[u8] = b"hepta.context-product-profile.v2";
const SNAPSHOT_LINEAGE_DOMAIN: &[u8] = b"hepta.context-admission-lineage.v2";

/// Exact product artifact revisions consumed by one compiler profile.
///
/// `base_profile` binds semantic model/provider/tokenizer/serializer/template
/// identities.  The additional fields bind the concrete binaries, vocabulary,
/// normalization and role-placement policy that realize those semantics.  A
/// digest-only alias can therefore no longer silently switch implementations.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextModelProfileRevisionV2 {
    pub profile_id: StableId,
    pub base_profile: ContextModelProfileV2,
    pub provider_revision_digest: Digest32,
    pub model_revision_digest: Digest32,
    pub tokenizer_binary_digest: Digest32,
    pub tokenizer_vocabulary_digest: Digest32,
    pub tokenizer_normalization_digest: Digest32,
    pub serializer_revision_digest: Digest32,
    pub template_revision_digest: Digest32,
    pub tool_schema_revision_digest: Digest32,
    pub role_profile_digest: Digest32,
}

impl ContextModelProfileRevisionV2 {
    pub fn validate(&self) -> Result<(), ContextCompilerV2Error> {
        self.base_profile.validate()?;
        for (name, digest) in [
            ("provider_revision", self.provider_revision_digest),
            ("model_revision", self.model_revision_digest),
            ("tokenizer_binary", self.tokenizer_binary_digest),
            ("tokenizer_vocabulary", self.tokenizer_vocabulary_digest),
            (
                "tokenizer_normalization",
                self.tokenizer_normalization_digest,
            ),
            ("serializer_revision", self.serializer_revision_digest),
            ("template_revision", self.template_revision_digest),
            ("tool_schema_revision", self.tool_schema_revision_digest),
            ("role_profile", self.role_profile_digest),
        ] {
            if digest.is_zero() {
                return Err(ContextCompilerV2Error::EmptyDigest(name));
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn digest(&self) -> Digest32 {
        let mut bytes = PRODUCT_PROFILE_DOMAIN.to_vec();
        push_id(&mut bytes, &self.profile_id);
        bytes.extend_from_slice(self.base_profile.digest().as_array());
        for digest in [
            self.provider_revision_digest,
            self.model_revision_digest,
            self.tokenizer_binary_digest,
            self.tokenizer_vocabulary_digest,
            self.tokenizer_normalization_digest,
            self.serializer_revision_digest,
            self.template_revision_digest,
            self.tool_schema_revision_digest,
            self.role_profile_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Verified monotonic ancestry for the current admission snapshot.
///
/// A plain `VerifiedAdmissionSnapshotV2` proves that one snapshot was accepted
/// by a verifier.  This wrapper additionally proves how that snapshot descends
/// from the root used by this compilation generation.  Product attachment and
/// pre-dispatch helpers accept this type so a forked-but-monotonic snapshot
/// cannot be substituted without first passing successor verification.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedAdmissionSnapshotLineageV2 {
    root_snapshot_digest: Digest32,
    current: VerifiedAdmissionSnapshotV2,
    depth: u32,
    lineage_digest: Digest32,
}

impl VerifiedAdmissionSnapshotLineageV2 {
    pub fn verify_root(
        snapshot: ContextAdmissionSnapshotV2,
        verifier: &(impl ContextAdmissionVerifierV2 + ?Sized),
    ) -> Result<Self, ContextCompilerV2Error> {
        let current = verify_admission_snapshot_v2(snapshot, verifier)?;
        let root_snapshot_digest = current.snapshot_digest();
        let depth = 0;
        let lineage_digest = compute_lineage_digest(
            root_snapshot_digest,
            current.snapshot_digest(),
            current.verification_digest(),
            depth,
        );
        Ok(Self {
            root_snapshot_digest,
            current,
            depth,
            lineage_digest,
        })
    }

    pub fn verify_successor(
        snapshot: ContextAdmissionSnapshotV2,
        predecessor: &Self,
        verifier: &(impl ContextAdmissionVerifierV2 + ?Sized),
    ) -> Result<Self, ContextCompilerV2Error> {
        let current =
            verify_admission_snapshot_successor_v2(snapshot, &predecessor.current, verifier)?;
        let depth = predecessor
            .depth
            .checked_add(1)
            .ok_or(ContextCompilerV2Error::Arithmetic)?;
        let lineage_digest = compute_lineage_digest(
            predecessor.root_snapshot_digest,
            current.snapshot_digest(),
            current.verification_digest(),
            depth,
        );
        Ok(Self {
            root_snapshot_digest: predecessor.root_snapshot_digest,
            current,
            depth,
            lineage_digest,
        })
    }

    #[must_use]
    pub const fn current(&self) -> &VerifiedAdmissionSnapshotV2 {
        &self.current
    }

    #[must_use]
    pub const fn root_snapshot_digest(&self) -> Digest32 {
        self.root_snapshot_digest
    }

    #[must_use]
    pub const fn depth(&self) -> u32 {
        self.depth
    }

    #[must_use]
    pub const fn lineage_digest(&self) -> Digest32 {
        self.lineage_digest
    }
}

pub fn build_attachment_with_lineage_v2(
    compiled: &crate::CompiledContextV2,
    serialization: &SerializedContextV2,
    profile: &ContextModelProfileV2,
    current_lineage: &VerifiedAdmissionSnapshotLineageV2,
    attachment_id: StableId,
) -> Result<ContextAttachmentV2, ContextCompilerV2Error> {
    build_attachment(
        compiled,
        serialization,
        profile,
        current_lineage.current(),
        attachment_id,
    )
}

pub fn prepare_delivery_with_lineage_v2(
    compiled: &crate::CompiledContextV2,
    serialization: &SerializedContextV2,
    attachment: &ContextAttachmentV2,
    profile: &ContextModelProfileV2,
    current_lineage: &VerifiedAdmissionSnapshotLineageV2,
    preparation_id: StableId,
) -> Result<ContextDeliveryPreparationV2, ContextCompilerV2Error> {
    prepare_delivery_v2(
        compiled,
        serialization,
        attachment,
        profile,
        current_lineage.current(),
        preparation_id,
    )
}

impl ContextCompilerV2Error {
    /// Stable, payload-free operator code.  Variant debug strings remain an
    /// internal diagnostic and must not be used as metric labels or protocols.
    #[must_use]
    pub const fn stable_code(&self) -> &'static str {
        match self {
            Self::EmptyDigest(_) => "ctx_v2_empty_digest",
            Self::DigestMismatch(_) => "ctx_v2_digest_mismatch",
            Self::CandidateLimitExceeded => "ctx_v2_candidate_limit",
            Self::GroupLimitExceeded => "ctx_v2_group_limit",
            Self::InvalidModelContextLimit => "ctx_v2_model_context_limit",
            Self::InvalidTokenBudget => "ctx_v2_token_budget_invalid",
            Self::InvalidTokenCount(_) => "ctx_v2_token_count_invalid",
            Self::CandidateContentTooLarge(_) => "ctx_v2_candidate_too_large",
            Self::InvalidSerializedTokenCount => "ctx_v2_serialized_token_count_invalid",
            Self::DuplicateCandidate(_) => "ctx_v2_duplicate_candidate",
            Self::DuplicateMandatoryGroup(_) => "ctx_v2_duplicate_mandatory_group",
            Self::EmptyMandatoryGroup(_) => "ctx_v2_empty_mandatory_group",
            Self::DuplicateMandatoryItem(_) => "ctx_v2_duplicate_mandatory_item",
            Self::UnknownMandatoryItem(_) => "ctx_v2_unknown_mandatory_item",
            Self::GenerationVectorMismatch(_) => "ctx_v2_generation_mismatch",
            Self::TokenizationItemMismatch(_) => "ctx_v2_tokenization_item_mismatch",
            Self::TokenizerMismatch(_) => "ctx_v2_tokenizer_mismatch",
            Self::TokenizerProfileMismatch => "ctx_v2_tokenizer_profile_mismatch",
            Self::ValueOutOfRange(_) => "ctx_v2_value_out_of_range",
            Self::SecretRejected(_) => "ctx_v2_secret_rejected",
            Self::InvalidAdmissionTime(_) => "ctx_v2_admission_time_invalid",
            Self::InvalidAdmissionSnapshotTime => "ctx_v2_snapshot_time_invalid",
            Self::DuplicateRevocation(_) => "ctx_v2_duplicate_revocation",
            Self::NonCanonicalRevocationList => "ctx_v2_revocation_noncanonical",
            Self::RevocationLimitExceeded => "ctx_v2_revocation_limit",
            Self::IncompleteRevocationSnapshot => "ctx_v2_revocation_incomplete",
            Self::UnexpectedSnapshotPredecessor => "ctx_v2_snapshot_unexpected_predecessor",
            Self::SnapshotPredecessorMismatch => "ctx_v2_snapshot_predecessor_mismatch",
            Self::SnapshotDomainMismatch => "ctx_v2_snapshot_domain_mismatch",
            Self::RevocationFrontierMismatch => "ctx_v2_revocation_frontier_mismatch",
            Self::RevocationResurrection(_) => "ctx_v2_revocation_resurrection",
            Self::AdmissionRecordUnverified(_) => "ctx_v2_admission_record_unverified",
            Self::AdmissionSnapshotUnverified => "ctx_v2_admission_snapshot_unverified",
            Self::AdmissionNotYetValid(_) => "ctx_v2_admission_not_yet_valid",
            Self::AdmissionExpired(_) => "ctx_v2_admission_expired",
            Self::AdmissionRevoked(_) => "ctx_v2_admission_revoked",
            Self::AdmissionBindingMismatch(_) => "ctx_v2_admission_binding_mismatch",
            Self::AdmissionVerifierMismatch(_) => "ctx_v2_admission_verifier_mismatch",
            Self::AdmissionSnapshotDomainMismatch(_) => "ctx_v2_admission_snapshot_domain_mismatch",
            Self::StaleAdmissionSnapshot => "ctx_v2_admission_snapshot_stale",
            Self::MandatoryReferenceLimitExceeded => "ctx_v2_mandatory_reference_limit",
            Self::InsufficientMandatoryBudget { .. } => "ctx_v2_mandatory_budget_insufficient",
            Self::TokenBudgetExceeded => "ctx_v2_token_budget_exceeded",
            Self::SelectedSetMismatch => "ctx_v2_selected_set_mismatch",
            Self::SelectedTokenCountMismatch => "ctx_v2_selected_token_count_mismatch",
            Self::ModelProfileMismatch => "ctx_v2_model_profile_mismatch",
            Self::SerializerProfileMismatch => "ctx_v2_serializer_profile_mismatch",
            Self::RealizationSetMismatch => "ctx_v2_realization_set_mismatch",
            Self::DuplicateRealization(_) => "ctx_v2_duplicate_realization",
            Self::RealizedRoleMismatch(_) => "ctx_v2_realized_role_mismatch",
            Self::RealizedContentMismatch(_) => "ctx_v2_realized_content_mismatch",
            Self::RealizedContentTooLarge(_) => "ctx_v2_realized_content_too_large",
            Self::RealizationBytesExceeded => "ctx_v2_realization_bytes_exceeded",
            Self::EmptySerializedPayload => "ctx_v2_serialized_payload_empty",
            Self::SerializedPayloadTooLarge => "ctx_v2_serialized_payload_too_large",
            Self::SerializedTokenBudgetExceeded { .. } => "ctx_v2_serialized_token_budget",
            Self::SerializationMismatch => "ctx_v2_serialization_mismatch",
            Self::AttachmentMismatch => "ctx_v2_attachment_mismatch",
            Self::DeliveryMismatch => "ctx_v2_delivery_mismatch",
            Self::MissingProviderInputBinding => "ctx_v2_provider_input_missing",
            Self::MissingProviderInputWitness => "ctx_v2_provider_witness_missing",
            Self::ProviderModelProfileMismatch => "ctx_v2_provider_model_mismatch",
            Self::ProviderReceiptInvalid(_) => "ctx_v2_provider_receipt_invalid",
            Self::ProviderEvidenceInvalid(_) => "ctx_v2_provider_evidence_invalid",
            Self::MissingTerminalObservation => "ctx_v2_terminal_missing",
            Self::InvalidDeliveryDisposition => "ctx_v2_delivery_disposition_invalid",
            Self::InvalidObservationTime => "ctx_v2_observation_time_invalid",
            Self::AuthorityGranted => "ctx_v2_authority_granted",
            Self::Arithmetic => "ctx_v2_arithmetic",
        }
    }
}

fn compute_lineage_digest(
    root_snapshot_digest: Digest32,
    current_snapshot_digest: Digest32,
    current_verification_digest: Digest32,
    depth: u32,
) -> Digest32 {
    let mut bytes = SNAPSHOT_LINEAGE_DOMAIN.to_vec();
    bytes.extend_from_slice(root_snapshot_digest.as_array());
    bytes.extend_from_slice(current_snapshot_digest.as_array());
    bytes.extend_from_slice(current_verification_digest.as_array());
    bytes.extend_from_slice(&depth.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
