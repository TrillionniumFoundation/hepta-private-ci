//! Explicit historical source admission for one already registered Root scope.
//! The old issuer is checked against today's trust at its original admission
//! time; neither that time nor its identity is used to authorize a new task.

use super::*;
use crate::cell_q24_task_ledger::RegisteredCellQ24RetainedSourceV1;

impl AgentdState {
    pub(super) async fn require_registered_retained_source(
        &self,
        request: &LearningIterationRequestV1,
        source: &std::sync::Arc<RegisteredCellQ24RetainedSourceV1>,
    ) -> Result<(), AgentdError> {
        let store = source.original_outbox(self.identity(), request)?;
        let observed: crate::OriginalCellQ24RetainedLearningReadyV1 =
            source.observe_retained_learning(self.identity()).await?;
        let record = source.original_record();
        self.require_retained_source_authentication(source)?;
        let delivery = store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await
            .map_err(|error| invalid(&format!("original retained outbox: {error:?}")))?
            .ok_or_else(|| invalid("original retained completion intent is missing"))?;
        let intent = &delivery.intent;
        if intent.source_run_id != request.source_run_id.as_str()
            || intent.operation_id != request.operation_id.as_str()
            || intent.completed_task_receipt.as_str() != request.completed_task_receipt.to_string()
            || intent.objective_digest.as_str() != request.envelope.objective_digest.to_string()
        {
            return Err(invalid(
                "retained request differs from its original completion",
            ));
        }
        let trace = store
            .bounded_circuit_committed_trace(request.source_run_id.as_str())
            .await
            .map_err(|error| invalid(&format!("original retained trace: {error}")))?
            .ok_or_else(|| invalid("original retained Circuit history is missing"))?;
        observed
            .require_retained_task(source, self.identity(), record, &trace)
            .await?;
        let current = store
            .circuit_learning_delivery(request.source_run_id.as_str())
            .await
            .map_err(|error| invalid(&format!("original retained outbox recheck: {error:?}")))?
            .ok_or_else(|| invalid("original retained completion intent disappeared"))?;
        if current.intent != delivery.intent {
            return Err(invalid("original retained completion changed"));
        }
        observed
            .require_retained_task(source, self.identity(), record, &trace)
            .await?;
        self.require_retained_source_authentication(source)
    }

    fn require_retained_source_authentication(
        &self,
        source: &RegisteredCellQ24RetainedSourceV1,
    ) -> Result<(), AgentdError> {
        authbus_ingress::require_objective_ready(self)?;
        let trust = authbus_ingress::attached(self)?.trust(self)?;
        authenticate_learning_source_at(
            source.original_record(),
            &trust,
            source.original_identity(),
            authbus_ingress::now_ms()?,
        )
    }
}
