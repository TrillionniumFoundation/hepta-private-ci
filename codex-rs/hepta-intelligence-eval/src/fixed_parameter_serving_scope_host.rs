//! Finite original independent E purpose before any Generator/Observer effect.
//! Root supplies an authenticated whole original Serving response; E independently
//! reopens training CURRENT/material. A mismatch never becomes fabricated G/O.
use crate::fixed_calibration_host::boundary;
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::fixed_parameter_generator_v3::ParameterRoleSourceV3;
use crate::*;
use codex_hepta_contracts::MAX_ORIGINAL_PARAMETER_SERVING_RESPONSE_BYTES_V1;
use codex_hepta_contracts::ParameterServingScopePayloadV1;
use codex_hepta_contracts::decode_original_parameter_serving_scope_response_v1;
use codex_hepta_learning_ledger::*;
use codex_hepta_neuron::MAX_NEURON_GENERATION_MATERIAL_BYTES_V2;
use codex_hepta_neuron::decode_neuron_generation_material_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::path::Path;

type HostResult<T> = Result<T, Box<dyn std::error::Error>>;
const MAX_CONFIG: u64 = 32 * 1024;
const MAX_INPUTS: u64 = 64 * 1024;
/// Complete protected input identity. No model advice or caller metric is read.
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterServingScopeInputsV1 {
    pub schema: String,
    pub round: ParameterPreRegistrationRoundV1,
    pub original_round_hex: String,
    pub serving_observation: ParameterRoleSourceV3,
    pub training_material: ParameterRoleSourceV3,
    pub training_registration: ParameterRoleSourceV3,
    pub subject: String,
}

/// Encode only the complete public purpose inputs. Neither this operation nor
/// successful parsing grants source custody or signs a terminal.
pub fn encode_fixed_parameter_serving_scope_inputs_v1(
    value: &FixedParameterServingScopeInputsV1,
) -> HostResult<Vec<u8>> {
    value.round.validate(value.round.admitted_at_ms)?;
    codex_hepta_contracts::AgentId::parse(&value.subject)?;
    let round = decode_review_payload_hex(&value.original_round_hex)?;
    if value.schema != "hepta.parameter-serving-scope-inputs.v1"
        || round.is_empty()
        || round.len() > 4096
        || Digest32::of_bytes(&round) != value.round.round_payload_digest.parse()?
    {
        return Err("whole original Serving-scope input shape".into());
    }
    for source in [
        &value.serving_observation,
        &value.training_material,
        &value.training_registration,
    ] {
        let pin: Digest32 = source.digest.parse()?;
        if !source.path.is_absolute() || pin.is_zero() || pin.to_string() != source.digest {
            return Err("whole original Serving-scope Source identity".into());
        }
    }
    let bytes = serde_json::to_vec(value)?;
    if bytes.len() > MAX_INPUTS as usize {
        return Err("whole scope inputs bound".into());
    }
    Ok(bytes)
}

