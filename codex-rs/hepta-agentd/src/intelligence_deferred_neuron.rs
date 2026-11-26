use super::*;
use crate::neuron_runtime_v2::AgentdDeferredNeuronInvocationV2;

impl DurableNeuronInvocation for AgentdDeferredNeuronInvocationV2 {
    fn runtime_body_digest(&self) -> Digest32 {
        AgentdDeferredNeuronInvocationV2::runtime_body_digest(self)
    }

    fn matches_run(&self, run_id: &StableId, body_generation: u64) -> bool {
        AgentdDeferredNeuronInvocationV2::matches_run(self, run_id, body_generation)
    }

    fn execute_stage(
        &self,
        input: &CanonicalPortInputV1,
        guard: &mut dyn NeuronAdmissionGuard,
    ) -> Result<AgentdNeuronStageResult, AgentdNeuronStageError> {
        let commit = self
            .execute(input, guard)
            .map_err(AgentdNeuronStageError::Unified)?;
        Ok(AgentdNeuronStageResult {
            output: commit.output,
            disposition: commit.disposition,
            operation_digest: Some(commit.operation_digest),
        })
    }
}

impl AgentdIntelligenceProductRunnerV1 {
    pub(crate) async fn prepare_for_composition_with_deferred_neuron_v2(
        &self,
        composition: &crate::RuntimeComposition,
        request: CanonicalIntelligenceRunRequestV1,
        inputs: AgentdIntelligenceOwnerInputsV1,
        neuron: AgentdDeferredNeuronInvocationV2,
    ) -> Result<AgentdIntelligenceProductOutcomeV1, AgentdIntelligenceProductError> {
        self.prepare_with_durable_neuron(composition, request, inputs, neuron)
            .await
    }
}
