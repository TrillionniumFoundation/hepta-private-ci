//! Actual independent E measurement before candidate artifact registration.
use crate::SelfIterationPreparationDispositionV1;
use crate::SelfIterationPreparationFactsV1;
use crate::fixed_calibration_host::boundary;
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::initial_neuron_operational_metrics::measure;
use crate::initial_neuron_operational_source::HostResult;
use crate::operational_registered_measurement_v3::Execution;
use crate::operational_registered_measurement_v3::Replay;
use crate::operational_registered_measurement_v3::replay;
use crate::parameter_pre_registration_policy_v1::Inputs;
use crate::parameter_pre_registration_policy_v1::inspect;
use crate::parameter_pre_registration_policy_v1::validate_reviewer;
use crate::parameter_pre_registration_v1::*;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::fs::File;
use std::path::Path;

#[derive(Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct Body {
    pub schema: String,
    pub claim_scope: String,
    pub configuration_digest: String,
    pub round: ParameterPreRegistrationRoundV1,
    pub purpose: ParameterPreRegistrationPurposeV1,
    pub subject: String,
    pub candidate_id: String,
    pub baseline_material_digest: String,
    pub baseline_registration_digest: String,
    pub baseline_model_artifact_id: String,
    pub baseline_registry_head: String,
    pub baseline_signed_head_hex: String,
    pub baseline_current_witness: String,
    pub baseline_publication_operation: String,
    pub baseline_publication_state: String,
    pub generator_digest: String,
    pub admission_digest: String,
    pub source_configuration_digest: String,
    pub source_binding_digest: String,
    pub measured_at_ms: u64,
    pub evaluator_uid: u32,
    pub evaluator_gid: u32,
    pub evaluator_program_digest: String,
    pub evaluator_cgroup: String,
    pub calibration: Replay,
    pub ood: Replay,
    pub calibration_execution: Execution,
    pub ood_execution: Execution,
    pub original_head_calibration: Value,
    pub original_head_ood: Value,
    pub operational_constraints_passed: bool,
    pub cpu_answer_acceptance_permitted: bool,
    pub final_material_digest: Option<String>,
    pub final_material_hex: Option<String>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Report {
    pub body: Body,
    pub evaluator_signed_evidence: ReviewEvidenceWireV1,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Output {
    pub publication: Report,
    pub preparation_terminal_hex: Option<String>,
}
pub(super) fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}
pub(super) fn payload(body: &Body) -> HostResult<Vec<u8>> {
    let bytes = serde_json::to_vec(body)?;
    if bytes.len() > MAX_PARAMETER_PRE_REGISTRATION_REPORT_BYTES_V1 {
        return Err("bounded complete pre-registration material/report".into());
    }
    Ok([
        b"hepta.intelligence-eval.parameter-pre-registration.v1\0".as_slice(),
        Digest32::of_bytes(&bytes).as_array(),
    ]
    .concat())
}
pub(super) fn constraints(
    inputs: &Inputs,
    config: &FixedParameterPreRegistrationConfigV1,
    facts: &Replay,
    execution: &Execution,
) -> bool {
    let limits = &inputs.plan.runtime.resource_envelope;
    facts.all_require_calibration
        && facts.rows > 0
        && facts.rows <= 2048
        && facts.maximum_checkpoint_bytes <= limits.checkpoint_bytes
        && facts.maximum_projection_count
            <= inputs.plan.runtime.calibration.maximum_projection_count
        && execution.p95_latency_micros <= limits.p95_latency_micros
        && execution.p99_latency_micros <= limits.p99_latency_micros
        && execution.resident_high_water_bytes <= config.maximum_resident_bytes
}
pub(super) fn measure_body(
    config: &FixedParameterPreRegistrationConfigV1,
    inputs: &Inputs,
    configuration_digest: Digest32,
    measured_at_ms: u64,
    cgroup: String,
    signed_execution: Option<(&Execution, &Execution)>,
) -> HostResult<Body> {
    let (calibration, calibration_execution) =
        replay(&inputs.plan, &inputs.source.native.calibration)?;
    let (ood, ood_execution) = replay(&inputs.plan, &inputs.source.native.ood)?;
    let (calibration_execution, ood_execution) = signed_execution
        .map(|(calibration, ood)| (calibration.clone(), ood.clone()))
        .unwrap_or((calibration_execution, ood_execution));
    let head_calibration = measure(
        &inputs.source.native.calibration,
        &inputs.source.native.policy.gates,
    )?;
    let head_ood = measure(
        &inputs.source.native.ood,
        &inputs.source.native.policy.gates,
    )?;
    let measured_ece = head_calibration
        .measured_ece_ppm
        .max(head_ood.measured_ece_ppm);
    let measured_false = head_calibration
        .measured_false_acceptance_ppm
        .max(head_ood.measured_false_acceptance_ppm);
    let passed = constraints(inputs, config, &calibration, &calibration_execution)
        && constraints(inputs, config, &ood, &ood_execution)
        && head_calibration.operational_constraints_passed
        && head_ood.operational_constraints_passed
        && measured_ece <= inputs.plan.runtime.calibration.maximum_ece_ppm
        && measured_false <= inputs.plan.runtime.calibration.maximum_false_acceptance_ppm;
    let material = if passed {
        Some(encode_neuron_generation_material_v2(
            &finalize_parameter_pre_registration_material_v1(
                &inputs.plan,
                measured_ece,
                measured_false,
            )?,
        )?)
    } else {
        None
    };
    Ok(Body {
        schema: "hepta.parameter-pre-registration-evaluation.v1".into(),
        claim_scope: PARAMETER_PRE_REGISTRATION_CLAIM_V1.into(),
        configuration_digest: configuration_digest.to_string(),
        round: config.round.clone(),
        purpose: config.purpose,
        subject: config.subject.clone(),
        candidate_id: config.candidate_id.clone(),
        baseline_material_digest: config.baseline_material.digest.clone(),
        baseline_registration_digest: config.baseline_registration.digest.clone(),
        baseline_model_artifact_id: inputs.baseline.manifests()[0]
            .manifest
            .artifact_id
            .to_string(),
        baseline_registry_head: inputs
            .baseline
            .current_head()
            .witness
            .head_digest
            .to_string(),
        baseline_signed_head_hex: hex(
            &codex_hepta_learning_artifacts::encode_untrusted_signed_artifact_head_v1(
                inputs.baseline.current_head(),
            ),
        ),
        baseline_current_witness: inputs
            .baseline
            .acknowledgement()
            .witness_receipt
            .ok_or("original baseline witness ACK")?
            .witness_digest
            .to_string(),
        baseline_publication_operation: inputs.baseline.acknowledgement().operation_id.to_string(),
        baseline_publication_state: inputs.baseline.acknowledgement().state_digest.to_string(),
        generator_digest: inputs.admission.generator_digest.to_string(),
        admission_digest: config.admission.digest.clone(),
        source_configuration_digest: config.source_configuration.digest.clone(),
        source_binding_digest: inputs.source.binding.binding_digest()?.to_string(),
        measured_at_ms,
        evaluator_uid: config.uid,
        evaluator_gid: config.gid,
        evaluator_program_digest: config.program_digest.clone(),
        evaluator_cgroup: cgroup,
        calibration,
        ood,
        calibration_execution,
        ood_execution,
        original_head_calibration: serde_json::to_value(head_calibration)?,
        original_head_ood: serde_json::to_value(head_ood)?,
        operational_constraints_passed: passed,
        cpu_answer_acceptance_permitted: false,
        final_material_digest: material
            .as_ref()
            .map(|bytes| Digest32::of_bytes(bytes).to_string()),
        final_material_hex: material.as_ref().map(|bytes| hex(bytes)),
    })
}
pub(super) fn sign(
    inputs: &Inputs,
    signing: &SigningKey,
    bytes: &[u8],
    now: u64,
) -> HostResult<SignedLearningEvidenceV1> {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!("parameter.e1.{}", Digest32::of_bytes(bytes)))?,
        principal_id: inputs.reviewer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: inputs.trust.verifier().trust_digest(),
        scope_digest: inputs.plan.scope.scope_digest,
        objective_digest: inputs.plan.scope.objective_digest,
        authority_epoch: inputs.reviewer.principal.authority_epoch,
        issued_at: now,
        expires_at: inputs.expiry,
        payload_digest: Digest32::of_bytes(bytes),
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    let actual =
        inputs
            .trust
            .verifier()
            .verify(LearningEvidenceRoleV1::Evaluator, &evidence, bytes, now)?;
    for actor in [&inputs.generator, &inputs.observer] {
        verify_signed_actor_separation(actor, &actual, now)?;
    }
    for cut in [&inputs.source.native.calibration, &inputs.source.native.ood] {
        for actor in &cut.actors {
            verify_signed_actor_separation(actor, &actual, now)?;
        }
    }
    Ok(evidence)
}
pub(super) fn preparation_facts(
    config: &FixedParameterPreRegistrationConfigV1,
    config_digest: Digest32,
    publication: &Report,
) -> HostResult<SelfIterationPreparationFactsV1> {
    let evidence_digest = |e: &ReviewEvidenceWireV1| -> HostResult<Digest32> {
        let e = e.native()?;
        Ok(Digest32::of_bytes(
            &[e.signing_bytes().as_slice(), &e.signature].concat(),
        ))
    };
    Ok(SelfIterationPreparationFactsV1 {
        disposition: SelfIterationPreparationDispositionV1::Ineligible,
        round_identity_digest: config.round.round_digest.parse()?,
        round_payload_digest: config.round.round_payload_digest.parse()?,
        canonical_policy_digest: config.round.canonical_policy_digest.parse()?,
        execution_envelope_digest: config.round.execution_digest.parse()?,
        enrolled_inputs_digest: config_digest,
        generated_digest: publication.body.generator_digest.parse()?,
        admission_digest: config.admission.digest.parse()?,
        generator_evidence_digest: evidence_digest(&config.generator_evidence)?,
        observer_evidence_digest: evidence_digest(&config.observer_evidence)?,
        evaluation_publication_digest: Digest32::of_bytes(&serde_json::to_vec(publication)?),
        admitted_at_ms: config.round.admitted_at_ms,
        deadline_ms: config.round.deadline_ms,
        observed_at_ms: publication.body.measured_at_ms,
    })
}
pub fn run_parameter_pre_registration_evaluator_v1(path: &Path) -> HostResult<()> {
    let bytes = read_root_review_input(path, 64 * 1024)?;
    let config: FixedParameterPreRegistrationConfigV1 = serde_json::from_slice(&bytes)?;
    let cgroup = boundary(config.uid, config.gid)?;
    crate::verify_registered_operational_program_v3(
        &std::env::current_exe()?,
        config.program_digest.parse()?,
    )?;
    for denied in &config.inaccessible_paths {
        match File::open(denied) {
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => return Err("pre-registration E can read Gold/other-role private key".into()),
        }
    }
    let started = now_ms()?;
    let inputs = inspect(&config, started)?;
    validate_reviewer(&config, &inputs)?;
    let signing = key(&config.private_key_path, config.uid)?;
    if signing.verifying_key().to_bytes() != inputs.reviewer.verifying_key {
        return Err("actual E1 signing key differs from independent original roster".into());
    }
    let mut body = measure_body(
        &config,
        &inputs,
        Digest32::of_bytes(&bytes),
        started,
        cgroup,
        None,
    )?;
    let measured = now_ms()?;
    if measured < started {
        return Err("pre-registration E clock rollback".into());
    }
    body.measured_at_ms = measured;
    let current = inspect(&config, measured)?;
    inputs.baseline.revalidate(measured)?;
    if read_root_review_input(path, 64 * 1024)? != bytes {
        return Err("E1 protected config changed".into());
    }
    let signed = sign(&current, &signing, &payload(&body)?, measured)?;
    let publication = Report {
        body,
        evaluator_signed_evidence: ReviewEvidenceWireV1::from_native(&signed),
    };
    let preparation_terminal_hex = if !publication.body.operational_constraints_passed {
        let facts = preparation_facts(&config, Digest32::of_bytes(&bytes), &publication)?;
        let signed = sign(
            &current,
            &signing,
            &crate::self_iteration_preparation_terminal_signing_payload_v1(&facts)?,
            measured,
        )?;
        Some(hex(&crate::encode_self_iteration_preparation_terminal_v1(
            &facts, &signed,
        )?))
    } else {
        None
    };
    let final_now = now_ms()?;
    if final_now < measured {
        return Err("E1 final-use clock rollback".into());
    }
    inspect(&config, final_now)?
        .baseline
        .revalidate(final_now)?;
    if read_root_review_input(path, 64 * 1024)? != bytes {
        return Err("E1 final source changed".into());
    }
    let output = serde_json::to_vec(&Output {
        publication,
        preparation_terminal_hex,
    })?;
    if output.len() > MAX_PARAMETER_PRE_REGISTRATION_REPORT_BYTES_V1 {
        return Err("whole E1 output bound".into());
    }
    let settled_now = now_ms()?;
    if settled_now < final_now {
        return Err("E1 output clock rollback".into());
    }
    config.round.validate(settled_now)?;
    current.trust.revalidate_at(settled_now)?;
    if settled_now >= current.expiry {
        return Err("E1 expired before publication".into());
    }
    println!("{}", std::str::from_utf8(&output)?);
    Ok(())
}
