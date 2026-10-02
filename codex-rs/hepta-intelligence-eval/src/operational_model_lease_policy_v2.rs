//! Root-frozen stable-model policy; no Goal digest or promotion scope is accepted.
use crate::ConservativeCpuRuntimeProfileV2;
use crate::OperationalModelLeaseBindingV2;
use crate::OperationalModelUseV2;
use crate::initial_neuron_operational_host::Config;
use crate::initial_neuron_operational_host::OperationalInputs;
use crate::initial_neuron_operational_host::Policy as NativePolicy;
use crate::initial_neuron_operational_host::inspect_inputs_with_policy;
use crate::initial_neuron_operational_metrics::Gates;
use crate::initial_neuron_operational_source::HostResult;
use crate::operational_model_lease_material_v2::MaterialSources;
use crate::operational_model_lease_material_v2::VerifiedMaterial;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::sync::Arc;

pub(super) const CONFIG_SCHEMA: &str = "hepta.fixed-operational-model-lease-evaluator-config.v2";
pub(super) const CLAIM: &str = "operational-model-lease;training-source-reused;no-unseen-holdout;no-primary-superiority;cpu-abstention-only";

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct BindingWire {
    pub model_generation: u64,
    pub model_manifest_digest: String,
    pub weights_digest: String,
    pub normalization_digest: String,
    pub encoder_manifest_digest: String,
    pub tokenizer_digest: String,
    pub training_code_digest: String,
    pub source_training_digest: String,
    pub preregistration_digest: String,
    pub body_implementation_digest: String,
    pub model_runtime_profile_digest: String,
    pub purpose: OperationalModelUseV2,
}
impl BindingWire {
    pub(super) fn native(&self) -> HostResult<OperationalModelLeaseBindingV2> {
        let binding = OperationalModelLeaseBindingV2 {
            model_generation: self.model_generation,
            model_manifest_digest: self.model_manifest_digest.parse()?,
            weights_digest: self.weights_digest.parse()?,
            normalization_digest: self.normalization_digest.parse()?,
            encoder_manifest_digest: self.encoder_manifest_digest.parse()?,
            tokenizer_digest: self.tokenizer_digest.parse()?,
            training_code_digest: self.training_code_digest.parse()?,
            source_training_digest: self.source_training_digest.parse()?,
            preregistration_digest: self.preregistration_digest.parse()?,
            body_implementation_digest: self.body_implementation_digest.parse()?,
            model_runtime_profile_digest: self.model_runtime_profile_digest.parse()?,
            purpose: self.purpose,
        };
        binding.validate()?;
        Ok(binding)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Policy {
    pub schema: String,
    pub scope_digest: String,
    pub binding: BindingWire,
    pub runtime_profile: ConservativeCpuRuntimeProfileV2,
    pub material: MaterialSources,
    pub frozen_at_ms: u64,
    pub expires_at_ms: u64,
    pub calibration_rows: usize,
    pub ood_rows: usize,
}
impl Policy {
    pub(super) fn validate(&self, now: u64) -> HostResult<OperationalModelLeaseBindingV2> {
        let binding = self.binding.native()?;
        if self.schema != "hepta.cpu-neuron.operational-model-lease-policy.v2"
            || self.scope_digest.parse::<Digest32>()?.is_zero()
            || self.frozen_at_ms == 0
            || self.frozen_at_ms > now
            || self.expires_at_ms <= now
            || self.expires_at_ms.saturating_sub(self.frozen_at_ms) > 86_400_000
            || !(20..=2048).contains(&self.calibration_rows)
            || !(20..=2048).contains(&self.ood_rows)
            || self.runtime_profile.semantic_digest()? != binding.model_runtime_profile_digest
        {
            return Err("bounded conservative stable-model policy/current lifetime".into());
        }
        self.material.validate_pins(&binding)?;
        Ok(binding)
    }
    fn native_policy(&self, binding: &OperationalModelLeaseBindingV2) -> HostResult<NativePolicy> {
        Ok(NativePolicy {
            schema: "hepta.cpu-neuron.initial-operational-policy.v1".into(),
            generation: 1,
            qualified_predecessor: None,
            scope_digest: self.scope_digest.clone(),
            objective_digest: binding.binding_digest()?.to_string(),
            baseline_manifest_digest: self.binding.model_manifest_digest.clone(),
            baseline_weights_digest: self.binding.weights_digest.clone(),
            source_training_digest: self.binding.source_training_digest.clone(),
            preregistration_digest: self.binding.preregistration_digest.clone(),
            initial_product_profile_digest: None,
            frozen_at_ms: self.frozen_at_ms,
            expires_at_ms: self.expires_at_ms,
            calibration_rows: self.calibration_rows,
            ood_rows: self.ood_rows,
            claim_scope: "initial-operational;training-source-reused;no-unseen-holdout;no-primary-superiority".into(),
            gates: serde_json::from_value::<Gates>(serde_json::to_value(&self.runtime_profile.calibration_gates)?)?,
        })
    }
}

pub(super) struct Inputs {
    pub policy: Policy,
    pub binding: OperationalModelLeaseBindingV2,
    pub native: OperationalInputs,
    pub material: Arc<VerifiedMaterial>,
}
enum MaterialAdmission<'a> {
    Original,
    Retained(&'a Arc<VerifiedMaterial>),
}
pub(super) fn inspect_inputs(config: &Config, now: u64) -> HostResult<Inputs> {
    inspect(config, now, MaterialAdmission::Original)
}
pub(super) fn reinspect_inputs(
    config: &Config,
    now: u64,
    material: &Arc<VerifiedMaterial>,
) -> HostResult<Inputs> {
    inspect(config, now, MaterialAdmission::Retained(material))
}
fn inspect(config: &Config, now: u64, admission: MaterialAdmission<'_>) -> HostResult<Inputs> {
    if config.schema != CONFIG_SCHEMA
        || config.uid == 0
        || config.gid == 0
        || config.inaccessible_paths.len() != 5
    {
        return Err("independent operational model evaluator protected profile".into());
    }
    let policy: Policy = serde_json::from_slice(&config.policy.read(32 * 1024)?)?;
    let binding = policy.validate(now)?;
    let material = match admission {
        MaterialAdmission::Original => {
            Arc::new(VerifiedMaterial::inspect(&policy.material, &binding)?)
        }
        MaterialAdmission::Retained(material) => {
            material.revalidate(&policy.material, &binding)?;
            Arc::clone(material)
        }
    };
    let native = inspect_inputs_with_policy(config, policy.native_policy(&binding)?, now)?;
    // These original measurements describe the fixed ten-wide CPU bootstrap.
    // Other declared dimensions are consumer-enforced limits, not measurements.
    let weights = config.baseline_weights.read(8 * 1024 * 1024)?;
    let profile = &policy.runtime_profile;
    if weights.len() < 14
        || &weights[..8] != b"HPTNCPU1"
        || weights.len() as u64 > profile.maximum_load_bytes
    {
        return Err("bounded original CPU weights/header".into());
    }
    let dimension = |at| u32::from(u16::from_be_bytes([weights[at], weights[at + 1]]));
    if profile.input_feature_dimension != dimension(8)
        || profile.modulator_dimension != dimension(10)
        || profile.state_width != dimension(12)
        || profile.state_width != 10
    {
        return Err("stable model profile differs from original measured CPU dimensions".into());
    }
    for cut in [&native.calibration, &native.ood] {
        for (row, _) in &cut.source_rows {
            if row["drive_q24"].as_array().map(Vec::len) != Some(10)
                || row["prediction_q24"].as_array().map(Vec::len) != Some(10)
            {
                return Err("stable model original numeric output width".into());
            }
        }
    }
    Ok(Inputs {
        policy,
        binding,
        native,
        material,
    })
}

#[cfg(test)]
#[path = "operational_model_lease_policy_v2_tests.rs"]
mod tests;
