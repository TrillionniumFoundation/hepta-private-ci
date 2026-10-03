//! Compatibility entry points delegate to the sole original Neuron codec.
use crate::CpuNeuronGenerationPlanV1;
use codex_hepta_agentd::AgentdError;
pub use codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as MAX_CPU_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_neuron::NeuronGenerationMaterialErrorV2;

pub fn encode_cpu_neuron_generation_material_v2(
    plan: &CpuNeuronGenerationPlanV1,
) -> Result<Vec<u8>, AgentdError> {
    codex_hepta_neuron::encode_neuron_generation_material_v2(plan).map_err(map_error)
}
pub fn decode_cpu_neuron_generation_material_v2(
    bytes: &[u8],
) -> Result<CpuNeuronGenerationPlanV1, AgentdError> {
    codex_hepta_neuron::decode_neuron_generation_material_v2(bytes).map_err(map_error)
}
pub(crate) fn map_error(error: NeuronGenerationMaterialErrorV2) -> AgentdError {
    match error {
        NeuronGenerationMaterialErrorV2::Invalid(message) => AgentdError::Invalid(message),
        NeuronGenerationMaterialErrorV2::Json(error) => AgentdError::Json(error),
    }
}
#[cfg(test)]
#[path = "local_cpu_generation_material_codec_v2_tests.rs"]
mod tests;
