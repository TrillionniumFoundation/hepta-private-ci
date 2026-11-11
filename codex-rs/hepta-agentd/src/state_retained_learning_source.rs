//! Register historical source reads separately from current task execution.

use std::sync::Arc;

use codex_hepta_types::StableId;

use crate::AgentdError;
use crate::AgentdState;
use crate::CircuitTaskLearningReadinessV1;
use crate::cell_q24_task_ledger::RegisteredCellQ24RetainedSourceV1;
use crate::learning_iteration::CircuitLearningSourceV1;

impl AgentdState {
    pub(crate) fn attach_original_retained_learning_source(
        &self,
        source: Arc<RegisteredCellQ24RetainedSourceV1>,
    ) -> Result<(), AgentdError> {
        source.original_outbox(self.identity(), source.request())?;
        self.circuit_learning_source.set(
            crate::circuit_task_learning::RegisteredCircuitLearningSourcesV1 {
                sources: vec![source.source_run_id().clone()],
                origin: CircuitLearningSourceV1::OriginalQ24,
                retained_source: Some(source),
            },
        ).map_err(|_| AgentdError::Invalid("Circuit learning source already attached".into()))
    }

    pub(crate) fn retained_circuit_learning_source(
        &self,
        run: &StableId,
    ) -> Option<&Arc<RegisteredCellQ24RetainedSourceV1>> {
        let registry = self.circuit_learning_source.get()?;
        let source = registry.retained_source.as_ref()?;
        (matches!(registry.origin, CircuitLearningSourceV1::OriginalQ24)
            && registry.sources.as_slice() == std::slice::from_ref(run)
            && source.source_run_id() == run).then_some(source)
    }

    /// The original source supplies the complete RunStart and actual trace.
    /// The successor's Objective journal or database need not contain A.
    pub(crate) async fn reconcile_retained_learning_source(
        &self,
        source: &Arc<RegisteredCellQ24RetainedSourceV1>,
    ) -> Result<(), AgentdError> {
        let ready: crate::OriginalCellQ24RetainedLearningReadyV1 = source.observe_retained_learning(self.identity()).await?;
        self.enqueue_original_circuit_learning(
            source.original_record(), source.original_trace(),
            CircuitTaskLearningReadinessV1::Retained(ready),
        ).await
    }
}
