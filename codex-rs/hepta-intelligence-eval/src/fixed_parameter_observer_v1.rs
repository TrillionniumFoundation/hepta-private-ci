//! Finite admission observation under the original Root custody O controller.
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::fixed_paired_custody_host::verify_original_observer_controller;
use crate::fixed_paired_generator_host::sample;
use crate::fixed_parameter_generator_v3::ParameterRoleSourceV3;
use crate::fixed_parameter_generator_v3::parameter_role_evidence_id;
use crate::fixed_parameter_generator_v3::validate_parameter_generator_baseline_v3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_learning_ledger::verify_signed_role_separation;
use codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_neuron::decode_neuron_generation_material_v2;
use codex_hepta_plasticity::decode_untrusted_parameter_generator_profile_v3;
use codex_hepta_plasticity::decode_untrusted_plasticity_admission_v1;
use codex_hepta_plasticity::parameter_generator_signing_payload_v3;
use codex_hepta_plasticity::plasticity_admission_signing_payload_v1;
use codex_hepta_plasticity::validate_parameter_admission_binding_v1;
use codex_hepta_types::Digest32;
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde::Serialize;
use std::path::Path;
use std::path::PathBuf;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterObserverConfigV1 {
    pub schema: String,
    pub program_digest: String,
    pub root_verifying_key_hex: String,
    pub trust_config: ParameterRoleSourceV3,
    pub cycle_approval: Option<ParameterRoleSourceV3>,
    pub source: ParameterRoleSourceV3,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterObserverInputsV1 {
    pub schema: String,
    pub trust: ReviewTrustWireV1,
    pub profile: ParameterRoleSourceV3,
    pub baseline_material: ParameterRoleSourceV3,
    /// Immutable output from the authenticated original current admission owner.
    /// Root must obtain it through that owner's factual port, not a DTO echo.
    pub admission: ParameterRoleSourceV3,
    pub generator_evidence: ReviewEvidenceWireV1,
    pub round_digest: String,
    pub canonical_policy_digest: String,
    pub admitted_at_ms: u64,
    pub deadline_ms: u64,
}
fn window(inputs: &FixedParameterObserverInputsV1, now: u64) -> Result<()> {
    if inputs.schema != "hepta.fixed-parameter-observer-inputs.v1"
        || inputs.round_digest.parse::<Digest32>()?.is_zero()
        || inputs
            .canonical_policy_digest
            .parse::<Digest32>()?
            .is_zero()
        || inputs.admitted_at_ms > now
        || inputs.deadline_ms <= now
        || inputs.admitted_at_ms >= inputs.deadline_ms
    {
        return Err("original O parameter inputs/window".into());
    }
    Ok(())
}
/// Actual O process signs only the original complete admission payload. It
/// preserves the existing custody controller, original key and exact signing
/// bytes; it does not create a candidate, tick, grant or evaluation.
pub fn run_fixed_parameter_observer_v1(path: &Path) -> Result<()> {
    crate::fixed_product_host::root_boundary()?;
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: FixedParameterObserverConfigV1 = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-parameter-observer-config.v1" {
        return Err("fixed O parameter purpose".into());
    }
    let program = crate::verify_registered_operational_program_v3(
        &std::env::current_exe()?,
        config.program_digest.parse()?,
    )?;
    let input_bytes = config.source.read(64 * 1024)?;
    let inputs: FixedParameterObserverInputsV1 = serde_json::from_slice(&input_bytes)?;
    window(&inputs, now_ms()?)?;
    if inputs.trust.root_verifying_key_hex != config.root_verifying_key_hex {
        return Err("independently pinned Root O trust key".into());
    }
    let (root, distribution) = inputs.trust.native()?;
    let observer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| {
            s.principal.principal_id.as_str() == "fixed-custody-observer"
                && s.roles == [LearningEvidenceRoleV1::Observer]
        })
        .ok_or("original O admission absent")?
        .clone();
    let trust_bytes = config.trust_config.read(16 * 1024)?;
    let trust_policy: serde_json::Value = serde_json::from_slice(&trust_bytes)?;
    let approval = config
        .cycle_approval
        .as_ref()
        .map(|s| s.read(32 * 1024))
        .transpose()?;
    verify_original_observer_controller(program, &trust_bytes, approval.as_deref(), &observer)?;
    let key_path = PathBuf::from(
        trust_policy["observer_key_path"]
            .as_str()
            .ok_or("original O own key path")?,
    );
    let trust = activate_learning_trust(&root, distribution, None, now_ms()?)?;
    let mut last = None;
    sample(&trust, &mut last)?;
    let profile_bytes = inputs.profile.read(1024 * 1024)?;
    let profile = decode_untrusted_parameter_generator_profile_v3(&profile_bytes)?;
    let baseline_bytes = inputs
        .baseline_material
        .read(MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?;
    let baseline = decode_neuron_generation_material_v2(&baseline_bytes)?;
    let generated = validate_parameter_generator_baseline_v3(
        &profile,
        &baseline,
        trust.verifier().scope_digest(),
        trust.verifier().objective_digest(),
    )?;
    let admission_bytes = inputs.admission.read(16 * 1024)?;
    let admission = decode_untrusted_plasticity_admission_v1(&admission_bytes)?;
    validate_parameter_admission_binding_v1(&profile, &generated, &admission)?;
    if admission.baseline_id != baseline.runtime.model_id
        || admission.baseline_generation != baseline.runtime.generation
        || admission.objective_digest != trust.verifier().objective_digest()
    {
        return Err(
            "O admission changed actual whole baseline/generation/training objective".into(),
        );
    }
    let generator = inputs.generator_evidence.native()?;
    let verified_g = trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &generator,
        &parameter_generator_signing_payload_v3(&generated),
        sample(&trust, &mut last)?,
    )?;
    let payload = plasticity_admission_signing_payload_v1(&admission);
    let now = sample(&trust, &mut last)?;
    window(&inputs, now)?;
    trust.revalidate_at(now)?;
    observer.principal.validate(now)?;
    if read_root_review_input(path, 32 * 1024)? != config_bytes
        || config.source.read(64 * 1024)? != input_bytes
        || config.trust_config.read(16 * 1024)? != trust_bytes
        || config
            .cycle_approval
            .as_ref()
            .map(|s| s.read(32 * 1024))
            .transpose()?
            != approval
        || inputs.profile.read(1024 * 1024)? != profile_bytes
        || inputs.admission.read(16 * 1024)? != admission_bytes
        || inputs
            .baseline_material
            .read(MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?
            != baseline_bytes
    {
        return Err("original O protected whole inputs changed before signature".into());
    }
    crate::fixed_product_host::root_boundary()?;
    let signing = key(&key_path, 0)?;
    if signing.verifying_key().to_bytes() != observer.verifying_key {
        return Err("actual O key differs from original current admission".into());
    }
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: parameter_role_evidence_id(
            LearningEvidenceRoleV1::Observer,
            inputs.round_digest.parse()?,
            Digest32::of_bytes(&payload),
        )?,
        principal_id: observer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Observer,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: observer.principal.scope_digest,
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: observer.principal.authority_epoch,
        issued_at: now,
        expires_at: observer
            .principal
            .expires_at
            .min(trust.expires_at())
            .min(inputs.deadline_ms),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    if evidence.expires_at <= now {
        return Err("original O parameter expiry".into());
    }
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    let final_now = sample(&trust, &mut last)?;
    window(&inputs, final_now)?;
    let verified_o = trust.verifier().verify(
        LearningEvidenceRoleV1::Observer,
        &evidence,
        &payload,
        final_now,
    )?;
    verify_signed_role_separation(&verified_g, &verified_o, final_now)?;
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.fixed-parameter-observer-result.v1","source_digest":config.source.digest,"round_digest":inputs.round_digest,"canonical_policy_digest":inputs.canonical_policy_digest,"admission_digest":Digest32::of_bytes(&admission_bytes).to_string(),"observer_evidence":ReviewEvidenceWireV1::from_native(&evidence),"observer_program_digest":program.to_string(),"qualified":false,"authority_grants_any":false})
    );
    Ok(())
}
#[cfg(test)]
#[path = "fixed_parameter_observer_v1_tests.rs"]
mod tests;
