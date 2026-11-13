//! Install the fixed remote Cell path in the original daemon lane. The same
//! AgentdState supplies the original AutomationStore and signed RunStart checks;
//! there is no alternate SQL owner, task journal or raw submission API.

use super::*;
use crate::circuit_task::remote::{DaemonCellPort, DaemonClient, OriginalRootCircuitTaskDaemonInputsV1};

pub(crate) fn channel(identity: &AgentdIdentity, inputs: OriginalRootCircuitTaskDaemonInputsV1)
    -> Result<(CircuitTaskRuntimeBootstrapV1, Arc<DaemonClient>), AgentdError>
{
    let end = std::time::Instant::now() + inputs.lifetime;
    channel_until(identity, inputs, end)
}

pub(crate) fn channel_until(identity: &AgentdIdentity, inputs: OriginalRootCircuitTaskDaemonInputsV1,
    end: std::time::Instant) -> Result<(CircuitTaskRuntimeBootstrapV1, Arc<DaemonClient>), AgentdError>
{
    TaskFlowFence::new(inputs.fence.owner_agent_id.clone(), &inputs.fence.owner_id,
        inputs.fence.owner_epoch, inputs.fence.generation, &inputs.fence.fencing_token)
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let pending = Arc::new(AtomicUsize::new(0));
    let fence = inputs.fence.clone();
    let (client, capacity) = DaemonClient::new_until(identity, inputs, Arc::clone(&pending), end).map_err(agent_error)?;
    let (sender, mut receiver) = mpsc::channel::<Command>(capacity);
    let handle = CircuitTaskHandleV1 { sender, generation: fence.generation, pending,
        original_remote: Some(Arc::clone(&client)) };
    let original: Arc<DaemonClient> = Arc::clone(&client);
    let bootstrap = CircuitTaskRuntimeBootstrapV1 {
        identity: identity.clone(), handle, original_root: None,
        owner: Box::new(move |store, state, cancellation| Box::pin(async move {
            let (reverse, mut reverse_terminal) = original.run_reverse(&state, cancellation.clone())
                .map_err(agent_error)?;
            let result = async {
                let mut driver = CircuitTaskDriverV1 {
                    store, fence, cells: DaemonCellPort::new(Arc::clone(&original)),
                    inputs: Arc::clone(&original),
                };
                loop {
                    let command = tokio::select! {
                        _ = cancellation.cancelled() => return Ok(()),
                        stopped = &mut reverse_terminal => {
                            let detail = match stopped { Ok(Ok(())) => "Root loan stream closed".to_owned(),
                                Ok(Err(error)) => error.to_string(), Err(error) => error.to_string() };
                            return Err(AgentdError::Protocol(format!("original Root loan ended: {detail}")));
                        }
                        command = receiver.recv() => command,
                    };
                    let Some(command) = command else {
                        cancellation.cancelled().await;
                        return Ok(());
                    };
                    if command.response.is_closed() { continue; }
                    let Command { request, record, mode, response, _pending } = command;
                    let result = match request.validate_record(&record, driver.fence.generation) {
                        Err(error) => Err(error),
                        Ok(()) => driver.execute(&request, mode, || {
                            if cancellation.is_cancelled() { return Err(Error::Unavailable); }
                            let now_ms = state.require_current_run_start(&record).map_err(|_| Error::Unavailable)?;
                            let sampled = original.sample_original_clock()?;
                            let sampled = CircuitCellTimeV1 { circuit_millis: sampled.circuit_millis.max(now_ms),
                                cell_micros: sampled.cell_micros };
                            if sampled.circuit_millis == u64::MAX || sampled.cell_micros == u64::MAX {
                                return Err(Error::ReconciliationRequired);
                            }
                            Ok(sampled)
                        }).await,
                    };
                    let _ = response.send(result);
                    drop(_pending);
                }
            }.await;
            original.stop_reverse();
            let joined = reverse.join().map_err(|_| AgentdError::Protocol("original Root loan worker panicked".into()))?;
            if !cancellation.is_cancelled() { joined.map_err(agent_error)?; }
            result
        })),
    };
    Ok((bootstrap, client))
}

fn agent_error(error: Error) -> AgentdError {
    AgentdError::Protocol(format!("original Root task runtime: {error}"))
}
