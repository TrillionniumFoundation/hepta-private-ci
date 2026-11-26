//! Named product writer service for the immutable learning-artifact store.
//!
//! This is the single product caller of LearningArtifactOwnerHost. The service
//! serializes publications under one writer fence, owns the in-process artifact
//! registry and current withdrawal frontier, and blocks unrelated work while a
//! prior operation has a non-terminal durable checkpoint.

use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerPublicationCheckpointV1;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerHost;
use crate::RegistryHeadRequirementV1;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

#[derive(Clone, Debug)]
pub struct LearningArtifactOwnerServiceConfigV1 {
    pub root: PathBuf,
    pub trust: ArtifactOwnerTrustV1,
    pub writer_lease: SignedArtifactWriterLeaseV1,
    pub required_current_head: Option<SignedCurrentArtifactHeadV1>,
    pub withdrawal_registry: DatasetWithdrawalRegistry,
    pub storage_binding: Digest32,
    pub now: u64,
}

#[derive(Clone, Debug)]
pub struct LearningArtifactPublishRequestV1 {
    pub operation_id: StableId,
    pub admission: WithdrawalBoundArtifactAdmissionV3,
    pub payload: Vec<u8>,
    pub signed_current_head: SignedCurrentArtifactHeadV1,
    pub expected_registry_predecessor_head: Digest32,
    pub now: u64,
}

pub struct LearningArtifactOwnerService {
    host: LearningArtifactOwnerHost,
    withdrawal_registry: DatasetWithdrawalRegistry,
    registry: ArtifactRegistry,
    storage_binding: Digest32,
    recovery_required: Option<StableId>,
}

impl fmt::Debug for LearningArtifactOwnerService {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LearningArtifactOwnerService")
            .field("host", &self.host)
            .field("registry_head", &self.registry.snapshot().head_digest)
            .field("withdrawal_head", &self.withdrawal_registry.head_digest())
            .field("storage_binding", &self.storage_binding)
            .field("recovery_required", &self.recovery_required)
            .finish()
    }
}

