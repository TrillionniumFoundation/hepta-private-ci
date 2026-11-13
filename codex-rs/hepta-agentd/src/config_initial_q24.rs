//! Select one actual Initial Q24 Circuit profile before any Root publication.

use super::AgentdConfig;
use crate::AgentdError;

impl AgentdConfig {
    pub(crate) fn require_original_initial_q24_configuration(&self) -> Result<(), AgentdError> {
        self.require_no_circuit_task_profile()?;
        self.require_circuit_task_execution_profile()?;
        self.require_unconfigured_production_hosts()?;
        if self.authbus_trust_file.is_none()
            || self.authbus_checkpoint_file.is_none()
            || self.objective_profile_file.is_none()
        {
            return Err(AgentdError::GenerationFenced(
                "Initial Q24 requires original AuthBus, replay checkpoint and Objective inputs"
                    .into(),
            ));
        }
        if self.plasticity_bootstrap.is_some()
            || self.learning_iteration_bootstrap.is_some()
            || self.terminal_learning_bootstrap.is_some()
            || self.neuron_generation_bootstrap.is_some()
            || self.root_learning_inputs.is_some()
        {
            return Err(AgentdError::GenerationFenced(
                "Initial Q24 cannot share an already selected generation or learning profile"
                    .into(),
            ));
        }
        Ok(())
    }
}
