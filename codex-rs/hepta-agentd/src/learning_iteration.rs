//! Explicit, supervised learning work through shared owner facilities.

use std::error::Error;
use std::fmt;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_types::Digest32;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::LearningIterationOwnerPortsV1;
use crate::PlasticityRuntimeCallErrorV1;

#[path = "learning_iteration_delivery_runtime.rs"]
mod delivery;
#[cfg(target_os = "linux")]
#[path = "learning_iteration_retained_source.rs"]
mod retained_source;
#[cfg(target_os = "linux")]
#[path = "learning_iteration_same_actor.rs"]
mod same_actor;
pub(crate) use delivery::CircuitLearningDeliveryRuntimeV1;
pub(crate) use delivery::CircuitLearningSourceV1;
#[path = "circuit_learning_delivery_registry.rs"]
mod registry;
pub use registry::CircuitLearningDeliveryRegistryV1;
pub(crate) use registry::MAX_REGISTERED_CIRCUIT_LEARNING;

const MAX_LEARNING_QUEUE: usize = 64;
const MAX_ITERATION_SECONDS: u64 = 86_400;
const MAX_READBACK_SECONDS: u64 = 30;

#[derive(Debug)]
pub enum LearningIterationRuntimeErrorV1 {
    Validation(LearningIterationError),
    WrongScope,
    Unavailable,
    QueueFull,
    DeadlineExceeded,
    OwnerUnavailable(&'static str),
    CommitUncertain,
    #[cfg(unix)]
    Checkpoint(crate::LearningIterationCheckpointErrorV1),
    Evidence(SignedEvidenceError),
    Proposal(PlasticityRuntimeCallErrorV1),
}
impl fmt::Display for LearningIterationRuntimeErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for LearningIterationRuntimeErrorV1 {}
impl From<LearningIterationError> for LearningIterationRuntimeErrorV1 {
    fn from(error: LearningIterationError) -> Self {
        Self::Validation(error)
    }
}

enum LearningIterationModeV1 {
    Submit,
    Readback,
}

struct LearningIterationCommandV1 {
    mode: LearningIterationModeV1,
    request: Box<LearningIterationRequestV1>,
    response: oneshot::Sender<Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1>>,
}

/// Capacity exhaustion refuses immediately; it does not accumulate waiters.
#[derive(Clone)]
pub struct LearningIterationHandleV1 {
    sender: mpsc::Sender<LearningIterationCommandV1>,
}

/// One bounded actor slot held before a durable delivery claim is recorded.
pub(crate) struct LearningIterationReservationV1<'a> {
    permit: mpsc::Permit<'a, LearningIterationCommandV1>,
}

impl LearningIterationHandleV1 {
    pub async fn submit(
        &self,
        request: LearningIterationRequestV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        self.call(request, LearningIterationModeV1::Submit).await
    }

    /// Authenticate only the original durable snapshot. Missing state remains
    /// uncertain; this cannot create a checkpoint or execute another stage.
    pub async fn readback(
        &self,
        request: LearningIterationRequestV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        self.call(request, LearningIterationModeV1::Readback).await
    }

    async fn call(
        &self,
        request: LearningIterationRequestV1,
        mode: LearningIterationModeV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        self.reserve()?.call(request, mode).await
    }

    pub(crate) fn reserve(
        &self,
    ) -> Result<LearningIterationReservationV1<'_>, LearningIterationRuntimeErrorV1> {
        let permit = self.sender.try_reserve().map_err(|error| match error {
            mpsc::error::TrySendError::Full(_) => LearningIterationRuntimeErrorV1::QueueFull,
            mpsc::error::TrySendError::Closed(_) => LearningIterationRuntimeErrorV1::Unavailable,
        })?;
        Ok(LearningIterationReservationV1 { permit })
    }
}

