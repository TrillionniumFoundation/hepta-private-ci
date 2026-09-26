//! Named product writer service for the immutable learning-artifact store.
//!
//! Publications are serialized under one writer fence. Recovery and terminal
//! replay never grant selection, activation, promotion or release authority.

#[path = "owner/publication_recovery.rs"]
mod publication_recovery;

use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerHost;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;
use publication_recovery::rebuild_transaction;
use publication_recovery::receipt_from_checkpoint;
use publication_recovery::validate_request_against_checkpoint;
use publication_recovery::validate_request_identity;
use publication_recovery::verify_request_head;

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
    retry_trust: ArtifactOwnerTrustV1,
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
        let retry_trust = config.trust.clone();
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
            retry_trust,
        })
    }

    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

    /// Return an opaque, authenticated CURRENT view, not caller-supplied evidence.
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

    /// Install only an exact monotonic prefix extension in the same scope.
    /// Authentication and durable provisioning of this frontier remain host-owned.
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

    /// Exact terminal retries return historical receipts, never renewed eligibility.
    /// A replay error leaves mutation admission fenced until the exact operation
    /// can be reconciled, including when the checkpoint itself is unreadable.
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
        validate_request_identity(&request)?;
        let operation_id = request.operation_id.clone();
        match self.publish_inner(&request) {
            Ok(receipt) => {
                if receipt.authority != AuthorityPosture::DENY_ALL {
                    self.recovery_required = Some(operation_id);
                    return Err(LearningArtifactOwnerServiceError::RequestMismatch);
                }
                self.recovery_required = None;
                Ok(receipt)
            }
            Err(error) => {
                self.recovery_required = Some(operation_id.clone());
                match self.host.recover_publication(&operation_id) {
                    Ok(Some(recovery))
                        if recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged => {}
                    Ok(_) => self.recovery_required = None,
                    Err(recovery_error) => return Err(recovery_error.into()),
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
        let checkpoint = self.host.recover_publication(&request.operation_id)?;
        let historical = checkpoint.as_ref().is_some_and(|recovery| {
            recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged
        });
        let witness_digest = verify_request_head(&self.retry_trust, request, historical)?;
        if let Some(recovery) = checkpoint.as_ref() {
            validate_request_against_checkpoint(request, &recovery.checkpoint, witness_digest)?;
            if historical {
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
#[path = "owner/service_tests.rs"]
mod service_tests;

#[cfg(test)]
mod tests {
    #[test]
    fn named_owner_service_publishes_retries_and_reopens_from_current_head() {
        super::service_tests::assert_service_roundtrip();
    }
}
