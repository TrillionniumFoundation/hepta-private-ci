//! Publish-to-runtime V13 handoff without exposing the guarded Cell owner.

use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use codex_hepta_neuron::FileAnchorWitnessStore;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeOptionsV1;
use crate::neuron_generation_update_bootstrap::AgentdGenerationUpdateRuntimeV1;
use crate::neuron_generation_update_bootstrap::ReadyAgentdGenerationUpdateV1;
use crate::neuron_v13_generation_bootstrap::owners::V13BackendOwner;

/// A published guarded journal paired with the exact preflighted V13 worker
/// and owned durable control. No caller can replace its port, clock or files.
pub struct ReadyAgentdV13GenerationUpdateV1 {
    ready: ReadyAgentdGenerationUpdateV1<FileAnchorWitnessStore>,
    backend: V13BackendOwner,
}

impl ReadyAgentdV13GenerationUpdateV1 {
    pub(crate) fn new(
        ready: ReadyAgentdGenerationUpdateV1<FileAnchorWitnessStore>,
        backend: V13BackendOwner,
    ) -> Self {
        Self { ready, backend }
    }

    /// Keep the typed handle private until the ordinary runtime is ready.
    /// This writes the stable actual preparation cost before creating the
    /// control actor or exposing any endpoint. Exact reopen adds no cost frame;
    /// independently repeated preparation remains a new measured observation.
    pub fn into_runtime(
        mut self,
        config: AgentdConfig,
        options: AgentdGenerationUpdateRuntimeOptionsV1,
    ) -> Result<AgentdGenerationUpdateRuntimeV1, AgentdError> {
        config.require_neuron_generation_profile()?;
        self.backend.validate_identity(config.identity())?;
        let binding = CellGenerationOwnerBindingV1::new(
            &self.backend.configuration().generation,
            self.backend.configuration().max_records,
        )
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
        if options.queue_capacity != self.backend.configuration().queue_capacity {
            return Err(AgentdError::Invalid(
                "V13 runtime queue differs from its preflighted configuration".into(),
            ));
        }
        self.ready
            .record_backend_preparation(&binding, self.backend.preparation_cost()?)?;
        let (port, clock) = self.backend.spawn()?;
        self.ready
            .into_runtime(config, port, move || clock(), options)
    }
}
