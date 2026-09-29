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
#[path = "owner/durable_request_identity.rs"]
mod durable_request_identity;
#[path = "owner/durable_withdrawals.rs"]
mod durable_withdrawals;
#[path = "owner/publication_recovery.rs"]
mod publication_recovery;
#[path = "owner/request_identity.rs"]
mod request_identity;

use durable_control::DurableDrain;
use durable_inputs::verify_durable_inputs;
use durable_request_identity::DurableRequestIdentity;
use durable_request_identity::DurableRequestIdentityError;
use durable_withdrawals::DurableWithdrawalFloor;
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningArtifactOwnerOperationalStateV1 {
    pub registry_head_digest: Digest32,
    pub registry_records: usize,
    pub withdrawal_head_digest: Digest32,
    pub withdrawal_records: usize,
    pub recovery_operation_id: Option<StableId>,
    pub recovery_observed_age_seconds: Option<u64>,
    pub draining: bool,
    pub durable_drain: bool,
    pub drain_observed_age_seconds: Option<u64>,
    pub withdrawal_frontier_durable: bool,
    pub request_identity_persistence_unknown: bool,
}

pub struct LearningArtifactOwnerService {
    host: LearningArtifactOwnerHost,
    root: PathBuf,
    durable_drain: DurableDrain,
    durable_request_identities: DurableRequestIdentity,
    durable_withdrawals: DurableWithdrawalFloor,
    withdrawal_persistence_uncertain: bool,
    withdrawal_registry: DatasetWithdrawalRegistry,
    registry: ArtifactRegistry,
    storage_binding: Digest32,
    request_identity: RequestIdentityVerifier,
    identity_persistence_uncertain: Option<StableId>,
    recovery_required: Option<StableId>,
    recovery_observed_at: Option<u64>,
    draining: bool,
    drain_durable: bool,
    drain_persistence_uncertain: bool,
    drain_observed_at: Option<u64>,
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
            .field("recovery_observed_at", &self.recovery_observed_at)
            .field(
                "identity_persistence_uncertain",
                &self.identity_persistence_uncertain,
            )
            .field(
                "withdrawal_persistence_uncertain",
                &self.withdrawal_persistence_uncertain,
            )
            .field("draining", &self.draining)
            .field("drain_durable", &self.drain_durable)
            .field("drain_observed_at", &self.drain_observed_at)
            .field(
                "drain_persistence_uncertain",
                &self.drain_persistence_uncertain,
            )
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
            // Existing bytes may come from a write whose sync outcome was unknown.
            // Re-establish durability under the retained writer fence on reopen.
            durable_drain
                .persist()
                .map_err(|_| LearningArtifactOwnerServiceError::PersistenceUnknown)?;
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
        let durable_request_identities =
            DurableRequestIdentity::new(&root, &registry_id, scope, config.storage_binding);
        let durable_withdrawals =
            DurableWithdrawalFloor::new(&root, &registry_id, scope, config.storage_binding);
        // The writer fence is already held. Stored bytes may only constrain
        // (never replace) the independently authenticated startup frontier.
        durable_withdrawals
            .persist(&config.withdrawal_registry)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        Ok(Self {
            host,
            root,
            durable_drain,
            durable_request_identities,
            durable_withdrawals,
            withdrawal_persistence_uncertain: false,
            withdrawal_registry: config.withdrawal_registry,
            registry,
            storage_binding: config.storage_binding,
            request_identity,
            identity_persistence_uncertain: None,
            recovery_observed_at: recovery_required.as_ref().map(|_| config.now),
            recovery_required,
            draining,
            drain_durable: draining,
            drain_persistence_uncertain: false,
            drain_observed_at: draining.then_some(config.now),
        })
    }

    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

    /// Return the exact authenticated CURRENT registry view for read-only
    /// product consumers. Current-head discovery, signature validation and
    /// snapshot binding remain owned by the fenced artifact owner.
    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, LearningArtifactOwnerServiceError> {
        self.require_durable_withdrawals()?;
        if self.identity_persistence_uncertain.is_some() {
            return Err(LearningArtifactOwnerServiceError::PersistenceUnknown);
        }
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

    #[must_use]
    pub fn operational_state(&self, now: u64) -> LearningArtifactOwnerOperationalStateV1 {
        let registry = self.registry.snapshot();
        let withdrawals = self.withdrawal_registry.snapshot();
        LearningArtifactOwnerOperationalStateV1 {
            registry_head_digest: registry.head_digest,
            registry_records: self.registry.records().len(),
            withdrawal_head_digest: withdrawals.head_digest,
            withdrawal_records: withdrawals.records().len(),
            recovery_operation_id: self.recovery_required.clone(),
            recovery_observed_age_seconds: self
                .recovery_observed_at
                .map(|started| now.saturating_sub(started)),
            draining: self.draining,
            durable_drain: self.durable_drain_requested(),
            drain_observed_age_seconds: self
                .drain_observed_at
                .map(|started| now.saturating_sub(started)),
            withdrawal_frontier_durable: self.withdrawal_frontier_is_durable(),
            request_identity_persistence_unknown: self.identity_persistence_uncertain.is_some(),
        }
    }

    /// Stop admitting new publications for this process lifetime.
    ///
    /// Exact terminal retries and reconciliation of an existing operation remain
    /// available. Use begin_drain_durable_at before acknowledging an operator
    /// stop that must survive restart. Neither method releases the writer fence.
    pub fn begin_drain(&mut self) {
        self.begin_drain_at(0);
    }

    pub fn begin_drain_at(&mut self, now: u64) {
        self.draining = true;
        if now != 0 && self.drain_observed_at.is_none() {
            self.drain_observed_at = Some(now);
        }
    }

    /// Durably stop new admission, including after reopening this store.
    pub fn begin_drain_durable(&mut self) -> Result<(), LearningArtifactOwnerServiceError> {
        self.begin_drain_durable_at(0)
    }

    /// Requires the embedding host's action authorization. The local marker is
    /// create-only, scope-bound and synced with its containing directories. An
    /// I/O error keeps admission closed and cannot become successful drain.
    /// No online clear/resume API exists. Restoring a pre-stop backup still
    /// requires an independently retained operator stop floor.
    pub fn begin_drain_durable_at(
        &mut self,
        now: u64,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        self.begin_drain_at(now);
        self.drain_persistence_uncertain = true;
        if self.durable_drain.persist().is_err() {
            return Err(LearningArtifactOwnerServiceError::PersistenceUnknown);
        }
        self.drain_durable = true;
        self.drain_persistence_uncertain = false;
        Ok(())
    }

    #[must_use]
    pub fn durable_drain_requested(&self) -> bool {
        self.drain_durable && !self.drain_persistence_uncertain
    }

    /// No uncertain publication or drain write remains. Process termination and
    /// deployment acceptance are separate; this method does not release a lock.
    #[must_use]
    pub fn is_drained(&self) -> bool {
        self.draining
            && !self.drain_persistence_uncertain
            && !self.withdrawal_persistence_uncertain
            && self.identity_persistence_uncertain.is_none()
            && self.recovery_required.is_none()
    }

    /// Install an authenticated newer withdrawal frontier. The service accepts
    /// only an exact monotonic prefix extension in the same scope. The local
    /// floor is durable before success. A failed write keeps the newer in-memory
    /// frontier, fences use, and requires exact reconciliation or a newer prefix.
    /// The caller still authenticates withdrawal actors and external freshness.
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
        self.withdrawal_persistence_uncertain = true;
        if self
            .durable_withdrawals
            .persist(&self.withdrawal_registry)
            .is_err()
        {
            return Err(LearningArtifactOwnerServiceError::PersistenceUnknown);
        }
        self.withdrawal_persistence_uncertain = false;
        Ok(())
    }

    /// Storage acknowledgement only, not actor authentication or runtime use.
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

    fn bind_request_identity(
        &mut self,
        operation_id: &StableId,
        request_digest: Digest32,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        match self
            .durable_request_identities
            .bind(operation_id, request_digest)
        {
            Ok(()) => {
                if self.identity_persistence_uncertain.as_ref() == Some(operation_id) {
                    self.identity_persistence_uncertain = None;
                }
                Ok(())
            }
            Err(DurableRequestIdentityError::PersistenceUnknown(_)) => {
                self.identity_persistence_uncertain = Some(operation_id.clone());
                Err(LearningArtifactOwnerServiceError::PersistenceUnknown)
            }
            Err(error) => Err(error.into()),
        }
    }

    /// Execute or reconcile one complete immutable publication.
    ///
    /// Exact retries of an acknowledged operation return the same historical
    /// receipt. A non-terminal retry verifies actual durable objects before
    /// reconstructing the transaction and continuing. Callers supply trusted time.
    pub fn publish(
        &mut self,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        self.require_durable_withdrawals()?;
        if let Some(blocked) = &self.identity_persistence_uncertain
            && blocked != &request.operation_id
        {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                blocked.clone(),
            ));
        }
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
                self.identity_persistence_uncertain = None;
                self.recovery_required = None;
                self.recovery_observed_at = None;
                Ok(receipt)
            }
            Err(error) => {
                match self.host.recover_publication(&operation_id) {
                    Ok(Some(recovery))
                        if recovery.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged =>
                    {
                        self.recovery_required = Some(operation_id);
                        self.recovery_observed_at.get_or_insert(request.now);
                    }
                    Ok(_) => {}
                    Err(recovery_error) => {
                        // An unreadable checkpoint is uncertainty, never proof
                        // that a write did not happen. Fence reads and writes.
                        self.recovery_required = Some(operation_id);
                        self.recovery_observed_at.get_or_insert(request.now);
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
        let request_digest = self.request_identity.verify_and_digest(request)?;
        let checkpoint = self.host.recover_publication(&request.operation_id)?;
        if let Some(recovery) = checkpoint.as_ref() {
            self.durable_request_identities
                .verify(&request.operation_id, request_digest)?;
            validate_request_against_checkpoint(request, &recovery.checkpoint)?;
            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                return receipt_from_checkpoint(&recovery.checkpoint);
            }
        }
        // Historical terminal receipts remain readable, but a new or pending
        // DAG must not lose ancestry in the single-parent compatibility store.
        if request.admission.validated_manifest.manifest.predecessor_ids.len() > 1 {
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        if self.draining && checkpoint.is_none() {
            return Err(LearningArtifactOwnerServiceError::Draining);
        }
        if checkpoint.is_none() {
            let current = self.host.recover_current_registry(request.now)?;
            if current.snapshot().head_digest != request.expected_registry_predecessor_head {
                return Err(LearningArtifactOwnerServiceError::RequestMismatch);
            }
        }
        let predecessor = self
            .host
            .recover_registry_by_head(request.expected_registry_predecessor_head)?;
        let mut staged = predecessor.clone();
        // Preview deterministic registry projection before writing any request
        // identity or publication checkpoint.
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
            return Err(LearningArtifactOwnerServiceError::RequestMismatch);
        }
        if let Some(recovery) = checkpoint.as_ref() {
            verify_durable_inputs(&self.root, &staged, request, &recovery.checkpoint)?;
        } else {
            self.bind_request_identity(&request.operation_id, request_digest)?;
        }
        let mut transaction = self.host.begin_publication(
            request.operation_id.clone(),
            request.admission.clone(),
            &self.withdrawal_registry,
            &predecessor,
            request.expected_registry_predecessor_head,
            request.now,
        )?;
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LearningArtifactOwnerErrorCodeV1 {
    IdentityConflict,
    IdentityMissing,
    StaleOwner,
    WithdrawalFrontierConflict,
    WithdrawalDurabilityUnknown,
    PersistenceUnknown,
    CapacityExhausted,
    RecoveryRequired,
    Draining,
    InvalidRequest,
    CorruptState,
    Internal,
}

impl LearningArtifactOwnerErrorCodeV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::IdentityConflict => "identity_conflict",
            Self::IdentityMissing => "identity_missing",
            Self::StaleOwner => "stale_owner",
            Self::WithdrawalFrontierConflict => "withdrawal_frontier_conflict",
            Self::WithdrawalDurabilityUnknown => "withdrawal_durability_unknown",
            Self::PersistenceUnknown => "persistence_unknown",
            Self::CapacityExhausted => "capacity_exhausted",
            Self::RecoveryRequired => "recovery_required",
            Self::Draining => "draining",
            Self::InvalidRequest => "invalid_request",
            Self::CorruptState => "corrupt_state",
            Self::Internal => "internal",
        }
    }
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
    RequestIdentityConflict,
    RequestIdentityMissing,
    RequestMismatch,
    CheckpointShape,
    CheckpointMismatch,
    UnexpectedPhase,
    PersistenceUnknown,
    StaleOwner,
    CapacityExhausted,
    Draining,
}

