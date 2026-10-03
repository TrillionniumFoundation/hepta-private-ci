//! Finite Generator purpose for the original deterministic parameter profile.
//! Root-pinned facts do not become selections, model use, or outcome authority.
use crate::fixed_calibration_host::boundary_in_service;
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::fixed_paired_generator_host::actual_generator;
use crate::fixed_paired_generator_host::actual_limits;
use crate::fixed_paired_generator_host::sample;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::ReviewTrustWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::activate_learning_trust;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_neuron::NeuronGenerationMaterialV2;
use codex_hepta_neuron::decode_neuron_generation_material_v2;
use codex_hepta_plasticity::GeneratedParameterCandidateSetV3;
use codex_hepta_plasticity::ParameterGeneratorProfileV3;
use codex_hepta_plasticity::decode_untrusted_parameter_generator_profile_v3;
use codex_hepta_plasticity::generate_parameter_candidates_v3;
use codex_hepta_plasticity::parameter_generator_signing_payload_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::path::Path;
use std::path::PathBuf;
type Result<T> = std::result::Result<T, Box<dyn std::error::Error>>;

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ParameterRoleSourceV3 {
    pub path: PathBuf,
    pub digest: String,
}
impl ParameterRoleSourceV3 {
    pub(super) fn read(&self, maximum: u64) -> Result<Vec<u8>> {
        let bytes = read_root_review_input(&self.path, maximum)?;
        let expected: Digest32 = self.digest.parse()?;
        if expected.is_zero() || Digest32::of_bytes(&bytes) != expected {
            return Err("Root parameter role source pin changed".into());
        }
        Ok(bytes)
    }
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterGeneratorConfigV3 {
    pub schema: String,
    pub uid: u32,
    pub gid: u32,
    pub program_digest: String,
    pub private_key_path: PathBuf,
    pub root_verifying_key_hex: String,
    pub source: ParameterRoleSourceV3,
    pub scope_digest: String,
    pub objective_digest: String,
    pub distribution_generation: u64,
    pub authority_epoch: u64,
    pub inaccessible_paths: Vec<PathBuf>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterGeneratorInputsV3 {
    pub schema: String,
    pub trust: ReviewTrustWireV1,
    pub profile: ParameterRoleSourceV3,
    pub baseline_material: ParameterRoleSourceV3,
    pub round_digest: String,
    pub canonical_policy_digest: String,
    pub admitted_at_ms: u64,
    pub deadline_ms: u64,
}
/// Validate original profile/baseline bindings. These typed facts grant no use.
pub fn validate_parameter_generator_baseline_v3(
    profile: &ParameterGeneratorProfileV3,
    baseline: &NeuronGenerationMaterialV2,
    scope: Digest32,
    objective: Digest32,
) -> Result<GeneratedParameterCandidateSetV3> {
    codex_hepta_neuron::validate_neuron_generation_material_v2(baseline)?;
    if baseline.scope.scope_digest != scope
        || baseline.scope.objective_digest != objective
        || profile.selected_artifact_digest != baseline.native.model_digest
    {
        return Err("parameter Generator changed actual whole baseline/scope/objective".into());
    }
    Ok(generate_parameter_candidates_v3(profile.clone())?)
}
fn validate_policy(
    config: &FixedParameterGeneratorConfigV3,
    inputs: &FixedParameterGeneratorInputsV3,
    now: u64,
) -> Result<()> {
    if config.schema != "hepta.fixed-parameter-generator-config.v3"
        || config.uid == 0
        || config.gid == 0
        || config.inaccessible_paths.len() != 5
        || config.distribution_generation == 0
        || config.authority_epoch == 0
        || inputs.schema != "hepta.fixed-parameter-generator-inputs.v3"
        || inputs.trust.root_verifying_key_hex != config.root_verifying_key_hex
        || inputs.trust.scope_digest != config.scope_digest
        || inputs.trust.objective_digest != config.objective_digest
        || inputs.trust.generation != config.distribution_generation
        || inputs.trust.authority_epoch != config.authority_epoch
        || inputs.round_digest.parse::<Digest32>()?.is_zero()
        || inputs
            .canonical_policy_digest
            .parse::<Digest32>()?
            .is_zero()
        || inputs.admitted_at_ms > now
        || inputs.deadline_ms <= now
        || inputs.admitted_at_ms >= inputs.deadline_ms
    {
        return Err("fixed original parameter G policy/window/trust".into());
    }
    Ok(())
}
/// Actual MainPID consumes only its admitted Generator key and pinned public
/// profile. It signs the original generator payload after recomputing all rules.
pub fn run_fixed_parameter_generator_v3(path: &Path) -> Result<()> {
    let config_bytes = read_root_review_input(path, 32 * 1024)?;
    let config: FixedParameterGeneratorConfigV3 = serde_json::from_slice(&config_bytes)?;
    let cgroup = boundary_in_service(config.uid, config.gid, "hepta-native-generator-")?;
    actual_limits(&cgroup)?;
    let program = crate::verify_registered_operational_program_v3(
        &std::env::current_exe()?,
        config.program_digest.parse()?,
    )?;
    for denied in &config.inaccessible_paths {
        match File::open(denied) {
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => {
                return Err(
                    "actual parameter G has other-role/custody access or missing denial".into(),
                );
            }
        }
    }
    let input_bytes = config.source.read(64 * 1024)?;
    let inputs: FixedParameterGeneratorInputsV3 = serde_json::from_slice(&input_bytes)?;
    validate_policy(&config, &inputs, now_ms()?)?;
    let (root, distribution) = inputs.trust.native()?;
    let signer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == "native-unprivileged-generator")
        .ok_or("original G admission missing")?
        .clone();
    actual_generator(&signer, program, config.uid, &root.verifying_key)?;
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
        config.scope_digest.parse()?,
        config.objective_digest.parse()?,
    )?;
    let payload = parameter_generator_signing_payload_v3(&generated);
    let now = sample(&trust, &mut last)?;
    validate_policy(&config, &inputs, now)?;
    if read_root_review_input(path, 32 * 1024)? != config_bytes
        || config.source.read(64 * 1024)? != input_bytes
        || inputs.profile.read(1024 * 1024)? != profile_bytes
        || inputs
            .baseline_material
            .read(MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?
            != baseline_bytes
    {
        return Err("Root parameter G inputs changed before signature".into());
    }
    actual_limits(&boundary_in_service(
        config.uid,
        config.gid,
        "hepta-native-generator-",
    )?)?;
    let signing = key(&config.private_key_path, config.uid)?;
    if signing.verifying_key().to_bytes() != signer.verifying_key {
        return Err("actual G key differs from current admitted key".into());
    }
    signer.principal.validate(now)?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: parameter_role_evidence_id(
            LearningEvidenceRoleV1::Generator,
            inputs.round_digest.parse()?,
            Digest32::of_bytes(&payload),
        )?,
        principal_id: signer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Generator,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: signer.principal.scope_digest,
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: signer.principal.authority_epoch,
        issued_at: now,
        expires_at: signer
            .principal
            .expires_at
            .min(trust.expires_at())
            .min(inputs.deadline_ms),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    if evidence.expires_at <= now {
        return Err("actual parameter G expiry".into());
    }
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    trust.verifier().verify(
        LearningEvidenceRoleV1::Generator,
        &evidence,
        &payload,
        sample(&trust, &mut last)?,
    )?;
    println!(
        "{}",
        serde_json::json!({"schema":"hepta.fixed-parameter-generator-result.v3","source_digest":config.source.digest,"round_digest":inputs.round_digest,"canonical_policy_digest":inputs.canonical_policy_digest,"profile_digest":Digest32::of_bytes(&profile_bytes).to_string(),"generator_digest":generated.generator_digest.to_string(),"generator_evidence":ReviewEvidenceWireV1::from_native(&evidence),"generator_uid":config.uid,"generator_gid":config.gid,"generator_program_digest":program.to_string(),"generator_cgroup":cgroup,"qualified":false,"authority_grants_any":false})
    );
    Ok(())
}
// StableId has a 128-byte bound. Hash both complete pins with a finite role
// discriminator rather than concatenating their two 64-character encodings.
pub(super) fn parameter_role_evidence_id(
    role: LearningEvidenceRoleV1,
    round: Digest32,
    payload: Digest32,
) -> Result<StableId> {
    let prefix = match role {
        LearningEvidenceRoleV1::Generator => "parameter-g",
        LearningEvidenceRoleV1::Observer => "parameter-o",
        LearningEvidenceRoleV1::Evaluator
        | LearningEvidenceRoleV1::CreditAllocator
        | LearningEvidenceRoleV1::UnlearningAuthority
        | LearningEvidenceRoleV1::Selector => {
            return Err("unsupported fixed parameter evidence role".into());
        }
    };
    let digest = Digest32::of_parts(&[
        b"hepta.fixed-parameter-role-evidence-id.v1\0",
        prefix.as_bytes(),
        round.as_array(),
        payload.as_array(),
    ]);
    Ok(StableId::new(format!("{prefix}.{digest}"))?)
}
#[cfg(test)]
#[path = "fixed_parameter_generator_v3_tests.rs"]
mod tests;