impl LearningIterationReservationV1<'_> {
    pub(crate) async fn submit(
        self,
        request: LearningIterationRequestV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        self.call(request, LearningIterationModeV1::Submit).await
    }

    pub(crate) async fn readback(
        self,
        request: LearningIterationRequestV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        self.call(request, LearningIterationModeV1::Readback).await
    }

    async fn call(
        self,
        request: LearningIterationRequestV1,
        mode: LearningIterationModeV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        let (response, receive) = oneshot::channel();
        self.permit.send(LearningIterationCommandV1 {
            mode,
            request: Box::new(request),
            response,
        });
        // Missing acknowledgement does not prove absence of a durable commit.
        receive
            .await
            .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?
    }
}

/// Consumed once by Agentd. No mutable writer or trust root reaches the sender.
/// Trust rotation requires a newly admitted process-owner bootstrap.
#[cfg(target_os = "linux")]
#[path = "learning_iteration_successor.rs"]
mod successor;
#[cfg(target_os = "linux")]
pub(crate) use successor::OriginalQ24SuccessorContext;

pub struct LearningIterationRuntimeBootstrapV1 {
    agent_id: AgentId,
    spawn_generation: u64,
    owners: LearningIterationOwnersV1,
    ports: Arc<dyn LearningIterationOwnerPortsV1>,
    verifier: LearningEvidenceVerifierV1,
    scope: Option<FrozenLearningScopeV2>,
    receiver: mpsc::Receiver<LearningIterationCommandV1>,
    sender: mpsc::Sender<LearningIterationCommandV1>,
    circuit_delivery_registry: Option<CircuitLearningDeliveryRegistryV1>,
    circuit_delivery_source: delivery::CircuitLearningSourceV1,
    #[cfg(target_os = "linux")]
    retained_source: Option<Arc<crate::cell_q24_task_ledger::RegisteredCellQ24RetainedSourceV1>>,
    enforce_circuit_admission: bool,
    #[cfg(target_os = "linux")]
    original_q24: Option<Arc<crate::OriginalCellQ24LearningStageOwnersV1>>,
    #[cfg(target_os = "linux")]
    successor: Option<Arc<crate::circuit_q24_successor::SuccessorSlot>>,
}

pub fn learning_iteration_channel_v1(
    agent_id: AgentId,
    spawn_generation: u64,
    owners: LearningIterationOwnersV1,
    ports: Arc<dyn LearningIterationOwnerPortsV1>,
    verifier: LearningEvidenceVerifierV1,
    capacity: usize,
) -> Result<
    (
        LearningIterationHandleV1,
        LearningIterationRuntimeBootstrapV1,
    ),
    AgentdError,
> {
    learning_iteration_channel(
        agent_id,
        spawn_generation,
        owners,
        ports,
        verifier,
        capacity,
        /*scope*/ None,
    )
}

/// Select a frozen Cell/Organ update boundary with its matching registered
/// checkpoint. Legacy ports cannot enter this profile or silently downgrade it.
pub fn learning_iteration_channel_scoped_v2(
    agent_id: AgentId,
    spawn_generation: u64,
    owners: LearningIterationOwnersV1,
    ports: Arc<dyn LearningIterationOwnerPortsV1>,
    verifier: LearningEvidenceVerifierV1,
    capacity: usize,
    scope: FrozenLearningScopeV2,
) -> Result<
    (
        LearningIterationHandleV1,
        LearningIterationRuntimeBootstrapV1,
    ),
    AgentdError,
> {
    learning_iteration_channel(
        agent_id,
        spawn_generation,
        owners,
        ports,
        verifier,
        capacity,
        Some(scope),
    )
}

fn learning_iteration_channel(
    agent_id: AgentId,
    spawn_generation: u64,
    owners: LearningIterationOwnersV1,
    ports: Arc<dyn LearningIterationOwnerPortsV1>,
    verifier: LearningEvidenceVerifierV1,
    capacity: usize,
    scope: Option<FrozenLearningScopeV2>,
) -> Result<
    (
        LearningIterationHandleV1,
        LearningIterationRuntimeBootstrapV1,
    ),
    AgentdError,