/// The existing independently enrolled evaluator and original controller own
/// this additional fixed purpose. Root does not read a key or supply a payload.
pub fn run_fixed_parameter_serving_scope_evaluator_v1(path: &Path) -> HostResult<()> {
    let config_bytes = read_root_review_input(path, MAX_CONFIG)?;
    let config: FixedParameterEvaluatorConfigV1 = serde_json::from_slice(&config_bytes)?;
    if config.schema != "hepta.fixed-parameter-serving-scope-config.v1"
        || config.uid == 0
        || config.gid == 0
        || config.distribution_generation == 0
        || config.authority_epoch == 0
        || config.inaccessible_paths.len() != 5
    {
        return Err("original finite Serving-scope E enrollment".into());
    }
    boundary(config.uid, config.gid)?;
    let program = verify_registered_operational_program_v3(
        &std::env::current_exe()?,
        config.program_digest.parse()?,
    )?;
    for denied in &config.inaccessible_paths {
        match File::open(denied) {
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => {
                return Err(
                    "Serving-scope E must lack physical Gold/custody/other-key access".into(),
                );
            }
        }
    }
    let trust_bytes = read_root_review_input(&config.trust_path, 128 * 1024)?;
    if Digest32::of_bytes(&trust_bytes) != config.trust_digest.parse()? {
        return Err("original independent E installed trust pin".into());
    }
    let wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
    if wire.root_verifying_key_hex != config.root_verifying_key_hex
        || wire.scope_digest != config.scope_digest
        || wire.objective_digest != config.objective_digest
        || wire.generation != config.distribution_generation
        || wire.authority_epoch != config.authority_epoch
    {
        return Err("original E training scope/window".into());
    }
    let (root, distribution) = wire.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("original independent E absent")?
        .clone();
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        &reviewer,
        program,
        &root.verifying_key,
        config.uid,
        config.gid,
        None,
    )?;
    let mut last = now_ms()?;
    let trust = activate_learning_trust(&root, distribution, None, last)?;
    let input_bytes = read_root_review_input(&config.inputs_path, MAX_INPUTS)?;
    if Digest32::of_bytes(&input_bytes) != config.inputs_digest.parse()? {
        return Err("whole enrolled scope inputs pin".into());
    }
    let input: FixedParameterServingScopeInputsV1 = serde_json::from_slice(&input_bytes)?;
    if input.schema != "hepta.parameter-serving-scope-inputs.v1" {
        return Err("scope input purpose".into());
    }
    input.round.validate(last)?;
    let round_bytes = decode_review_payload_hex(&input.original_round_hex)?;
    if round_bytes.len() > 4096
        || round_bytes.is_empty()
        || Digest32::of_bytes(&round_bytes) != input.round.round_payload_digest.parse()?
    {
        return Err("whole original admitted Round source".into());
    }
    let material_bytes = input
        .training_material
        .read(MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?;
    let material = decode_neuron_generation_material_v2(&material_bytes)?;
    // Original Generator/load_input_context training contract, independent of
    // descriptor.neuron's actual Serving Goal scope. A normal new user Goal is
    // not an incompatibility and cannot enter this terminal purpose.
    if material.scope.scope_digest == config.scope_digest.parse()?
        && material.scope.objective_digest == config.objective_digest.parse()?
    {
        return Err("compatible original training contract has no ineligible terminal".into());
    }
    let current = inspect_registered_artifact_current_material_v3(
        &input.training_registration.path,
        input.training_registration.digest.parse()?,
        &material,
        &StableId::new(input.subject.clone())?,
        last,
    )?;
    let observation = input
        .serving_observation
        .read(MAX_ORIGINAL_PARAMETER_SERVING_RESPONSE_BYTES_V1 as u64)?;
    let response = decode_original_parameter_serving_scope_response_v1(&observation)?;
    if response.request_id == 0
        || response.spawn_generation == 0
        || response.current_generation == 0
        || response.agent_id.to_string() != input.subject
    {
        return Err("whole authenticated original Serving response identity".into());
    }
    let ParameterServingScopePayloadV1::ParameterServingScopeV1(scope) = &response.payload;
    let codex_hepta_contracts::ParameterServingScopeV1 {
        round_hex,
        neuron_generation,
        configuration_digest,
        body_bundle_digest,
        scope_digest,
        objective_digest,
        goal_ordinal,
    } = scope;
    if *round_hex != input.original_round_hex
        || *neuron_generation != material.runtime.generation.get()
        || configuration_digest.parse::<Digest32>()? != material.store_context.runtime_config_digest
        || body_bundle_digest.parse::<Digest32>()? != material.store_context.body_bundle_digest
    {
        return Err(
            "actual Serving model differs from independently authenticated training model".into(),
        );
    }
    let mut sample = || -> HostResult<u64> {
        if read_root_review_input(path, MAX_CONFIG)? != config_bytes
            || read_root_review_input(&config.trust_path, 128 * 1024)? != trust_bytes
            || read_root_review_input(&config.inputs_path, MAX_INPUTS)? != input_bytes
            || input
                .serving_observation
                .read(MAX_ORIGINAL_PARAMETER_SERVING_RESPONSE_BYTES_V1 as u64)?
                != observation
            || input
                .training_material
                .read(MAX_NEURON_GENERATION_MATERIAL_BYTES_V2 as u64)?
                != material_bytes
            || verify_registered_operational_program_v3(&std::env::current_exe()?, program)?
                != program
        {
            return Err("actual scope/training Sources changed".into());
        }
        let now = now_ms()?;
        if now < last {
            return Err("Serving E clock rollback".into());
        }
        last = now;
        input.round.validate(now)?;
        trust.revalidate_at(now)?;
        current.revalidate_current(now)?;
        // Sample after potentially slow complete source/current reads as well.
        let final_now = now_ms()?;
        if final_now < last {
            return Err("Serving E final clock rollback".into());
        }
        last = final_now;
        input.round.validate(final_now)?;
        trust.revalidate_at(final_now)?;
        if final_now >= current.expires_at() {
            return Err("current facts expired after observation".into());
        }
        Ok(final_now)
    };
    let mut facts = SelfIterationServingScopeIncompatibleFactsV1 {
        round_identity_digest: input.round.round_digest.parse()?,
        round_payload_digest: input.round.round_payload_digest.parse()?,
        canonical_policy_digest: input.round.canonical_policy_digest.parse()?,
        execution_envelope_digest: input.round.execution_digest.parse()?,
        enrolled_inputs_digest: Digest32::of_bytes(&input_bytes),
        serving_observation_digest: Digest32::of_bytes(&observation),
        training_material_digest: Digest32::of_bytes(&material_bytes),
        training_registration_digest: input.training_registration.digest.parse()?,
        registry_binding_digest: current.current_head().binding,
        registry_head_digest: current.current_head().witness.head_digest,
        registry_acknowledgement_digest: Digest32::of_bytes(
            &codex_hepta_learning_artifacts::encode_artifact_owner_publication_checkpoint_v1(
                current.acknowledgement(),
            ),
        ),
        serving_scope_digest: scope_digest.parse()?,
        serving_objective_digest: objective_digest.parse()?,
        training_scope_digest: material.scope.scope_digest,
        training_objective_digest: material.scope.objective_digest,
        expected_training_scope_digest: config.scope_digest.parse()?,
        expected_training_objective_digest: config.objective_digest.parse()?,
        configuration_digest: configuration_digest.parse()?,
        body_bundle_digest: body_bundle_digest.parse()?,
        neuron_generation: *neuron_generation,
        goal_ordinal: *goal_ordinal,
        admitted_at_ms: input.round.admitted_at_ms,
        deadline_ms: input.round.deadline_ms,
        observed_at_ms: sample()?,
    };
    let signing = key(&config.private_key_path, config.uid)?;
    if Digest32::of_bytes(signing.verifying_key().as_bytes())
        != reviewer.principal.signing_key_digest
    {
        return Err("original E own key differs from admission".into());
    }
    facts.observed_at_ms = sample()?;
    let payload = self_iteration_serving_scope_signing_payload_v1(&facts)?;
    let expires_at = input
        .round
        .deadline_ms
        .min(trust.expires_at())
        .min(reviewer.principal.expires_at)
        .min(current.expires_at());
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!(
            "fixed.serving-scope.{}",
            Digest32::of_bytes(&payload)
        ))?,
        principal_id: reviewer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: reviewer.principal.scope_digest,
        objective_digest: config.objective_digest.parse()?,
        authority_epoch: reviewer.principal.authority_epoch,
        issued_at: facts.observed_at_ms,
        expires_at,
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    let packet = encode_self_iteration_serving_scope_terminal_v1(&facts, &evidence)?;
    let now = sample()?;
    trust
        .verifier()
        .verify(LearningEvidenceRoleV1::Evaluator, &evidence, &payload, now)?;
    println!(
        "{}",
        serde_json::to_string(&serde_json::json!({
            "schema":"hepta.parameter.serving-scope-incompatible-output.v1",
            "preparation_terminal_hex": packet.iter().map(|b| format!("{b:02x}")).collect::<String>()
        }))?
    );
    Ok(())
}
