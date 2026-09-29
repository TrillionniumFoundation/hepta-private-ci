//! Named product writer service for the immutable learning-artifact store.
//!
//! The service owns the in-process registry, durable withdrawal floor, durable
//! drain state, canonical request identity and one recovery-required fence.

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
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalRegistry;
use crate::LearningArtifactOwnerHost;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

#[path = "owner/durable_control.rs"]
mod durable_control;
#[path = "owner/durable_inputs.rs"]
mod durable_inputs;
#[path = "owner/durable_withdrawals.rs"]
mod durable_withdrawals;
#[path = "owner/operational_metrics.rs"]
mod operational_metrics;
#[path = "owner/publication_recovery.rs"]
mod publication_recovery;
#[path = "owner/request_identity.rs"]
mod request_identity;

use durable_control::DurableDrain;
use durable_inputs::verify_durable_inputs;
use durable_withdrawals::DurableWithdrawalFloor;
pub use operational_metrics::ArtifactOwnerBlockReasonV1;
pub use operational_metrics::ArtifactOwnerOperationalMetricsV1;
pub use operational_metrics::ArtifactOwnerOperationalSnapshotV1;
pub use operational_metrics::ArtifactOwnerStageSummaryV1;
pub use operational_metrics::ArtifactOwnerStageV1;
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
    root: PathBuf,
    durable_drain: DurableDrain,
    durable_withdrawals: DurableWithdrawalFloor,
    withdrawal_persistence_uncertain: bool,
    withdrawal_registry: DatasetWithdrawalRegistry,
    registry: ArtifactRegistry,
    storage_binding: Digest32,
    request_identity: RequestIdentityVerifier,
    recovery_required: Option<StableId>,
    draining: bool,
    drain_durable: bool,
    drain_persistence_uncertain: bool,
    operational_metrics: ArtifactOwnerOperationalMetricsV1,
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
            .field("withdrawal_persistence_uncertain", &self.withdrawal_persistence_uncertain)
            .field("draining", &self.draining)
            .field("drain_durable", &self.drain_durable)
            .field("drain_persistence_uncertain", &self.drain_persistence_uncertain)
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
        let operational_metrics = ArtifactOwnerOperationalMetricsV1::default();
        let _startup_timer = operational_metrics.start_stage(ArtifactOwnerStageV1::StartupRecoveryScan);
        let request_identity = RequestIdentityVerifier::new(&config.trust);
        let registry_id = config.trust.registry_id.clone();
        let scope = config.trust.withdrawal_scope_digest;
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
        let root = std::fs::canonicalize(&config.root)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        let durable_drain = DurableDrain::new(&root, &registry_id, scope, config.storage_binding);
        let draining = durable_drain
            .requested()
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        if draining {
            durable_drain
                .persist()
                .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
            operational_metrics.begin_drain();
        }
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
        if let Some(operation_id) = recovery_required.clone() {
            operational_metrics.mark_recovery_required(operation_id);
        }
        let durable_withdrawals =
            DurableWithdrawalFloor::new(&root, &registry_id, scope, config.storage_binding);
        durable_withdrawals
            .persist(&config.withdrawal_registry)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        Ok(Self {
            host,
            root,
            durable_drain,
            durable_withdrawals,
            withdrawal_persistence_uncertain: false,
            withdrawal_registry: config.withdrawal_registry,
            registry,
            storage_binding: config.storage_binding,
            request_identity,
            recovery_required,
            draining,
            drain_durable: draining,
            drain_persistence_uncertain: false,
            operational_metrics,
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
        let _timer = self
            .operational_metrics
            .start_stage(ArtifactOwnerStageV1::PinnedAcquire);
        let result = (|| {
            self.require_durable_withdrawals()?;
            if let Some(operation_id) = &self.recovery_required {
                return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                    operation_id.clone(),
                ));
            }
            Ok(self.host.current_registry_view(now)?)
        })();
        if let Err(error) = &result {
            self.record_error(error);
        }
        result
    }

    #[must_use]
    pub fn withdrawal_registry(&self) -> &DatasetWithdrawalRegistry {
        &self.withdrawal_registry
    }

    #[must_use]
    pub fn recovery_required(&self) -> Option<&StableId> {
        self.recovery_required.as_ref()
    }

    #[must_use]
    pub fn operational_metrics(&self) -> ArtifactOwnerOperationalSnapshotV1 {
        self.operational_metrics.snapshot()
    }

    #[must_use]
    pub fn operational_metrics_handle(&self) -> ArtifactOwnerOperationalMetricsV1 {
        self.operational_metrics.clone()
    }

    pub fn begin_drain(&mut self) {
        self.draining = true;
        self.operational_metrics.begin_drain();
    }

    pub fn begin_drain_durable(&mut self) -> Result<(), LearningArtifactOwnerServiceError> {
        self.begin_drain();
        self.drain_persistence_uncertain = true;
        let result = {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::CheckpointPersist);
            self.durable_drain.persist()
        };
        if let Err(error) = result {
            let service_error = LearningArtifactOwnerServiceError::ControlIo(error);
            self.record_error(&service_error);
            return Err(service_error);
        }
        self.drain_durable = true;
        self.drain_persistence_uncertain = false;
        Ok(())
    }

    #[must_use]
    pub fn durable_drain_requested(&self) -> bool {
        self.drain_durable && !self.drain_persistence_uncertain
    }

    #[must_use]
    pub fn is_drained(&self) -> bool {
        self.draining
            && !self.drain_persistence_uncertain
            && !self.withdrawal_persistence_uncertain
            && self.recovery_required.is_none()
    }

    pub fn install_withdrawal_frontier(
        &mut self,
        next: DatasetWithdrawalRegistry,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        if next.scope_digest() != self.withdrawal_registry.scope_digest() {
            let error = LearningArtifactOwnerServiceError::WithdrawalFrontierConflict;
            self.record_error(&error);
            return Err(error);
        }
        let current = self.withdrawal_registry.snapshot();
        let next_snapshot = next.snapshot();
        if next_snapshot.records().len() < current.records().len()
            || &next_snapshot.records()[..current.records().len()] != current.records()
        {
            let error = LearningArtifactOwnerServiceError::WithdrawalFrontierConflict;
            self.record_error(&error);
            return Err(error);
        }
        self.withdrawal_registry = next;
        self.withdrawal_persistence_uncertain = true;
        let result = {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::CheckpointPersist);
            self.durable_withdrawals.persist(&self.withdrawal_registry)
        };
        if let Err(error) = result {
            let service_error = LearningArtifactOwnerServiceError::ControlIo(error);
            self.record_error(&service_error);
            return Err(service_error);
        }
        self.withdrawal_persistence_uncertain = false;
        self.operational_metrics.clear_withdrawal_block();
        Ok(())
    }

    #[must_use]
    pub fn withdrawal_frontier_is_durable(&self) -> bool {
        !self.withdrawal_persistence_uncertain
    }

    fn require_durable_withdrawals(&self) -> Result<(), LearningArtifactOwnerServiceError> {
        if self.withdrawal_persistence_uncertain {
            return Err(LearningArtifactOwnerServiceError::WithdrawalDurabilityUnknown);
        }
        Ok(())
    }

    pub fn publish(
        &mut self,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        if let Err(error) = self.require_durable_withdrawals() {
            self.record_error(&error);
            return Err(error);
        }
        if let Some(blocked) = &self.recovery_required
            && blocked != &request.operation_id
        {
            let error = LearningArtifactOwnerServiceError::RecoveryRequired(blocked.clone());
            self.record_error(&error);
            return Err(error);
        }
        let operation_id = request.operation_id.clone();
        let result = self.publish_inner(&request);
        match result {
            Ok(receipt) => {
                self.recovery_required = None;
                self.operational_metrics.clear_recovery_required();
                Ok(receipt)
            }
            Err(error) => {
                match self.host.recover_publication(&operation_id) {
                    Ok(Some(recovery))
                        if recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged =>
                    {
                        self.recovery_required = Some(operation_id.clone());
                        self.operational_metrics.mark_recovery_required(operation_id);
                    }
                    Ok(_) => {}
                    Err(recovery_error) => {
                        self.recovery_required = Some(operation_id.clone());
                        self.operational_metrics.mark_recovery_required(operation_id);
                        self.operational_metrics.record_recovery_failure();
                        let service_error = LearningArtifactOwnerServiceError::from(recovery_error);
                        self.record_error(&service_error);
                        return Err(service_error);
                    }
                }
                self.record_error(&error);
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
            return Err(LearningArtifactOwnerServiceError::IdentityConflict);
        }
        {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::RequestIdentityAndPayloadHash);
            self.request_identity.verify(request)?;
        }
        let checkpoint = {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::RecoveryReconciliation);
            self.host.recover_publication(&request.operation_id)?
        };
        if let Some(recovery) = checkpoint.as_ref() {
            validate_request_against_checkpoint(request, &recovery.checkpoint)?;
            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                return receipt_from_checkpoint(&recovery.checkpoint);
            }
        }
        if request.admission.validated_manifest.manifest.predecessor_ids.len() > 1 {
            return Err(LearningArtifactOwnerServiceError::IdentityConflict);
        }
        if self.draining && checkpoint.is_none() {
            return Err(LearningArtifactOwnerServiceError::Draining);
        }
        if checkpoint.is_none() {
            let current = self.host.recover_current_registry(request.now)?;
            if current.snapshot().head_digest != request.expected_registry_predecessor_head {
                return Err(LearningArtifactOwnerServiceError::StaleOwner);
            }
        }
        let predecessor = self
            .host
            .recover_registry_by_head(request.expected_registry_predecessor_head)?;
        let mut staged = predecessor.clone();
        let preview = ArtifactPublicationTransactionV1::begin(
            request.operation_id.clone(),
            request.admission.clone(),
            &self.withdrawal_registry,
            &predecessor,
            request.expected_registry_predecessor_head,
            request.now,
        )?;
        self.host
            .stage_compatibility_registration(&preview, &mut staged, request.now)?;
        if staged.snapshot().head_digest != request.signed_current_head.witness.head_digest {
            return Err(LearningArtifactOwnerServiceError::IdentityConflict);
        }
        if let Some(recovery) = checkpoint.as_ref() {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::RecoveryReconciliation);
            verify_durable_inputs(&self.root, &staged, request, &recovery.checkpoint)?;
        }
        let mut transaction = {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::CheckpointPersist);
            self.host.begin_publication(
                request.operation_id.clone(),
                request.admission.clone(),
                &self.withdrawal_registry,
                &predecessor,
                request.expected_registry_predecessor_head,
                request.now,
            )?
        };
        if let Some(recovery) = checkpoint {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::RecoveryReconciliation);
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
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::PayloadWriteAndSync);
            self.host.ensure_payload_durable(
                &mut transaction,
                &staged,
                &request.payload,
                request.now,
            )?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::PayloadDurable {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::RegistrySnapshotAndSync);
            self.host.ensure_registry_durable(
                &mut transaction,
                &staged,
                &self.withdrawal_registry,
                self.storage_binding,
                request.now,
            )?;
        }
        if transaction.phase() == ArtifactPublicationPhaseV1::RegistryDurable {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::CurrentSwitchAndSync);
            self.host.ensure_witness_durable(
                &mut transaction,
                &request.signed_current_head,
                &self.withdrawal_registry,
                request.now,
            )?;
        }
        let receipt = if transaction.phase() == ArtifactPublicationPhaseV1::WitnessDurable {
            let _timer = self
                .operational_metrics
                .start_stage(ArtifactOwnerStageV1::CheckpointPersist);
            self.host
                .acknowledge(&mut transaction, &self.withdrawal_registry, request.now)?
        } else {
            return Err(LearningArtifactOwnerServiceError::UnexpectedPhase);
        };
        self.registry = staged;
        Ok(receipt)
    }

    fn record_error(&self, error: &LearningArtifactOwnerServiceError) {
        let reason = match error.code() {
            LearningArtifactOwnerServiceErrorCodeV1::IdentityConflict => {
                ArtifactOwnerBlockReasonV1::IdentityConflict
            }
            LearningArtifactOwnerServiceErrorCodeV1::StaleOwner => {
                self.operational_metrics.record_owner_epoch_conflict();
                ArtifactOwnerBlockReasonV1::StaleOwner
            }
            LearningArtifactOwnerServiceErrorCodeV1::WithdrawalFrontierInsufficient => {
                self.operational_metrics.record_withdrawal_epoch_conflict();
                self.operational_metrics.mark_withdrawal_block();
                ArtifactOwnerBlockReasonV1::WithdrawalFrontierInsufficient
            }
            LearningArtifactOwnerServiceErrorCodeV1::PersistenceUnknown => {
                self.operational_metrics.mark_withdrawal_block();
                ArtifactOwnerBlockReasonV1::PersistenceUnknown
            }
            LearningArtifactOwnerServiceErrorCodeV1::CapacityExceeded => {
                ArtifactOwnerBlockReasonV1::CapacityExceeded
            }
            LearningArtifactOwnerServiceErrorCodeV1::RecoveryRequired => {
                ArtifactOwnerBlockReasonV1::RecoveryRequired
            }
            LearningArtifactOwnerServiceErrorCodeV1::Draining => {
                ArtifactOwnerBlockReasonV1::Draining
            }
            LearningArtifactOwnerServiceErrorCodeV1::WriterBusy => {
                ArtifactOwnerBlockReasonV1::WriterBusy
            }
            LearningArtifactOwnerServiceErrorCodeV1::InvalidConfiguration
            | LearningArtifactOwnerServiceErrorCodeV1::CorruptState
            | LearningArtifactOwnerServiceErrorCodeV1::Internal => return,
        };
        self.operational_metrics.record_block(reason);
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningArtifactOwnerServiceErrorCodeV1 {
    IdentityConflict,
    StaleOwner,
    WithdrawalFrontierInsufficient,
    PersistenceUnknown,
    CapacityExceeded,
    RecoveryRequired,
    Draining,
    WriterBusy,
    InvalidConfiguration,
    CorruptState,
    Internal,
}

impl LearningArtifactOwnerServiceErrorCodeV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::IdentityConflict => "identity_conflict",
            Self::StaleOwner => "stale_owner",
            Self::WithdrawalFrontierInsufficient => "withdrawal_frontier_insufficient",
            Self::PersistenceUnknown => "persistence_unknown",
            Self::CapacityExceeded => "capacity_exceeded",
            Self::RecoveryRequired => "recovery_required",
            Self::Draining => "draining",
            Self::WriterBusy => "writer_busy",
            Self::InvalidConfiguration => "invalid_configuration",
            Self::CorruptState => "corrupt_state",
            Self::Internal => "internal",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningArtifactOwnerRetryClassV1 {
    Never,
    ExactOperationOnly,
    AfterReauthorization,
    AfterWithdrawalAdvance,
    AfterReconciliation,
    AfterCapacityReleased,
    AfterContention,
}

#[derive(Debug)]
pub enum LearningArtifactOwnerServiceError {
    Host(ArtifactOwnerHostError),
    Publication(ArtifactPublicationError),
    ControlIo(std::io::Error),
    InvalidConfiguration,
    WithdrawalFrontierConflict,
    WithdrawalDurabilityUnknown,
    RecoveryConflict,
    RecoveryRequired(StableId),
    RequestMismatch,
    IdentityConflict,
    StaleOwner,
    CapacityExceeded,
    CheckpointShape,
    CheckpointMismatch,
    UnexpectedPhase,
    Draining,
}

impl LearningArtifactOwnerServiceError {
    #[must_use]
    pub fn code(&self) -> LearningArtifactOwnerServiceErrorCodeV1 {
        match self {
            Self::RequestMismatch | Self::IdentityConflict => {
                LearningArtifactOwnerServiceErrorCodeV1::IdentityConflict
            }
            Self::StaleOwner
            | Self::Host(
                ArtifactOwnerHostError::UnknownSigner
                | ArtifactOwnerHostError::SignerContext
                | ArtifactOwnerHostError::SignerRevoked
                | ArtifactOwnerHostError::WriterLeaseContext
                | ArtifactOwnerHostError::CurrentHeadExpired
                | ArtifactOwnerHostError::CurrentHeadRollback,
            ) => LearningArtifactOwnerServiceErrorCodeV1::StaleOwner,
            Self::WithdrawalFrontierConflict => {
                LearningArtifactOwnerServiceErrorCodeV1::WithdrawalFrontierInsufficient
            }
            Self::WithdrawalDurabilityUnknown
            | Self::ControlIo(_)
            | Self::Host(ArtifactOwnerHostError::Indeterminate) => {
                LearningArtifactOwnerServiceErrorCodeV1::PersistenceUnknown
            }
            Self::CapacityExceeded | Self::Host(ArtifactOwnerHostError::Capacity) => {
                LearningArtifactOwnerServiceErrorCodeV1::CapacityExceeded
            }
            Self::RecoveryRequired(_) => LearningArtifactOwnerServiceErrorCodeV1::RecoveryRequired,
            Self::Draining => LearningArtifactOwnerServiceErrorCodeV1::Draining,
            Self::Host(ArtifactOwnerHostError::WriterFenceBusy) => {
                LearningArtifactOwnerServiceErrorCodeV1::WriterBusy
            }
            Self::InvalidConfiguration => {
                LearningArtifactOwnerServiceErrorCodeV1::InvalidConfiguration
            }
            Self::RecoveryConflict
            | Self::CheckpointShape
            | Self::CheckpointMismatch
            | Self::UnexpectedPhase
            | Self::Host(
                ArtifactOwnerHostError::CheckpointMissing
                | ArtifactOwnerHostError::CheckpointGap
                | ArtifactOwnerHostError::CheckpointMismatch
                | ArtifactOwnerHostError::CurrentHeadFork,
            ) => LearningArtifactOwnerServiceErrorCodeV1::CorruptState,
            Self::Host(_)
            | Self::Publication(_) => LearningArtifactOwnerServiceErrorCodeV1::Internal,
        }
    }

    #[must_use]
    pub fn retry_class(&self) -> LearningArtifactOwnerRetryClassV1 {
        match self.code() {
            LearningArtifactOwnerServiceErrorCodeV1::IdentityConflict
            | LearningArtifactOwnerServiceErrorCodeV1::InvalidConfiguration
            | LearningArtifactOwnerServiceErrorCodeV1::CorruptState
            | LearningArtifactOwnerServiceErrorCodeV1::Internal => {
                LearningArtifactOwnerRetryClassV1::Never
            }
            LearningArtifactOwnerServiceErrorCodeV1::StaleOwner => {
                LearningArtifactOwnerRetryClassV1::AfterReauthorization
            }
            LearningArtifactOwnerServiceErrorCodeV1::WithdrawalFrontierInsufficient => {
                LearningArtifactOwnerRetryClassV1::AfterWithdrawalAdvance
            }
            LearningArtifactOwnerServiceErrorCodeV1::PersistenceUnknown => {
                LearningArtifactOwnerRetryClassV1::AfterReconciliation
            }
            LearningArtifactOwnerServiceErrorCodeV1::CapacityExceeded => {
                LearningArtifactOwnerRetryClassV1::AfterCapacityReleased
            }
            LearningArtifactOwnerServiceErrorCodeV1::RecoveryRequired
            | LearningArtifactOwnerServiceErrorCodeV1::Draining => {
                LearningArtifactOwnerRetryClassV1::ExactOperationOnly
            }
            LearningArtifactOwnerServiceErrorCodeV1::WriterBusy => {
                LearningArtifactOwnerRetryClassV1::AfterContention
            }
        }
    }
}

impl fmt::Display for LearningArtifactOwnerServiceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}: {self:?}", self.code().as_str())
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

#[cfg(all(test, unix))]
#[path = "owner/withdrawal_service_tests.rs"]
mod withdrawal_tests;
