//! Independent E entry for the CPU abstention-only stable-model lease.
use crate::fixed_calibration_host::boundary;
use crate::fixed_calibration_host::key;
use crate::fixed_calibration_host::now_ms;
use crate::initial_neuron_operational_host::Config;
use crate::initial_neuron_operational_host::measurement_body as native_body;
use crate::initial_neuron_operational_source::HostResult;
use crate::operational_model_lease_policy_v2::CLAIM;
use crate::operational_model_lease_policy_v2::CONFIG_SCHEMA;
use crate::operational_model_lease_policy_v2::Inputs;
use crate::operational_model_lease_policy_v2::inspect_inputs;
use crate::operational_model_lease_policy_v2::reinspect_inputs;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::read_root_review_input;
use codex_hepta_learning_ledger::verify_signed_actor_separation;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use serde_json::Value;
use serde_json::json;
use std::fs::File;
use std::path::Path;

pub(super) fn payload(body: &Value) -> HostResult<Vec<u8>> {
    let bytes = serde_json::to_vec(body)?;
    if bytes.len() > 64 * 1024 {
        return Err("bounded stable operational model report".into());
    }
    let mut payload = b"hepta.intelligence-eval.operational-model-lease.v2".to_vec();
    payload.extend_from_slice(Digest32::of_bytes(&bytes).as_array());
    Ok(payload)
}
pub(super) fn body(
    config: &Config,
    inputs: &Inputs,
    config_digest: Digest32,
    now: u64,
    program: Digest32,
    cgroup: &str,
) -> HostResult<Value> {
    if now < inputs.policy.frozen_at_ms {
        return Err("stable model report predates frozen measurements".into());
    }
    for cut in [&inputs.native.calibration, &inputs.native.ood] {
        for original in &cut.original_resources {
            if original["executed_at_ms"]
                .as_u64()
                .is_none_or(|at| at > now)
            {
                return Err("stable model report predates a native observation".into());
            }
        }
        for original in [
            cut.publication.cut.generator_evidence.native()?,
            cut.publication.cut.freeze_evidence.native()?,
            cut.publication.observer_evidence.native()?,
        ] {
            if original.issued_at > now {
                return Err("stable model report predates authenticated source evidence".into());
            }
        }
    }
    let mut result = native_body(config, &inputs.native, config_digest, now, program, cgroup)?;
    let profile = &inputs.policy.runtime_profile;
    let passed = [&result["calibration"], &result["ood"]]
        .into_iter()
        .all(|metrics| {
            metrics["p95_latency_micros"]
                .as_u64()
                .is_some_and(|v| v <= profile.p95_latency_micros)
                && metrics["p99_latency_micros"]
                    .as_u64()
                    .is_some_and(|v| v <= profile.p99_latency_micros)
                && metrics["maximum_transient_allocation_bytes"]
                    .as_u64()
                    .is_some_and(|v| v <= profile.transient_allocation_bytes)
        });
    result["schema"] = json!("hepta.cpu-neuron.operational-model-lease-measurements.v2");
    result["claim_scope"] = json!(CLAIM);
    result["model_binding"] = serde_json::to_value(&inputs.policy.binding)?;
    result["binding_digest"] = json!(inputs.binding.binding_digest()?.to_string());
    result["runtime_profile"] = serde_json::to_value(profile)?;
    result["operational_constraints_passed"] =
        json!(passed && result["operational_constraints_passed"] == true);
    result["cpu_answer_acceptance_permitted"] = json!(false);
    result["execution_ceilings_independently_measured"] = json!(false);
    Ok(result)
}

pub(super) fn expires_at(inputs: &Inputs, reviewer_expiry: u64) -> HostResult<u64> {
    let mut expiry = inputs.policy.expires_at_ms.min(reviewer_expiry);
    for cut in [&inputs.native.calibration, &inputs.native.ood] {
        for actor in &cut.actors {
            expiry = expiry.min(actor.principal().expires_at);
        }
        for evidence in [
            cut.publication.cut.generator_evidence.native()?,
            cut.publication.cut.freeze_evidence.native()?,
            cut.publication.observer_evidence.native()?,
        ] {
            expiry = expiry.min(evidence.expires_at);
        }
    }
    Ok(expiry)
}

