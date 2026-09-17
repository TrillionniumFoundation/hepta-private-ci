//! Fail-closed host publication contract joining V2 admission to durable state.
//!
//! A publication plan binds the exact V2 admission, legacy immutable registry
//! projection, withdrawal frontier/domain and lifecycle frontier. Durable
//! receipts must then be acknowledged for all three state files before a commit
//! can be sealed. Dropping an incomplete transaction is the crash path: it
//! yields no commit that a host may place behind its authenticated current
//! pointer.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::ArtifactAdmissionError;
use crate::ArtifactLifecycleJournalV2;
use crate::ArtifactRegistry;
use crate::AuthoritySnapshotKindV1;
use crate::AuthoritySnapshotReceiptV1;
use crate::DatasetWithdrawalRegistry;
use crate::ProvenanceModeV1;
use crate::RegistrySnapshotReceipt;
use crate::WithdrawalAuthorityDomainV1;
use crate::WithdrawalBoundArtifactAdmissionV3;
use crate::validate_artifact_publication_v3;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationPlanV1 {
    pub publication_scope_digest: Digest32,
    pub generation: Generation,
    pub predecessor_publication_digest: Digest32,
    pub artifact_id: StableId,
    pub manifest_digest: Digest32,
    pub admission_digest: Digest32,
    pub registry_binding: Digest32,
    pub registry_head_digest: Digest32,
    pub registry_records: usize,
    pub withdrawal_binding: Digest32,
    pub withdrawal_head_digest: Digest32,
    pub withdrawal_records: usize,
    pub lifecycle_binding: Digest32,
    pub lifecycle_head_digest: Digest32,
    pub lifecycle_records: usize,
    pub plan_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactPublicationCommitV1 {
    pub plan: ArtifactPublicationPlanV1,
    pub registry_snapshot_receipt: RegistrySnapshotReceipt,
    pub withdrawal_snapshot_receipt: AuthoritySnapshotReceiptV1,
    pub lifecycle_snapshot_receipt: AuthoritySnapshotReceiptV1,
    pub commit_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug)]
pub struct ArtifactPublicationTransactionV1 {
    plan: ArtifactPublicationPlanV1,
    registry_snapshot_receipt: Option<RegistrySnapshotReceipt>,
    withdrawal_snapshot_receipt: Option<AuthoritySnapshotReceiptV1>,
    lifecycle_snapshot_receipt: Option<AuthoritySnapshotReceiptV1>,
}

impl ArtifactPublicationTransactionV1 {
    #[must_use]
    pub fn new(plan: ArtifactPublicationPlanV1) -> Self {
        Self {
            plan,
            registry_snapshot_receipt: None,
            withdrawal_snapshot_receipt: None,
            lifecycle_snapshot_receipt: None,
        }
    }

    #[must_use]
    pub fn plan(&self) -> &ArtifactPublicationPlanV1 {
        &self.plan
    }

    pub fn acknowledge_registry_snapshot(
        &mut self,
        receipt: RegistrySnapshotReceipt,
    ) -> Result<(), ArtifactPublicationError> {
        if receipt.binding != self.plan.registry_binding
            || receipt.head_digest != self.plan.registry_head_digest
            || receipt.records != self.plan.registry_records
            || receipt.file_digest.is_zero()
            || receipt.encoded_bytes == 0
        {
            return Err(ArtifactPublicationError::RegistryReceiptMismatch);
        }
        self.registry_snapshot_receipt = Some(receipt);
        Ok(())
    }

    pub fn acknowledge_withdrawal_snapshot(
        &mut self,
        receipt: AuthoritySnapshotReceiptV1,
    ) -> Result<(), ArtifactPublicationError> {
        if receipt.kind != AuthoritySnapshotKindV1::DatasetWithdrawal
            || receipt.binding_digest != self.plan.withdrawal_binding
            || receipt.head_digest != self.plan.withdrawal_head_digest
            || receipt.records != self.plan.withdrawal_records
            || receipt.file_digest.is_zero()
            || receipt.encoded_bytes == 0
            || receipt.authority.grants_any()
        {
            return Err(ArtifactPublicationError::WithdrawalReceiptMismatch);
        }
        self.withdrawal_snapshot_receipt = Some(receipt);
        Ok(())
    }