> {
    if spawn_generation == 0
        || !(1..=MAX_LEARNING_QUEUE).contains(&capacity)
        || owners.evidence_trust_digest != verifier.trust_digest()
        || ports.frozen_scope_binding() != scope.as_ref().map(FrozenLearningScopeV2::binding)
    {
        return Err(AgentdError::Invalid(
            "learning owner requires generation, pinned trust, matching checkpoint profile and bounded queue".into(),
        ));
    }
    let (sender, receiver) = mpsc::channel(capacity);
    Ok((
        LearningIterationHandleV1 {
            sender: sender.clone(),
        },
        LearningIterationRuntimeBootstrapV1 {
            agent_id,
            spawn_generation,
            owners,
            ports,
            verifier,
            scope,
            receiver,
            sender,
            circuit_delivery_registry: None,
            circuit_delivery_source: delivery::CircuitLearningSourceV1::HostStageOwners,
            #[cfg(target_os = "linux")]
            retained_source: None,
            enforce_circuit_admission: false,
            #[cfg(target_os = "linux")]
            original_q24: None,
            #[cfg(target_os = "linux")]
            successor: None,
        },
    ))
}

impl LearningIterationRuntimeBootstrapV1 {
    #[cfg(target_os = "linux")]
    pub(crate) fn with_original_q24_stage_owners(
        mut self,
        owners: Arc<crate::OriginalCellQ24LearningStageOwnersV1>,
    ) -> Result<Self, AgentdError> {
        let prepared = owners.prepared();
        if self.original_q24.is_some()
            || self.owners != prepared.initial().owners
            || self.scope.as_ref() != Some(prepared.scope())
            || !self.enforce_circuit_admission
            || !matches!(
                self.circuit_delivery_source,
                CircuitLearningSourceV1::OriginalObjective
            )
        {
            return Err(AgentdError::Invalid(
                "original Root Q24 learning profile differs".into(),
            ));
        }
        self.original_q24 = Some(owners);
        self.circuit_delivery_source = CircuitLearningSourceV1::OriginalQ24;
        Ok(self)
    }

    pub(crate) async fn require_proposal_owner(
        &self,
        governed_plasticity_present: bool,
    ) -> Result<(), AgentdError> {
        #[cfg(target_os = "linux")]
        if let Some(original) = &self.original_q24 {
            let original: &Arc<crate::OriginalCellQ24LearningStageOwnersV1> = original;
            return original
                .require_current()
                .await
                .map_err(|error| AgentdError::GenerationFenced(error.to_string()));
        }
        if !governed_plasticity_present {
            return Err(AgentdError::Invalid("learning iteration requires the governed plasticity owner or original Root Q24 owner assembly".into()));
        }
        Ok(())
    }

