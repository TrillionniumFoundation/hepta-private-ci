//! Named product writer service for the immutable learning-artifact store.
//!
//! Request/current-authority validation, publication-state coordination,
//! durable storage, and recovery are separate boundaries. The service owns no
//! filesystem layout and may be composed with independently qualified stores.

use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactOwnerHostError;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactOwnerVerifierV1;
use crate::ArtifactPublicationError;
use crate::ArtifactPublicationPhaseV1;
use crate::ArtifactPublicationReceiptV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactRegistry;
use crate::CurrentArtifactUseErrorV1;
use crate::CurrentArtifactUseViewV1;
use crate::DatasetWithdrawalRegistry;
use crate::RegistryHeadRequirementV1;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::WithdrawalBoundArtifactAdmissionV3;

#[path = "owner/control_store.rs"]
mod control_store;
#[path = "owner/durable_control.rs"]
mod durable_control;
#[path = "owner/durable_inputs.rs"]
mod durable_inputs;
#[path = "owner/durable_withdrawals.rs"]
mod durable_withdrawals;
#[path = "owner/publication_recovery.rs"]
mod publication_recovery;
#[path = "owner/publication_store.rs"]
mod publication_store;
#[path = "owner/request_identity.rs"]
mod request_identity;

pub use control_store::FsOwnerControlStoreV1;
pub use control_store::OwnerControlStoreIdentityV1;
pub use control_store::OwnerControlStoreV1;
pub use publication_store::FsOwnerPublicationStoreV1;
pub use publication_store::OwnerPublicationStoreIdentityV1;
pub use publication_store::OwnerPublicationStoreV1;

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
    // The legacy field name is retained for source-compatible internal tests;
    // its type is now the narrow injectable publication-store port.
    host: Box<dyn OwnerPublicationStoreV1>,
    control_store: Box<dyn OwnerControlStoreV1>,
    withdrawal_persistence_uncertain: bool,
    withdrawal_registry: DatasetWithdrawalRegistry,
    registry: ArtifactRegistry,
    storage_binding: Digest32,
    request_identity: RequestIdentityVerifier,
    recovery_required: Option<StableId>,
    draining: bool,
    drain_durable: bool,
    drain_persistence_uncertain: bool,
}

