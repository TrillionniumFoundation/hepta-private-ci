//! The ordinary Config remains in the non-Root daemon. Install the fixed
//! remote Cell bootstrap and invocation through all original profile guards.

use super::AgentdConfig;
use crate::{AgentdError, OriginalRootCircuitTaskDaemonInputsV1};

impl AgentdConfig {
    pub(crate) fn with_original_root_circuit_task_until(
        self, inputs: crate::OriginalRootCircuitTaskDaemonInputsV1, end: std::time::Instant,
    ) -> Result<Self, AgentdError> {
        self.require_no_circuit_task_profile()?;
        self.require_circuit_task_execution_profile()?;
        let (bootstrap, invocation) = crate::circuit_task::original_remote_channel_until(
            self.identity(), inputs, end)?;
        self.with_circuit_task_bootstrap(bootstrap, invocation)
    }

    pub fn with_original_root_circuit_task(self, inputs: OriginalRootCircuitTaskDaemonInputsV1)
        -> Result<Self, AgentdError>
    {
        self.require_no_circuit_task_profile()?;
        self.require_circuit_task_execution_profile()?;
        let (bootstrap, invocation) = crate::circuit_task::original_remote_channel(
            self.identity(), inputs,
        )?;
        self.with_circuit_task_bootstrap(bootstrap, invocation)
    }
}
