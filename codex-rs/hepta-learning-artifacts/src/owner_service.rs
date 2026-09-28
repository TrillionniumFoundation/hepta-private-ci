//! Single fenced product writer for immutable learning artifacts.
//! Recovery, withdrawal and stop intent remain owned by this service; diagnostic
//! observations cannot change durable state or grant activation authority.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;
use std::time::Instant;

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

#[path = "owner/diagnostics.rs"]
mod diagnostics;
#[path = "owner/durable_control.rs"]
mod durable_control;
#[path = "owner/durable_inputs.rs"]
mod durable_inputs;
#[path = "owner/durable_withdrawals.rs"]
mod durable_withdrawals;
#[path = "owner/publication_recovery.rs"]
mod publication_recovery;
#[path = "owner/request_identity.rs"]
mod request_identity;
#[path = "owner/request_journal.rs"]
mod request_journal;
#[path = "owner/request_record.rs"]
mod request_record;
#[path = "owner/service_observation.rs"]
mod service_observation;
#[path = "owner/service_publication.rs"]
mod service_publication;

pub use diagnostics::ArtifactOwnerDiagnosticsV1;
pub use diagnostics::ArtifactPhaseTimingV1;

use diagnostics::Observations;
use diagnostics::Phase;
use durable_control::DurableDrain;
use durable_inputs::verify_durable_inputs;
use durable_withdrawals::DurableWithdrawalFloor;
use publication_recovery::rebuild_transaction;
use publication_recovery::receipt_from_checkpoint;
use publication_recovery::validate_request_against_checkpoint;
use request_identity::RequestIdentityVerifier;
use request_journal::RequestJournal;
use request_record::RequestRecord;

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
    request_journal: RequestJournal,
    observations: Observations,
    recovery_required: Option<StableId>,
    draining: bool,
    drain_durable: bool,
    drain_persistence_uncertain: bool,
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
            .field(
                "withdrawal_persistence_uncertain",
                &self.withdrawal_persistence_uncertain,
            )
            .field("request_bindings", &self.request_journal.len())
            .field(
                "request_binding_bytes",
                &self.request_journal.encoded_bytes(),
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
        let opened_at = Instant::now();
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
            durable_drain
                .persist()
                .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        }
        if let Some(current) = host.discover_current_head(config.now)?
            && current.signed.binding != config.storage_binding
        {
            return Err(LearningArtifactOwnerServiceError::InvalidConfiguration);
        }
        let registry = host.recover_current_registry(config.now)?;
        let durable_withdrawals =
            DurableWithdrawalFloor::new(&root, &registry_id, scope, config.storage_binding);
        durable_withdrawals
            .persist(&config.withdrawal_registry)
            .map_err(LearningArtifactOwnerServiceError::ControlIo)?;
        let request_journal = RequestJournal::open(
            &root,
            &registry_id,
            scope,
            config.storage_binding,
            &request_identity,
        )?;
        let mut pending = BTreeSet::new();
        for checkpoint in host.recovery_required_operations()? {
            pending.insert(checkpoint.operation_id);
        }
        // Binding precedes Prepared. An interrupted binding cannot disappear
        // merely because no publication checkpoint was written yet.
        for record in request_journal.records() {
            if host
                .recover_publication(&record.operation_id)?
                .is_none_or(|value| {
                    value.checkpoint.phase != ArtifactPublicationPhaseV1::Acknowledged
                })
            {
                pending.insert(record.operation_id.clone());
            }
        }
        if pending.len() > 1 {
            return Err(LearningArtifactOwnerServiceError::RecoveryConflict);
        }
        let recovery_required = pending.into_iter().next();
        let mut observations = Observations::default();
        observations.restore(recovery_required.is_some(), draining);
        observations.record(Phase::Open, opened_at, &Ok::<(), ()>(()));
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
            request_journal,
            observations,
            recovery_required,
            draining,
            drain_durable: draining,
            drain_persistence_uncertain: false,
        })
    }

    #[must_use]
    pub fn registry(&self) -> &ArtifactRegistry {
        &self.registry
    }

    /// Current reads remain fenced while a publication or withdrawal is unknown.
    pub fn current_registry_view(
        &self,
        now: u64,
    ) -> Result<VerifiedCurrentRegistryViewV1, LearningArtifactOwnerServiceError> {
        self.require_durable_withdrawals()?;
        if let Some(operation) = &self.recovery_required {
            return Err(LearningArtifactOwnerServiceError::RecoveryRequired(
                operation.clone(),
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

    /// Process-local admission stop. Durable operator stop uses begin_drain_durable.
    /// Neither operation releases the OS writer fence.
    pub fn begin_drain(&mut self) {
        self.draining = true;
        self.observations.observe_state(
            self.recovery_required.is_some(),
            self.draining,
            self.withdrawal_persistence_uncertain,
        );
    }

    fn begin_drain_recorded(&mut self) -> Result<(), LearningArtifactOwnerServiceError> {
        self.draining = true;
        self.drain_persistence_uncertain = true;
        self.durable_drain
            .persist()
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

    /// The embedding host authenticates actors and external frontier freshness.
    fn install_withdrawal_frontier_recorded(
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
        self.durable_withdrawals
            .persist(&self.withdrawal_registry)
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

    fn publish_recorded(
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
                let started = Instant::now();
                let recovery = self.host.recover_publication(&operation_id);
                self.observations
                    .record(Phase::Reconcile, started, &recovery);
                match recovery {
                    Ok(Some(recovery))
                        if recovery.checkpoint.phase
                            != ArtifactPublicationPhaseV1::Acknowledged =>
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
    RequestBindingCorrupt,
    LegacyRequestUnbound,
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
