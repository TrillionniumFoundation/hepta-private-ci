// Read current eligibility through the original Serving controller. A prior
// operation's prepared bytes and retired archives cannot supply this fact.
impl AgentdNeuronGenerationControllerV2 {
    pub fn current_sparse_checkpoint_v2(
        &self,
        generation: AgentdNeuronGenerationIdV2,
        configuration: Digest32,
        body: Digest32,
        scope: codex_hepta_agent_components::neuron::JournalScope,
        required_anchor: codex_hepta_agent_components::neuron::JournalAnchor,
    ) -> Result<
        Option<codex_hepta_agent_components::neuron::SparseCheckpoint>,
        AgentdNeuronControlErrorV2,
    > {
        let state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Serving {
            return Err(AgentdNeuronControlErrorV2::NotServing);
        }
        if state.active.generation()? != generation.get()
            || state.active.configuration_digest() != configuration
            || state.active.body_bundle_digest() != Some(body)
        {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        let (actual_generation, actual_scope, checkpoint) = state
            .active
            .owner
            .current_sparse_checkpoint_control(required_anchor)?;
        if actual_generation.get() != generation.get() || actual_scope != scope {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        Ok(checkpoint)
    }
}
impl AgentdNeuronRuntimeV2Host {
    /// Read current owner state without holding the Goal driver or dispatching.
    pub fn current_sparse_checkpoint_v2(
        &self,
        generation: AgentdNeuronGenerationIdV2,
        configuration: Digest32,
        body: Digest32,
        scope: codex_hepta_agent_components::neuron::JournalScope,
        required_anchor: codex_hepta_agent_components::neuron::JournalAnchor,
    ) -> Result<Option<codex_hepta_agent_components::neuron::SparseCheckpoint>, crate::AgentdError>
    {
        self.controller
            .current_sparse_checkpoint_v2(generation, configuration, body, scope, required_anchor)
            .map_err(|error| neuron_product_error("current sparse checkpoint inspection", error))
    }
}