impl fmt::Debug for LearningArtifactOwnerService {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("LearningArtifactOwnerService")
            .field("publication_store", self.host.identity())
            .field("control_store", self.control_store.identity())
            .field("registry_head", &self.registry.snapshot().head_digest)
            .field("withdrawal_head", &self.withdrawal_registry.head_digest())
            .field("storage_binding", &self.storage_binding)
            .field("recovery_required", &self.recovery_required)
            .field(
                "withdrawal_persistence_uncertain",
                &self.withdrawal_persistence_uncertain,
            )
            .field("draining", &self.draining)
            .field("drain_durable", &self.drain_durable)
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
        Self::validate_config(&config)?;
        let publication_store = FsOwnerPublicationStoreV1::open(&config)?;
        let root = publication_store.identity().root().to_path_buf();
        let control_store = FsOwnerControlStoreV1::new(
            root,
            config.trust.registry_id.clone(),
            config.trust.withdrawal_scope_digest,
            config.storage_binding,
        );
        Self::open_with_stores(
            config,
            Box::new(publication_store),
            Box::new(control_store),
        )
    }

    /// Compose the service over independently provided durable ports.
    ///
    /// The publication store must already hold its exclusive writer fence and
    /// enforce the required CURRENT restart anchor. Both immutable identities
    /// are checked against the supplied trust/configuration before recovery.
    pub fn open_with_stores(
        config: LearningArtifactOwnerServiceConfigV1,
        host: Box<dyn OwnerPublicationStoreV1>,
        control_store: Box<dyn OwnerControlStoreV1>,
    ) -> Result<Self, LearningArtifactOwnerServiceError> {
        Self::validate_config(&config)?;
        let canonical_root = std::fs::canonicalize(&config.root)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        let expected_trust_digest =
            ArtifactOwnerVerifierV1::new(config.trust.clone())?.trust_digest();
        let publication_identity = host.identity();
        if publication_identity.root() != canonical_root
            || publication_identity.registry_id() != &config.trust.registry_id
            || publication_identity.withdrawal_scope_digest()
                != config.trust.withdrawal_scope_digest
            || publication_identity.trust_digest() != expected_trust_digest
        {
            return Err(LearningArtifactOwnerServiceError::StoreIdentityMismatch);
        }
        let control_identity = control_store.identity();
        if control_identity.root() != canonical_root
            || control_identity.registry_id() != &config.trust.registry_id
            || control_identity.withdrawal_scope_digest()
                != config.trust.withdrawal_scope_digest
            || control_identity.storage_binding() != config.storage_binding
        {
            return Err(LearningArtifactOwnerServiceError::StoreIdentityMismatch);
        }

        let request_identity = RequestIdentityVerifier::new(&config.trust);
        let draining = control_store
            .drain_requested()
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        if draining {
            // Existing bytes may come from a write whose sync outcome was unknown.
            // Re-establish durability under the retained writer fence on reopen.
            control_store
                .persist_drain()
                .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
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
        // The writer fence is already held. Stored bytes may only constrain
        // (never replace) the independently authenticated startup frontier.
        control_store
            .persist_withdrawal_frontier(&config.withdrawal_registry)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        Ok(Self {
            host,
            control_store,
            withdrawal_persistence_uncertain: false,
            withdrawal_registry: config.withdrawal_registry,
            registry,
            storage_binding: config.storage_binding,
            request_identity,
            recovery_required,
            draining,
            drain_durable: draining,
            drain_persistence_uncertain: false,
        })
    }

    fn validate_config(
        config: &LearningArtifactOwnerServiceConfigV1,
    ) -> Result<(), LearningArtifactOwnerServiceError> {
        if config.storage_binding.is_zero()
            || config.withdrawal_registry.scope_digest()
                != Some(config.trust.withdrawal_scope_digest)
        {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        Ok(())
    }

    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

    /// Return the exact authenticated CURRENT registry view for compatibility
    /// consumers. New long-lived consumers should use `current_artifact_use_view`.
    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, LearningArtifactOwnerServiceError> {
        self.require_durable_withdrawals()?;
        self.require_recovered()?;
        Ok(self.host.current_registry_view(now)?)
    }

    /// Return a final-use view that binds CURRENT registry state to the exact
    /// durable withdrawal frontier, authority epoch, head generation and expiry.
    pub fn current_artifact_use_view(
        &self,
        now: u64,
    ) -> Result<CurrentArtifactUseViewV1, LearningArtifactOwnerServiceError> {
        self.require_durable_withdrawals()?;
        self.require_recovered()?;
        let current_head = self
            .host
            .discover_current_head(now)?
            .ok_or(LearningArtifactOwnerServiceError::CurrentHeadUnavailable)?;
        let current = self.host.current_registry_view(now)?;
        let requirement = RegistryHeadRequirementV1 {
            registry_id: current_head.signed.witness.registry_id.clone(),
            minimum_generation: current_head.signed.witness.generation,
            expected_predecessor_head_digest: current_head
                .signed
                .witness
                .predecessor_head_digest,
            minimum_authority_epoch: current_head.signed.witness.authority_epoch,
            now,
        };
        CurrentArtifactUseViewV1::bind(
            current,
            &current_head.signed,
            &requirement,
            &self.withdrawal_registry,
            now,
        )
        .map_err(LearningArtifactOwnerServiceError::CurrentUse)
    }

    #[must_use]
    pub fn withdrawal_registry(&self) -> &DatasetWithdrawalRegistry {
        &self.withdrawal_registry
    }

    #[must_use]
    pub fn recovery_required(&self) -> Option<&StableId> {
        self.recovery_required.as_ref()
    }

    pub fn begin_drain(&mut self) {
        self.draining = true;
    }

    pub fn begin_drain_durable(&mut self) -> Result<(), LearningArtifactOwnerServiceError> {
        self.draining = true;
        self.drain_persistence_uncertain = true;
        self.control_store
            .persist_drain()
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
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
        self.control_store
            .persist_withdrawal_frontier(&self.withdrawal_registry)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        self.withdrawal_persistence_uncertain = false;
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

    fn require_recovered(&self) -> Result<(), LearningArtifactOwnerServiceError> {
        if let Some(operation_id) = &self.recovery_required {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                operation_id.clone(),
            ));
        }
        Ok(())
    }

    pub fn publish(
        &mut self,
        request: LearningArtifactPublishRequestV1,
    ) -> Result<ArtifactPublicationReceiptV1, LearningArtifactOwnerServiceError> {
        self.require_durable_withdrawals()?;
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
        self.request_identity.verify(request)?;
        let checkpoint = self.host.recover_publication(&request.operation_id)?;
        if let Some(recovery) = checkpoint.as_ref() {
            validate_request_against_checkpoint(request, &recovery.checkpoint)?;
            if recovery.checkpoint.phase == ArtifactPublicationPhaseV1::Acknowledged {
                return receipt_from_checkpoint(&recovery.checkpoint);
            }
        }
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
            self.host
                .verify_recovery_inputs(&staged, request, &recovery.checkpoint)?;
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

#[derive(Debug)]
pub enum LearningArtifactOwnerServiceError {
    Host(ArtifactOwnerHostError),
    Publication(ArtifactPublicationError),
    CurrentUse(CurrentArtifactUseErrorV1),
    ControlIo(std::io::Error),
    InvalidConfiguration,
    StoreIdentityMismatch,
    CurrentHeadUnavailable,
    WithdrawalFrontierConflict,
    WithdrawalDurabilityUnknown,
    RecoveryConflict,
    RecoveryRequired(StableId),
    RequestMismatch,
    CheckpointShape,
    CheckpointMismatch,
    UnexpectedPhase,
    Draining,
}

impl fmt::Display for LearningArtifactOwnerServiceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LearningArtifactOwnerServiceError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Host(error) => Some(error),
            Self::Publication(error) => Some(error),
            Self::CurrentUse(error) => Some(error),
            Self::ControlIo(error) => Some(error),
            Self::InvalidConfiguration
            | Self::StoreIdentityMismatch
            | Self::CurrentHeadUnavailable
            | Self::WithdrawalFrontierConflict
            | Self::WithdrawalDurabilityUnknown
            | Self::RecoveryConflict
            | Self::RecoveryRequired(_)
            | Self::RequestMismatch
            | Self::CheckpointShape
            | Self::CheckpointMismatch
            | Self::UnexpectedPhase
            | Self::Draining => None,
        }
    }
}

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