/// Only the actual independent evaluator role signs newly measured V2 evidence.
/// This never reads holdout, selects a candidate, or admits a CPU-produced answer.
pub fn run_operational_model_lease_evaluator_v2(path: &Path) -> HostResult<()> {
    let bytes = read_root_review_input(path, 32 * 1024)?;
    let config: Config = serde_json::from_slice(&bytes)?;
    if config.schema != CONFIG_SCHEMA || config.inaccessible_paths.len() != 5 {
        return Err("fixed stable-model evaluator schema/custody boundary".into());
    }
    let cgroup = boundary(config.uid, config.gid)?;
    let program = Digest32::of_bytes(&read_root_review_input(
        &std::env::current_exe()?,
        128 * 1024 * 1024,
    )?);
    if program.is_zero() || program != config.program_digest.parse::<Digest32>()? {
        return Err("stable model evaluator actual executable pin".into());
    }
    for inaccessible in &config.inaccessible_paths {
        match File::open(inaccessible) {
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => return Err("independent model evaluator can read gold or another key".into()),
        }
    }
    let now = now_ms()?;
    let inputs = inspect_inputs(&config, now)?;
    let (_, distribution) = inputs.native.calibration.publication.trust.native()?;
    let reviewer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|s| s.principal.principal_id.as_str() == "fixed-no-custody-reviewer")
        .ok_or("independent stable model evaluator not Root admitted")?;
    crate::fixed_calibration_cycle_evaluator::verify_actual_reviewer(
        reviewer,
        program,
        &inputs.native.calibration.root_key,
        config.uid,
        config.gid,
        None,
    )?;
    let signing = key(&config.private_key_path, config.uid)?;
    if Digest32::of_bytes(signing.verifying_key().as_bytes())
        != reviewer.principal.signing_key_digest
    {
        return Err("stable model evaluator key differs from admitted E".into());
    }
    let body = body(
        &config,
        &inputs,
        Digest32::of_bytes(&bytes),
        now,
        program,
        &cgroup,
    )?;
    let payload = payload(&body)?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: StableId::new(format!(
            "operational.model.v2.{}",
            Digest32::of_bytes(&payload)
        ))?,
        principal_id: reviewer.principal.principal_id.clone(),
        role: LearningEvidenceRoleV1::Evaluator,
        trust_digest: inputs.native.calibration.trust.verifier().trust_digest(),
        scope_digest: inputs.policy.scope_digest.parse()?,
        objective_digest: inputs.binding.binding_digest()?,
        authority_epoch: reviewer.principal.authority_epoch,
        issued_at: now,
        expires_at: expires_at(&inputs, reviewer.principal.expires_at)?,
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    evidence.signature = signing.sign(&evidence.signing_bytes()).to_bytes();
    let actual = inputs.native.calibration.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence,
        &payload,
        now,
    )?;
    for cut in [&inputs.native.calibration, &inputs.native.ood] {
        for actor in &cut.actors {
            verify_signed_actor_separation(actor, &actual, now)?;
        }
    }
    let final_now = now_ms()?;
    if final_now < now || read_root_review_input(path, 32 * 1024)? != bytes {
        return Err("stable model clock rolled back or protected config changed".into());
    }
    reinspect_inputs(&config, final_now, &inputs.material)?;
    inputs.native.calibration.trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &evidence,
        &payload,
        final_now,
    )?;
    println!(
        "{}",
        serde_json::to_string(
            &json!({"body":body,"evaluator_signed_evidence":ReviewEvidenceWireV1::from_native(&evidence)})
        )?
    );
    Ok(())
}

#[cfg(test)]
#[path = "operational_model_lease_host_v2_tests.rs"]
mod tests;
