//! Stage S consumes the actual registered candidate and rollback admissions.
use super::*;
use ed25519_dalek::Signer;

pub fn select_registered_cpu_self_iteration_stage_v1(
    path: &Path,
    pin: Digest32,
) -> HostResult<Value> {
    let loaded = Loaded::read(path, pin, false)?;
    let key = role::actual_role_for_program(&loaded.config.program, &loaded.config.actor)?;
    if key.verifying_key().to_bytes() != loaded.actor.verifying_key {
        return Err("actual registered S key differs from admitted principal".into());
    }
    let payload = loaded.stage_payload();
    let now = loaded.revalidate()?;
    let mut evidence = loaded.evidence(ledger::LearningEvidenceRoleV1::Selector, &payload, now)?;
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    let final_now = loaded.revalidate()?;
    let signed = loaded.trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Selector,
        &evidence,
        &payload,
        final_now,
    )?;
    let evaluator = loaded.trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Evaluator,
        &loaded.evaluator_evidence,
        &payload,
        final_now,
    )?;
    ledger::verify_signed_independent_roles_v1(loaded.frozen.generator(), &signed, final_now)?;
    ledger::verify_signed_independent_roles_v1(&evaluator, &signed, final_now)?;
    Ok(serde_json::json!({
        "schema":"hepta.cpu-neuron.self-iteration-stage-selection.v1",
        "configuration_digest":pin.to_string(), "frozen_digest":loaded.frozen.frozen_digest().to_string(),
        "evaluation_digest":loaded.evaluation_digest.to_string(), "selector_uid":loaded.config.actor.uid,
        "selector_evidence":ledger::ReviewEvidenceWireV1::from_native(&evidence),
        "artifact_publication":false,"production_activation":false,
    }))
}
