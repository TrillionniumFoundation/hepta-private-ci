//! One physical tuple check for fresh Root publication and independent S use.
use super::*;
use codex_hepta_agent_components::intelligence_eval::OperationalModelUseV2;
use codex_hepta_agent_components::intelligence_eval::VerifiedOperationalModelLeaseV2;

pub(super) fn verify(
    installed: &Inputs,
    lease: &VerifiedOperationalModelLeaseV2,
    body_implementation: &Source,
) -> HostResult<()> {
    let binding = lease.binding();
    let profile = lease.runtime_profile();
    let runtime = &installed.runtime;
    if binding.purpose != OperationalModelUseV2::ConservativeCpuAbstentionOnlyV1
        || binding.model_generation != runtime.generation.get()
        || binding.model_generation != 1
        || binding.model_manifest_digest != digest(&installed.profile.model.digest)?
        || binding.weights_digest != digest(&installed.profile.weights.digest)?
        || binding.training_code_digest != digest(&installed.profile.training_code.digest)?
        || binding.source_training_digest
            != digest(
                installed.evidence.measurements()["source_training_digest"]
                    .as_str()
                    .ok_or("original installed training source")?,
            )?
        || binding.normalization_digest != runtime.normalization_digest
        || binding.body_implementation_digest != digest(&body_implementation.digest)?
        || profile.input_feature_dimension as usize != runtime.input_feature_dimension
        || profile.state_width as usize != runtime.state_width
        || profile.modulator_dimension as usize != runtime.modulator_dimension
        || profile.p95_latency_micros != runtime.resource_envelope.p95_latency_micros
        || profile.p99_latency_micros != runtime.resource_envelope.p99_latency_micros
        || profile.transient_allocation_bytes
            != runtime.resource_envelope.transient_allocation_bytes
        || profile.checkpoint_bytes != runtime.resource_envelope.checkpoint_bytes
        || profile.write_amplification_ppm != runtime.resource_envelope.write_amplification_ppm
        || serde_json::to_value(&profile.calibration_gates)?
            != installed.evidence.measurements()["initial_product_gates"]
    {
        return Err("stable E model use differs from the current installed CPU tuple".into());
    }
    Ok(())
}
