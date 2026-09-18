//! Host transaction contract binding V2 admission to durable V1 publication.
//!
//! This module does not pretend that two files are an atomic transaction. It
//! instead makes the host-owned commit tuple explicit and replayable: the exact
//! V2 admission, withdrawal frontier, predecessor registry, candidate registry
//! and authenticated head witness are bound into one deny-all receipt. Recovery
//! is decided only from the independently authenticated current head.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};

use crate::{
    ArtifactAdmissionError, ArtifactClosureError, ArtifactEvent, ArtifactRegistry,
    DatasetWithdrawalRegistry, RegistryHeadRequirementV1, RegistryHeadWitnessV1,
    WithdrawalAuthorityDomainV1, WithdrawalBoundArtifactAdmissionV3,
    validate_artifact_publication_v3, validate_registry_head_witness,
};

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationTransactionV1 {
    pub registry_id: StableId,
    pub registry_generation: Generation,
    pub predecessor_registry_head_digest: Digest32,
    pub candidate_registry_head_digest: Digest32,
    pub withdrawal_domain_digest: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub manifest_digest: Digest32,
    pub admission_digest: Digest32,
    pub witness_digest: Digest32,
    pub transaction_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationRecoveryV1 {
    NotCommitted,
    Committed,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationError {
    Admission(ArtifactAdmissionError),
    RegistryWitness(ArtifactClosureError),
    CandidateNotSuccessor,
    ManifestBridgeMissing,
    ManifestBridgeMismatch,
    WitnessHeadMismatch,
    RecoveryHeadConflict,
    RecoveryGenerationConflict,
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
            Self::RegistryWitness(error) => Some(error),
            Self::CandidateNotSuccessor
            | Self::ManifestBridgeMissing
            | Self::ManifestBridgeMismatch
            | Self::WitnessHeadMismatch
            | Self::RecoveryHeadConflict
            | Self::RecoveryGenerationConflict => None,
        }
    }
}

impl From<ArtifactAdmissionError> for ArtifactPublicationError {
    fn from(value: ArtifactAdmissionError) -> Self {
        Self::Admission(value)
    }
}

