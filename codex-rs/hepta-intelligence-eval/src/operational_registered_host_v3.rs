//! Independently deployed E signs a full registered successor and measurements
//! from the original sparse kernel, retaining mandatory calibration/slow-path.
use crate::fixed_calibration_host::boundary;
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::initial_neuron_operational_metrics::measure;
use crate::initial_neuron_operational_source::HostResult;
use crate::operational_registered_measurement_v3::Execution;
use crate::operational_registered_measurement_v3::Replay;
use crate::operational_registered_measurement_v3::replay;
use crate::operational_registered_model_v3::RegisteredOperationalModelBindingV3;
use crate::operational_registered_policy_v3::Config;
use crate::operational_registered_policy_v3::Inputs;
use crate::operational_registered_policy_v3::inspect;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;
use std::fs::File;
use std::path::Path;

#[derive(Debug, Deserialize, Serialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub(super) struct Body {
    pub schema: String,
    pub binding: RegisteredOperationalModelBindingV3,
    pub configuration_digest: String,
    pub original_source_configuration_digest: String,
    pub original_source_binding_digest: String,
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
    pub cpu_answer_acceptance_permitted: bool,
    pub operational_constraints_passed: bool,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Report {
    pub body: Body,
    pub evaluator_signed_evidence: ReviewEvidenceWireV1,
}

pub(super) fn payload(body: &Body) -> HostResult<Vec<u8>> {
    let bytes = serde_json::to_vec(body)?;
    if bytes.len() > 64 * 1024 {
        return Err("bounded whole registered operational report".into());
    }
    let mut payload = b"hepta.intelligence-eval.registered-operational-evaluation.v3\0".to_vec();
    payload.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    Ok(payload)
}
pub(super) fn replay_constraints(
    inputs: &Inputs,
    config: &Config,
    replay: &Replay,
    execution: &Execution,
) -> bool {
    let limits = &inputs.plan.runtime.resource_envelope;
    replay.all_require_calibration
        && replay.rows > 0
        && replay.rows <= 2048
        && replay.maximum_checkpoint_bytes <= limits.checkpoint_bytes
        && replay.maximum_projection_count
            <= inputs.plan.runtime.calibration.maximum_projection_count
        && execution.p95_latency_micros <= limits.p95_latency_micros
        && execution.p99_latency_micros <= limits.p99_latency_micros
        && execution.resident_high_water_bytes <= config.maximum_resident_bytes
}
pub(super) fn validate_reviewer(config: &Config, inputs: &Inputs) -> HostResult<()> {
    let root =
        codex_hepta_learning_ledger::decode_review_payload_hex(&config.root_verifying_key_hex)?;
    let root: [u8; 32] = root
        .try_into()
        .map_err(|_| "current Root verifying key width")?;
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        &inputs.reviewer,
        config.program_digest.parse()?,
        &root,
        config.uid,
        config.gid,
        None,
    )
}

/// Actual E role entry. This opens only that role's original signing key and
/// read-only authenticated public inputs; no model/Artifact owner is mutated.
pub fn run_registered_operational_model_evaluator_v3(path: &Path) -> HostResult<()> {
    let bytes = read_root_review_input(path, 64 * 1024)?;
    let config: Config = serde_json::from_slice(&bytes)?;
    let cgroup = boundary(config.uid, config.gid)?;
    let program = crate::verify_registered_operational_program_v3(
        &std::env::current_exe()?,
        config.program_digest.parse()?,
    )?;
    for denied in &config.inaccessible_paths {
        match File::open(denied) {
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => return Err("registered E can read Gold/other role key".into()),
        }
    }
    let started = now_ms()?;
    let inputs = inspect(&config, started)?;
    validate_reviewer(&config, &inputs)?;
    let signing = key(&config.private_key_path, config.uid)?;
    if signing.verifying_key().to_bytes() != inputs.reviewer.verifying_key {
        return Err("registered E actual key/roster mismatch".into());
    }
    let (calibration, calibration_execution) =
        replay(&inputs.plan, &inputs.source.native.calibration)?;
    let (ood, ood_execution) = replay(&inputs.plan, &inputs.source.native.ood)?;
    let original_head_calibration = serde_json::to_value(measure(
        &inputs.source.native.calibration,
        &inputs.source.native.policy.gates,
    )?)?;
    let original_head_ood = serde_json::to_value(measure(
        &inputs.source.native.ood,
        &inputs.source.native.policy.gates,
    )?)?;
    let constraints = replay_constraints(&inputs, &config, &calibration, &calibration_execution)
        && replay_constraints(&inputs, &config, &ood, &ood_execution)
        && original_head_calibration["operational_constraints_passed"] == true
        && original_head_ood["operational_constraints_passed"] == true;
    let measured = now_ms()?;
    if measured < started {
        return Err("registered E clock rollback".into());
    }
    let body = Body {
        schema: "hepta.registered-operational-model-evaluation.v3".into(),
        binding: inputs.binding.clone(),
        configuration_digest: Digest32::of_bytes(&bytes).to_string(),
        original_source_configuration_digest: config.source_configuration.digest.clone(),
        original_source_binding_digest: inputs.source.binding.binding_digest()?.to_string(),
        measured_at_ms: measured,
        evaluator_uid: config.uid,
        evaluator_gid: config.gid,
        evaluator_program_digest: program.to_string(),
        evaluator_cgroup: cgroup,
        calibration,
        ood,
        calibration_execution,
        ood_execution,
        original_head_calibration,
        original_head_ood,
        cpu_answer_acceptance_permitted: false,
        operational_constraints_passed: constraints,
    };
    let payload = payload(&body)?;
    let final_inputs = inspect(&config, measured)?;
    if final_inputs.binding != inputs.binding || read_root_review_input(path, 64 * 1024)? != bytes {
        return Err("registered E protected material/current/config changed".into());
    }
    let mut signed = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!(
            "registered.operational.v3.{}",
            Digest32::of_bytes(&payload)
        ))?,
        principal_id: inputs.reviewer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: inputs.current_trust.verifier().trust_digest(),
        scope_digest: inputs.plan.scope.scope_digest,
        objective_digest: inputs.plan.scope.objective_digest,
        authority_epoch: inputs.reviewer.principal.authority_epoch,
        issued_at: measured,
        expires_at: inputs.expiry.min(final_inputs.expiry),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    signed.signature = signing.sign(&signed.signing_bytes()).to_bytes();
    let actual = final_inputs.current_trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &payload,
        measured,
    )?;
    for cut in [&inputs.source.native.calibration, &inputs.source.native.ood] {
        for actor in &cut.actors {
            verify_signed_actor_separation(actor, &actual, measured)?;
        }
    }
    let now = now_ms()?;
    if now < measured
        || inspect(&config, now)?.binding != inputs.binding
        || read_root_review_input(path, 64 * 1024)? != bytes
    {
        return Err("registered E final-use current/source changed".into());
    }
    final_inputs.current_trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &signed,
        &payload,
        now,
    )?;
    println!(
        "{}",
        serde_json::to_string(&Report {
            body,
            evaluator_signed_evidence: ReviewEvidenceWireV1::from_native(&signed)
        })?
    );
    Ok(())
}
