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

#[path = "owner_revocation_service.rs"]
mod revocation;
pub use revocation::ArtifactRevocationReceiptV1;
pub use revocation::LearningArtifactRevokeRequestV1;

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
    // Writer -> observation lock order. Retained while any publication is
    // uncertain so another process cannot turn a readable ACK into success.
    observation_guard: Option<std::fs::File>,
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
        let observation_guard = host.acquire_current_observation_exclusive()?;
        // A crash can leave complete ACK bytes after a failed sync. Reestablish
        // their durability before interpreting a readable ACK as settled.
        host.reconcile_readable_acknowledgements()?;
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
            observation_guard: recovery_required.as_ref().map(|_| observation_guard),
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
        if let Some(operation_id) = &self.recovery_required {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                operation_id.clone(),
            ));
        }
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
        self.ensure_observation_guard()?;
        let operation_id = request.operation_id.clone();
        let fenced_retry = self.recovery_required.as_ref() == Some(&operation_id);
        let result = self.publish_inner(&request);
        let result = match result {
            Ok(receipt) => {
                self.recovery_required = None;
                Ok(receipt)
            }
            Err(error) => {
                // Reconciliation can itself fail after an uncertain write. Fence
                // readers and unrelated writers before inspecting that outcome.
                self.recovery_required = Some(operation_id.clone());
                let uncertain = matches!(
                    error,
                    LearningArtifactOwnerServiceError::Host(ArtifactOwnerHostError::Indeterminate)
                        | LearningArtifactOwnerServiceError::Host(ArtifactOwnerHostError::Storage(
                            crate::ArtifactStorageError::Indeterminate
                        ))
                );
                match self.host.recover_publication(&operation_id)? {
                    Some(recovery) => {
                        if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged
                            && !uncertain
                            && !fenced_retry
                        {
                            self.recovery_required = None;
                        }
                    }
                    None => {
                        if !uncertain && !fenced_retry {
                            self.recovery_required = None;
                        }
                    }
                }
                Err(error)
            }
        };
        if self.recovery_required.is_none() {
            self.observation_guard = None;
        }
        result
    }

    fn ensure_observation_guard(&mut self) -> Result<(), LearningArtifactOwnerServiceError> {
        if self.observation_guard.is_none() {
            self.observation_guard = Some(self.host.acquire_current_observation_exclusive()?);
        }
        Ok(())
    }

    fn publish_inner(
        &mut self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
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
            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                self.host
                    .reconcile_acknowledged_publication(&recovery.checkpoint)?;
                if self.recovery_required.as_ref() == Some(&request.operation_id) {
                    self.registry = self.host.recover_current_registry(request.now)?;
                }
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
    if checkpoint.revocation.is_some()
        || checkpoint.operation_id != request.operation_id
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
#[path = "owner_revocation_tests.rs"]
mod revocation_tests;

#[cfg(all(test, any(target_os = "linux", target_os = "macos")))]
#[path = "owner_reader_tests.rs"]
mod reader_tests;

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

    pub(super) struct TestDir(pub(super) PathBuf);

    impl TestDir {
        pub(super) fn new() -> Self {
            let id = NEXT_TEST_DIR.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "hepta-learning-artifact-service-{}-{id}",
                std::process::id()
            ));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).fixture("create service test dir");
            // The reader requires the same canonical root retained by the writer,
            // including temporary-directory aliases such as macOS /var.
            Self(path.canonicalize().fixture("canonical service test dir"))
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    pub(super) fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).fixture("stable id")
    }

    pub(super) fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    pub(super) fn key() -> SigningKey {
        SigningKey::from_bytes(&[9u8; 32])
    }

    pub(super) fn scope() -> DatasetWithdrawalScopeV1 {
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

    pub(super) fn trust(key: &SigningKey, scope_digest: Digest32) -> ArtifactOwnerTrustV1 {
        ArtifactOwnerTrustV1 {
            registry_id: id("learning-artifacts"),
            withdrawal_scope_digest: scope_digest,
            minimum_registry_generation: Generation::new(/*value*/ 1).fixture("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer(key)],
            head_signers: vec![signer(key)],
        }
    }

    pub(super) fn lease(key: &SigningKey, scope_digest: Digest32) -> SignedArtifactWriterLeaseV1 {
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

    pub(super) fn manifest() -> LearningArtifactManifestV2 {
        LearningArtifactManifestV2 {
            artifact_id: id("candidate"),
            kind: ArtifactKind::Model,
            generation: Generation::new(/*value*/ 1).fixture("generation"),
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

    pub(super) fn publish_request(
        key: &SigningKey,
        withdrawals: &DatasetWithdrawalRegistry,
        predecessor: Digest32,
        head: Digest32,
    ) -> LearningArtifactPublishRequestV1 {
        let admission = admit_manifest_at_withdrawal_head_v3(
            withdrawals,
            withdrawals.head_digest(),
            manifest(),
            /*now*/ 20,
        )
        .fixture("admission");
        let mut signed = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: withdrawals.scope_digest().fixture("scope digest"),
            binding: digest("binding"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("learning-artifacts"),
                generation: Generation::new(/*value*/ 1).fixture("generation"),
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
            /*now*/ 20,
        )
        .fixture("admission for head calculation");
        let mut staged = ArtifactRegistry::new();
        let preview = ArtifactPublicationTransactionV1::begin(
            id("operation"),
            admission,
            &withdrawals,
            &staged,
            predecessor,
            /*now*/ 20,
        )
        .fixture("preview");
        service
            .host
            .stage_compatibility_registration(&preview, &mut staged, /*now*/ 20)
            .fixture("preview registration");
        let request = publish_request(
            &key,
            &withdrawals,
            predecessor,
            staged.snapshot().head_digest,
        );

        service
            .host
            .acknowledgement_sync_fault
            .store(true, Ordering::Relaxed);
        assert!(matches!(
            service.publish(request.clone()),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::Indeterminate
            ))
        ));
        assert_eq!(
            service
                .host
                .recover_publication(&request.operation_id)
                .fixture("read uncertain acknowledgement")
                .fixture("acknowledgement exists")
                .checkpoint
                .phase,
            ArtifactPublicationPhaseV1::Acknowledged
        );
        assert!(matches!(
            service.current_registry_view(/*now*/ 20),
            Err(LearningArtifactOwnerServiceError::RecoveryRequired(operation_id))
                if operation_id == request.operation_id
        ));
        let mut mismatched_retry = request.clone();
        mismatched_retry.signed_current_head.binding = digest("foreign-binding");
        assert!(matches!(
            service.publish(mismatched_retry),
            Err(LearningArtifactOwnerServiceError::RequestMismatch)
        ));
        assert_eq!(service.recovery_required(), Some(&request.operation_id));
        assert!(matches!(
            service.current_registry_view(/*now*/ 20),
            Err(LearningArtifactOwnerServiceError::RecoveryRequired(operation_id))
                if operation_id == request.operation_id
        ));
        // An exact retry must actually sync existing ACK bytes; readable equality
        // alone cannot settle the uncertainty. Inject failure at that retry sync.
        service
            .host
            .acknowledgement_sync_fault
            .store(true, Ordering::Relaxed);
        assert!(matches!(
            service.publish(request.clone()),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::Indeterminate
            ))
        ));
        assert_eq!(service.recovery_required(), Some(&request.operation_id));
        let receipt = service
            .publish(request.clone())
            .fixture("reconcile and sync acknowledgement");
        assert_eq!(
            service.registry().snapshot().head_digest,
            receipt.registry_head_digest
        );
        let retry = service.publish(request.clone()).fixture("terminal retry");
        assert_eq!(retry, receipt);
        let current_view = service
            .current_registry_view(/*now*/ 20)
            .fixture("authenticated current registry view");
        assert_eq!(
            current_view.receipt().head_digest,
            receipt.registry_head_digest
        );
        assert!(!current_view.witness_digest().is_zero());
        assert!(!current_view.trust_digest().is_zero());
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
                .current_registry_view(/*now*/ 21)
                .fixture("reopened authenticated current view")
                .receipt()
                .head_digest,
            receipt.registry_head_digest
        );
    }

    #[test]
    fn current_view_is_fenced_until_unacknowledged_publication_is_reconciled() {
        let directory = TestDir::new();
        let key = key();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let scope_digest = withdrawals.scope_digest().fixture("scope digest");
        let config = LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&key, scope_digest),
            writer_lease: lease(&key, scope_digest),
            required_current_head: None,
            withdrawal_registry: withdrawals.clone(),
            storage_binding: digest("binding"),
            now: 20,
        };
        let service = LearningArtifactOwnerService::open(config.clone()).fixture("open service");
        let predecessor = service.registry().snapshot().head_digest;
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            /*now*/ 20,
        )
        .fixture("admission");
        let mut staged = service.registry().clone();
        let mut transaction = service
            .host
            .begin_publication(
                id("operation"),
                admission,
                &withdrawals,
                &staged,
                predecessor,
                /*now*/ 20,
            )
            .fixture("durable publication intent");
        service
            .host
            .stage_compatibility_registration(&transaction, &mut staged, /*now*/ 20)
            .fixture("stage registration");
        let request = publish_request(
            &key,
            &withdrawals,
            predecessor,
            staged.snapshot().head_digest,
        );
        service
            .host
            .ensure_payload_durable(&mut transaction, &staged, &request.payload, /*now*/ 20)
            .fixture("durable payload");
        service
            .host
            .ensure_registry_durable(
                &mut transaction,
                &staged,
                &withdrawals,
                digest("binding"),
                /*now*/ 20,
            )
            .fixture("durable registry");
        service
            .host
            .ensure_witness_durable(
                &mut transaction,
                &request.signed_current_head,
                &withdrawals,
                /*now*/ 20,
            )
            .fixture("durable CURRENT before acknowledgement");
        drop(service);

        let mut reopened = LearningArtifactOwnerService::open(config).fixture("reopen service");
        // CURRENT is authentic, but the durable operation still needs its ACK.
        reopened
            .host
            .current_registry_view(/*now*/ 20)
            .fixture("host CURRENT exists");
        assert!(matches!(
            reopened.current_registry_view(/*now*/ 20),
            Err(LearningArtifactOwnerServiceError::RecoveryRequired(operation_id))
                if operation_id == id("operation")
        ));
        reopened
            .publish(request)
            .fixture("reconcile exact publication");
        reopened
            .current_registry_view(/*now*/ 20)
            .fixture("CURRENT after reconciliation");
    }

    #[test]
    fn corrupt_checkpoint_reconciliation_keeps_current_use_and_restart_closed() {
        let directory = TestDir::new();
        let key = key();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
        let scope_digest = withdrawals.scope_digest().fixture("scope digest");
        let config = LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&key, scope_digest),
            writer_lease: lease(&key, scope_digest),
            required_current_head: None,
            withdrawal_registry: withdrawals.clone(),
            storage_binding: digest("binding"),
            now: 20,
        };
        let mut service =
            LearningArtifactOwnerService::open(config.clone()).fixture("open service");
        let predecessor = service.registry().snapshot().head_digest;
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            /*now*/ 20,
        )
        .fixture("admission");
        let mut staged = service.registry().clone();
        let transaction = service
            .host
            .begin_publication(
                id("operation"),
                admission,
                &withdrawals,
                &staged,
                predecessor,
                /*now*/ 20,
            )
            .fixture("durable prepared intent");
        service
            .host
            .stage_compatibility_registration(&transaction, &mut staged, /*now*/ 20)
            .fixture("stage registration");
        let request = publish_request(
            &key,
            &withdrawals,
            predecessor,
            staged.snapshot().head_digest,
        );
        let operation_digest = Digest32::of_bytes(request.operation_id.as_str().as_bytes());
        let checkpoint = directory
            .0
            .join("transactions")
            .join(format!("{operation_digest}-0.checkpoint"));
        let original = fs::read(&checkpoint).fixture("read prepared checkpoint");
        fs::write(&checkpoint, b"corrupt prepared checkpoint").fixture("inject corrupt write");
        assert!(matches!(
            service.publish(request.clone()),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::CheckpointMismatch
            ))
        ));
        assert_eq!(service.recovery_required(), Some(&id("operation")));
        assert!(matches!(
            service.current_registry_view(/*now*/ 20),
            Err(LearningArtifactOwnerServiceError::RecoveryRequired(operation_id))
                if operation_id == id("operation")
        ));
        drop(service);
        assert!(matches!(
            LearningArtifactOwnerService::open(config.clone()),
            Err(LearningArtifactOwnerServiceError::Host(
                ArtifactOwnerHostError::CheckpointMismatch
            ))
        ));
        // An independently retained exact checkpoint repairs the test fault;
        // startup still requires reconciliation instead of forgetting the intent.
        fs::write(checkpoint, original).fixture("restore exact fixture checkpoint");
        let mut reopened =
            LearningArtifactOwnerService::open(config).fixture("reopen repaired store");
        assert_eq!(reopened.recovery_required(), Some(&id("operation")));
        reopened
            .publish(request)
            .fixture("reconcile exact publication");
        reopened
            .current_registry_view(/*now*/ 20)
            .fixture("use reconciled CURRENT");
    }
}
