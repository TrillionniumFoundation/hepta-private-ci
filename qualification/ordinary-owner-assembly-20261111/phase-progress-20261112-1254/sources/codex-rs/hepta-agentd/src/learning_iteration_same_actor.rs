//! Run the actual scoped learning process under its original phase deadline.
//! The default worker, budget checks, authentication and process stay intact.

use super::*;
use crate::same_actor_q24_phase_learning::OriginalSameActorLearningWork;

impl LearningIterationRuntimeBootstrapV1 {
    pub(crate) async fn run_original_same_actor(
        mut self,
        state: Arc<AgentdState>,
        cancellation: CancellationToken,
        phase: Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        let _closing = phase.original_failure_scope();
        let result = self
            .run_original_same_actor_commands(&state, &cancellation, &phase)
            .await;
        // Returning from the command loop has already dropped its in-progress
        // process future, running the original Training/aggregate cancel guards.
        // The actual blocking JoinHandles remain owned by this same phase.
        phase.gate().close();
        let joined = phase.close_and_join_original_work().await;
        match (result, joined) {
            (Err(error), Err(join)) => Err(AgentdError::GenerationFenced(format!(
                "{error}; original learning cleanup: {join}"
            ))),
            (Err(error), Ok(())) => Err(error),
            (Ok(()), result) => result,
        }
    }

    async fn run_original_same_actor_commands(
        &mut self,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        phase: &Arc<OriginalSameActorLearningWork>,
    ) -> Result<(), AgentdError> {
        self.require_identity(state.identity())?;
        phase.require_identity_and_gate(state.identity(), phase.gate())?;
        let original: &Arc<crate::OriginalCellQ24LearningStageOwnersV1> =
            self.original_q24.as_ref().ok_or_else(|| {
                AgentdError::GenerationFenced(
                    "same-actor learning requires its actual original Q24 aggregate".into(),
                )
            })?;
        original.require_original_same_actor_work(phase)
            .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
        loop {
            phase
                .require_original_work_entry()
                .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
            let command = tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = phase.gate().cancelled() => {
                    return Err(AgentdError::GenerationFenced(
                        "original learning phase closed".into(),
                    ));
                }
                _ = tokio::time::sleep_until(
                    tokio::time::Instant::from_std(phase.gate().deadline().instant()),
                ) => {
                    return Err(AgentdError::GenerationFenced(
                        "original learning phase expired".into(),
                    ));
                }
                command = self.receiver.recv() => command,
            };
            let Some(command) = command else {
                return Err(AgentdError::GenerationFenced("original learning queue closed".into()));
            };
            let LearningIterationCommandV1 { mode, request, mut response } = command;
            if response.is_closed() {
                return Err(AgentdError::GenerationFenced(
                    "original learning caller disappeared before dispatch".into(),
                ));
            }
            // Both timeout layers retain their original purposes. The existing
            // request/readback budget is unchanged, and this outer absolute end
            // was fixed by the original receive; it is never now + remaining.
            let result = {
                let process = tokio::time::timeout_at(
                    tokio::time::Instant::from_std(phase.gate().deadline().instant()),
                    self.process_with_deadline(state, *request, mode),
                );
                tokio::pin!(process);
                tokio::select! {
                    _ = cancellation.cancelled() => Err(LearningIterationRuntimeErrorV1::CommitUncertain),
                    _ = phase.gate().cancelled() => Err(LearningIterationRuntimeErrorV1::CommitUncertain),
                    _ = response.closed() => Err(LearningIterationRuntimeErrorV1::CommitUncertain),
                    result = &mut process => result
                        .map_err(|_| LearningIterationRuntimeErrorV1::CommitUncertain)
                        .and_then(|result| result),
                }
            };
            if let Err(error) = &result {
                let cause = error.to_string();
                phase.gate().close();
                // Preserve the original typed response; cleanup does not turn
                // a failed, pending or uncertain stage into NoUpdate.
                let joined = phase.close_and_join_original_work().await;
                let _ = response.send(result);
                return Err(AgentdError::GenerationFenced(match joined {
                    Ok(()) => cause,
                    Err(join) => format!("{cause}; original learning cleanup: {join}"),
                }));
            }
            phase
                .require_original_work_entry()
                .map_err(|error| AgentdError::GenerationFenced(error.to_string()))?;
            if response.send(result).is_err() {
                return Err(AgentdError::GenerationFenced(
                    "original learning result acknowledgement was lost".into(),
                ));
            }
        }
    }
}
