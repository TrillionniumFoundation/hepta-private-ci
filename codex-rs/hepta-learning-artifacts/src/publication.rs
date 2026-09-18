//! Publication transaction contract for V2/V3 artifact admission.
//!
//! The crate does not own a host CURRENT pointer. Instead it supplies a hard
//! ordering contract: prepare against an in-memory candidate registry, sync the
//! payload and immutable registry snapshot, revalidate withdrawal freshness,
//! then mint a commit receipt. Hosts MUST NOT publish a CURRENT pointer without
//! a matching commit receipt.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::ArtifactAdmissionError;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::RegistrySnapshotReceipt;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::WithdrawalRegistryScopeV1;
use crate::validate_artifact_publication_v3;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationIntentV1 {
    pub admission_digest: Digest32,
    pub manifest_digest: Digest32,
    pub payload_digest: Digest32,
    pub withdrawal_scope: WithdrawalRegistryScopeV1,
    pub withdrawal_head_digest: Digest32,
    pub candidate_registry_head_digest: Digest32,
    pub intent_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationCommitV1 {
    pub intent_digest: Digest32,
    pub registry_snapshot_receipt: RegistrySnapshotReceipt,
    pub committed_at: u64,
    pub commit_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationError {
    Admission(ArtifactAdmissionError),
    RegistryManifestMissing,
    RegistryManifestMismatch,
    SnapshotMismatch,
    InvalidSnapshotReceipt,
    AuthorityGrant,
}

impl fmt::Display for ArtifactPublicationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ArtifactPublicationError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Admission(error) => Some(error),
            Self::RegistryManifestMissing
            | Self::RegistryManifestMismatch
            | Self::SnapshotMismatch
            | Self::InvalidSnapshotReceipt
            | Self::AuthorityGrant => None,
        }
    }
}

impl From<ArtifactAdmissionError> for ArtifactPublicationError {
    fn from(value: ArtifactAdmissionError) -> Self {
        Self::Admission(value)
    }
}

pub fn prepare_artifact_publication_v1(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    candidate_registry: &ArtifactRegistry,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    current_scope: &WithdrawalRegistryScopeV1,
    now: u64,
) -> Result<ArtifactPublicationIntentV1, ArtifactPublicationError> {
    validate_artifact_publication_v3(admission, withdrawal_registry, current_scope, now)?;
    if admission.authority.grants_any() || admission.validated_manifest.authority.grants_any() {
        return Err(ArtifactPublicationError::AuthorityGrant);
    }

    let manifest = &admission.validated_manifest.manifest;
    let durable = candidate_registry
        .manifest(&manifest.artifact_id)
        .ok_or(ArtifactPublicationError::RegistryManifestMissing)?;
    if durable.artifact_id != manifest.artifact_id
        || durable.kind != manifest.kind
        || durable.generation != manifest.generation
        || durable.content_digest != manifest.bytes_digest
        || durable.producer_id != manifest.producer_id
        || durable.compatibility_digest != manifest.compatibility_digest
        || durable.encoded_size_bytes != manifest.encoded_size_bytes
    {
        return Err(ArtifactPublicationError::RegistryManifestMismatch);
    }

    let candidate_registry_head_digest = candidate_registry.snapshot().head_digest;
    let intent_digest = digest_intent(
        admission.admission_digest,
        admission.validated_manifest.manifest_digest,
        manifest.bytes_digest,
        current_scope,
        admission.withdrawal_head_digest,
        candidate_registry_head_digest,
    );
    Ok(ArtifactPublicationIntentV1 {
        admission_digest: admission.admission_digest,
        manifest_digest: admission.validated_manifest.manifest_digest,
        payload_digest: manifest.bytes_digest,
        withdrawal_scope: current_scope.clone(),
        withdrawal_head_digest: admission.withdrawal_head_digest,
        candidate_registry_head_digest,
        intent_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn finalize_artifact_publication_v1(
    intent: &ArtifactPublicationIntentV1,
    admission: &WithdrawalBoundArtifactAdmissionV3,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    current_scope: &WithdrawalRegistryScopeV1,
    registry_snapshot_receipt: RegistrySnapshotReceipt,
    now: u64,
) -> Result<ArtifactPublicationCommitV1, ArtifactPublicationError> {
    if intent.authority.grants_any() || admission.authority.grants_any() {
        return Err(ArtifactPublicationError::AuthorityGrant);
    }
    validate_artifact_publication_v3(admission, withdrawal_registry, current_scope, now)?;
    if intent.admission_digest != admission.admission_digest
        || intent.manifest_digest != admission.validated_manifest.manifest_digest
        || intent.payload_digest != admission.validated_manifest.manifest.bytes_digest
        || &intent.withdrawal_scope != current_scope
        || intent.withdrawal_head_digest != admission.withdrawal_head_digest
    {
        return Err(ArtifactPublicationError::SnapshotMismatch);
    }
    if registry_snapshot_receipt.binding.is_zero()
        || registry_snapshot_receipt.file_digest.is_zero()
        || registry_snapshot_receipt.encoded_bytes == 0
        || registry_snapshot_receipt.head_digest != intent.candidate_registry_head_digest
    {
        return Err(ArtifactPublicationError::InvalidSnapshotReceipt);
    }

    let commit_digest = digest_commit(intent.intent_digest, registry_snapshot_receipt, now);
    Ok(ArtifactPublicationCommitV1 {
        intent_digest: intent.intent_digest,
        registry_snapshot_receipt,
        committed_at: now,
        commit_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn digest_intent(
    admission_digest: Digest32,
    manifest_digest: Digest32,
    payload_digest: Digest32,
    scope: &WithdrawalRegistryScopeV1,
    withdrawal_head_digest: Digest32,
    candidate_registry_head_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-intent.v1".to_vec();
    bytes.extend_from_slice(admission_digest.as_array());
    bytes.extend_from_slice(manifest_digest.as_array());
    bytes.extend_from_slice(payload_digest.as_array());
    push_id(&mut bytes, scope.registry_id.as_str());
    push_id(&mut bytes, scope.authority_domain_id.as_str());
    push_id(&mut bytes, scope.scope_id.as_str());
    bytes.extend_from_slice(withdrawal_head_digest.as_array());
    bytes.extend_from_slice(candidate_registry_head_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_commit(
    intent_digest: Digest32,
    receipt: RegistrySnapshotReceipt,
    committed_at: u64,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-commit.v1".to_vec();
    bytes.extend_from_slice(intent_digest.as_array());
    bytes.extend_from_slice(receipt.binding.as_array());
    bytes.extend_from_slice(receipt.head_digest.as_array());
    bytes.extend_from_slice(receipt.file_digest.as_array());
    bytes.extend_from_slice(&(receipt.records as u64).to_be_bytes());
    bytes.extend_from_slice(&(receipt.encoded_bytes as u64).to_be_bytes());
    bytes.extend_from_slice(&committed_at.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