impl LearningArtifactOwnerService {
    pub fn open(
        config: LearningArtifactOwnerServiceConfigV1,
    ) -> Result<Self, LearningArtifactOwnerServiceError> {
        if config.storage_binding.is_zero()
            || config.withdrawal_registry.scope_digest()
                != Some(config.trust.withdrawal_scope_digest)
        {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        let host = match config.required_current_head {
            Some(current) => LearningArtifactOwnerHost::open_with_required_current_head(
                &config.root,
                config.trust,
                config.writer_lease,
                current,
                config.now,
            )?,
            None => LearningArtifactOwnerHost::open(
                &config.root,
                config.trust,
                config.writer_lease,
                config.now,
            )?,
        };
        let registry = host.recover_current_registry(config.now)?;
        let recovery = host.recovery_required_operations()?;
        if recovery.len() > 1 {
            return Err(LearningArtifactOwnerServiceError::RecoveryConflict);
        }
        let recovery_required = recovery
            .first()
            .map(|checkpoint| checkpoint.operation_id.clone());
        Ok(Self {
            host,
            withdrawal_registry: config.withdrawal_registry,
            registry,
            storage_binding: config.storage_binding,
            recovery_required,
        })
    }

    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

    /// Return the exact authenticated CURRENT registry view for read-only
    /// product consumers. This delegates current-head discovery, signature
    /// validation and snapshot binding to the fenced artifact owner.
    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, LearningArtifactOwnerServiceError> {
        Ok(self.host.current_registry_view(now)?)
    }

    #[must_use]
    pub fn withdrawal_registry(&self) -> &DatasetWithdrawalRegistry {
        &self.withdrawal_registry
    }

    #[must_use]
    pub fn recovery_required(&self) -> Option<&StableId> {
        self.recovery_required.as_ref()
    }

    /// Install an authenticated newer withdrawal frontier. The service accepts
    /// only an exact monotonic prefix extension in the same scope.
    pub fn install_withdrawal_frontier(
        &mut self,
        next: DatasetWithdrawalRegistry,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        if next.scope_digest() != self.withdrawal_registry.scope_digest() {
            return Err(LearningArtifactOwnerServiceError::WithdrawalFrontierConflict);
        }
        let current = self.withdrawal_registry.snapshot();
        let next_snapshot = next.snapshot();
        if next_snapshot.records().len() < current.records().len()
            || &next_snapshot.records()[..current.records().len()] != current.records()
        {
            return Err(LearningArtifactOwnerServiceError::WithdrawalFrontierConflict);
        }
        self.withdrawal_registry = next;
        Ok(())
    }

    /// Execute or reconcile one complete immutable publication.
    ///
    /// Exact retries of an acknowledged operation return the same terminal
    /// receipt. A non-terminal retry reconstructs the transaction from the
    /// durable checkpoint and predecessor registry before continuing.
    pub fn publish(
        &mut self,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        if let Some(blocked) = &self.recovery_required
            && blocked != &request.operation_id
        {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                blocked.clone(),
            ));
        }
        let operation_id = request.operation_id.clone();
        let result = self.publish_inner(&request);
        match result {
            Ok(receipt) => {
                self.recovery_required = None;
                Ok(receipt)
            }
            Err(error) => {
                if let Some(recovery) = self.host.recover_publication(&operation_id)?
                    && recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged
                {
                    self.recovery_required = Some(operation_id);
                }
                Err(error)
            }
        }
    }

    fn publish_inner(
        &mut self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        // Revalidate supplied bytes and historical admission identity even on
        // acknowledged retries. This grants no current publication authority.
        let manifest = &request.admission.validated_manifest.manifest;
        if request.payload.len() as u64 != manifest.encoded_size_bytes
            || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
            || crate::verify_artifact_admission_v3(
                &request.admission,
                request.admission.withdrawal_head_digest,
                request.admission.admitted_at,
            )
            .is_err()
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }

        if request.signed_current_head.binding != self.storage_binding
            || request.signed_current_head.witness.predecessor_head_digest
                != request.expected_registry_predecessor_head
            || request.signed_current_head.withdrawal_scope_digest
                != request.admission.withdrawal_scope_digest
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }

        let checkpoint = self.host.recover_publication(&request.operation_id)?;
        if let Some(recovery) = checkpoint.as_ref() {
            validate_request_against_checkpoint(request, &recovery.checkpoint)?;
            if phase_at_least(
                recovery.checkpoint.phase,
                ArtifactPublicationPhaseV1::WitnessDurable,
            ) {
                self.host.verify_published_head_replay(
                    &request.signed_current_head,
                    &recovery.checkpoint,
                )?;
            }
            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                return receipt_from_checkpoint(&recovery.checkpoint);
            }
        }

        let predecessor = self
            .host
            .recover_registry_by_head(request.expected_registry_predecessor_head)?;
        let mut staged = predecessor.clone();
        let mut transaction = self.host.begin_publication(
            request.operation_id.clone(),
            request.admission.clone(),
            &self.withdrawal_registry,
            &predecessor,
            request.expected_registry_predecessor_head,
            request.now,
        )?;
        self.host
            .stage_compatibility_registration(&transaction, &mut staged, request.now)?;

        if let Some(recovery) = checkpoint {
            transaction = rebuild_transaction(
                transaction,
                &staged,
                &self.withdrawal_registry,
                request,
                &recovery.checkpoint,
            )?;
            transaction = self
                .host
                .resume_publication(transaction.snapshot(), request.now)?;
        }

        if transaction.phase() == ArtifactPublicationPhaseV1::Prepared {
            self.host.ensure_payload_durable(
                &mut transaction,
                &staged,
                &request.payload,
                request.now,
            )?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::PayloadDurable {
            self.host.ensure_registry_durable(
                &mut transaction,
                &staged,
                &self.withdrawal_registry,
                self.storage_binding,
                request.now,
            )?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::RegistryDurable {
            self.host.ensure_witness_durable(
                &mut transaction,
                &request.signed_current_head,
                &self.withdrawal_registry,
                request.now,
            )?;
        }
        let receipt = if transaction.phase() == ArtifactPublicationPhaseV1::WitnessDurable {
            self.host
                .acknowledge(&mut transaction, &self.withdrawal_registry, request.now)?
        } else {
            return Err(LearningArtifactOwnerServiceError::UnexpectedPhase);
        };
        self.registry = staged;
        Ok(receipt)
    }
}

