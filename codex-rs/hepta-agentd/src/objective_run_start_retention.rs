//! Join the actual append/sync receipt to the original Root before executing A.
//! A retained data cut never substitutes today's readiness or AuthBus checks.

use super::*;
use crate::production_launcher::run_start_retention::OriginalInitialRunStartRetainerV1;

impl ObjectiveRuntimeHost {
    pub(crate) fn with_original_run_start_retention(
        mut self,
        retained: OriginalInitialRunStartRetainerV1,
    ) -> Result<Self, AgentdError> {
        if self.original_run_start_retention.is_some() {
            return Err(invalid("original RunStart retainer already installed"));
        }
        self.original_run_start_retention = Some(retained);
        Ok(self)
    }

    pub(super) async fn retain_original_run_start_before_execution(
        &self,
        agentd: &AgentdState,
        record: &RunStartRecordV1,
        published: &codex_hepta_intelligence::PublishedObjectiveRunV1,
    ) -> Result<(), AgentdError> {
        let Some(retained) = &self.original_run_start_retention else {
            return Ok(());
        };
        if retained.identity != *agentd.identity() || !agentd.circuit_task_enabled() {
            return Err(invalid("original RunStart retainer left its Q24 runtime"));
        }
        retained
            .retain_live_append(record.clone(), published.clone())
            .await?;
        authbus_ingress::require_objective_ready(agentd)?;
        let generation = agentd.current_generation()?;
        if record.snapshot.generation != generation
            || record.snapshot.fence_digest != objective_fence(agentd.identity(), generation)
        {
            return Err(AgentdError::GenerationFenced(
                "objective generation changed during original Root retention".into(),
            ));
        }
        let current = authbus_ingress::attached(agentd)?.trust(agentd)?;
        if !authentication_is_current(
            record,
            &current,
            agentd.identity(),
            authbus_ingress::now_ms()?,
        )? {
            return Err(invalid(
                "objective trust changed during original Root retention",
            ));
        }
        Ok(())
    }
}