    pub(crate) fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.agent_id != identity.agent_id || self.spawn_generation != identity.spawn_generation
        {
            return Err(AgentdError::GenerationFenced(
                "learning owner scope does not match Agentd".into(),
            ));
        }
        Ok(())
    }

    pub(crate) async fn run(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        self.require_identity(state.identity())?;
        loop {
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                command = self.receiver.recv() => command,
            };
            let Some(command) = command else {
                cancellation.cancelled().await;
                return Ok(());
            };
            if command.response.is_closed() {
                continue;
            }
            let result = tokio::select! {
                _ = cancellation.cancelled() => {
                    let _ = command.response.send(Err(LearningIterationRuntimeErrorV1::CommitUncertain));
                    return Ok(());
                }
                result = self.process_with_deadline(&state, *command.request, command.mode) => result,
            };
            let _ = command.response.send(result);
        }
    }

    async fn process_with_deadline(
        &self,
        state: &AgentdState,
        request: LearningIterationRequestV1,
        mode: LearningIterationModeV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        // Readback can only restore the original operation and reauthenticate
        // its historical owner receipts. It must not inherit a one-second work
        // timeout after expiry or a far-future new-work admission ceiling.
        // Neither expiry nor this bounded read-only window grants new stages.
        let timeout_seconds = match &mode {
            LearningIterationModeV1::Readback => MAX_READBACK_SECONDS,
            LearningIterationModeV1::Submit => {
                let remaining = request
                    .envelope
                    .expiry_unix_seconds
                    .saturating_sub(now_unix_seconds()?);
                if remaining > MAX_ITERATION_SECONDS {
                    return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
                }
                remaining.max(1)
            }
        };
        tokio::time::timeout(Duration::from_secs(timeout_seconds), async {
            match mode {
                LearningIterationModeV1::Readback => {
                    self.process_readback(state, request, now_unix_seconds)
                        .await
                }
                LearningIterationModeV1::Submit => {
                    self.process(state, request, now_unix_seconds).await
                }
            }
        })
        .await
        .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?
    }

    pub(super) async fn process_readback(
        &self,
        state: &AgentdState,
        request: LearningIterationRequestV1,
        clock: impl Fn() -> Result<u64, LearningIterationRuntimeErrorV1> + Send + Sync,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        if request.agent_id.as_str() != self.agent_id.to_string()
            || state.identity().agent_id != self.agent_id
            || state.identity().spawn_generation != self.spawn_generation
        {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        self.require_frozen_scope(&request)?;
        LearningIterationCoordinatorV1::new(request.clone(), self.owners.clone())?;
        require_ready(state)?;
        let snapshot = self
            .ports
            .restore(&request)
            .await?
            .ok_or(LearningIterationRuntimeErrorV1::CommitUncertain)?;
        if snapshot.request != request || snapshot.owners != self.owners {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        let restored = LearningIterationCoordinatorV1::from_snapshot(snapshot)?;
        if let Some(scope) = &self.scope {
            scope.validate_snapshot(restored.snapshot())?;
        } else if restored.snapshot().requires_scoped_owner_v2() {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        crate::learning_iteration_auth::authenticate_restored_iteration_v1(
            state,
            self.ports.as_ref(),
            &self.verifier,
            &restored,
            &clock,
        )
        .await?;
        require_ready(state)?;
        Ok(restored.snapshot().clone())
    }

    pub(super) async fn process(
        &self,
        state: &AgentdState,
        request: LearningIterationRequestV1,
        clock: impl Fn() -> Result<u64, LearningIterationRuntimeErrorV1> + Send + Sync,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        if request.agent_id.as_str() != self.agent_id.to_string()
            || state.identity().agent_id != self.agent_id
            || state.identity().spawn_generation != self.spawn_generation
        {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        self.require_frozen_scope(&request)?;
        let initial = LearningIterationCoordinatorV1::new(request.clone(), self.owners.clone())?;
        require_ready(state)?;
        let mut coordinator = match self.ports.restore(&request).await? {
            Some(snapshot) => {
                if snapshot.request != request || snapshot.owners != self.owners {
                    return Err(LearningIterationRuntimeErrorV1::WrongScope);
                }
                let restored = LearningIterationCoordinatorV1::from_snapshot(snapshot)?;
                if let Some(scope) = &self.scope {
                    scope.validate_snapshot(restored.snapshot())?;
                } else if restored.snapshot().requires_scoped_owner_v2() {
                    return Err(LearningIterationRuntimeErrorV1::WrongScope);
                }
                require_ready(state)?;
                if restored.next_stage().is_some()
                    && clock()? >= request.envelope.expiry_unix_seconds
                {
                    return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
                }
                crate::learning_iteration_auth::authenticate_restored_iteration_v1(
                    state,
                    self.ports.as_ref(),
                    &self.verifier,
                    &restored,
                    &clock,
                )
                .await?;
                require_ready(state)?;
                restored
            }
            None => {
                self.require_stage_admission(state)?;
                if clock()? >= request.envelope.expiry_unix_seconds {
                    return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
                }
                let head = self
                    .ports
                    .checkpoint(Digest32::ZERO, initial.snapshot())
                    .await?;
                if head != initial.snapshot().head_digest {
                    return Err(LearningIterationRuntimeErrorV1::CommitUncertain);
                }
                initial
            }
        };
        while let Some(stage) = coordinator.next_stage() {
            self.require_stage_admission(state)?;
            if clock()? >= request.envelope.expiry_unix_seconds {
                return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
            }
            #[cfg(target_os = "linux")]
            self.wait_original_same_actor_evaluation_stage(state, coordinator.snapshot(), stage)
                .await?;
            #[cfg(target_os = "linux")]
            self.wait_original_successor_stage(state, coordinator.snapshot(), stage)
                .await?;
            // Check the current local authorization before asking an original
            // owner to publish or use its selected generation, not only after
            // that owner returns an observation of the side effect.
            if let Some(decision) = coordinator.snapshot().receipts.iter().find(|receipt| {
                matches!(
                    receipt.observation,
                    codex_hepta_learning_artifacts::LearningIterationObservationV1::LocalDecisionV2(
                        _
                    )
                )
            }) {
                crate::learning_iteration_auth::authenticate_iteration_receipt_v1(
                    state,
                    self.ports.as_ref(),
                    &self.verifier,
                    &coordinator,
                    decision,
                    &clock,
                )
                .await?;
            }
            let receipt = if stage == LearningIterationStageV1::Proposal {
                crate::learning_iteration_proposal::submit_iteration_proposal_v1(
                    state,
                    self.ports.as_ref(),
                    &coordinator,
                    &clock,
                )
                .await?
            } else {
                let call = self.ports.execute_stage(coordinator.snapshot(), stage);
                let receipt = if stage == LearningIterationStageV1::Training {
                    tokio::time::timeout(
                        Duration::from_millis(request.budget.maximum_training_milliseconds),
                        call,
                    )
                    .await
                    .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)??
                } else {
                    call.await?
                };
                if self.scope.is_none()
                    && matches!(receipt.observation,
                        codex_hepta_learning_artifacts::LearningIterationObservationV1::TrainingNoUpdateV2(_)
                        | codex_hepta_learning_artifacts::LearningIterationObservationV1::LocalDecisionV2(_))
                {
                    return Err(LearningIterationRuntimeErrorV1::WrongScope);
                }
                crate::learning_iteration_auth::authenticate_iteration_receipt_v1(
                    state,
                    self.ports.as_ref(),
                    &self.verifier,
                    &coordinator,
                    &receipt,
                    &clock,
                )
                .await?;
                receipt
            };
            self.require_stage_admission(state)?;
            if let Some(scope) = &self.scope {
                scope.validate_observation(&receipt.observation)?;
            }
            let previous = coordinator.snapshot().head_digest;
            coordinator.record(receipt, clock()?)?;
            let committed = self
                .ports
                .checkpoint(previous, coordinator.snapshot())
                .await?;
            if committed != coordinator.snapshot().head_digest {
                return Err(LearningIterationRuntimeErrorV1::CommitUncertain);
            }
        }
        Ok(coordinator.snapshot().clone())
    }

    fn require_frozen_scope(
        &self,
        request: &LearningIterationRequestV1,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        if self.ports.frozen_scope_binding()
            != self.scope.as_ref().map(FrozenLearningScopeV2::binding)
        {
            return Err(LearningIterationRuntimeErrorV1::WrongScope);
        }
        if let Some(scope) = &self.scope {
            scope.validate_request(request, &self.owners)?;
        }
        Ok(())
    }

    fn require_stage_admission(
        &self,
        state: &AgentdState,
    ) -> Result<(), LearningIterationRuntimeErrorV1> {
        require_ready(state)?;
        if self.enforce_circuit_admission
            && !state
                .automation_admission_ready()
                .map_err(|_| LearningIterationRuntimeErrorV1::Unavailable)?
        {
            return Err(LearningIterationRuntimeErrorV1::Unavailable);
        }
        Ok(())
    }
}

pub(super) fn require_ready(state: &AgentdState) -> Result<(), LearningIterationRuntimeErrorV1> {
    if !state
        .plasticity_admission_ready()
        .map_err(|_| LearningIterationRuntimeErrorV1::Unavailable)?
    {
        return Err(LearningIterationRuntimeErrorV1::Unavailable);
    }
    Ok(())
}

fn now_unix_seconds() -> Result<u64, LearningIterationRuntimeErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .map_err(|_| LearningIterationRuntimeErrorV1::OwnerUnavailable("clock"))
}
