//! Explicit ordinary-task Circuit profile, paired with its sole Cell owner.

use std::sync::Arc;

use super::AgentdConfig;
use crate::AgentdCircuitTaskInvocationProviderV1;
use crate::AgentdError;
use crate::CircuitTaskRuntimeBootstrapV1;

type CircuitTaskCompositionV1 = (
    CircuitTaskRuntimeBootstrapV1,
    Arc<dyn AgentdCircuitTaskInvocationProviderV1>,
);

impl AgentdConfig {
    /// Select Circuit execution for ordinary authenticated ObjectiveStart.
    /// The embedding supplies original Cell owners, current model controls and
    /// a durable input/result provider. No signer or evaluator is inferred.
    pub fn with_circuit_task_bootstrap(
        mut self,
        bootstrap: CircuitTaskRuntimeBootstrapV1,
        invocation: Arc<dyn AgentdCircuitTaskInvocationProviderV1>,
    ) -> Result<Self, AgentdError> {
        self.require_no_circuit_task_profile()?;
        self.require_circuit_task_execution_profile()?;
        bootstrap.require_identity(&self.identity)?;
        self.circuit_task_bootstrap = Some(bootstrap);
        self.circuit_task_invocation = Some(invocation);
        Ok(self)
    }

    pub(super) fn require_no_circuit_task_profile(&self) -> Result<(), AgentdError> {
        if self.circuit_task_bootstrap.is_some() || self.circuit_task_invocation.is_some() {
            return Err(AgentdError::Invalid(
                "Circuit task execution profile is already selected".into(),
            ));
        }
        Ok(())
    }

    pub(super) fn require_circuit_task_execution_profile(&self) -> Result<(), AgentdError> {
        #[cfg(target_os = "linux")]
        if self.notes_ui.is_some()
            || self.notes_thread_tools.is_some()
            || self.desktop_thread_tools.is_some()
        {
            return Err(AgentdError::Invalid(
                "Circuit tasks cannot share a finite application execution profile".into(),
            ));
        }
        if self.notes_objective.is_some()
            || self.desktop_objective.is_some()
            || self.intelligence_product_runner.is_some()
            || self.intelligence_invocation_provider.is_some()
        {
            return Err(AgentdError::Invalid(
                "Circuit tasks require one explicit ordinary execution profile".into(),
            ));
        }
        Ok(())
    }

    pub(crate) fn take_circuit_task_bootstrap(
        &mut self,
    ) -> Result<Option<CircuitTaskCompositionV1>, AgentdError> {
        match (&self.circuit_task_bootstrap, &self.circuit_task_invocation) {
            (None, None) => return Ok(None),
            (Some(bootstrap), Some(_)) => bootstrap.require_identity(&self.identity)?,
            _ => {
                return Err(AgentdError::Invalid(
                    "incomplete Circuit task profile".into(),
                ));
            }
        }
        self.require_circuit_task_execution_profile()?;
        if self.authbus_trust_file.is_none()
            || self.authbus_checkpoint_file.is_none()
            || self.objective_profile_file.is_none()
        {
            return Err(AgentdError::Invalid(
                "Circuit task execution requires AuthBus trust, replay checkpoint and objective profile".into(),
            ));
        }
        Ok(self
            .circuit_task_bootstrap
            .take()
            .zip(self.circuit_task_invocation.take()))
    }
}
