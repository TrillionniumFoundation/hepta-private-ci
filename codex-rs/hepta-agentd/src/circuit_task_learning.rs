//! A committed business task and learning readiness have separate outcomes.
//! Only an original Q24 producer can construct its opaque Ready observation.
//! Explicit older stage-owner profiles keep their existing completion contract.

use std::sync::Arc;

use codex_hepta_automation::CircuitCommittedTraceV2;
use codex_hepta_learning_ledger::RunStartRecordV1;

use crate::AgentdError;
use crate::AgentdState;
use crate::learning_iteration::CircuitLearningSourceV1;

pub(crate) struct RegisteredCircuitLearningSourcesV1 {
    pub(crate) sources: Vec<codex_hepta_types::StableId>,
    pub(crate) origin: CircuitLearningSourceV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CircuitTaskLearningPendingV1 {
    TerminalOutcome,
    CommitUncertain,
    OwnerUnavailable,
    Refused(String),
}

pub enum CircuitTaskLearningReadinessV1 {
    NonLearning,
    Pending(CircuitTaskLearningPendingV1),
    #[cfg(target_os = "linux")]
    Ready(crate::OriginalCellQ24TaskLearningReadyV1),
}

impl AgentdState {
    /// This may finish the original learning journal/ledger only. Task execution
    /// has already completed; no error here authorizes a second dispatch.
    pub(crate) async fn observe_circuit_learning(
        &self,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> CircuitTaskLearningReadinessV1 {
        let Some(provider) = self.circuit_task_invocation.get() else {
            return CircuitTaskLearningReadinessV1::Pending(
                CircuitTaskLearningPendingV1::OwnerUnavailable,
            );
        };
        let provider: Arc<dyn crate::AgentdCircuitTaskInvocationProviderV1> = Arc::clone(provider);
        let identity = self.identity().clone();
        let record = record.clone();
        let trace = trace.clone();
        match tokio::task::spawn_blocking(move || {
            provider.observe_learning(&identity, &record, &trace)
        })
        .await
        {
            Ok(value) => value,
            Err(error) => CircuitTaskLearningReadinessV1::Pending(
                CircuitTaskLearningPendingV1::Refused(format!(
                    "original learning owner observation stopped: {error}"
                )),
            ),
        }
    }

    /// Only a source explicitly selected by the original learning bootstrap can
    /// enqueue. Q24 requires its original producer; an absent cap is never a
    /// request to downgrade to the older host-stage or Objective contract.
    pub(crate) async fn enqueue_original_circuit_learning(
        &self,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
        readiness: CircuitTaskLearningReadinessV1,
    ) -> Result<(), AgentdError> {
        let origin = self.circuit_learning_origin(&record.snapshot.run_id);
        match readiness {
            CircuitTaskLearningReadinessV1::NonLearning => {
                if matches!(origin, Some(CircuitLearningSourceV1::OriginalQ24)) {
                    eprintln!(
                        "Q24 learning is pending: original producer unavailable (run_id={}, task_committed=true)",
                        record.snapshot.run_id
                    );
                    return Ok(());
                }
                if origin.is_none() {
                    return Ok(());
                }
                // This contract was selected by an actual original bootstrap.
                // It is not a Q24 Ready capability or an inferred role grant.
            }
            CircuitTaskLearningReadinessV1::Pending(reason) => {
                eprintln!(
                    "committed task awaits its original learning owner (run_id={}, task_committed=true, learning_pending={reason:?})",
                    record.snapshot.run_id
                );
                return Ok(());
            }
            #[cfg(target_os = "linux")]
            CircuitTaskLearningReadinessV1::Ready(ready) => {
                let ready: crate::OriginalCellQ24TaskLearningReadyV1 = ready;
                if origin.is_none() {
                    return Ok(());
                }
                ready.require_task(self.identity(), record, trace)?;
                self.enqueue_circuit_learning_pointer(record, trace).await?;
                ready.require_task(self.identity(), record, trace)?;
                return Ok(());
            }
        }
        self.enqueue_circuit_learning_pointer(record, trace).await
    }

    async fn enqueue_circuit_learning_pointer(
        &self,
        record: &RunStartRecordV1,
        trace: &CircuitCommittedTraceV2,
    ) -> Result<(), AgentdError> {
        if trace.run().run_id() != record.snapshot.run_id.as_str()
            || trace.run().outcome().is_none()
            || trace.run().unresolved() != 0
        {
            return Err(AgentdError::Protocol(
                "original learning completion differs from RunStart".into(),
            ));
        }
        let objective = codex_hepta_contracts::Sha256Digest::parse(
            record.snapshot.objective_digest.to_string(),
        )
        .map_err(|error| AgentdError::Protocol(format!("Circuit learning objective: {error}")))?;
        self.circuit_task_store()?
            .enqueue_circuit_learning(trace, objective)
            .await
            .map_err(|error| AgentdError::Protocol(format!(
                "task committed; Circuit learning outbox remains pending: {error:?}"
            )))?;
        Ok(())
    }
}
