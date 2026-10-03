//! Fixed real E purpose for a deterministic no-update frontier. No caller
//! metrics, arbitrary signing payload, Gold access, or model advice is accepted.
use super::fixed_parameter_no_change::*;
use crate::fixed_calibration_host::{boundary, key, now_ms};
use crate::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_plasticity::*;
use codex_hepta_types::{Digest32, StableId};
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::path::{Path, PathBuf};

const MAX_CONFIG_BYTES: u64 = 32 * 1024;
const MAX_INPUT_BYTES: u64 = 4 * MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1 as u64 + 32 * 1024;
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FixedParameterEvaluatorConfigV1 {
    pub schema: String,
    pub uid: u32,
    pub gid: u32,
    pub program_digest: String,
    pub private_key_path: PathBuf,
    pub trust_path: PathBuf,
    pub trust_digest: String,
    pub root_verifying_key_hex: String,
    pub scope_digest: String,
    pub objective_digest: String,
    pub distribution_generation: u64,
    pub authority_epoch: u64,
    pub inputs_path: PathBuf,
    pub inputs_digest: String,
    pub inaccessible_paths: Vec<PathBuf>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct Inputs {
    pub(crate) schema: String,
    pub(crate) profile_hex: String,
    pub(crate) admission_hex: String,
    pub(crate) generator_evidence: ReviewEvidenceWireV1,
    pub(crate) observer_evidence: ReviewEvidenceWireV1,
    pub(crate) round_identity_digest: String,
    pub(crate) round_payload_digest: String,
    pub(crate) canonical_policy_digest: String,
    pub(crate) execution_envelope_digest: String,
    pub(crate) admitted_at_ms: u64,
    pub(crate) deadline_ms: u64,
    #[serde(default)]
    pub(crate) candidate_id: Option<String>,
    #[serde(default)]
    pub(crate) completed_reviews:
        Vec<crate::fixed_parameter_preparation_review::FixedParameterCompletedReviewSourceV1>,
}

/// Root supplies a purpose-specific immutable enrolled request; the actual
/// independently admitted E validates all original G/O bytes before signing.
pub fn run_fixed_parameter_no_change_evaluator_v1(path: &Path) -> HostResult<()> {
    run_evaluator(path, false)
}
/// The same real E replays every completed original measurement before declaring
/// an ineligible/insufficient preparation. Missing or unknown work is rejected.
pub fn run_fixed_parameter_preparation_evaluator_v1(path: &Path) -> HostResult<()> {
    run_evaluator(path, true)
}
fn run_evaluator(path: &Path, measured_rejection: bool) -> HostResult<()> {
    let config_bytes = read_root_review_input(path, MAX_CONFIG_BYTES)?;
    let config: FixedParameterEvaluatorConfigV1 = serde_json::from_slice(&config_bytes)?;
    let schema = if measured_rejection {
        "hepta.fixed-parameter-preparation-config.v1"
    } else {
        "hepta.fixed-parameter-no-change-config.v1"
    };
    if config.schema != schema
        || config.uid == 0
        || config.gid == 0
        || config.distribution_generation == 0
        || config.authority_epoch == 0
        || config.inaccessible_paths.len() != 5
    {
        return Err("fixed parameter E enrollment policy".into());
    }
    boundary(config.uid, config.gid)?;
    let program = Digest32::of_bytes(&read_root_review_input(
        &std::env::current_exe()?,
        128 * 1024 * 1024,
    )?);
    if program != config.program_digest.parse()? {
        return Err("fixed parameter E program pin".into());
    }
    for inaccessible in &config.inaccessible_paths {
        match File::open(inaccessible) {
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => {
                return Err(
                    "parameter E requires physical denial of Gold/custody/other role keys".into(),
                );
            }
        }
    }
    let trust_bytes = read_root_review_input(&config.trust_path, 128 * 1024)?;
    if Digest32::of_bytes(&trust_bytes) != config.trust_digest.parse()? {
        return Err("parameter E independent installed trust pin".into());
    }
    let wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
    if wire.root_verifying_key_hex != config.root_verifying_key_hex
        || wire.scope_digest != config.scope_digest
        || wire.objective_digest != config.objective_digest
        || wire.generation != config.distribution_generation
        || wire.authority_epoch != config.authority_epoch
    {
        return Err("parameter E installed scope/trust window".into());
    }
    let (root, distribution) = wire.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|signer| signer.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("original E admission absent")?
        .clone();
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        &reviewer,
        program,
        &root.verifying_key,
        config.uid,
        config.gid,
        None,
    )?;
    let mut previous_now = now_ms()?;
    let trust = activate_learning_trust(&root, distribution, None, previous_now)?;
    let inputs_bytes = read_root_review_input(&config.inputs_path, MAX_INPUT_BYTES)?;
    if Digest32::of_bytes(&inputs_bytes) != config.inputs_digest.parse()? {
        return Err("parameter E immutable enrolled inputs pin".into());
    }
    let inputs: Inputs = serde_json::from_slice(&inputs_bytes)?;
    let input_schema = if measured_rejection {
        "hepta.parameter-preparation-inputs.v1"
    } else {
        "hepta.parameter-no-change-inputs.v1"
    };
    if inputs.schema != input_schema
        || inputs.candidate_id.is_some()
        || (!measured_rejection && !inputs.completed_reviews.is_empty())
    {
        return Err("parameter E exact input purpose".into());
    }
    let profile = decode_untrusted_parameter_generator_profile_v3(&unhex(
        &inputs.profile_hex,
        MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1,
    )?)?;
    let admission = decode_untrusted_plasticity_admission_v1(&unhex(
        &inputs.admission_hex,
        MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1,
    )?)?;
    if admission.objective_digest != config.objective_digest.parse()? {
        return Err("parameter E original objective".into());
    }
    let generated = if measured_rejection {
        let generated = generate_parameter_candidates_v3(profile.clone())?;
        validate_parameter_admission_binding_v1(&profile, &generated, &admission)?;
        generated
    } else {
        no_change(&profile, &admission)?
    };
    let generator = inputs.generator_evidence.native()?;
    let observer = inputs.observer_evidence.native()?;
    let signing = key(&config.private_key_path, config.uid)?;
    if Digest32::of_bytes(signing.verifying_key().as_bytes())
        != reviewer.principal.signing_key_digest
    {
        return Err("parameter E own key admission".into());
    }
    let mut current = || -> HostResult<u64> {
        if read_root_review_input(path, MAX_CONFIG_BYTES)? != config_bytes
            || read_root_review_input(&config.trust_path, 128 * 1024)? != trust_bytes
            || read_root_review_input(&config.inputs_path, MAX_INPUT_BYTES)? != inputs_bytes
            || Digest32::of_bytes(&read_root_review_input(
                &std::env::current_exe()?,
                128 * 1024 * 1024,
            )?) != program
        {
            return Err("parameter E immutable inputs changed".into());
        }
        let now = now_ms()?;
        if now < previous_now || now < inputs.admitted_at_ms || now >= inputs.deadline_ms {
            return Err("parameter E original round time admission".into());
        }
        previous_now = now;
        trust.revalidate_at(now)?;
        let g = trust.verifier().verify(
            LearningEvidenceRoleV1::Generator,
            &generator,
            &parameter_generator_signing_payload_v3(&generated),
            now,
        )?;
        let o = trust.verifier().verify(
            LearningEvidenceRoleV1::Observer,
            &observer,
            &plasticity_admission_signing_payload_v1(&admission),
            now,
        )?;
        for actor in [&g, &o] {
            verify_independent_roles(actor.principal(), &reviewer.principal, now)?;
            if actor.controller_id() == &reviewer.controller_id {
                return Err("parameter E shares actual G/O controller".into());
            }
        }
        Ok(now)
    };
    let expires_at = inputs
        .deadline_ms
        .min(reviewer.principal.expires_at)
        .min(trust.expires_at())
        .min(generator.expires_at)
        .min(observer.expires_at);
    let sign = |purpose: &str, payload: &[u8], now: u64| -> HostResult<SignedLearningEvidenceV1> {
        if now >= expires_at {
            return Err("parameter E purpose expiry".into());
        }
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: StableId::new(format!(
                "fixed.parameter.{purpose}.{}",
                inputs.round_identity_digest
            ))?,
            principal_id: reviewer.principal.principal_id.clone(),
            role: LearningEvidenceRoleV1::Evaluator,
            trust_digest: trust.verifier().trust_digest(),
            scope_digest: reviewer.principal.scope_digest,
            objective_digest: admission.objective_digest,
            authority_epoch: reviewer.principal.authority_epoch,
            issued_at: now,
            expires_at,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
        trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Evaluator, &evidence, payload, now)?;
        Ok(evidence)
    };
    let (publication_bytes, disposition) = if measured_rejection {
        crate::fixed_parameter_preparation_review::replay_rejected_preparation(
            &inputs.completed_reviews,
            &generated,
            &admission,
            &generator,
            &reviewer.principal,
            &trust,
            current()?,
        )?
    } else {
        let no_change_attestation = sign(
            "no-change",
            &no_change_disposition_signing_payload_v1(&generated, &admission)?,
            current()?,
        )?;
        let publication_bytes = serde_json::to_vec(&Publication {
            schema: "hepta.parameter.no-admissible-update.v1".to_owned(),
            profile_digest: Digest32::of_bytes(&encode_untrusted_parameter_generator_profile_v3(
                &profile,
            )?)
            .to_string(),
            generator_digest: generated.generator_digest.to_string(),
            admission_digest: Digest32::of_bytes(&plasticity_admission_signing_payload_v1(
                &admission,
            ))
            .to_string(),
            evaluator_evidence: ReviewEvidenceWireV1::from_native(&no_change_attestation),
        })?;
        (
            publication_bytes,
            SelfIterationPreparationDispositionV1::NoAdmissibleUpdate,
        )
    };
    let mut facts = SelfIterationPreparationFactsV1 {
        disposition,
        round_identity_digest: inputs.round_identity_digest.parse()?,
        round_payload_digest: inputs.round_payload_digest.parse()?,
        canonical_policy_digest: inputs.canonical_policy_digest.parse()?,
        execution_envelope_digest: inputs.execution_envelope_digest.parse()?,
        enrolled_inputs_digest: Digest32::of_bytes(&inputs_bytes),
        generated_digest: generated.generator_digest,
        admission_digest: Digest32::of_bytes(&plasticity_admission_signing_payload_v1(&admission)),
        generator_evidence_digest: evidence_digest(&generator),
        observer_evidence_digest: evidence_digest(&observer),
        evaluation_publication_digest: Digest32::of_bytes(&publication_bytes),
        admitted_at_ms: inputs.admitted_at_ms,
        deadline_ms: inputs.deadline_ms,
        observed_at_ms: current()?,
    };
    if measured_rejection {
        let replay = crate::fixed_parameter_preparation_review::replay_rejected_preparation(
            &inputs.completed_reviews,
            &generated,
            &admission,
            &generator,
            &reviewer.principal,
            &trust,
            current()?,
        )?;
        if replay != (publication_bytes.clone(), disposition) {
            return Err("original measured preparation changed before terminal signing".into());
        }
    }
    facts.observed_at_ms = current()?;
    let terminal = sign(
        "preparation",
        &self_iteration_preparation_terminal_signing_payload_v1(&facts)?,
        facts.observed_at_ms,
    )?;
    let terminal_bytes = encode_self_iteration_preparation_terminal_v1(&facts, &terminal)?;
    let output = serde_json::to_vec(&Output {
        schema: if measured_rejection {
            "hepta.parameter.preparation-output.v1"
        } else {
            "hepta.parameter.no-change-output.v1"
        }
        .to_owned(),
        publication_hex: hex(&publication_bytes),
        preparation_terminal_hex: hex(&terminal_bytes),
    })?;
    if !measured_rejection {
        decode_fixed_parameter_no_change_output_v1(
            &output,
            &profile,
            &admission,
            &generator,
            &observer,
            &trust,
            current()?,
        )?;
    } else {
        current()?;
        if output.len() > 2 * MAX_PARAMETER_ROLE_MATERIAL_BYTES_V1 + 64 * 1024 {
            return Err("whole measured preparation output bound".into());
        }
    }
    println!("{}", std::str::from_utf8(&output)?);
    Ok(())
}
