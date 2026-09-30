//! Narrow durable publication port used by [`LearningArtifactOwnerService`].
//!
//! The service coordinates request identity and the publication state machine;
//! it does not know filesystem layout, checkpoint filenames, or sync ordering.
//! Implementations must hold one exclusive writer fence for their full lifetime,
//! persist every returned phase before reporting success, and fail closed on an
//! indeterminate effect.

use std::fmt;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerPublicationCheckpointV1;
use crate::ArtifactOwnerRecoveryV1;
use crate::ArtifactOwnerVerifierV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionSnapshotV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerHost;
use crate::RegistryAppendReceipt;
use crate::RegistryHeadWitnessReceipt;
use crate::RegistrySnapshotReceipt;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

use super::LearningArtifactOwnerServiceConfigV1;
use super::LearningArtifactOwnerServiceError;
use super::LearningArtifactPublishRequestV1;
use super::durable_inputs::verify_durable_inputs;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerPublicationStoreIdentityV1 {
    root: PathBuf,
    registry_id: StableId,
    withdrawal_scope_digest: Digest32,
    trust_digest: Digest32,
}

impl OwnerPublicationStoreIdentityV1 {
    #[must_use]
    pub fn root(&self) -> &std::path::Path {
        &self.root
    }

    #[must_use]
    pub fn registry_id(&self) -> &StableId {
        &self.registry_id
    }

    #[must_use]
    pub const fn withdrawal_scope_digest(&self) -> Digest32 {
        self.withdrawal_scope_digest
    }

    #[must_use]
    pub const fn trust_digest(&self) -> Digest32 {
        self.trust_digest
    }
}

/// Injectable persistence/recovery boundary for one artifact owner.
///
/// Supplying an implementation grants no selection, activation, or release
/// authority. `open_with_stores` verifies this immutable identity against the
/// independently supplied trust/configuration before any request is admitted.
pub trait OwnerPublicationStoreV1: Send {
    fn identity(&self) -> &OwnerPublicationStoreIdentityV1;

    fn discover_current_head(
        &self,
        now: u64,
    ) -> Result<Option<VerifiedCurrentArtifactHeadV1>, ArtifactOwnerHostError>;

    fn recover_current_registry(
        &self,
        now: u64,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError>;

    fn recovery_required_operations(
        &self,
    ) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError>;

    fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError>;

    fn recover_publication(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<ArtifactOwnerRecoveryV1>, ArtifactOwnerHostError>;

    fn recover_registry_by_head(
        &self,
        head_digest: Digest32,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError>;

    fn stage_compatibility_registration(
        &self,
        transaction: &ArtifactPublicationTransactionV1,
        registry: &mut ArtifactRegistry,
        now: u64,
    ) -> Result<RegistryAppendReceipt, ArtifactOwnerHostError>;

    fn begin_publication(
        &self,
        operation_id: StableId,
        admission: WithdrawalBoundArtifactAdmissionV3,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        registry: &ArtifactRegistry,
        expected_registry_predecessor_head: Digest32,
        now: u64,
    ) -> Result<ArtifactPublicationTransactionV1, ArtifactOwnerHostError>;

    fn verify_recovery_inputs(
        &self,
        staged: &ArtifactRegistry,
        request: &LearningArtifactPublishRequestV1,
        checkpoint: &ArtifactOwnerPublicationCheckpointV1,
    ) -> Result<(), LearningArtifactOwnerServiceError>;

    fn resume_publication(
        &self,
        snapshot: ArtifactPublicationTransactionSnapshotV1,
        now: u64,
    ) -> Result<ArtifactPublicationTransactionV1, ArtifactOwnerHostError>;

    fn ensure_payload_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        staged_registry: &ArtifactRegistry,
        bytes: &[u8],
        now: u64,
    ) -> Result<PathBuf, ArtifactOwnerHostError>;

    fn ensure_registry_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        registry: &ArtifactRegistry,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        binding: Digest32,
        now: u64,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError>;

    fn ensure_witness_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        signed: &SignedCurrentArtifactHeadV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<RegistryHeadWitnessReceipt, ArtifactOwnerHostError>;

    fn acknowledge(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<ArtifactPublicationReceiptV1, ArtifactOwnerHostError>;
}

/// Filesystem-backed adapter over the reviewed fenced owner host.
pub struct FsOwnerPublicationStoreV1 {
    identity: OwnerPublicationStoreIdentityV1,
    host: LearningArtifactOwnerHost,
}

impl fmt::Debug for FsOwnerPublicationStoreV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FsOwnerPublicationStoreV1")
            .field("identity", &self.identity)
            .field("host", &self.host)
            .finish()
    }
}

impl FsOwnerPublicationStoreV1 {
    pub fn open(
        config: &LearningArtifactOwnerServiceConfigV1,
    ) -> Result<Self, LearningArtifactOwnerServiceError> {
        let registry_id = config.trust.registry_id.clone();
        let withdrawal_scope_digest = config.trust.withdrawal_scope_digest;
        let host = match config.required_current_head.clone() {
            Some(current) => LearningArtifactOwnerHost::open_with_required_current_head(
                &config.root,
                config.trust.clone(),
                config.writer_lease.clone(),
                current,
                config.now,
            )?,
            None => LearningArtifactOwnerHost::open(
                &config.root,
                config.trust.clone(),
                config.writer_lease.clone(),
                config.now,
            )?,
        };
        let root = std::fs::canonicalize(&config.root)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        let trust_digest = host.trust_digest();
        // Recompute once at this adapter boundary so an implementation cannot
        // claim an identity unrelated to the supplied trust object.
        if ArtifactOwnerVerifierV1::new(config.trust.clone())?.trust_digest() != trust_digest {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        Ok(Self {
            identity: OwnerPublicationStoreIdentityV1 {
                root,
                registry_id,
                withdrawal_scope_digest,
                trust_digest,
            },
            host,
        })
    }
}

impl OwnerPublicationStoreV1 for FsOwnerPublicationStoreV1 {
    fn identity(&self) -> &OwnerPublicationStoreIdentityV1 {
        &self.identity
    }