    pub fn acknowledge_lifecycle_snapshot(
        &mut self,
        receipt: AuthoritySnapshotReceiptV1,
    ) -> Result<(), ArtifactPublicationError> {
        if receipt.kind != AuthoritySnapshotKindV1::ArtifactLifecycle
            || receipt.binding_digest != self.plan.lifecycle_binding
            || receipt.head_digest != self.plan.lifecycle_head_digest
            || receipt.records != self.plan.lifecycle_records
            || receipt.file_digest.is_zero()
            || receipt.encoded_bytes == 0
            || receipt.authority.grants_any()
        {
            return Err(ArtifactPublicationError::LifecycleReceiptMismatch);
        }
        self.lifecycle_snapshot_receipt = Some(receipt);
        Ok(())
    }

    /// Seal only after all immutable state files have returned exact durable
    /// receipts. Hosts MUST persist this commit and fsync it before atomically
    /// changing their independently authenticated current-generation pointer.
    pub fn seal(self) -> Result<ArtifactPublicationCommitV1, ArtifactPublicationError> {
        let registry_snapshot_receipt = self
            .registry_snapshot_receipt
            .ok_or(ArtifactPublicationError::DurabilityIncomplete)?;
        let withdrawal_snapshot_receipt = self
            .withdrawal_snapshot_receipt
            .ok_or(ArtifactPublicationError::DurabilityIncomplete)?;
        let lifecycle_snapshot_receipt = self
            .lifecycle_snapshot_receipt
            .ok_or(ArtifactPublicationError::DurabilityIncomplete)?;
        let commit_digest = digest_commit(
            self.plan.plan_digest,
            registry_snapshot_receipt,
            withdrawal_snapshot_receipt,
            lifecycle_snapshot_receipt,
        );
        Ok(ArtifactPublicationCommitV1 {
            plan: self.plan,
            registry_snapshot_receipt,
            withdrawal_snapshot_receipt,
            lifecycle_snapshot_receipt,
            commit_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[allow(clippy::too_many_arguments)]
pub fn prepare_artifact_publication_v1(
    admission: &WithdrawalBoundArtifactAdmissionV3,
    artifact_registry: &ArtifactRegistry,
    registry_binding: Digest32,
    withdrawal_registry: &DatasetWithdrawalRegistry,
    withdrawal_domain: &WithdrawalAuthorityDomainV1,
    lifecycle_journal: &ArtifactLifecycleJournalV2,
    lifecycle_binding: Digest32,
    publication_scope_digest: Digest32,
    generation: Generation,
    predecessor_publication_digest: Digest32,
    now: u64,
) -> Result<ArtifactPublicationPlanV1, ArtifactPublicationError> {
    if registry_binding.is_zero()
        || lifecycle_binding.is_zero()
        || publication_scope_digest.is_zero()
    {
        return Err(ArtifactPublicationError::InvalidBinding);
    }
    validate_artifact_publication_v3(admission, withdrawal_registry, withdrawal_domain, now)?;

    let v2 = &admission.validated_manifest.manifest;
    let v1 = artifact_registry
        .manifest(&v2.artifact_id)
        .ok_or(ArtifactPublicationError::RegistryProjectionMissing)?;
    if !artifact_registry.is_eligible(&v2.artifact_id)
        || v1.artifact_id != v2.artifact_id
        || v1.kind != v2.kind
        || v1.generation != v2.generation
        || v1.content_digest != v2.bytes_digest
        || v1.objective_digest != v2.objective_class_digest
        || v1.producer_id != v2.producer_id
        || v1.compatibility_digest != v2.compatibility_digest
        || v1.encoded_size_bytes != v2.encoded_size_bytes
    {
        return Err(ArtifactPublicationError::RegistryProjectionMismatch);
    }
    // The V1 support digest is intentionally not treated as complete V2
    // provenance. DatasetDerived V2 may contain multiple inputs; withdrawal
    // authority is therefore carried by the separately bound V3 frontier.
    if v2.provenance_mode == ProvenanceModeV1::DatasetDerived
        && v2.source_dataset_digests.is_empty()
    {
        return Err(ArtifactPublicationError::RegistryProjectionMismatch);
    }

    let registry_snapshot = artifact_registry.snapshot();
    let withdrawal_snapshot = withdrawal_registry.snapshot();
    if withdrawal_snapshot.head_digest != admission.withdrawal_head_digest {
        return Err(ArtifactPublicationError::WithdrawalFrontierMismatch);
    }
    let withdrawal_binding = withdrawal_domain_digest(withdrawal_domain)?;
    if withdrawal_binding != admission.withdrawal_domain_digest {
        return Err(ArtifactPublicationError::WithdrawalFrontierMismatch);
    }

    let mut plan = ArtifactPublicationPlanV1 {
        publication_scope_digest,
        generation,
        predecessor_publication_digest,
        artifact_id: v2.artifact_id.clone(),
        manifest_digest: admission.validated_manifest.manifest_digest,
        admission_digest: admission.admission_digest,
        registry_binding,
        registry_head_digest: registry_snapshot.head_digest,
        registry_records: registry_snapshot.records().len(),
        withdrawal_binding,
        withdrawal_head_digest: withdrawal_snapshot.head_digest,
        withdrawal_records: withdrawal_snapshot.records().len(),
        lifecycle_binding,
        lifecycle_head_digest: lifecycle_journal.head_digest(),
        lifecycle_records: lifecycle_journal.records().len(),
        plan_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    plan.plan_digest = digest_plan(&plan);
    Ok(plan)
}

pub fn verify_artifact_publication_commit_v1(
    commit: &ArtifactPublicationCommitV1,
    expected_publication_scope_digest: Digest32,
    expected_generation: Generation,
    expected_predecessor_publication_digest: Digest32,
) -> Result<(), ArtifactPublicationError> {
    if commit.authority.grants_any()
        || commit.plan.authority.grants_any()
        || commit.plan.publication_scope_digest != expected_publication_scope_digest
        || commit.plan.generation != expected_generation
        || commit.plan.predecessor_publication_digest != expected_predecessor_publication_digest
        || commit.plan.plan_digest != digest_plan(&commit.plan)
    {
        return Err(ArtifactPublicationError::CommitMismatch);
    }
    let expected = digest_commit(
        commit.plan.plan_digest,
        commit.registry_snapshot_receipt,
        commit.withdrawal_snapshot_receipt,
        commit.lifecycle_snapshot_receipt,
    );
    if expected != commit.commit_digest {
        return Err(ArtifactPublicationError::CommitMismatch);
    }
    let mut transaction = ArtifactPublicationTransactionV1::new(commit.plan.clone());
    transaction.acknowledge_registry_snapshot(commit.registry_snapshot_receipt)?;
    transaction.acknowledge_withdrawal_snapshot(commit.withdrawal_snapshot_receipt)?;
    transaction.acknowledge_lifecycle_snapshot(commit.lifecycle_snapshot_receipt)?;
    Ok(())
}

fn withdrawal_domain_digest(
    domain: &WithdrawalAuthorityDomainV1,
) -> Result<Digest32, ArtifactPublicationError> {
    if domain.scope_digest.is_zero() || domain.authority_epoch == 0 {
        return Err(ArtifactPublicationError::InvalidBinding);
    }
    let mut bytes = b"hepta.learning-artifacts.withdrawal-authority-domain.v1".to_vec();
    push_id(&mut bytes, &domain.registry_id);
    bytes.extend_from_slice(domain.scope_digest.as_array());
    push_id(&mut bytes, &domain.authority_id);
    bytes.extend_from_slice(&domain.authority_epoch.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_plan(plan: &ArtifactPublicationPlanV1) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-plan.v1".to_vec();
    bytes.extend_from_slice(plan.publication_scope_digest.as_array());
    bytes.extend_from_slice(&plan.generation.get().to_be_bytes());
    bytes.extend_from_slice(plan.predecessor_publication_digest.as_array());
    push_id(&mut bytes, &plan.artifact_id);
    bytes.extend_from_slice(plan.manifest_digest.as_array());
    bytes.extend_from_slice(plan.admission_digest.as_array());
    bytes.extend_from_slice(plan.registry_binding.as_array());
    bytes.extend_from_slice(plan.registry_head_digest.as_array());
    bytes.extend_from_slice(&(plan.registry_records as u64).to_be_bytes());
    bytes.extend_from_slice(plan.withdrawal_binding.as_array());
    bytes.extend_from_slice(plan.withdrawal_head_digest.as_array());
    bytes.extend_from_slice(&(plan.withdrawal_records as u64).to_be_bytes());
    bytes.extend_from_slice(plan.lifecycle_binding.as_array());
    bytes.extend_from_slice(plan.lifecycle_head_digest.as_array());
    bytes.extend_from_slice(&(plan.lifecycle_records as u64).to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn digest_commit(
    plan_digest: Digest32,
    registry: RegistrySnapshotReceipt,
    withdrawal: AuthoritySnapshotReceiptV1,
    lifecycle: AuthoritySnapshotReceiptV1,
) -> Digest32 {
    let mut bytes = b"hepta.learning-artifacts.publication-commit.v1".to_vec();
    bytes.extend_from_slice(plan_digest.as_array());
    for digest in [
        registry.binding,
        registry.head_digest,
        registry.file_digest,
        withdrawal.binding_digest,
        withdrawal.head_digest,
        withdrawal.file_digest,
        lifecycle.binding_digest,
        lifecycle.head_digest,
        lifecycle.file_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(registry.records as u64).to_be_bytes());
    bytes.extend_from_slice(&(registry.encoded_bytes as u64).to_be_bytes());
    bytes.extend_from_slice(&(withdrawal.records as u64).to_be_bytes());
    bytes.extend_from_slice(&(withdrawal.encoded_bytes as u64).to_be_bytes());
    bytes.extend_from_slice(&(lifecycle.records as u64).to_be_bytes());
    bytes.extend_from_slice(&(lifecycle.encoded_bytes as u64).to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ArtifactPublicationError {
    Admission(ArtifactAdmissionError),
    InvalidBinding,
    RegistryProjectionMissing,
    RegistryProjectionMismatch,
    WithdrawalFrontierMismatch,
    RegistryReceiptMismatch,
    WithdrawalReceiptMismatch,
    LifecycleReceiptMismatch,
    DurabilityIncomplete,
    CommitMismatch,
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
            Self::InvalidBinding
            | Self::RegistryProjectionMissing
            | Self::RegistryProjectionMismatch
            | Self::WithdrawalFrontierMismatch
            | Self::RegistryReceiptMismatch
            | Self::WithdrawalReceiptMismatch
            | Self::LifecycleReceiptMismatch
            | Self::DurabilityIncomplete
            | Self::CommitMismatch => None,
        }
    }
}

impl From<ArtifactAdmissionError> for ArtifactPublicationError {
    fn from(value: ArtifactAdmissionError) -> Self {
        Self::Admission(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::Generation;

    use crate::ArtifactEvent;
    use crate::ArtifactKind;
    use crate::ArtifactLifecycleEventV1;
    use crate::ArtifactLifecycleStateV1;
    use crate::ArtifactManifest;
    use crate::LearningArtifactManifestV2;
    use crate::LifecycleActorEvidenceV2;
    use crate::LifecycleActorRoleV2;
    use crate::admit_manifest_at_withdrawal_head_v3;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn domain() -> WithdrawalAuthorityDomainV1 {
        WithdrawalAuthorityDomainV1 {
            registry_id: id("withdrawal-registry"),
            scope_digest: digest("withdrawal-scope"),
            authority_id: id("withdrawal-authority"),
            authority_epoch: 5,
        }
    }

    fn v2_manifest() -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: id("candidate"),
            kind: ArtifactKind::Model,
            generation: Generation::new(1).expect("generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![digest("dataset")],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: digest("bytes"),
            encoded_size_bytes: 512,
            training_code_digest: digest("training-code"),
            runtime_tuple_digest: digest("runtime"),
            device_profile_digest: digest("device"),
            objective_class_digest: digest("objective"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: id("producer"),
            created_at: 10,
            expires_at: 100,
        }
    }

    fn registry_for(manifest: &LearningArtifactManifestV2) -> ArtifactRegistry {
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("register-candidate"),
                manifest: ArtifactManifest {
                    artifact_id: manifest.artifact_id.clone(),
                    kind: manifest.kind,
                    generation: manifest.generation,
                    predecessor_id: None,
                    content_digest: manifest.bytes_digest,
                    objective_digest: manifest.objective_class_digest,
                    support_digest: manifest.source_dataset_digests[0],
                    producer_id: manifest.producer_id.clone(),
                    compatibility_digest: manifest.compatibility_digest,
                    encoded_size_bytes: manifest.encoded_size_bytes,
                },
            })
            .expect("register projection");
        registry
    }

    fn lifecycle() -> ArtifactLifecycleJournalV2 {
        let producer_id = id("producer");
        let actor = LifecycleActorEvidenceV2 {
            actor_id: producer_id.clone(),
            credential_digest: digest("credential"),
            role: LifecycleActorRoleV2::Producer,
            authority_epoch: 3,
            verified_at: 10,
            expires_at: 100,
        };
        let mut journal = ArtifactLifecycleJournalV2::new();
        journal
            .append(
                Digest32::ZERO,
                &producer_id,
                actor.clone(),
                ArtifactLifecycleEventV1 {
                    event_id: id("trained"),
                    artifact_id: id("candidate"),
                    prior_state: ArtifactLifecycleStateV1::Proposed,
                    next_state: ArtifactLifecycleStateV1::Trained,
                    actor_id: actor.actor_id.clone(),
                    actor_credential_digest: actor.credential_digest,
                    evidence_digest: digest("evidence"),
                    authority_epoch: actor.authority_epoch,
                    occurred_at: 20,
                },
                20,
            )
            .expect("lifecycle append");
        journal
    }

    #[test]
    fn art_08_publication_transaction_is_unsealable_after_partial_durability() {
        let withdrawal_registry = DatasetWithdrawalRegistry::new();
        let domain = domain();
        let manifest = v2_manifest();
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal_registry,
            domain.clone(),
            withdrawal_registry.snapshot().head_digest,
            manifest.clone(),
            20,
        )
        .expect("admission");
        let registry = registry_for(&manifest);
        let lifecycle = lifecycle();
        let plan = prepare_artifact_publication_v1(
            &admission,
            &registry,
            digest("registry-binding"),
            &withdrawal_registry,
            &domain,
            &lifecycle,
            digest("lifecycle-binding"),
            digest("publication-scope"),
            Generation::new(1).expect("generation"),
            Digest32::ZERO,
            20,
        )
        .expect("publication plan");
        let mut transaction = ArtifactPublicationTransactionV1::new(plan.clone());
        transaction
            .acknowledge_registry_snapshot(RegistrySnapshotReceipt {
                binding: plan.registry_binding,
                head_digest: plan.registry_head_digest,
                file_digest: digest("registry-file"),
                records: plan.registry_records,
                encoded_bytes: 128,
            })
            .expect("registry durable");
        assert_eq!(
            transaction.seal(),
            Err(ArtifactPublicationError::DurabilityIncomplete)
        );
    }

    #[test]
    fn art_08_publication_commit_binds_all_durable_receipts() {
        let withdrawal_registry = DatasetWithdrawalRegistry::new();
        let domain = domain();
        let manifest = v2_manifest();
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawal_registry,
            domain.clone(),
            withdrawal_registry.snapshot().head_digest,
            manifest.clone(),
            20,
        )
        .expect("admission");
        let registry = registry_for(&manifest);
        let lifecycle = lifecycle();
        let plan = prepare_artifact_publication_v1(
            &admission,
            &registry,
            digest("registry-binding"),
            &withdrawal_registry,
            &domain,
            &lifecycle,
            digest("lifecycle-binding"),
            digest("publication-scope"),
            Generation::new(2).expect("generation"),
            digest("previous-publication"),
            20,
        )
        .expect("publication plan");
        let registry_receipt = RegistrySnapshotReceipt {
            binding: plan.registry_binding,
            head_digest: plan.registry_head_digest,
            file_digest: digest("registry-file"),
            records: plan.registry_records,
            encoded_bytes: 128,
        };
        let withdrawal_receipt = AuthoritySnapshotReceiptV1 {
            kind: AuthoritySnapshotKindV1::DatasetWithdrawal,
            binding_digest: plan.withdrawal_binding,
            head_digest: plan.withdrawal_head_digest,
            file_digest: digest("withdrawal-file"),
            records: plan.withdrawal_records,
            encoded_bytes: 96,
            authority: AuthorityPosture::DENY_ALL,
        };
        let lifecycle_receipt = AuthoritySnapshotReceiptV1 {
            kind: AuthoritySnapshotKindV1::ArtifactLifecycle,
            binding_digest: plan.lifecycle_binding,
            head_digest: plan.lifecycle_head_digest,
            file_digest: digest("lifecycle-file"),
            records: plan.lifecycle_records,
            encoded_bytes: 160,
            authority: AuthorityPosture::DENY_ALL,
        };
        let mut transaction = ArtifactPublicationTransactionV1::new(plan.clone());
        transaction
            .acknowledge_registry_snapshot(registry_receipt)
            .expect("registry durable");
        transaction
            .acknowledge_withdrawal_snapshot(withdrawal_receipt)
            .expect("withdrawal durable");
        transaction
            .acknowledge_lifecycle_snapshot(lifecycle_receipt)
            .expect("lifecycle durable");
        let commit = transaction.seal().expect("all durable components commit");
        verify_artifact_publication_commit_v1(
            &commit,
            plan.publication_scope_digest,
            plan.generation,
            plan.predecessor_publication_digest,
        )
        .expect("commit verifies");
        assert!(!commit.authority.grants_any());
    }
}
