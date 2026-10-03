//! Preserve the complete enrolled search and policy; update only the original
//! numerical norm measured from the actual current sparse parameters.
use super::*;
use codex_hepta_agent_components::plasticity::*;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::sparse_parameter_norm_denominator_v1;

pub(super) fn project(
    blueprint: &blueprint::Blueprint,
    material: &NeuronGenerationMaterialV2,
    public: &Path,
) -> Result<InstalledCpuSourceV1> {
    let bytes = configuration::source(&blueprint.search_shape, 32 * 1024)?;
    let mut profile = decode_untrusted_parameter_generator_profile_v3(&bytes)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    ensure!(
        profile.selected_artifact_digest == material.native.model_digest
            && profile.mutation_policy.selected_artifact_digest == material.native.model_digest
            && profile.mutation_policy.window == profile.window
            && profile.norm_layers.len() == 1
            && profile.norm_layers[0].layer_id.as_str() == "neuron.sparse.rates.q24.v1",
        "actual head content/window needs independently published policy or enrolled shape"
    );
    profile.norm_layers[0].baseline_squared_l2_raw_q64 =
        sparse_parameter_norm_denominator_v1(&material.native)
            .map_err(|error| anyhow::anyhow!("{error}"))?;
    let projected = encode_untrusted_parameter_generator_profile_v3(&profile)
        .map_err(|error| anyhow::anyhow!("{error}"))?;
    let pin = Digest32::of_bytes(&projected);
    let source = original_facts::publish(
        public,
        &format!("actual-search-{pin}.bin"),
        &projected,
        32 * 1024,
    )?;
    ensure!(
        configuration::source(&blueprint.search_shape, 32 * 1024)? == bytes,
        "whole original search/policy Source changed"
    );
    Ok(source)
}