impl LearningArtifactOwnerServiceError {
    #[must_use]
    pub const fn code(&self) -> LearningArtifactOwnerErrorCodeV1 {
        match self {
            Self::RequestIdentityConflict => LearningArtifactOwnerErrorCodeV1::IdentityConflict,
            Self::RequestIdentityMissing => LearningArtifactOwnerErrorCodeV1::IdentityMissing,
            Self::StaleOwner => LearningArtifactOwnerErrorCodeV1::StaleOwner,
            Self::WithdrawalFrontierConflict => {
                LearningArtifactOwnerErrorCodeV1::WithdrawalFrontierConflict
            }
            Self::WithdrawalDurabilityUnknown => {
                LearningArtifactOwnerErrorCodeV1::WithdrawalDurabilityUnknown
            }
            Self::PersistenceUnknown => LearningArtifactOwnerErrorCodeV1::PersistenceUnknown,
            Self::CapacityExhausted => LearningArtifactOwnerErrorCodeV1::CapacityExhausted,
            Self::RecoveryRequired(_) | Self::RecoveryConflict => {
                LearningArtifactOwnerErrorCodeV1::RecoveryRequired
            }
            Self::Draining => LearningArtifactOwnerErrorCodeV1::Draining,
            Self::InvalidConfiguration | Self::RequestMismatch => {
                LearningArtifactOwnerErrorCodeV1::InvalidRequest
            }
            Self::CheckpointShape | Self::CheckpointMismatch | Self::ControlIo(_) => {
                LearningArtifactOwnerErrorCodeV1::CorruptState
            }
            Self::Host(_) | Self::Publication(_) | Self::UnexpectedPhase => {
                LearningArtifactOwnerErrorCodeV1::Internal
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
        match value {
            ArtifactOwnerHostError::IdentityConflict => Self::RequestIdentityConflict,
            ArtifactOwnerHostError::WriterLeaseContext
            | ArtifactOwnerHostError::SignerRevoked
            | ArtifactOwnerHostError::CurrentHeadExpired
            | ArtifactOwnerHostError::CurrentHeadRollback => Self::StaleOwner,
            ArtifactOwnerHostError::Capacity => Self::CapacityExhausted,
            ArtifactOwnerHostError::Indeterminate => Self::PersistenceUnknown,
            other => Self::Host(other),
        }
    }
}

impl From<ArtifactPublicationError> for LearningArtifactOwnerServiceError {
    fn from(value: ArtifactPublicationError) -> Self {
        Self::Publication(value)
    }
}

impl From<DurableRequestIdentityError> for LearningArtifactOwnerServiceError {
    fn from(value: DurableRequestIdentityError) -> Self {
        match value {
            DurableRequestIdentityError::Missing => Self::RequestIdentityMissing,
            DurableRequestIdentityError::Conflict => Self::RequestIdentityConflict,
            DurableRequestIdentityError::PersistenceUnknown(_) => Self::PersistenceUnknown,
            DurableRequestIdentityError::Io(error) => Self::ControlIo(error),
        }
    }
}

#[cfg(test)]
#[path = "owner_service_tests.rs"]
mod tests;

#[cfg(all(test, unix))]
#[path = "owner/withdrawal_service_tests.rs"]
mod withdrawal_tests;
