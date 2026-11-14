//! The live append hook can only accompany the original configured Q24 task.

use super::AgentdConfig;
use crate::AgentdError;
use crate::production_launcher::run_start_retention::OriginalInitialRunStartRetainerV1;

impl AgentdConfig {
    pub(crate) fn install_original_run_start_retention(
        &mut self,
        retained: OriginalInitialRunStartRetainerV1,
    ) -> Result<(), AgentdError> {
        if self.original_run_start_retention.is_some()
            || self.original_source_capture.is_none()
            || self.original_source_close.is_none()
            || self.circuit_task_bootstrap.is_none()
            || self.circuit_task_invocation.is_none()
            || self.objective_profile_file.is_none()
            || self.authbus_trust_file.is_none()
            || self.authbus_checkpoint_file.is_none()
            || retained.identity != self.identity
        {
            return Err(AgentdError::Invalid(
                "original RunStart retention requires its complete Q24 runtime".into(),
            ));
        }
        self.original_run_start_retention = Some(retained);
        Ok(())
    }

    pub(crate) fn take_original_run_start_retention(
        &mut self,
    ) -> Option<OriginalInitialRunStartRetainerV1> {
        self.original_run_start_retention.take()
    }
}