    fn discover_current_head(
        &self,
        now: u64,
    ) -> Result<Option<VerifiedCurrentArtifactHeadV1>, ArtifactOwnerHostError> {
        self.host.discover_current_head(now)
    }

    fn recover_current_registry(
        &self,
        now: u64,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError> {
        self.host.recover_current_registry(now)
    }

    fn recovery_required_operations(
        &self,
    ) -> Result<Vec<ArtifactOwnerPublicationCheckpointV1>, ArtifactOwnerHostError> {
        self.host.recovery_required_operations()
    }

    fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, ArtifactOwnerHostError> {
        self.host.current_registry_view(now)
    }

    fn recover_publication(
        &self,
        operation_id: &StableId,
    ) -> Result<Option<ArtifactOwnerRecoveryV1>, ArtifactOwnerHostError> {
        self.host.recover_publication(operation_id)
    }

    fn recover_registry_by_head(
        &self,
        head_digest: Digest32,
    ) -> Result<ArtifactRegistry, ArtifactOwnerHostError> {
        self.host.recover_registry_by_head(head_digest)
    }

    fn stage_compatibility_registration(
        &self,
        transaction: &ArtifactPublicationTransactionV1,
        registry: &mut ArtifactRegistry,
        now: u64,
    ) -> Result<RegistryAppendReceipt, ArtifactOwnerHostError> {
        self.host
            .stage_compatibility_registration(transaction, registry, now)
    }

    fn begin_publication(
        &self,
        operation_id: StableId,
        admission: WithdrawalBoundArtifactAdmissionV3,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        registry: &ArtifactRegistry,
        expected_registry_predecessor_head: Digest32,
        now: u64,
    ) -> Result<ArtifactPublicationTransactionV1, ArtifactOwnerHostError> {
        self.host.begin_publication(
            operation_id,
            admission,
            withdrawal_registry,
            registry,
            expected_registry_predecessor_head,
            now,
        )
    }

    fn verify_recovery_inputs(
        &self,
        staged: &ArtifactRegistry,
        request: &LearningArtifactPublishRequestV1,
        checkpoint: &ArtifactOwnerPublicationCheckpointV1,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        verify_durable_inputs(self.identity.root(), staged, request, checkpoint)
    }

    fn resume_publication(
        &self,
        snapshot: ArtifactPublicationTransactionSnapshotV1,
        now: u64,
    ) -> Result<ArtifactPublicationTransactionV1, ArtifactOwnerHostError> {
        self.host.resume_publication(snapshot, now)
    }

    fn ensure_payload_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        staged_registry: &ArtifactRegistry,
        bytes: &[u8],
        now: u64,
    ) -> Result<PathBuf, ArtifactOwnerHostError> {
        self.host
            .ensure_payload_durable(transaction, staged_registry, bytes, now)
    }

    fn ensure_registry_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        registry: &ArtifactRegistry,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        binding: Digest32,
        now: u64,
    ) -> Result<RegistrySnapshotReceipt, ArtifactOwnerHostError> {
        self.host.ensure_registry_durable(
            transaction,
            registry,
            withdrawal_registry,
            binding,
            now,
        )
    }

    fn ensure_witness_durable(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        signed: &SignedCurrentArtifactHeadV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<RegistryHeadWitnessReceipt, ArtifactOwnerHostError> {
        self.host
            .ensure_witness_durable(transaction, signed, withdrawal_registry, now)
    }

    fn acknowledge(
        &self,
        transaction: &mut ArtifactPublicationTransactionV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        now: u64,
    ) -> Result<ArtifactPublicationReceiptV1, ArtifactOwnerHostError> {
        self.host
            .acknowledge(transaction, withdrawal_registry, now)
    }
}
