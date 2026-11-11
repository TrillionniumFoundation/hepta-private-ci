//! Explicit, supervised learning work through shared owner facilities.

use std::error::Error;
use std::fmt;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
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

const MAX_LEARNING_QUEUE: usize = 64;
const MAX_ITERATION_SECONDS: u64 = 86_400;

#[derive(Debug)]
pub enum LearningIterationRuntimeErrorV1 {
    Validation(LearningIterationError),
    WrongScope,
    Unavailable,
    QueueFull,
    DeadlineExceeded,
    OwnerUnavailable(&'static str),
    CommitUncertain,
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

struct LearningIterationCommandV1 {
    request: Box<LearningIterationRequestV1>,
    response: oneshot::Sender<Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1>>,
}

/// Capacity exhaustion refuses immediately; it does not accumulate waiters.
#[derive(Clone)]
pub struct LearningIterationHandleV1 {
    sender: mpsc::Sender<LearningIterationCommandV1>,
}

impl LearningIterationHandleV1 {
    pub async fn submit(
        &self,
        request: LearningIterationRequestV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .try_send(LearningIterationCommandV1 {
                request: Box::new(request),
                response,
            })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => LearningIterationRuntimeErrorV1::QueueFull,
                mpsc::error::TrySendError::Closed(_) => {
                    LearningIterationRuntimeErrorV1::Unavailable
                }
            })?;
        // Missing acknowledgement does not prove absence of a durable commit.
        receive
            .await
            .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?
    }
}

/// Consumed once by Agentd. No mutable writer or trust root reaches the sender.
/// Trust rotation requires a newly admitted process-owner bootstrap.
pub struct LearningIterationRuntimeBootstrapV1 {
    agent_id: AgentId,
    spawn_generation: u64,
    owners: LearningIterationOwnersV1,
    ports: Arc<dyn LearningIterationOwnerPortsV1>,
    verifier: LearningEvidenceVerifierV1,
    receiver: mpsc::Receiver<LearningIterationCommandV1>,
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
    if spawn_generation == 0
        || !(1..=MAX_LEARNING_QUEUE).contains(&capacity)
        || owners.evidence_trust_digest != verifier.trust_digest()
    {
        return Err(AgentdError::Invalid(
            "learning owner requires generation, pinned trust and bounded queue".into(),
        ));
    }
    let (sender, receiver) = mpsc::channel(capacity);
    Ok((
        LearningIterationHandleV1 { sender },
        LearningIterationRuntimeBootstrapV1 {
            agent_id,
            spawn_generation,
            owners,
            ports,
            verifier,
            receiver,
        },
    ))
}

impl LearningIterationRuntimeBootstrapV1 {
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
                result = self.process_with_deadline(&state, *command.request) => result,
            };
            let _ = command.response.send(result);
        }
    }

    async fn process_with_deadline(
        &self,
        state: &AgentdState,
        request: LearningIterationRequestV1,
    ) -> Result<LearningIterationSnapshotV1, LearningIterationRuntimeErrorV1> {
        let remaining = request
            .envelope
            .expiry_unix_seconds
            .saturating_sub(now_unix_seconds()?);
        if remaining > MAX_ITERATION_SECONDS {
            return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
        }
        // Expired operations may reconcile a completed receipt. New stages and
        // create-if-absent checkpoints are still rejected inside process.
        tokio::time::timeout(
            Duration::from_secs(remaining.max(1)),
            self.process(state, request, now_unix_seconds),
        )
        .await
        .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)?
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
        let initial = LearningIterationCoordinatorV1::new(request.clone(), self.owners.clone())?;
        require_ready(state)?;
        let mut coordinator = match self.ports.restore(&request).await? {
            Some(snapshot) => {
                if snapshot.request != request || snapshot.owners != self.owners {
                    return Err(LearningIterationRuntimeErrorV1::WrongScope);
                }
                LearningIterationCoordinatorV1::from_snapshot(snapshot)?
            }
            None => {
                require_ready(state)?;
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
            require_ready(state)?;
            if clock()? >= request.envelope.expiry_unix_seconds {
                return Err(LearningIterationRuntimeErrorV1::DeadlineExceeded);
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
                crate::learning_iteration_auth::authenticate_iteration_receipt_v1(
                    self.ports.as_ref(),
                    &self.verifier,
                    &coordinator,
                    &receipt,
                    clock()?,
                )
                .await?;
                receipt
            };
            require_ready(state)?;
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
