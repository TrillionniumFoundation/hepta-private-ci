//! One supervised blocking lane for the original Circuit/Cell owners. Caller
//! cancellation never releases the lane or hides active work from drain.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_learning_ledger::RunStartRecordV1;
use codex_hepta_neuron::CellInferenceReadbackPortV1;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::CellStateOwnerV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio_util::sync::CancellationToken;

use super::CircuitTaskErrorV1 as Error;
use super::CircuitTaskInputProviderV1;
use super::CircuitTaskModeV1;
use super::CircuitTaskReceiptV1;
use super::CircuitTaskRequestV1;
use super::driver::CircuitTaskDriverV1;
use crate::AgentdCircuitCellOwnerV1;
use crate::AgentdError;
use crate::AgentdIdentity;
use crate::AgentdState;
use crate::CircuitCellTimeV1;

struct PendingWork(Arc<AtomicUsize>);

impl Drop for PendingWork {
    fn drop(&mut self) {
        self.0.fetch_sub(1, Ordering::AcqRel);
    }
}

struct Command {
    request: CircuitTaskRequestV1,
    record: RunStartRecordV1,
    mode: CircuitTaskModeV1,
    response: oneshot::Sender<Result<CircuitTaskReceiptV1, Error>>,
    _pending: PendingWork,
}

/// Submission is crate-private: the ordinary signed ingress supplies the
/// retained RunStart. This handle exposes no writer, inference port or fence.
#[derive(Clone)]
pub struct CircuitTaskHandleV1 {
    sender: mpsc::Sender<Command>,
    generation: u64,
    pending: Arc<AtomicUsize>,
}

impl CircuitTaskHandleV1 {
    /// Queue and active lane work, including work whose caller lost its ACK.
    /// Durable unresolved Circuit runs are additional AutomationStore blockers.
    pub fn pending_count(&self) -> usize {
        self.pending.load(Ordering::Acquire)
    }

    pub(crate) async fn submit(
        &self,
        request: CircuitTaskRequestV1,
        record: RunStartRecordV1,
    ) -> Result<CircuitTaskReceiptV1, Error> {
        self.call(request, record, CircuitTaskModeV1::Drive).await
    }

    pub(crate) async fn readback(
        &self,
        request: CircuitTaskRequestV1,
        record: RunStartRecordV1,
    ) -> Result<CircuitTaskReceiptV1, Error> {
        self.call(request, record, CircuitTaskModeV1::Readback)
            .await
    }

    async fn call(
        &self,
        request: CircuitTaskRequestV1,
        record: RunStartRecordV1,
        mode: CircuitTaskModeV1,
    ) -> Result<CircuitTaskReceiptV1, Error> {
        request.validate_record(&record, self.generation)?;
        let (response, receive) = oneshot::channel();
        self.pending.fetch_add(1, Ordering::AcqRel);
        self.sender
            .try_send(Command {
                request,
                record,
                mode,
                response,
                _pending: PendingWork(Arc::clone(&self.pending)),
            })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => Error::QueueFull,
                mpsc::error::TrySendError::Closed(_) => Error::Unavailable,
            })?;
        receive.await.map_err(|_| Error::CommitUncertain)?
    }
}

type OwnerFuture = Pin<Box<dyn Future<Output = Result<(), AgentdError>> + Send>>;
type OwnerLoop =
    Box<dyn FnOnce(AutomationStore, Arc<AgentdState>, CancellationToken) -> OwnerFuture + Send>;

/// Erases only the native owner types. External callers cannot supply a fake
/// completed-task implementation; construction always installs the real driver.
pub struct CircuitTaskRuntimeBootstrapV1 {
    identity: AgentdIdentity,
    handle: CircuitTaskHandleV1,
    owner: OwnerLoop,
}

