//! Custody O signs the original physical verdict over an acknowledged canary.
use super::*;
use codex_hepta_agent_components::neuron::MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2;
use codex_hepta_agent_components::neuron::NeuronAcknowledgedOperationV2;
use codex_hepta_agentd::AgentdSelfIterationCanaryVerdictV1;
use codex_hepta_agentd::self_iteration_canary_payload_v1;
use ed25519_dalek::Signer;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Selection {
    schema: String,
    configuration_digest: String,
    frozen_digest: String,
    evaluation_digest: String,
    selector_uid: u32,
    selector_evidence: ledger::ReviewEvidenceWireV1,
    artifact_publication: bool,
    production_activation: bool,
}
pub fn observe_registered_cpu_self_iteration_canary_v1(path: &Path, pin: Digest32) -> HostResult<Value> {
    let loaded = Loaded::read(path, pin, true)?;
    let selection_source = loaded.config.selection.as_ref().ok_or("actual Root S Source absent")?;
    let canary_source = loaded.config.canary.as_ref().ok_or("actual Root canary Source absent")?;
    let selection_bytes = selection_source.read(32 * 1024)?;
    let canary_bytes = canary_source.read(MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2 as u64)?;
    let selected: Selection = serde_json::from_slice(&selection_bytes)?;
    if selected.schema != "hepta.cpu-neuron.self-iteration-stage-selection.v1"
        || digest(&selected.configuration_digest)?.is_zero()
        || digest(&selected.frozen_digest)? != loaded.frozen.frozen_digest()
        || digest(&selected.evaluation_digest)? != loaded.evaluation_digest
        || selected.selector_uid != 0 || selected.artifact_publication || selected.production_activation {
        return Err("actual registered S stage result differs from frozen/evaluation".into());
    }
    let selector_evidence = selected.selector_evidence.native()?;
    let now = loaded.revalidate()?;
    let stage_payload = loaded.stage_payload();
    let selector = loaded.trust.verifier().verify(ledger::LearningEvidenceRoleV1::Selector,
        &selector_evidence, &stage_payload, now)?;
    verify_selector(&loaded, &selector, now)?;
    let canary = NeuronAcknowledgedOperationV2::from_bytes(canary_bytes.clone(), digest(&canary_source.digest)?)?;
    if canary.scope() != loaded.successor.material().scope {
        return Err("actual physical canary is outside full registered scope".into());
    }
    let record = iteration_observation::observed_record(&loaded.frozen, loaded.evaluation_digest,
        &selector_evidence, &canary, loaded.round.deadline_ms())?;
    let observation = record.canary_observation.as_ref().ok_or("actual physical observation absent")?;
    let runtime = &loaded.successor.material().runtime;
    let verdict = iteration_observation::physical_verdict_with_bounds(observation, &canary,
        runtime.calibration.minimum_confidence_ppm, runtime.calibration.maximum_ood_ppm,
        runtime.resource_envelope.p99_latency_micros, loaded.canonical.policy().compute_budget.maximum_memory_bytes);
    let payload = self_iteration_canary_payload_v1(&record, verdict)?;
    let key = role::actual_role_for_program(&loaded.config.program, &loaded.config.actor)?;
    if key.verifying_key().to_bytes() != loaded.actor.verifying_key {
        return Err("actual custody O key differs from independently admitted principal".into());
    }
    check_sources(selection_source, canary_source, &selection_bytes, &canary_bytes)?;
    let final_now = loaded.revalidate()?;
    let selector = loaded.trust.verifier().verify(ledger::LearningEvidenceRoleV1::Selector,
        &selector_evidence, &stage_payload, final_now)?;
    verify_selector(&loaded, &selector, final_now)?;
    let mut evidence = loaded.evidence(ledger::LearningEvidenceRoleV1::Observer, &payload, final_now)?;
    evidence.expires_at = evidence.expires_at.min(selector_evidence.expires_at);
    if final_now >= evidence.expires_at { return Err("actual registered S/O expiry".into()); }
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    check_sources(selection_source, canary_source, &selection_bytes, &canary_bytes)?;
    let settled = loaded.revalidate()?;
    let selector = loaded.trust.verifier().verify(ledger::LearningEvidenceRoleV1::Selector,
        &selector_evidence, &stage_payload, settled)?;
    verify_selector(&loaded, &selector, settled)?;
    let signed = loaded.trust.verifier().verify(ledger::LearningEvidenceRoleV1::Observer,
        &evidence, &payload, settled)?;
    let evaluator = loaded.trust.verifier().verify(ledger::LearningEvidenceRoleV1::Evaluator,
        &loaded.evaluator_evidence, &stage_payload, settled)?;
    for actor in [loaded.frozen.generator(), &evaluator, &selector] {
        ledger::verify_signed_independent_roles_v1(actor, &signed, settled)?;
    }
    Ok(serde_json::json!({"schema":"hepta.cpu-neuron.self-iteration-canary-observation.v1",
        "configuration_digest":pin.to_string(),"frozen_digest":loaded.frozen.frozen_digest().to_string(),
        "canary_receipt_digest":canary_source.digest,"canary_operation_digest":record.canary_operation_digest.map(|d|d.to_string()),
        "canary_checkpoint_digest":record.canary_checkpoint_digest.map(|d|d.to_string()),
        "physical_observation":observation,"verdict":match verdict { AgentdSelfIterationCanaryVerdictV1::Accept=>"accept", AgentdSelfIterationCanaryVerdictV1::RollBack=>"rollback" },
        "observer_evidence":ledger::ReviewEvidenceWireV1::from_native(&evidence),"production_activation":false}))
}
fn check_sources(selection: &Source, canary: &Source, selection_bytes: &[u8], canary_bytes: &[u8]) -> HostResult<()> {
    if selection.read(32 * 1024)? != selection_bytes
        || canary.read(MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2 as u64)? != canary_bytes {
        return Err("whole physical canary/S Sources changed".into());
    }
    Ok(())
}
fn verify_selector(loaded: &Loaded, selector: &ledger::VerifiedLearningEvidenceV1, now: u64) -> HostResult<()> {
    let original = loaded.successor.selector_identity();
    if selector.principal().principal_id.as_str() != original.id
        || selector.principal().credential_chain_digest != digest(&original.credential_digest)?
        || selector.principal().signing_key_digest != Digest32::of_bytes(&public(&original.public_key_hex)?) {
        return Err("physical observation received a different original registered S".into());
    }
    let evaluator = loaded.trust.verifier().verify(ledger::LearningEvidenceRoleV1::Evaluator,
        &loaded.evaluator_evidence, &loaded.stage_payload(), now)?;
    iteration_observation::require_independent_actors(loaded.frozen.generator(), &evaluator, selector, now)?;
    ledger::verify_independent_roles(selector.principal(), &loaded.actor.principal, now)?;
    if selector.controller_id() == &loaded.actor.controller_id {
        return Err("actual physical O and S share controller".into());
    }
    Ok(())
}
