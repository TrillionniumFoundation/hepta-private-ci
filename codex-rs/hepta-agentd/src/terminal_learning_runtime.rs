//! Explicit supervised terminal-only learning profile. Default configuration
//! does not attach this worker. Ordinary turns never submit training implicitly.

use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_types::StableId;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::AgentdTerminalLearningOwnerV1;
use crate::TerminalLearningErrorV1;
use crate::TerminalLearningReceiptV1;
use crate::TerminalLearningRequestV1;
use crate::terminal_learning_types::TerminalLearningModeV1;

struct Command {
    request: Box<TerminalLearningRequestV1>,
    mode: TerminalLearningModeV1,
    response: oneshot::Sender<Result<TerminalLearningReceiptV1, TerminalLearningErrorV1>>,
}

#[derive(Clone)]
pub struct TerminalLearningHandleV1 {
    sender: mpsc::Sender<Command>,
    agent_id: AgentId,
    producer_id: StableId,
}

impl TerminalLearningHandleV1 {
    pub async fn submit(
        &self,
        request: TerminalLearningRequestV1,
    ) -> Result<TerminalLearningReceiptV1, TerminalLearningErrorV1> {
        self.call(request, TerminalLearningModeV1::Train).await
    }

    pub async fn readback(
        &self,
        request: TerminalLearningRequestV1,
    ) -> Result<TerminalLearningReceiptV1, TerminalLearningErrorV1> {
        self.call(request, TerminalLearningModeV1::Readback).await
    }

    async fn call(
        &self,
        request: TerminalLearningRequestV1,
        mode: TerminalLearningModeV1,
    ) -> Result<TerminalLearningReceiptV1, TerminalLearningErrorV1> {
        // Reject unbounded caller vectors before retaining them in the queue.
        request.job_digest(&self.agent_id, &self.producer_id)?;
        let (response, receive) = oneshot::channel();
        self.sender
            .try_send(Command {
                request: Box::new(request),
                mode,
                response,
            })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => TerminalLearningErrorV1::QueueFull,
                mpsc::error::TrySendError::Closed(_) => TerminalLearningErrorV1::Unavailable,
            })?;
        receive
            .await
            .map_err(|_| TerminalLearningErrorV1::CommitUncertain)?
    }
}

pub struct TerminalLearningRuntimeBootstrapV1 {
    agent_id: AgentId,
    spawn_generation: u64,
    owner: AgentdTerminalLearningOwnerV1,
    receiver: mpsc::Receiver<Command>,
}

/// Consumes one native owner under the existing Agentd generation/supervision.
/// This profile needs neither a generic host callback nor proposal authority.
pub fn terminal_learning_channel_v1(
    agent_id: AgentId,
    spawn_generation: u64,
    owner: AgentdTerminalLearningOwnerV1,
    capacity: usize,
) -> Result<(TerminalLearningHandleV1, TerminalLearningRuntimeBootstrapV1), AgentdError> {
    if spawn_generation == 0 || !(1..=64).contains(&capacity) || owner.agent_id() != &agent_id {
        return Err(AgentdError::Invalid(
            "terminal learning requires exact scope and bounded queue".into(),
        ));
    }
    let (sender, receiver) = mpsc::channel(capacity);
    let handle = TerminalLearningHandleV1 {
        sender,
        agent_id: agent_id.clone(),
        producer_id: owner.producer_id().clone(),
    };
    Ok((
        handle,
        TerminalLearningRuntimeBootstrapV1 {
            agent_id,
            spawn_generation,
            owner,
            receiver,
        },
    ))
}

impl TerminalLearningRuntimeBootstrapV1 {
    pub(crate) fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.agent_id != identity.agent_id || self.spawn_generation != identity.spawn_generation
        {
            return Err(AgentdError::GenerationFenced(
                "terminal learning owner scope does not match Agentd".into(),
            ));
        }
        Ok(())
    }

    pub(crate) async fn run(
        self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        self.run_with_clock(state, cancellation, now_seconds).await
    }

    pub(crate) async fn run_with_clock(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
        clock: impl Fn() -> Result<u64, TerminalLearningErrorV1> + Send + Sync,
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
            let Command {
                request,
                mode,
                response,
            } = command;
            if response.is_closed() {
                continue;
            }
            let result = tokio::select! {
                _ = cancellation.cancelled() => {
                    let _ = response.send(Err(TerminalLearningErrorV1::CommitUncertain));
                    return Ok(());
                }
                result = async {
                    require_ready(&state)?;
                    let now = clock()?;
                    let result = match mode {
                        TerminalLearningModeV1::Readback => self.owner.readback(*request, now).await,
                        TerminalLearningModeV1::Train => self.owner.train(*request, now).await,
                    };
                    require_ready(&state)?;
                    result
                } => result,
            };
            let _ = response.send(result);
        }
    }
}

fn require_ready(state: &AgentdState) -> Result<(), TerminalLearningErrorV1> {
    if !state
        .plasticity_admission_ready()
        .map_err(|_| TerminalLearningErrorV1::Unavailable)?
    {
        return Err(TerminalLearningErrorV1::Unavailable);
    }
    Ok(())
}

fn now_seconds() -> Result<u64, TerminalLearningErrorV1> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|value| value.as_secs())
        .map_err(|_| TerminalLearningErrorV1::Unavailable)
}