fn validate_request_against_checkpoint(
    request: &LearningArtifactPublishRequestV1,
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<(), LearningArtifactOwnerServiceError> {
    if checkpoint.operation_id != request.operation_id
        || checkpoint.admission_digest != request.admission.admission_digest
        || checkpoint.withdrawal_scope_digest != request.admission.withdrawal_scope_digest
        || checkpoint.withdrawal_head_digest != request.admission.withdrawal_head_digest
        || checkpoint.expected_registry_predecessor_head
            != request.expected_registry_predecessor_head
    {
        return Err(LearningArtifactOwnerServiceError::RequestMismatch);
    }
    Ok(())
}

fn rebuild_transaction(
    mut transaction: ArtifactPublicationTransactionV1,
    staged: &ArtifactRegistry,
    withdrawals: &DatasetWithdrawalRegistry,
    request: &LearningArtifactPublishRequestV1,
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<ArtifactPublicationTransactionV1, LearningArtifactOwnerServiceError> {
    if phase_at_least(checkpoint.phase, ArtifactPublicationPhaseV1::PayloadDurable) {
        let manifest = &request.admission.validated_manifest.manifest;
        transaction.record_payload_durable(manifest.bytes_digest, manifest.encoded_size_bytes)?;
    }
    if phase_at_least(
        checkpoint.phase,
        ArtifactPublicationPhaseV1::RegistryDurable,
    ) {
        transaction.record_registry_durable(
            staged,
            checkpoint
                .registry_receipt
                .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
            withdrawals,
            request.now,
        )?;
    }
    if phase_at_least(checkpoint.phase, ArtifactPublicationPhaseV1::WitnessDurable) {
        let witness = &request.signed_current_head.witness;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: witness.registry_id.clone(),
            minimum_generation: witness.generation,
            expected_predecessor_head_digest: request.expected_registry_predecessor_head,
            minimum_authority_epoch: witness.authority_epoch,
            now: request.now,
        };
        transaction.record_witness_durable(
            witness,
            &requirement,
            checkpoint
                .witness_receipt
                .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
            withdrawals,
            request.now,
        )?;
    }
    if checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
        transaction.acknowledge(
            withdrawals,
            checkpoint
                .acknowledged_at
                .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
        )?;
    }
    if transaction.state_digest() != checkpoint.state_digest {
        return Err(LearningArtifactOwnerServiceError::CheckpointMismatch);
    }
    Ok(transaction)
}

fn receipt_from_checkpoint(
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
    let registry = checkpoint
        .registry_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    let witness = checkpoint
        .witness_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    Ok(ArtifactPublicationReceiptV1 {
        operation_id: checkpoint.operation_id.clone(),
        admission_digest: checkpoint.admission_digest,
        registry_head_digest: registry.head_digest,
        witness_digest: witness.witness_digest,
        state_digest: checkpoint.state_digest,
        acknowledged_at: checkpoint
            .acknowledged_at
            .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
        authority: AuthorityPosture::DENY_ALL,
    })
}

const fn phase_at_least(
    actual: ArtifactPublicationPhaseV1,
    expected: ArtifactPublicationPhaseV1,
) -> bool {
    phase_rank(actual) >= phase_rank(expected)
}

const fn phase_rank(phase: ArtifactPublicationPhaseV1) -> u8 {
    match phase {
        ArtifactPublicationPhaseV1::Prepared => 0,
        ArtifactPublicationPhaseV1::PayloadDurable => 1,
        ArtifactPublicationPhaseV1::RegistryDurable => 2,
        ArtifactPublicationPhaseV1::WitnessDurable => 3,
        ArtifactPublicationPhaseV1::Acknowledged => 4,
    }
}

#[derive(Debug)]
pub enum LearningArtifactOwnerServiceError {
    Host(ArtifactOwnerHostError),
    Publication(ArtifactPublicationError),
    InvalidConfiguration,
    WithdrawalFrontierConflict,
    RecoveryConflict,
    RecoveryRequired(StableId),
    RequestMismatch,
    CheckpointShape,
    CheckpointMismatch,
    UnexpectedPhase,
}

impl fmt::Display for LearningArtifactOwnerServiceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningArtifactOwnerServiceError {}

impl From<ArtifactOwnerHostError> for LearningArtifactOwnerServiceError {
    fn from(value: ArtifactOwnerHostError) -> Self {
        Self::Host(value)
    }
}