#[expect(
    clippy::too_many_arguments,
    reason = "publication preparation binds the complete immutable host transaction tuple"
)]
pub fn prepare_artifact_publication_transaction_v1(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    withdrawal_domain: &WithdrawalAuthorityDomainV1,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    current_registry: &ArtifactRegistry,
    candidate_registry: &ArtifactRegistry,
    witness: &RegistryHeadWitnessV1,
    requirement: &RegistryHeadRequirementV1,
    now: u64,
) -> Result<ArtifactPublicationTransactionV1, ArtifactPublicationError> {
    validate_artifact_publication_v3(admission, withdrawal_domain, withdrawal_registry, now)?;

    let current_records = current_registry.records();
    let candidate_records = candidate_registry.records();
    if candidate_records.len() <= current_records.len()
        || candidate_records.get(..current_records.len()) != Some(current_records)
    {
        return Err(ArtifactPublicationError::CandidateNotSuccessor);
    }

    let v2 = &admission.validated_manifest.manifest;
    let bridge = candidate_records[current_records.len()..]
        .iter()
        .find_map(|record| match &record.event {
            ArtifactEvent::Register { manifest, .. } if manifest.artifact_id == v2.artifact_id => {
                Some(manifest)
            }
            ArtifactEvent::Register { .. }
            | ArtifactEvent::Quarantine(_)
            | ArtifactEvent::Revoke(_) => None,
        })
        .ok_or(ArtifactPublicationError::ManifestBridgeMissing)?;

    if bridge.kind != v2.kind
        || bridge.generation != v2.generation
        || bridge.content_digest != v2.bytes_digest
        || bridge.producer_id != v2.producer_id
        || bridge.compatibility_digest != v2.compatibility_digest
        || bridge.encoded_size_bytes != v2.encoded_size_bytes
        || !candidate_registry.is_eligible(&v2.artifact_id)
    {
        return Err(ArtifactPublicationError::ManifestBridgeMismatch);
    }
    match &bridge.predecessor_id {
        Some(predecessor) if !v2.predecessor_ids.contains(predecessor) => {
            return Err(ArtifactPublicationError::ManifestBridgeMismatch);
        }
        None if !v2.predecessor_ids.is_empty() => {
            return Err(ArtifactPublicationError::ManifestBridgeMismatch);
        }
        Some(_) | None => {}
    }

    let predecessor_registry_head_digest = current_registry.snapshot().head_digest;
    let candidate_registry_head_digest = candidate_registry.snapshot().head_digest;
    if candidate_registry_head_digest.is_zero()
        || candidate_registry_head_digest == predecessor_registry_head_digest
        || witness.predecessor_head_digest != predecessor_registry_head_digest
        || witness.head_digest != candidate_registry_head_digest
        || requirement.expected_predecessor_head_digest != predecessor_registry_head_digest
    {
        return Err(ArtifactPublicationError::WitnessHeadMismatch);
    }

    let witness_receipt = validate_registry_head_witness(witness, requirement)
        .map_err(ArtifactPublicationError::RegistryWitness)?;

    let transaction_digest = digest_transaction(
        &witness.registry_id,
        witness.generation,
        predecessor_registry_head_digest,
        candidate_registry_head_digest,
        admission.withdrawal_domain_digest,
        admission.withdrawal_head_digest,
        admission.validated_manifest.manifest_digest,
        admission.admission_digest,
        witness_receipt.witness_digest,
    );

    Ok(ArtifactPublicationTransactionV1 {
        registry_id: witness.registry_id.clone(),
        registry_generation: witness.generation,
        predecessor_registry_head_digest,
        candidate_registry_head_digest,
        withdrawal_domain_digest: admission.withdrawal_domain_digest,
        withdrawal_head_digest: admission.withdrawal_head_digest,
        manifest_digest: admission.validated_manifest.manifest_digest,
        admission_digest: admission.admission_digest,
        witness_digest: witness_receipt.witness_digest,
        transaction_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Classify crash recovery using a host-authenticated current-head witness.
///
/// NotCommitted means payload/snapshot/intent files may exist but the old head
/// is still authoritative. Committed means the exact candidate generation is
/// current. Any unrelated head or generation is a conflict requiring external
/// reconciliation; this crate never guesses or rolls back automatically.
pub fn classify_artifact_publication_recovery_v1(
    transaction: &ArtifactPublicationTransactionV1,
    current_witness: &RegistryHeadWitnessV1,
    current_requirement: &RegistryHeadRequirementV1,
) -> Result<ArtifactPublicationRecoveryV1, ArtifactPublicationError> {
    let receipt = validate_registry_head_witness(current_witness, current_requirement)
        .map_err(ArtifactPublicationError::RegistryWitness)?;
    if current_witness.registry_id != transaction.registry_id {
        return Err(ArtifactPublicationError::RecoveryHeadConflict);
    }

    if current_witness.head_digest == transaction.candidate_registry_head_digest {
        if receipt.generation != transaction.registry_generation {
            return Err(ArtifactPublicationError::RecoveryGenerationConflict);
        }
        return Ok(ArtifactPublicationRecoveryV1::Committed);
    }

    if current_witness.head_digest == transaction.predecessor_registry_head_digest {
        if receipt.generation >= transaction.registry_generation {
            return Err(ArtifactPublicationError::RecoveryGenerationConflict);
        }
        return Ok(ArtifactPublicationRecoveryV1::NotCommitted);
    }

    Err(ArtifactPublicationError::RecoveryHeadConflict)
}

#[expect(
    clippy::too_many_arguments,
    reason = "the digest commits every immutable publication transaction field"
)]
fn digest_transaction(
    registry_id: &StableId,
    registry_generation: Generation,
    predecessor_registry_head_digest: Digest32,
    candidate_registry_head_digest: Digest32,
    withdrawal_domain_digest: Digest32,
    withdrawal_head_digest: Digest32,
    manifest_digest: Digest32,
    admission_digest: Digest32,
    witness_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-transaction.v1".to_vec();
    push_id(&mut bytes, registry_id);
    bytes.extend_from_slice(&registry_generation.get().to_be_bytes());
    for digest in [
        predecessor_registry_head_digest,
        candidate_registry_head_digest,
        withdrawal_domain_digest,
        withdrawal_head_digest,
        manifest_digest,
        admission_digest,
        witness_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        ArtifactKind, ArtifactManifest, LearningArtifactManifestV2, ProvenanceModeV1,
        RegistryAppendDisposition, admit_manifest_at_withdrawal_head_v3,
        withdrawal_head_digest_v3,
    };

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn domain() -> WithdrawalAuthorityDomainV1 {
        WithdrawalAuthorityDomainV1 {
            registry_id: id("withdrawal-registry"),
            scope_digest: digest("tenant-a"),
            authority_id: id("withdrawal-authority"),
            authority_epoch: 7,
        }
    }

    fn manifest_v2() -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: id("artifact"),
            kind: ArtifactKind::Model,
            generation: Generation::new(2).unwrap(),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![digest("dataset")],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: vec![id("base")],
            rollback_predecessor: Some(id("base")),
            bytes_digest: digest("bytes"),
            encoded_size_bytes: 512,
            training_code_digest: digest("training"),
            runtime_tuple_digest: digest("runtime"),
            device_profile_digest: digest("device"),
            objective_class_digest: digest("objective-v2"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: id("producer"),
            created_at: 10,
            expires_at: 100,
        }
    }

    fn base_registry() -> ArtifactRegistry {
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("register-base"),
                manifest: ArtifactManifest {
                    artifact_id: id("base"),
                    kind: ArtifactKind::Model,
                    generation: Generation::new(1).unwrap(),
                    predecessor_id: None,
                    content_digest: digest("base-bytes"),
                    objective_digest: digest("objective-v1"),
                    support_digest: digest("base-support"),
                    producer_id: id("producer"),
                    compatibility_digest: digest("compatibility"),
                    encoded_size_bytes: 256,
                },
            })
            .unwrap();
        registry
    }

    fn candidate_registry(current: &ArtifactRegistry) -> ArtifactRegistry {
        let mut registry = current.clone();
        let receipt = registry
            .append(ArtifactEvent::Register {
                event_id: id("register-artifact"),
                manifest: ArtifactManifest {
                    artifact_id: id("artifact"),
                    kind: ArtifactKind::Model,
                    generation: Generation::new(2).unwrap(),
                    predecessor_id: Some(id("base")),
                    content_digest: digest("bytes"),
                    objective_digest: digest("objective-v1"),
                    support_digest: digest("support-v1"),
                    producer_id: id("producer"),
                    compatibility_digest: digest("compatibility"),
                    encoded_size_bytes: 512,
                },
            })
            .unwrap();
        assert_eq!(receipt.disposition, RegistryAppendDisposition::Appended);
        registry
    }

    fn witness(
        generation: u64,
        head: Digest32,
        predecessor: Digest32,
    ) -> RegistryHeadWitnessV1 {
        RegistryHeadWitnessV1 {
            registry_id: id("artifact-registry"),
            generation: Generation::new(generation).unwrap(),
            head_digest: head,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("registry-signer"),
            signing_key_digest: digest("registry-key"),
            issued_at: 20,
            expires_at: 100,
        }
    }

    fn requirement(
        minimum_generation: u64,
        expected_predecessor: Digest32,
    ) -> RegistryHeadRequirementV1 {
        RegistryHeadRequirementV1 {
            registry_id: id("artifact-registry"),
            minimum_generation: Generation::new(minimum_generation).unwrap(),
            expected_predecessor_head_digest: expected_predecessor,
            minimum_authority_epoch: 1,
            now: 20,
        }
    }

    fn prepared() -> ArtifactPublicationTransactionV1 {
        let withdrawal = DatasetWithdrawalRegistry::new();
        let domain = domain();
        let withdrawal_head = withdrawal_head_digest_v3(&withdrawal, &domain).unwrap();
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal,
            &domain,
            withdrawal_head,
            manifest_v2(),
            20,
        )
        .unwrap();
        let current = base_registry();
        let candidate = candidate_registry(&current);
        let predecessor_head = current.snapshot().head_digest;
        let candidate_head = candidate.snapshot().head_digest;
        let witness = witness(2, candidate_head, predecessor_head);
        prepare_artifact_publication_transaction_v1(
            &admission,
            &domain,
            &withdrawal,
            &current,
            &candidate,
            &witness,
            &requirement(2, predecessor_head),
            20,
        )
        .unwrap()
    }

    #[test]
    fn publication_transaction_binds_admission_registry_and_witness() {
        let transaction = prepared();
        assert!(!transaction.transaction_digest.is_zero());
        assert!(!transaction.authority.grants_any());
    }

    #[test]
    fn publication_transaction_rejects_candidate_that_revokes_admitted_artifact() {
        let withdrawal = DatasetWithdrawalRegistry::new();
        let domain = domain();
        let withdrawal_head = withdrawal_head_digest_v3(&withdrawal, &domain).unwrap();
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal,
            &domain,
            withdrawal_head,
            manifest_v2(),
            20,
        )
        .unwrap();
        let current = base_registry();
        let mut candidate = candidate_registry(&current);
        candidate
            .append(ArtifactEvent::Revoke(crate::StateChange {
                event_id: id("revoke-artifact"),
                artifact_id: id("artifact"),
                evaluator_id: id("independent-evaluator"),
                reason_digest: digest("revoke-reason"),
            }))
            .unwrap();
        let predecessor_head = current.snapshot().head_digest;
        let witness = witness(2, candidate.snapshot().head_digest, predecessor_head);

        assert_eq!(
            prepare_artifact_publication_transaction_v1(
                &admission,
                &domain,
                &withdrawal,
                &current,
                &candidate,
                &witness,
                &requirement(2, predecessor_head),
                20,
            ),
            Err(ArtifactPublicationError::ManifestBridgeMismatch)
        );
    }

    #[test]
    fn crash_before_current_witness_publish_is_not_committed() {
        let transaction = prepared();
        let old = witness(
            1,
            transaction.predecessor_registry_head_digest,
            digest("grandparent"),
        );
        let disposition = classify_artifact_publication_recovery_v1(
            &transaction,
            &old,
            &requirement(1, digest("grandparent")),
        )
        .unwrap();
        assert_eq!(disposition, ArtifactPublicationRecoveryV1::NotCommitted);
    }

    #[test]
    fn crash_after_current_witness_publish_is_committed() {
        let transaction = prepared();
        let current = witness(
            transaction.registry_generation.get(),
            transaction.candidate_registry_head_digest,
            transaction.predecessor_registry_head_digest,
        );
        let disposition = classify_artifact_publication_recovery_v1(
            &transaction,
            &current,
            &requirement(
                transaction.registry_generation.get(),
                transaction.predecessor_registry_head_digest,
            ),
        )
        .unwrap();
        assert_eq!(disposition, ArtifactPublicationRecoveryV1::Committed);
    }
}
