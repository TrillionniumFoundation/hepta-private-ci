//! Named product writer service for the immutable learning-artifact store.
//!
//! This is the single product caller of LearningArtifactOwnerHost. The service
//! serializes publications under one writer fence, owns the in-process artifact
//! registry and current withdrawal frontier, and blocks unrelated work while a
//! prior operation has a non-terminal durable checkpoint.

use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
#[cfg(test)]
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerHost;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

#[path = "owner/publication_recovery.rs"]
mod publication_recovery;
#[path = "owner/request_identity.rs"]
mod request_identity;

use publication_recovery::rebuild_transaction;
use publication_recovery::receipt_from_checkpoint;
use publication_recovery::validate_request_against_checkpoint;
use request_identity::RequestIdentityVerifier;

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
    request_identity: RequestIdentityVerifier,
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
        let request_identity = RequestIdentityVerifier::new(&config.trust);
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
        if let Some(current) = host.discover_current_head(config.now)?
            && current.signed.binding != config.storage_binding
        {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
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
            request_identity,
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
        let operation_id = request.operation_id.clone();
        let result = self.publish_inner(&request);
        match result {
            Ok(receipt) => {
                self.recovery_required = None;
                Ok(receipt)
            }
            Err(error) => {
                match self.host.recover_publication(&operation_id) {
                    Ok(Some(recovery))
                        if recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged =>
                    {
                        self.recovery_required = Some(operation_id);
                    }
                    Ok(_) => {}
                    Err(recovery_error) => {
                        // An unreadable checkpoint is uncertainty, never proof
                        // that a write did not happen. Fence reads and writes.
                        self.recovery_required = Some(operation_id);
                        return Err(recovery_error.into());
                    }
                }
                Err(error)
            }
        }
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

        // Validate the actual bytes and full admission before either returning
        // a cached terminal receipt or creating the Prepared checkpoint.
        self.request_identity.verify(request)?;
        let checkpoint = self.host.recover_publication(&request.operation_id)?;
        if let Some(recovery) = checkpoint.as_ref() {
            validate_request_against_checkpoint(request, &recovery.checkpoint)?;
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
#[path = "owner_service_tests.rs"]
mod tests;
