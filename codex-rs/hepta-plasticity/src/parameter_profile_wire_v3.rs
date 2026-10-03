//! Exact original profile fields; the original generator validates all semantics.
use crate::LayerNormDenominatorV2;
use crate::ParameterMutationPolicyV1;
use crate::ParameterMutationRuleV1;
use crate::ParameterMutationSurfaceV1;
use crate::ParameterPlasticitySignalV3;
use crate::parameter_material_wire::*;
use crate::*;
pub(super) fn write(value: &ParameterGeneratorProfileV3, w: &mut Writer) -> Result<()> {
    w.digest(value.selected_artifact_digest)?;
    w.window(&value.window)?;
    w.u32(value.norm_layers.len())?;
    for layer in &value.norm_layers {
        w.id(&layer.layer_id)?;
        w.put(&layer.baseline_squared_l2_raw_q64.to_be_bytes())?;
    }
    let policy = &value.mutation_policy;
    w.id(&policy.policy_id)?;
    w.digest(policy.mutation_grammar_digest)?;
    w.digest(policy.selected_artifact_digest)?;
    w.window(&policy.window)?;
    w.u32(policy.rules.len())?;
    for rule in &policy.rules {
        w.id(&rule.parameter_id)?;
        w.id(&rule.layer_id)?;
        w.u8(match rule.surface {
            ParameterMutationSurfaceV1::LearnableParameter => 0,
            ParameterMutationSurfaceV1::Authority => 1,
            ParameterMutationSurfaceV1::Evaluator => 2,
            ParameterMutationSurfaceV1::Deletion => 3,
            ParameterMutationSurfaceV1::RuntimeTopology => 4,
            ParameterMutationSurfaceV1::Credential => 5,
        })?;
        w.q(rule.minimum_delta)?;
        w.q(rule.maximum_delta)?;
    }
    w.digest(policy.policy_digest)?;
    w.u32(value.update_scales.len())?;
    for scale in &value.update_scales {
        w.q(*scale)?;
    }
    w.u32(value.signals.len())?;
    for signal in &value.signals {
        w.id(&signal.layer_id)?;
        w.id(&signal.parameter_id)?;
        for q in [
            signal.eligibility,
            signal.modulator,
            signal.learning_rate,
            signal.lower_bound,
            signal.upper_bound,
        ] {
            w.q(q)?;
        }
        w.digest(signal.evidence_digest)?;
    }
    Ok(())
}
pub(super) fn read(r: &mut Reader<'_>) -> Result<ParameterGeneratorProfileV3> {
    let selected_artifact_digest = r.digest()?;
    let window = r.window()?;
    let mut norm_layers = Vec::new();
    for _ in 0..r.len(256)? {
        norm_layers.push(LayerNormDenominatorV2 {
            layer_id: r.id()?,
            baseline_squared_l2_raw_q64: u128::from_be_bytes(
                r.take(16)?.try_into().map_err(|_| invalid())?,
            ),
        });
    }
    let policy_id = r.id()?;
    let mutation_grammar_digest = r.digest()?;
    let policy_artifact = r.digest()?;
    let policy_window = r.window()?;
    let mut rules = Vec::new();
    for _ in 0..r.len(4096)? {
        rules.push(ParameterMutationRuleV1 {
            parameter_id: r.id()?,
            layer_id: r.id()?,
            surface: match r.u8()? {
                0 => ParameterMutationSurfaceV1::LearnableParameter,
                1 => ParameterMutationSurfaceV1::Authority,
                2 => ParameterMutationSurfaceV1::Evaluator,
                3 => ParameterMutationSurfaceV1::Deletion,
                4 => ParameterMutationSurfaceV1::RuntimeTopology,
                5 => ParameterMutationSurfaceV1::Credential,
                _ => return Err(invalid()),
            },
            minimum_delta: r.q()?,
            maximum_delta: r.q()?,
        });
    }
    let policy_digest = r.digest()?;
    let mut update_scales = Vec::new();
    for _ in 0..r.len(31)? {
        update_scales.push(r.q()?);
    }
    let mut signals = Vec::new();
    for _ in 0..r.len(4096)? {
        signals.push(ParameterPlasticitySignalV3 {
            layer_id: r.id()?,
            parameter_id: r.id()?,
            eligibility: r.q()?,
            modulator: r.q()?,
            learning_rate: r.q()?,
            lower_bound: r.q()?,
            upper_bound: r.q()?,
            evidence_digest: r.digest()?,
        });
    }
    Ok(ParameterGeneratorProfileV3 {
        selected_artifact_digest,
        window,
        norm_layers,
        mutation_policy: ParameterMutationPolicyV1 {
            policy_id,
            mutation_grammar_digest,
            selected_artifact_digest: policy_artifact,
            window: policy_window,
            rules,
            policy_digest,
        },
        update_scales,
        signals,
    })
}
