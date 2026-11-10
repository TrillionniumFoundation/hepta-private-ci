//! Installs the actual Q24 ordinary-task composition in the normal daemon.

use codex_hepta_neuron::AnchorWitnessStore;

use super::AgentdConfig;
use crate::AgentdError;
use crate::AgentdQ24CircuitTaskRuntimeV1;
use crate::CircuitQ24TaskProfileV1;
use crate::circuit_q24_task_channel_v1;

impl AgentdConfig {
    pub fn with_q24_circuit_task_profile<SW, CW>(
        self,
        profile: CircuitQ24TaskProfileV1<SW, CW>,
    ) -> Result<AgentdQ24CircuitTaskRuntimeV1<SW, CW>, AgentdError>
    where
        SW: AnchorWitnessStore + Send + 'static,
        CW: AnchorWitnessStore + Send + 'static,
    {
        self.require_no_circuit_task_profile()?;
        self.require_circuit_task_execution_profile()?;
        let runtime = circuit_q24_task_channel_v1(self.identity(), profile)?;
        let source = runtime.source();
        let cell = runtime.cell();
        let config = runtime.install(self)?;
        Ok(AgentdQ24CircuitTaskRuntimeV1 { config, source, cell })
    }
}
