//! Named product writer service for the immutable learning-artifact store.
//!
//! Publications are serialized under the existing owner fence. Authentication
//! and deterministic request validation precede the first durable checkpoint.
//! A terminal retry is a receipt lookup, never permission to execute again.

use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;

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
use crate::validate_registry_head_witness;
use crate::verify_artifact_admission_v3;

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

/// An observation of this process, not a persisted qualification or authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactOwnerServiceStatusV1 {
    pub ready: bool,
    pub draining: bool,
    pub recovery_required: Option<StableId>,
    pub successful_requests: u64,
    pub rejected_requests: u64,
    pub terminal_replays: u64,
    pub authority: AuthorityPosture,
}

pub struct LearningArtifactOwnerService {
    host: LearningArtifactOwnerHost,
    withdrawal_registry: DatasetWithdrawalRegistry,
    registry: ArtifactRegistry,
    storage_binding: Digest32,
    recovery_required: Option<StableId>,
    trust: ArtifactOwnerTrustV1,
    lease: SignedArtifactWriterLeaseV1,
    last_now: u64,
    draining: bool,
    successful_requests: u64,
    rejected_requests: u64,
    terminal_replays: u64,
}

impl fmt::Debug for LearningArtifactOwnerService {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LearningArtifactOwnerService")
            .field("host", &self.host)
            .field("registry_head", &self.registry.snapshot().head_digest)
            .field("withdrawal_head", &self.withdrawal_registry.head_digest())
            .field("storage_binding", &self.storage_binding)
            .field("status_at_last_observed_time", &self.status(self.last_now))
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
        let trust = config.trust.clone();
        let lease = config.writer_lease.clone();
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
            trust,
            lease,
            last_now: config.now,
            draining: false,
            successful_requests: 0,
            rejected_requests: 0,
            terminal_replays: 0,
        })
    }

    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

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

    /// Process-local admission readiness. A transport must additionally check
    /// its authentication and independently supplied current-head freshness.
    /// `now` is supplied by the trusted host clock, never by a wire request.
    #[must_use]
    pub fn status(&self, now: u64) -> LearningArtifactOwnerServiceStatusV1 {
        let signer_live = self.trust.writer_signers.iter().any(|signer| {
            signer.signer_id == self.lease.signer_id
                && now <= signer.expires_at
                && signer.revoked_at.is_none_or(|at| now < at)
        });
        LearningArtifactOwnerServiceStatusV1 {
            ready: !self.draining
                && self.recovery_required.is_none()
                && now >= self.last_now
                && now >= self.lease.issued_at
                && now <= self.lease.expires_at
                && signer_live,
            draining: self.draining,
            recovery_required: self.recovery_required.clone(),
            successful_requests: self.successful_requests,
            rejected_requests: self.rejected_requests,
            terminal_replays: self.terminal_replays,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    /// Close admission while retaining the writer fence. Publication takes
    /// `&mut self`, so the host serializes drain after an in-flight call. Drop
    /// the drained service only after the transport has stopped admitting work.
    pub fn begin_shutdown(&mut self) {
        self.draining = true;
    }

    /// Install a same-scope monotonic prefix extension. Authentication and
    /// durable distribution of this frontier are host duties.
    pub fn install_withdrawal_frontier(
        &mut self,
        next: DatasetWithdrawalRegistry,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        if self.draining {
            return Err(LearningArtifactOwnerServiceError::ShuttingDown);
        }
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

    pub fn publish(
        &mut self,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        if self.draining {
            return Err(LearningArtifactOwnerServiceError::ShuttingDown);
        }
        if request.now < self.last_now {
            return Err(LearningArtifactOwnerServiceError::NonMonotonicTime);
        }
        self.last_now = request.now;
        if let Some(blocked) = &self.recovery_required
            && blocked != &request.operation_id
        {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(blocked.clone()));
        }
        let operation_id = request.operation_id.clone();
        match self.publish_inner(&request) {
            Ok(receipt) => {
                self.recovery_required = None;
                self.successful_requests = self.successful_requests.saturating_add(1);
                Ok(receipt)
            }
            Err(error) => {
                self.rejected_requests = self.rejected_requests.saturating_add(1);
                // A failed recovery read is itself an uncertainty fence. Do not
                // let `?` discard this guard and admit a different operation ID.
                match self.host.recover_publication(&operation_id) {
                    Ok(Some(recovery))
                        if recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged =>
                    {
                        self.recovery_required = Some(operation_id);
                    }
                    Err(recovery_error) => {
                        self.recovery_required = Some(operation_id);
                        return Err(recovery_error.into());
                    }
                    Ok(Some(_)) if matches!(
                        &error,
                        LearningArtifactOwnerServiceError::Host(ArtifactOwnerHostError::Indeterminate)
                            | LearningArtifactOwnerServiceError::Host(ArtifactOwnerHostError::Storage(
                                crate::ArtifactStorageError::Indeterminate
                            ))
                    ) => {
                        self.recovery_required = Some(operation_id);
                    }
                    Ok(Some(_)) | Ok(None) => {}
                }
                Err(error)
            }
        }
    }

    fn publish_inner(
        &mut self,
        request: &LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        let manifest = &request.admission.validated_manifest.manifest;
        if request.signed_current_head.binding != self.storage_binding
            || request.signed_current_head.witness.predecessor_head_digest
                != request.expected_registry_predecessor_head
            || request.signed_current_head.withdrawal_scope_digest
                != self.trust.withdrawal_scope_digest
            || request.admission.withdrawal_scope_digest != self.trust.withdrawal_scope_digest
            || request.payload.len() as u64 != manifest.encoded_size_bytes
            || request.payload.len() > 64 * 1024 * 1024
            || Digest32::of_bytes(&request.payload) != manifest.bytes_digest
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        // Validate the whole admission, not only caller-writable digest fields,
        // including for terminal receipt lookups after credential expiry.
        verify_artifact_admission_v3(
            &request.admission,
            request.admission.withdrawal_head_digest,
            request.admission.admitted_at,
        )
        .map_err(ArtifactPublicationError::from)?;

        let checkpoint = self.host.recover_publication(&request.operation_id)?;
        if let Some(recovery) = checkpoint.as_ref() {
            validate_request_against_checkpoint(request, &recovery.checkpoint)?;
            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                let at = recovery.checkpoint.acknowledged_at
                    .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
                let witness_digest = self.authenticate_head(request, at, true)?;
                if recovery.checkpoint.witness_receipt
                    .is_none_or(|receipt| receipt.witness_digest != witness_digest)
                    || recovery.checkpoint.registry_receipt.is_none_or(|receipt| {
                        receipt.head_digest != request.signed_current_head.witness.head_digest
                            || receipt.binding != self.storage_binding
                    })
                {
                    return Err(LearningArtifactOwnerServiceError::RequestMismatch);
                }
                if self.recovery_required.is_some() {
                    self.registry = self.host.recover_current_registry(request.now)?;
                }
                self.terminal_replays = self.terminal_replays.saturating_add(1);
                return receipt_from_checkpoint(&recovery.checkpoint);
            }
        } else if request.expected_registry_predecessor_head != self.registry.snapshot().head_digest {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }

        self.authenticate_head(request, request.now, false)?;
        if let Some(current) = self.host.discover_current_head(request.now)? {
            let witness = &request.signed_current_head.witness;
            if current.signed == request.signed_current_head {
                if checkpoint.is_none() {
                    return Err(LearningArtifactOwnerServiceError::RequestMismatch);
                }
            } else if current.signed.witness.head_digest != request.expected_registry_predecessor_head
                || witness.generation <= current.signed.witness.generation
                || witness.authority_epoch < current.signed.witness.authority_epoch
            {
                return Err(LearningArtifactOwnerServiceError::RequestMismatch);
            }
        }
        let predecessor = self.host.recover_registry_by_head(request.expected_registry_predecessor_head)?;
        let mut staged = predecessor.clone();
        // Pure preview: invalid content, signature, lineage or head must not
        // leave a Prepared checkpoint that blocks subsequent valid operations.
        let preview = ArtifactPublicationTransactionV1::begin(
            request.operation_id.clone(), request.admission.clone(),
            &self.withdrawal_registry, &predecessor,
            request.expected_registry_predecessor_head, request.now,
        )?;
        self.host.stage_compatibility_registration(&preview, &mut staged, request.now)?;
        if staged.snapshot().head_digest != request.signed_current_head.witness.head_digest {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        let mut transaction = match checkpoint {
            Some(recovery) => {
                let rebuilt = rebuild_transaction(preview, &staged, &self.withdrawal_registry,
                    request, &recovery.checkpoint)?;
                // Do not overwrite Prepared with the new lease's digest.
                self.host.resume_publication(rebuilt.snapshot(), request.now)?
            }
            None => self.host.begin_publication(
                request.operation_id.clone(), request.admission.clone(),
                &self.withdrawal_registry, &predecessor,
                request.expected_registry_predecessor_head, request.now,
            )?,
        };
        if transaction.phase() == ArtifactPublicationPhaseV1::Prepared {
            self.host.ensure_payload_durable(&mut transaction, &staged, &request.payload, request.now)?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::PayloadDurable {
            self.host.ensure_registry_durable(&mut transaction, &staged,
                &self.withdrawal_registry, self.storage_binding, request.now)?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::RegistryDurable {
            self.host.ensure_witness_durable(&mut transaction, &request.signed_current_head,
                &self.withdrawal_registry, request.now)?;
        }
        if transaction.phase() != ArtifactPublicationPhaseV1::WitnessDurable {
            return Err(LearningArtifactOwnerServiceError::UnexpectedPhase);
        }
        let receipt = self.host.acknowledge(&mut transaction, &self.withdrawal_registry, request.now)?;
        self.registry = staged;
        Ok(receipt)
    }

    fn authenticate_head(
        &self,
        request: &LearningArtifactPublishRequestV1,
        now: u64,
        historical: bool,
    ) -> Result<Digest32, LearningArtifactOwnerServiceError> {
        let signed = &request.signed_current_head;
        let witness = &signed.witness;
        let signer = self.trust.head_signers.iter()
            .find(|signer| signer.signer_id == witness.signer_id)
            .ok_or(LearningArtifactOwnerServiceError::RequestMismatch)?;
        if witness.registry_id != self.trust.registry_id
            || witness.signing_key_digest != Digest32::of_bytes(&signer.verifying_key)
            || witness.authority_epoch < signer.minimum_authority_epoch
            || witness.authority_epoch > signer.maximum_authority_epoch
            || witness.issued_at < signer.valid_from
            || witness.issued_at > signer.expires_at
            || signer.revoked_at.is_some_and(|at| witness.issued_at >= at)
            || (!historical && (now > signer.expires_at || signer.revoked_at.is_some_and(|at| now >= at)))
        {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        VerifyingKey::from_bytes(&signer.verifying_key)
            .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?
            .verify_strict(&signed.signing_bytes(), &Signature::from_bytes(&signed.signature))
            .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: self.trust.registry_id.clone(),
            minimum_generation: self.trust.minimum_registry_generation,
            expected_predecessor_head_digest: request.expected_registry_predecessor_head,
            minimum_authority_epoch: self.trust.minimum_authority_epoch,
            now,
        };
        Ok(validate_registry_head_witness(witness, &requirement)
            .map_err(|_| LearningArtifactOwnerServiceError::RequestMismatch)?.witness_digest)
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
        || checkpoint.expected_registry_predecessor_head != request.expected_registry_predecessor_head
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
    if phase_at_least(checkpoint.phase, ArtifactPublicationPhaseV1::RegistryDurable) {
        transaction.record_registry_durable(staged, checkpoint.registry_receipt
            .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?, withdrawals, request.now)?;
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
        transaction.record_witness_durable(witness, &requirement, checkpoint.witness_receipt
            .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?, withdrawals, request.now)?;
    }
    if transaction.state_digest() != checkpoint.state_digest {
        return Err(LearningArtifactOwnerServiceError::CheckpointMismatch);
    }
    Ok(transaction)
}

fn receipt_from_checkpoint(
    checkpoint: &ArtifactOwnerPublicationCheckpointV1,
) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
    let registry = checkpoint.registry_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    let witness = checkpoint.witness_receipt
        .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?;
    Ok(ArtifactPublicationReceiptV1 {
        operation_id: checkpoint.operation_id.clone(),
        admission_digest: checkpoint.admission_digest,
        registry_head_digest: registry.head_digest,
        witness_digest: witness.witness_digest,
        state_digest: checkpoint.state_digest,
        acknowledged_at: checkpoint.acknowledged_at
            .ok_or(LearningArtifactOwnerServiceError::CheckpointShape)?,
        authority: AuthorityPosture::DENY_ALL,
    })
}

const fn phase_at_least(actual: ArtifactPublicationPhaseV1, expected: ArtifactPublicationPhaseV1) -> bool {
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
    ShuttingDown,
    NonMonotonicTime,
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
