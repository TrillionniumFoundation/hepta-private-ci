//! Root obtains the existing unsigned model/profile digests before fresh G/O
//! execution. This preview verifies no material, signature or installation.
use super::*;
use codex_hepta_agent_components::intelligence_eval::ConservativeCpuRuntimeProfileV2;
use codex_hepta_agent_components::intelligence_eval::OperationalModelLeaseBindingV2;
use codex_hepta_agent_components::intelligence_eval::OperationalModelUseV2;
use serde::Serialize;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Pins {
    model_generation: u64,
    model_manifest_digest: String,
    weights_digest: String,
    normalization_digest: String,
    encoder_manifest_digest: String,
    tokenizer_digest: String,
    training_code_digest: String,
    source_training_digest: String,
    preregistration_digest: String,
    body_implementation_digest: String,
    purpose: OperationalModelUseV2,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema: String,
    model_pins: Pins,
    runtime_profile: ConservativeCpuRuntimeProfileV2,
}
impl Configuration {
    fn preview(self) -> HostResult<Value> {
        if self.schema != "hepta.cpu-neuron.root-model-use-preview-input.v2" {
            return Err("Root operational model-use preview schema".into());
        }
        let profile_digest = self.runtime_profile.semantic_digest()?;
        let pins = self.model_pins;
        let binding = OperationalModelLeaseBindingV2 {
            model_generation: pins.model_generation,
            model_manifest_digest: pins.model_manifest_digest.parse()?,
            weights_digest: pins.weights_digest.parse()?,
            normalization_digest: pins.normalization_digest.parse()?,
            encoder_manifest_digest: pins.encoder_manifest_digest.parse()?,
            tokenizer_digest: pins.tokenizer_digest.parse()?,
            training_code_digest: pins.training_code_digest.parse()?,
            source_training_digest: pins.source_training_digest.parse()?,
            preregistration_digest: pins.preregistration_digest.parse()?,
            body_implementation_digest: pins.body_implementation_digest.parse()?,
            model_runtime_profile_digest: profile_digest,
            purpose: pins.purpose,
        };
        let binding_digest = binding.binding_digest()?;
        let mut model_binding = serde_json::to_value(pins)?;
        model_binding["model_runtime_profile_digest"] =
            serde_json::to_value(profile_digest.to_string())?;
        Ok(serde_json::json!({
            "schema": "hepta.cpu-neuron.root-model-use-preview.v2",
            "model_binding": model_binding,
            "runtime_profile": self.runtime_profile,
            "runtime_profile_digest": profile_digest.to_string(),
            "binding_digest": binding_digest.to_string(),
            "physical_material_verified": false,
            "signature_issued": false,
            "runtime_admission_issued": false,
        }))
    }
}

pub(super) fn preview(path: &Path, pin: Digest32) -> HostResult<Value> {
    if rustix::process::geteuid().as_raw() != 0 {
        return Err("operational model-use preview requires the Root installer".into());
    }
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(16 * 1024)?;
    let configuration: Configuration = serde_json::from_slice(&bytes)?;
    let mut output = configuration.preview()?;
    if source.read(16 * 1024)? != bytes {
        return Err("Root operational model-use preview changed".into());
    }
    output["configuration"] = serde_json::to_value(source)?;
    Ok(output)
}

#[cfg(test)]
#[path = "initial_cpu_model_use_preview_v2_tests.rs"]
mod tests;
