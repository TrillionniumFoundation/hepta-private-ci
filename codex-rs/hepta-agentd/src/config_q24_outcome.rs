//! The original task composition transfers its actual producer into runtime.

use std::sync::Arc;

use super::AgentdConfig;
use crate::AgentdError;
use crate::OriginalCellQ24TaskLedgerProducerV1;

impl AgentdConfig {
    pub(crate) fn with_original_q24_outcome_control(
        mut self,
        producer: Arc<OriginalCellQ24TaskLedgerProducerV1>,
    ) -> Result<Self, AgentdError> {
        if self.original_q24_outcome_control.is_some()
            || self.circuit_task_bootstrap.is_none()
            || self.circuit_task_invocation.is_none()
        {
            return Err(AgentdError::Invalid(
                "original Q24 Outcome requires its unique installed task owner".into(),
            ));
        }
        producer.require_original_control_identity(self.identity())?;
        self.original_q24_outcome_control = Some(producer);
        Ok(self)
    }

    pub(crate) fn take_original_q24_outcome_control(
        &mut self,
    ) -> Option<Arc<OriginalCellQ24TaskLedgerProducerV1>> {
        self.original_q24_outcome_control.take()
    }
}