/// Uses Agentd's original AutomationStore at startup. The injected clock keeps
/// the Cell owner's existing monotonic epoch; Circuit time is never earlier
/// than the freshly authenticated daemon wall clock.
pub fn circuit_task_channel_v1<O, P, E, I, C>(
    identity: &AgentdIdentity,
    fence: TaskFlowFence,
    cells: AgentdCircuitCellOwnerV1<O, P, E>,
    inputs: I,
    mut clock: C,
    capacity: usize,
) -> Result<(CircuitTaskHandleV1, CircuitTaskRuntimeBootstrapV1), AgentdError>
where
    O: CellStateOwnerV1 + Send + 'static,
    P: NeuronInferenceControlPort + CellInferenceReadbackPortV1 + Send + 'static,
    E: CellInputEncoderV1 + Send + 'static,
    I: CircuitTaskInputProviderV1 + 'static,
    C: FnMut() -> CircuitCellTimeV1 + Send + 'static,
{
    TaskFlowFence::new(
        fence.owner_agent_id.clone(),
        &fence.owner_id,
        fence.owner_epoch,
        fence.generation,
        &fence.fencing_token,
    )
    .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    // AgentdState::refresh_generation accepts Running only at spawn + 1;
    // the spawn epoch itself is Starting and cannot authorize a task. Reject a
    // permanently unusable writer pin before installing a ready service.
    if fence.owner_agent_id != identity.agent_id
        || identity.spawn_generation == 0
        || identity.spawn_generation.checked_add(1) != Some(fence.generation)
        || !(1..=64).contains(&capacity)
    {
        return Err(AgentdError::Invalid(
            "Circuit task owner requires exact process scope and a 1..64 queue".into(),
        ));
    }
    let (sender, mut receiver) = mpsc::channel::<Command>(capacity);
    let handle = CircuitTaskHandleV1 {
        sender,
        generation: fence.generation,
        pending: Arc::new(AtomicUsize::new(0)),
    };
    let bootstrap = CircuitTaskRuntimeBootstrapV1 {
        identity: identity.clone(),
        handle: handle.clone(),
        owner: Box::new(move |store, state, cancellation| {
            Box::pin(async move {
                let mut driver = CircuitTaskDriverV1 {
                    store,
                    fence,
                    cells,
                    inputs,
                };
                loop {
                    let command = tokio::select! {
                        _ = cancellation.cancelled() => return Ok(()),
                        command = receiver.recv() => command,
                    };
                    let Some(command) = command else {
                        cancellation.cancelled().await;
                        return Ok(());
                    };
                    if command.response.is_closed() {
                        continue;
                    }
                    let Command {
                        request,
                        record,
                        mode,
                        response,
                        _pending,
                    } = command;
                    let result = match request.validate_record(&record, driver.fence.generation) {
                        Err(error) => Err(error),
                        Ok(()) => {
                            driver
                                .execute(&request, mode, || {
                                    if cancellation.is_cancelled() {
                                        return Err(Error::Unavailable);
                                    }
                                    let now_ms = state
                                        .require_current_run_start(&record)
                                        .map_err(|_| Error::Unavailable)?;
                                    let sampled = clock();
                                    Ok(CircuitCellTimeV1 {
                                        circuit_millis: sampled.circuit_millis.max(now_ms),
                                        cell_micros: sampled.cell_micros,
                                    })
                                })
                                .await
                        }
                    };
                    let _ = response.send(result);
                    // Drop only after synchronous inference and durable driver
                    // work finish, even when the receiver was abandoned.
                    drop(_pending);
                }
            })
        }),
    };
    Ok((handle, bootstrap))
}

impl CircuitTaskRuntimeBootstrapV1 {
    pub(crate) fn handle(&self) -> CircuitTaskHandleV1 {
        self.handle.clone()
    }

    pub(crate) fn require_identity(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if &self.identity != identity {
            return Err(AgentdError::GenerationFenced(
                "Circuit task owner differs from Agentd identity".into(),
            ));
        }
        Ok(())
    }

    pub(crate) async fn run(
        self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
    ) -> Result<(), AgentdError> {
        self.require_identity(state.identity())?;
        let store = state.circuit_task_store()?;
        if store.owner_agent_id() != &self.identity.agent_id {
            return Err(AgentdError::GenerationFenced(
                "Circuit task store differs from Agentd identity".into(),
            ));
        }
        let runtime = tokio::runtime::Handle::current();
        let worker_cancellation = cancellation.child_token();
        let _cancel_on_drop = worker_cancellation.clone().drop_guard();
        tokio::task::spawn_blocking(move || {
            runtime.block_on((self.owner)(store, state, worker_cancellation))
        })
        .await
        .map_err(|error| AgentdError::Protocol(format!("Circuit task owner stopped: {error}")))?
    }
}