impl From<ArtifactPublicationError> for LearningArtifactOwnerServiceError {
    fn from(value: ArtifactPublicationError) -> Self {
        Self::Publication(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    use std::fs;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    use codex_hepta_types::Generation;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use crate::ArtifactKind;
    use crate::DatasetWithdrawalScopeV1;
    use crate::LearningArtifactManifestV2;
    use crate::ProvenanceModeV1;
    use crate::RegistryHeadWitnessV1;
    use crate::TrustedArtifactSignerV1;
    use crate::admit_manifest_at_withdrawal_head_v3;
    use crate::test_support::FixtureValue;

    static NEXT_TEST_DIR: AtomicU64 = AtomicU64::new(1);

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let id = NEXT_TEST_DIR.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "hepta-learning-artifact-service-{}-{id}",
                std::process::id()
            ));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).fixture("create service test dir");
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).fixture("stable id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn key() -> SigningKey {
        SigningKey::from_bytes(&[9u8; 32])
    }

    fn scope() -> DatasetWithdrawalScopeV1 {
        DatasetWithdrawalScopeV1 {
            authority_domain_id: id("dataset-authority"),
            registry_id: id("withdrawals"),
            scope_id: id("scope"),
        }
    }

    fn signer(key: &SigningKey) -> TrustedArtifactSignerV1 {
        TrustedArtifactSignerV1 {
            signer_id: id("owner-authority"),
            verifying_key: key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 10,
            valid_from: 1,
            expires_at: 10_000,
            revoked_at: None,
        }
    }

    fn trust(key: &SigningKey, scope_digest: Digest32) -> ArtifactOwnerTrustV1 {
        ArtifactOwnerTrustV1 {
            registry_id: id("learning-artifacts"),
            withdrawal_scope_digest: scope_digest,
            minimum_registry_generation: Generation::new(1).fixture("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer(key)],
            head_signers: vec![signer(key)],
        }
    }

    fn lease(key: &SigningKey, scope_digest: Digest32) -> SignedArtifactWriterLeaseV1 {
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("writer-lease"),
            producer_id: id("trainer"),
            registry_id: id("learning-artifacts"),
            withdrawal_scope_digest: scope_digest,
            signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: 10,
            expires_at: 1_000,
            signature: [0; 64],
        };
        lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
        lease
    }

    fn manifest() -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: id("candidate"),
            kind: ArtifactKind::Model,
            generation: Generation::new(1).fixture("generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![digest("dataset")],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: Vec::new(),
            rollback_predecessor: None,
            bytes_digest: digest("payload"),
            encoded_size_bytes: 7,
            training_code_digest: digest("code"),
            runtime_tuple_digest: digest("runtime"),
            device_profile_digest: digest("device"),
            objective_class_digest: digest("objective"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: id("trainer"),
            created_at: 10,
            expires_at: 1_000,
        }
    }

    fn publish_request(
        key: &SigningKey,
        withdrawals: &DatasetWithdrawalRegistry,
        predecessor: Digest32,
        head: Digest32,
    ) -> LearningArtifactPublishRequestV1 {
        let admission = admit_manifest_at_withdrawal_head_v3(
            withdrawals,
            withdrawals.head_digest(),
            manifest(),
            20,
        )
        .fixture("admission");
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: withdrawals.scope_digest().fixture("scope digest"),
            binding: digest("binding"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("learning-artifacts"),
                generation: Generation::new(1).fixture("generation"),
                head_digest: head,
                predecessor_head_digest: predecessor,
                authority_epoch: 1,
                signer_id: id("owner-authority"),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 1_000,
            },
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        LearningArtifactPublishRequestV1 {
            operation_id: id("operation"),
            admission,
            payload: b"payload".to_vec(),
            signed_current_head: signed,
            expected_registry_predecessor_head: predecessor,
            now: 20,
        }
    }

    #[test]
    fn named_owner_service_publishes_retries_and_reopens_from_current_head() {
        let directory = TestDir::new();
        let key = key();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let scope_digest = withdrawals.scope_digest().fixture("scope digest");

        let mut service =
            LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                root: directory.0.clone(),
                trust: trust(&key, scope_digest),
                writer_lease: lease(&key, scope_digest),
                required_current_head: None,
                withdrawal_registry: withdrawals.clone(),
                storage_binding: digest("binding"),
                now: 20,
            })
            .fixture("open service");

        let predecessor = service.registry().snapshot().head_digest;
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            20,
        )
        .fixture("admission for head calculation");
        let mut staged = ArtifactRegistry::new();
        let preview = ArtifactPublicationTransactionV1::begin(
            id("operation"),
            admission,
            &withdrawals,
            &staged,
            predecessor,
            20,
        )
        .fixture("preview");
        service
            .host
            .stage_compatibility_registration(&preview, &mut staged, 20)
            .fixture("preview registration");
        let request = publish_request(
            &key,
            &withdrawals,
            predecessor,
            staged.snapshot().head_digest,
        );

        let receipt = service.publish(request.clone()).fixture("publish");
        let retry = service.publish(request.clone()).fixture("terminal retry");
        assert_eq!(retry, receipt);
        let current_view = service
            .current_registry_view(20)
            .fixture("authenticated current registry view");
        assert_eq!(
            current_view.receipt().head_digest,
            receipt.registry_head_digest
        );
        assert!(!current_view.witness_digest().is_zero());
        assert!(!current_view.trust_digest().is_zero());
        // The default CI regression must cover exact retry identity even
        // without the optional archived PFT files.
        let mut drift = request.clone();
        drift.payload[0] ^= 1;
        assert!(service.publish(drift).is_err());
        let mut drift = request.clone();
        drift.signed_current_head.signature[0] ^= 1;
        assert!(service.publish(drift).is_err());
        let mut drift = request.clone();
        drift
            .admission
            .validated_manifest
            .manifest
            .objective_class_digest = digest("drift");
        assert!(service.publish(drift).is_err());
        let mut drift = request.clone();
        drift.signed_current_head.witness.generation = Generation::new(99).unwrap();
        assert!(service.publish(drift).is_err());
        assert_eq!(service.publish(request.clone()).unwrap(), receipt);
        assert!(service.recovery_required().is_none());
        let current = request.signed_current_head;
        drop(service);

        let reopened = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&key, scope_digest),
            writer_lease: lease(&key, scope_digest),
            required_current_head: Some(current),
            withdrawal_registry: withdrawals,
            storage_binding: digest("binding"),
            now: 21,
        })
        .fixture("reopen service");
        assert_eq!(
            reopened.registry().snapshot().head_digest,
            receipt.registry_head_digest
        );
        assert!(reopened.recovery_required().is_none());
        assert_eq!(
            reopened
                .current_registry_view(21)
                .fixture("reopened authenticated current view")
                .receipt()
                .head_digest,
            receipt.registry_head_digest
        );
    }

    // Exercise the service restart path, not just the host snapshot API.
    // Each cut uses an isolated durable store and a fixture trust domain.
    #[test]
    fn pending_publication_exact_retry_across_four_durable_cuts() {
        for cut in [
            ArtifactPublicationPhaseV1::Prepared,
            ArtifactPublicationPhaseV1::PayloadDurable,
            ArtifactPublicationPhaseV1::RegistryDurable,
            ArtifactPublicationPhaseV1::WitnessDurable,
        ] {
            let directory = TestDir::new();
            let key = key();
            let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
            let scope_digest = withdrawals.scope_digest().unwrap();
            let config = LearningArtifactOwnerServiceConfigV1 {
                root: directory.0.clone(),
                trust: trust(&key, scope_digest),
                writer_lease: lease(&key, scope_digest),
                required_current_head: None,
                withdrawal_registry: withdrawals.clone(),
                storage_binding: digest("binding"),
                now: 20,
            };
            let service = LearningArtifactOwnerService::open(config.clone()).unwrap();
            let predecessor = service.registry().snapshot().head_digest;
            let admission = admit_manifest_at_withdrawal_head_v3(
                &withdrawals,
                withdrawals.head_digest(),
                manifest(),
                20,
            )
            .unwrap();
            let mut staged = service.registry().clone();
            let mut transaction = service
                .host
                .begin_publication(
                    id("operation"),
                    admission,
                    &withdrawals,
                    service.registry(),
                    predecessor,
                    20,
                )
                .unwrap();
            service
                .host
                .stage_compatibility_registration(&transaction, &mut staged, 20)
                .unwrap();
            let request = publish_request(
                &key,
                &withdrawals,
                predecessor,
                staged.snapshot().head_digest,
            );
            if phase_at_least(cut, ArtifactPublicationPhaseV1::PayloadDurable) {
                service
                    .host
                    .ensure_payload_durable(&mut transaction, &staged, &request.payload, 20)
                    .unwrap();
            }
            if phase_at_least(cut, ArtifactPublicationPhaseV1::RegistryDurable) {
                service
                    .host
                    .ensure_registry_durable(
                        &mut transaction,
                        &staged,
                        &withdrawals,
                        digest("binding"),
                        20,
                    )
                    .unwrap();
            }
            if phase_at_least(cut, ArtifactPublicationPhaseV1::WitnessDurable) {
                service
                    .host
                    .ensure_witness_durable(
                        &mut transaction,
                        &request.signed_current_head,
                        &withdrawals,
                        20,
                    )
                    .unwrap();
            }
            assert_eq!(transaction.phase(), cut);
            drop(transaction);
            drop(service);
            let mut reopened =
                LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                    now: 21,
                    ..config.clone()
                })
                .unwrap();
            assert_eq!(reopened.recovery_required(), Some(&request.operation_id));
            let mut unrelated = request.clone();
            unrelated.operation_id = id("unrelated");
            assert!(matches!(
                reopened.publish(unrelated),
                Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
            ));
            let mut changed = request.clone();
            changed.payload[0] ^= 1;
            assert!(reopened.publish(changed).is_err());
            let mut changed = request.clone();
            changed
                .admission
                .validated_manifest
                .manifest
                .objective_class_digest = digest("changed");
            assert!(reopened.publish(changed).is_err());
            if cut == ArtifactPublicationPhaseV1::WitnessDurable {
                let mut changed = request.clone();
                changed.signed_current_head.signature[0] ^= 1;
                assert!(reopened.publish(changed).is_err());
                let mut changed = request.clone();
                changed.signed_current_head.witness.generation = Generation::new(99).unwrap();
                assert!(reopened.publish(changed).is_err());
            }
            assert_eq!(reopened.recovery_required(), Some(&request.operation_id));
            let checkpoint = reopened
                .host
                .recover_publication(&request.operation_id)
                .unwrap()
                .unwrap();
            assert_eq!(checkpoint.checkpoint.phase, cut);
            let receipt = reopened.publish(request.clone()).unwrap();
            assert!(reopened.recovery_required().is_none());
            assert_eq!(reopened.publish(request.clone()).unwrap(), receipt);
            assert_eq!(
                reopened
                    .current_registry_view(21)
                    .unwrap()
                    .receipt()
                    .head_digest,
                receipt.registry_head_digest
            );
            drop(reopened);
            let mut terminal =
                LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                    now: 21,
                    required_current_head: Some(request.signed_current_head.clone()),
                    ..config
                })
                .unwrap();
            assert!(terminal.recovery_required().is_none());
            assert_eq!(terminal.publish(request).unwrap(), receipt);
            println!(
                "PENDING_CUT {:?} exact recovery and durable terminal replay; unrelated/drift rejected",
                cut
            );
        }
    }

    // Reuse the existing process-fault worker, but actually reconcile its
    // interrupted publications through the named public service after death.
    #[test]
    fn named_service_reconciles_process_death_between_effect_and_checkpoint() {
        use std::process::Command;
        use std::process::Stdio;
        use std::time::Duration;
        let executable = std::env::current_exe().unwrap();
        let key = SigningKey::from_bytes(&[7u8; 32]); // existing host worker fixture
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let scope_digest = withdrawals.scope_digest().unwrap();
        let preview_dir = TestDir::new();
        let preview_config = LearningArtifactOwnerServiceConfigV1 {
            root: preview_dir.0.clone(),
            trust: trust(&key, scope_digest),
            writer_lease: lease(&key, scope_digest),
            required_current_head: None,
            withdrawal_registry: withdrawals.clone(),
            storage_binding: digest("binding"),
            now: 20,
        };
        let preview = LearningArtifactOwnerService::open(preview_config.clone()).unwrap();
        let predecessor = preview.registry().snapshot().head_digest;
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            20,
        )
        .unwrap();
        let mut staged = preview.registry().clone();
        let transaction = ArtifactPublicationTransactionV1::begin(
            id("process-operation"),
            admission,
            &withdrawals,
            &staged,
            predecessor,
            20,
        )
        .unwrap();
        preview
            .host
            .stage_compatibility_registration(&transaction, &mut staged, 20)
            .unwrap();
        let mut request = publish_request(
            &key,
            &withdrawals,
            predecessor,
            staged.snapshot().head_digest,
        );
        request.operation_id = id("process-operation");
        drop(preview);
        for (stage, expected_phase) in [
            ("payload-effect", ArtifactPublicationPhaseV1::Prepared),
            (
                "registry-effect",
                ArtifactPublicationPhaseV1::PayloadDurable,
            ),
            ("head-effect", ArtifactPublicationPhaseV1::RegistryDurable),
            ("acknowledged", ArtifactPublicationPhaseV1::Acknowledged),
        ] {
            let directory = TestDir::new();
            let mut child = Command::new(&executable)
                .args([
                    "--ignored",
                    "--exact",
                    "owner_host::tests::owner_host_process_fault_worker",
                    "--nocapture",
                ])
                .env("HEPTA_ARTIFACT_OWNER_WORKER", "1")
                .env("HEPTA_ARTIFACT_OWNER_ROOT", &directory.0)
                .env("HEPTA_ARTIFACT_OWNER_STAGE", stage)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .spawn()
                .unwrap();
            let marker = directory.0.join(format!("worker-{stage}.ready"));
            let mut ready = false;
            for _ in 0..500 {
                if marker.is_file() {
                    ready = true;
                    break;
                }
                if child.try_wait().unwrap().is_some() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(10));
            }
            if !ready {
                let _ = child.kill();
                let _ = child.wait();
                panic!("worker failed before durable marker: {stage}");
            }
            child.kill().unwrap();
            let exit = child.wait().unwrap();
            assert!(!exit.success());
            let mut service =
                LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                    root: directory.0.clone(),
                    now: 21,
                    ..preview_config.clone()
                })
                .unwrap();
            let cp = service
                .host
                .recover_publication(&request.operation_id)
                .unwrap()
                .unwrap()
                .checkpoint;
            assert_eq!(cp.phase, expected_phase);
            if expected_phase != ArtifactPublicationPhaseV1::Acknowledged {
                assert_eq!(service.recovery_required(), Some(&request.operation_id));
                let mut unrelated = request.clone();
                unrelated.operation_id = id("unrelated");
                assert!(matches!(
                    service.publish(unrelated),
                    Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
                ));
            }
            let mut bad = request.clone();
            bad.payload[0] ^= 1;
            assert!(service.publish(bad).is_err());
            let receipt = service.publish(request.clone()).unwrap();
            assert_eq!(service.publish(request.clone()).unwrap(), receipt);
            assert!(service.recovery_required().is_none());
            assert_eq!(
                service
                    .current_registry_view(21)
                    .unwrap()
                    .receipt()
                    .head_digest,
                receipt.registry_head_digest
            );
            assert_eq!(
                service
                    .host
                    .recover_publication(&request.operation_id)
                    .unwrap()
                    .unwrap()
                    .checkpoint
                    .phase,
                ArtifactPublicationPhaseV1::Acknowledged
            );
            println!(
                "PROCESS_DEATH {stage} checkpoint={expected_phase:?} exact public reconciliation"
            );
        }
    }

    // Append within owner_service::tests. Explicit opt-in archived-data qualification.
    // This is a disposable research registry; metadata and local trust are test-scoped.
    // No evaluation signature or activation is created.
    #[test]
    #[ignore = "requires hash-pinned PFT archive; run explicitly"]
    fn pft_archived_family_public_owner_lifecycle() {
        use crate::ParameterFamilyGuardV1;
        use crate::PinnedCandidateLoadError;
        use crate::PinnedCandidateSpec;
        use crate::load_pinned_candidate;
        use std::fs::File;
        use std::io::Read;
        let data = PathBuf::from(std::env::var("PFT_R35_DATA").unwrap());
        let entries = [
            (
                "pft-parent",
                "parent.f64",
                "89dba314bb6d25569149098087f698789cfae70534ced133a318911903a6df32",
            ),
            (
                "pft-mean",
                "mean_generated_pair.f64",
                "6623a875e35a3f50effe9dd313e5c83dfbb12cf4c293e35ed06bd0ff3e0f6df0",
            ),
            (
                "pft-minimax",
                "minimax_generated_pair.f64",
                "0460c00ee92407133191eeb1c337cde1a6aad59829cf88e8ae360d00d8bad6cb",
            ),
        ];
        let payloads: Vec<Vec<u8>> = entries
            .iter()
            .map(|(_, name, hash)| {
                let bytes = fs::read(data.join(name)).unwrap();
                assert_eq!(bytes.len(), 8192);
                assert_eq!(Digest32::of_bytes(&bytes).to_string(), *hash);
                bytes
            })
            .collect();
        let source = fs::read(data.join("training_result.json")).unwrap();
        assert_eq!(
            Digest32::of_bytes(&source).to_string(),
            "2f311d97f2a9995687de43aa9709a27ec8b7eaa883d132093f7600a396a43d28"
        );
        let directory = TestDir::new();
        let mut secret = [0u8; 32];
        File::open("/dev/urandom")
            .unwrap()
            .read_exact(&mut secret)
            .unwrap();
        let key = SigningKey::from_bytes(&secret);
        secret.fill(0);
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let scope_digest = withdrawals.scope_digest().unwrap();
        let config = LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&key, scope_digest),
            writer_lease: lease(&key, scope_digest),
            required_current_head: None,
            withdrawal_registry: withdrawals.clone(),
            storage_binding: digest("binding"),
            now: 20,
        };
        let mut service = LearningArtifactOwnerService::open(config.clone()).unwrap();
        let mut signed_final = None;
        let mut drift_accepts = 0;
        let mut historical = Vec::new();
        for i in 0..3 {
            let mut m = manifest();
            m.artifact_id = id(entries[i].0);
            m.kind = ArtifactKind::Parameters;
            m.generation = Generation::new(if i == 0 { 1 } else { 2 }).unwrap();
            // Test-scoped provenance: archive identity, not a full pretraining lineage claim.
            m.source_dataset_digests = vec![Digest32::of_bytes(&source)];
            m.lineage_digests = vec![Digest32::of_bytes(&payloads[0])];
            m.predecessor_ids = if i == 0 {
                vec![]
            } else {
                vec![id(entries[0].0)]
            };
            m.bytes_digest = Digest32::of_bytes(&payloads[i]);
            m.encoded_size_bytes = payloads[i].len() as u64;
            let admission = admit_manifest_at_withdrawal_head_v3(
                &withdrawals,
                withdrawals.head_digest(),
                m,
                20,
            )
            .unwrap();
            let predecessor = service.registry().snapshot().head_digest;
            let op = id(&format!("pft-publish-{i}"));
            let mut staged = service.registry().clone();
            let preview = ArtifactPublicationTransactionV1::begin(
                op.clone(),
                admission.clone(),
                &withdrawals,
                &staged,
                predecessor,
                20,
            )
            .unwrap();
            service
                .host
                .stage_compatibility_registration(&preview, &mut staged, 20)
                .unwrap();
            let mut signed = SignedCurrentArtifactHeadV1 {
                withdrawal_scope_digest: scope_digest,
                binding: digest("binding"),
                witness: RegistryHeadWitnessV1 {
                    registry_id: id("learning-artifacts"),
                    generation: Generation::new((i + 1) as u64).unwrap(),
                    head_digest: staged.snapshot().head_digest,
                    predecessor_head_digest: predecessor,
                    authority_epoch: 1,
                    signer_id: id("owner-authority"),
                    signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                    issued_at: 20,
                    expires_at: 1000,
                },
                signature: [0; 64],
            };
            signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
            let request = LearningArtifactPublishRequestV1 {
                operation_id: op,
                admission,
                payload: payloads[i].clone(),
                signed_current_head: signed.clone(),
                expected_registry_predecessor_head: predecessor,
                now: 20,
            };
            let receipt = service.publish(request.clone()).unwrap();
            // Counterexample probe: terminal retry must not silently acknowledge a changed request.
            let mut drift = request.clone();
            drift.payload[0] ^= 1;
            let payload_accepted = service.publish(drift).is_ok();
            let mut drift = request.clone();
            drift.signed_current_head.signature[0] ^= 1;
            let signature_accepted = service.publish(drift).is_ok();
            let mut drift = request.clone();
            drift
                .admission
                .validated_manifest
                .manifest
                .objective_class_digest = digest("changed-objective");
            let admission_accepted = service.publish(drift).is_ok();
            let mut drift = request.clone();
            drift.signed_current_head.witness.generation = Generation::new(99).unwrap();
            let head_accepted = service.publish(drift).is_ok();
            println!(
                "RETRY_DRIFT {} payload={} signature={} admission={} head={}",
                entries[i].0,
                payload_accepted,
                signature_accepted,
                admission_accepted,
                head_accepted
            );
            drift_accepts += [
                payload_accepted,
                signature_accepted,
                admission_accepted,
                head_accepted,
            ]
            .iter()
            .filter(|v| **v)
            .count();
            assert_eq!(service.publish(request.clone()).unwrap(), receipt);
            historical.push((request, receipt.clone()));
            let current = service.current_registry_view(20).unwrap();
            assert_eq!(current.receipt().records, i + 1);
            assert_eq!(current.receipt().head_digest, receipt.registry_head_digest);
            println!(
                "PUBLISHED {} {} records={}",
                entries[i].0,
                entries[i].2,
                i + 1
            );
            signed_final = Some(signed);
        }
        for (request, receipt) in historical {
            assert_eq!(service.publish(request).unwrap(), receipt);
        }
        println!("DRIFT_ACCEPTS {}", drift_accepts);
        assert_eq!(drift_accepts, 0, "terminal retry accepted mutated request");
        let current = service.current_registry_view(20).unwrap();
        let receipt = current.receipt();
        let trust_digest = current.trust_digest();
        let registry_path = directory.0.join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        ));
        let mut pins = Vec::new();
        for (name, _, hash) in entries {
            let m = service.registry().manifest(&id(name)).unwrap().clone();
            let path = directory
                .0
                .join("payloads")
                .join(format!("{name}-{hash}.bin"));
            pins.push(
                load_pinned_candidate(
                    File::open(&registry_path).unwrap(),
                    File::open(path).unwrap(),
                    PinnedCandidateSpec {
                        registry_receipt: receipt,
                        manifest: m,
                    },
                )
                .unwrap(),
            );
        }
        let parent = pins.remove(0);
        let mut guard = ParameterFamilyGuardV1::new(
            parent,
            pins,
            &[id("pft-mean"), id("pft-minimax")],
            trust_digest,
        )
        .unwrap();
        let check =
            |p: &crate::LoadedPinnedCandidate, u: &[crate::LoadedPinnedCandidate], w: Digest32| {
                assert_eq!(p.bytes(), payloads[0].as_slice());
                assert_eq!(u.len(), 2);
                assert_eq!(u[0].bytes(), payloads[1].as_slice());
                assert_eq!(u[1].bytes(), payloads[2].as_slice());
                assert!(!w.is_zero());
                println!(
                    "FAMILY_READ {} {} {} witness={}",
                    entries[0].2, entries[1].2, entries[2].2, w
                );
            };
        guard.with_service(&service, 20, check).unwrap();
        drop(service);
        let reopened = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            required_current_head: signed_final,
            now: 21,
            ..config
        })
        .unwrap();
        assert!(reopened.recovery_required().is_none());
        guard.with_service(&reopened, 21, check).unwrap();
        assert!(matches!(
            guard.with_service(&reopened, 1001, |_, _, _| panic!("expired head")),
            Err(PinnedCandidateLoadError::Unavailable)
        ));
        assert!(matches!(
            guard.with_service(&reopened, 21, |_, _, _| panic!("latched")),
            Err(PinnedCandidateLoadError::Unavailable)
        ));
        println!(
            "PASS public publication + exact retry x3, family read x2, reopen required head, expired/latch rejection; no activation"
        );
    }
}
