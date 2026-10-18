// Whole live operation inspection through the original current controller.
// Cold archives and model-advice receipts cannot satisfy this boundary.
impl AgentdNeuronGenerationControllerV2 {
    pub fn export_current_operation_v2(
        &self,
        generation: AgentdNeuronGenerationIdV2,
        configuration: Digest32,
        body: Digest32,
        scope: codex_hepta_agent_components::neuron::JournalScope,
        operation: &AgentdNeuronOperationIdentityV2,
    ) -> Result<
        codex_hepta_agent_components::neuron::NeuronAcknowledgedOperationV2,
        AgentdNeuronControlErrorV2,
    > {
        let state = self.lock_state()?;
        if state.lifecycle != AgentdNeuronLifecycleStateV2::Serving {
            return Err(AgentdNeuronControlErrorV2::InvalidTransition);
        }
        if state.active.generation()? != generation.get()
            || state.active.configuration_digest() != configuration
            || state.active.body_bundle_digest() != Some(body)
        {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        // Hold the existing controller while the original serialized runtime
        // resolves its exact key. A concurrent reload cannot substitute an owner.
        let exported = state
            .active
            .owner
            .export_operation_control(operation.tick_id(), operation.input_semantic_digest())?;
        if exported.generation() != generation.get()
            || exported.record().config_semantic_digest != configuration
            || exported.record().body_bundle_digest != body
            || exported.scope() != scope
        {
            return Err(AgentdNeuronControlErrorV2::GenerationConflict);
        }
        Ok(exported)
    }
}
impl AgentdNeuronRuntimeV2Host {
    pub fn export_current_operation_v2(
        &self,
        generation: AgentdNeuronGenerationIdV2,
        configuration: Digest32,
        body: Digest32,
        scope: codex_hepta_agent_components::neuron::JournalScope,
        operation: &AgentdNeuronOperationIdentityV2,
    ) -> Result<
        codex_hepta_agent_components::neuron::NeuronAcknowledgedOperationV2,
        crate::AgentdError,
    > {
        self.controller
            .export_current_operation_v2(generation, configuration, body, scope, operation)
            .map_err(|error| neuron_product_error("current whole operation inspection", error))
    }
}
