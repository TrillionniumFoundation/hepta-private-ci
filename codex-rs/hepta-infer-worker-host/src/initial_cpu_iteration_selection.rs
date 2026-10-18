//! The original independent CPU Selector reviews a bounded authorized window.
//! This grants one cycle stage; artifact selection and publication stay separate.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::learning_ledger::ReviewEvidenceWireV1;
use codex_hepta_agent_components::learning_ledger::ReviewTrustWireV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agent_components::learning_ledger::activate_learning_trust;
use codex_hepta_agent_components::learning_ledger::verify_independent_roles;
use codex_hepta_agent_components::learning_ledger::verify_signed_independent_roles_v1;
use ed25519_dalek::Signer;
use std::path::PathBuf;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema: String,
    baseline_deployment: Source,
    learning_trust: Source,
    canonical_envelope_digest: String,
    consumer: RoleInput,
    evaluation: RoleInput,
    inaccessible_paths: [PathBuf; 5],
    candidates: Vec<Candidate>,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RoleInput {
    path: PathBuf,
    uid: u32,
}
impl RoleInput {
    fn read(&self, maximum: usize) -> HostResult<Vec<u8>> {
        read_self_iteration_role_input_v1(&self.path, self.uid, maximum)
    }
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Candidate {
    candidate_id: String,
    baseline_id: String,
    base_generation: u64,
    test_plan_digest: String,
    successor_configuration: String,
    rollback_configuration: String,
    successor_body: String,
    rollback_body: String,
    successor_artifacts: [Artifact; 3],
    rollback_artifacts: [Artifact; 3],
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Artifact {
    id: String,
    content_digest: String,
    support_digest: String,
    compatibility_digest: String,
    objective_digest: String,
    predecessor_id: String,
}

pub(super) fn select(path: &Path, pin: Digest32) -> HostResult<Value> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(64 * 1024)?;
    let config: Configuration = serde_json::from_slice(&bytes)?;
    if config.schema != "hepta.cpu-neuron.self-iteration-selection.v1"
        || !(1..=32).contains(&config.candidates.len())
        || config.consumer.uid == 0
        || config.evaluation.uid == 0
        || config.consumer.uid == config.evaluation.uid
    {
        return Err("original bounded CPU cycle selection policy".into());
    }
    let inputs = Inputs::read(
        &config.baseline_deployment.path,
        digest(&config.baseline_deployment.digest)?,
    )?;
    let selector = &inputs.profile.selector;
    if [config.consumer.uid, config.evaluation.uid].contains(&selector.uid) {
        return Err("cycle S shares the actual G or E process".into());
    }
    for private in &config.inaccessible_paths {
        match std::fs::File::open(private) {
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => {
                return Err(
                    "cycle S can read original custody/another key or denial is not physical"
                        .into(),
                );
            }
        }
    }
    let key = role::actual_role(&inputs, selector)?;
    let trust_bytes = config.learning_trust.read(64 * 1024)?;
    let wire: ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
    let (root, distribution) = wire.native()?;
    let selector_admission = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|signer| {
            signer.principal.principal_id.as_str() == selector.id
                && signer.roles.contains(&LearningEvidenceRoleV1::Selector)
        })
        .ok_or("original learning Selector admission missing")?
        .clone();
    if selector_admission.principal.signing_key_digest
        != Digest32::of_bytes(&key.verifying_key().to_bytes())
        || selector_admission.principal.credential_chain_digest
            != digest(&selector.credential_digest)?
    {
        return Err("original physical S does not own the admitted learning Selector".into());
    }
    let trust = activate_learning_trust(&root, distribution, None, now_ms()?)?;
    let consumer_bytes = config
        .consumer
        .read(MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES)?;
    let evaluation_bytes = config
        .evaluation
        .read(MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES)?;
    let frozen =
        inspect_signed_self_iteration_frozen_consumer_v1(&consumer_bytes, &trust, now_ms()?)?;
    if frozen.canonical_envelope_digest() != Some(digest(&config.canonical_envelope_digest)?) {
        return Err("original S authorized canonical window changed".into());
    }
    let evaluation = decode_self_iteration_evaluation_transport_v1(
        &evaluation_bytes,
        frozen.frozen_digest(),
        &trust,
        now_ms()?,
    )?;
    let authenticated = evaluation.admission().decision.authentication_digest;
    if evaluation.admission().decision.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err("original independently evaluated candidate is not eligible".into());
    }
    let (bundle, _, _, evaluator_use) = evaluation.into_parts();
    decode_self_iteration_frozen_consumer_v1(&consumer_bytes, &bundle, &trust, now_ms()?)?;
    let candidate = config
        .candidates
        .iter()
        .find(|value| value.candidate_id == frozen.candidate_id().as_str())
        .ok_or("candidate absent from original authorized window")?;
    if candidate.baseline_id != frozen.baseline_id().as_str()
        || candidate.base_generation != frozen.base_generation()
        || digest(&candidate.test_plan_digest)? != frozen.test_plan_digest()
        || digest(&candidate.successor_configuration)? != frozen.successor_configuration()
        || digest(&candidate.rollback_configuration)? != frozen.rollback_configuration()
        || digest(&candidate.successor_body)? != frozen.successor_body()
        || digest(&candidate.rollback_body)? != frozen.rollback_body()
    {
        return Err("original authorized CPU successor or rollback changed".into());
    }
    let owner = inputs.current()?;
    let current = owner.current_registry_view(now_ms()?)?;
    for (increment, artifacts) in [
        (1, &candidate.successor_artifacts),
        (2, &candidate.rollback_artifacts),
    ] {
        let generation = candidate
            .base_generation
            .checked_add(increment)
            .ok_or("cycle artifact generation overflow")?;
        for (expected, kind) in artifacts.iter().zip([
            ArtifactKind::Model,
            ArtifactKind::Policy,
            ArtifactKind::Policy,
        ]) {
            verify_artifact(
                expected,
                kind,
                generation,
                &current,
                &inputs.profile.owner_root,
            )?;
        }
    }
    let payload = self_iteration_evaluation_use_payload_v1(frozen.frozen_digest(), authenticated);
    let now = now_ms()?;
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!("cpu.cycle.selection.{}", frozen.frozen_digest()))?,
        principal_id: id(&selector.id)?,
        role: LearningEvidenceRoleV1::Selector,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: trust.verifier().scope_digest(),
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: trust.verifier().authority_epoch(),
        issued_at: now,
        expires_at: frozen
            .expires_at()
            .min(evaluator_use.expires_at)
            .min(trust.expires_at()),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    // All original sources and the exact current registry are checked after
    // payload reads, immediately before the one role signing effect.
    inputs.revalidate()?;
    if source.read(64 * 1024)? != bytes
        || config.learning_trust.read(64 * 1024)? != trust_bytes
        || config
            .consumer
            .read(MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES)?
            != consumer_bytes
        || config
            .evaluation
            .read(MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES)?
            != evaluation_bytes
    {
        return Err("original CPU cycle selection sources changed".into());
    }
    let final_now = now_ms()?;
    trust.revalidate_at(final_now)?;
    role::require_actual_program(&inputs.profile.program, selector)?;
    if selector_admission
        .revoked_at
        .is_some_and(|time| final_now >= time)
        || final_now >= selector_admission.principal.expires_at
    {
        return Err("original learning Selector was revoked or expired".into());
    }
    let signed_generator =
        inspect_signed_self_iteration_frozen_consumer_v1(&consumer_bytes, &trust, final_now)?;
    let signed_evaluator = trust.verifier().verify(
        LearningEvidenceRoleV1::Evaluator,
        &evaluator_use,
        &payload,
        final_now,
    )?;
    for actor in [signed_generator.generator(), &signed_evaluator] {
        verify_independent_roles(actor.principal(), &selector_admission.principal, final_now)?;
        if actor.controller_id() == &selector_admission.controller_id {
            return Err("original S shares a current G/E controller".into());
        }
    }
    let latest = owner.current_registry_view(final_now)?;
    if latest.receipt() != current.receipt()
        || latest.witness_digest() != current.witness_digest()
        || latest.trust_digest() != current.trust_digest()
        || final_now >= evidence.expires_at
    {
        return Err("current CPU cycle selection authority changed or expired".into());
    }
    evidence.issued_at = final_now;
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    let signed_selector = trust.verifier().verify(
        LearningEvidenceRoleV1::Selector,
        &evidence,
        &payload,
        final_now,
    )?;
    verify_signed_independent_roles_v1(frozen.generator(), &signed_selector, final_now)?;
    verify_signed_independent_roles_v1(&signed_evaluator, &signed_selector, final_now)?;
    Ok(serde_json::json!({
        "schema":"hepta.cpu-neuron.self-iteration-stage-selection.v1",
        "configuration_digest":pin.to_string(), "frozen_digest":frozen.frozen_digest().to_string(),
        "evaluation_digest":authenticated.to_string(), "selector_uid":selector.uid,
        "selector_evidence":ReviewEvidenceWireV1::from_native(&evidence),
        "artifact_publication":false, "production_activation":false,
    }))
}

fn verify_artifact(
    expected: &Artifact,
    kind: ArtifactKind,
    generation: u64,
    current: &VerifiedCurrentRegistryViewV1,
    root: &Path,
) -> HostResult<()> {
    let artifact_id = id(&expected.id)?;
    let manifest = current
        .eligible_manifest(&artifact_id)
        .ok_or("cycle artifact not currently eligible")?;
    verify_tuple(expected, manifest, kind, generation)?;
    let payload = read_root_review_input(
        &root.join("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.content_digest,
        )),
        manifest.encoded_size_bytes,
    )?;
    if payload.len() as u64 != manifest.encoded_size_bytes
        || Digest32::of_bytes(&payload) != manifest.content_digest
    {
        return Err("actual current successor payload changed".into());
    }
    Ok(())
}

fn verify_tuple(
    expected: &Artifact,
    manifest: &ArtifactManifest,
    kind: ArtifactKind,
    generation: u64,
) -> HostResult<()> {
    if manifest.artifact_id != id(&expected.id)?
        || manifest.kind != kind
        || manifest.generation.get() != generation
        || manifest.predecessor_id.as_ref() != Some(&id(&expected.predecessor_id)?)
        || manifest.content_digest != digest(&expected.content_digest)?
        || manifest.support_digest != digest(&expected.support_digest)?
        || manifest.compatibility_digest != digest(&expected.compatibility_digest)?
        || manifest.objective_digest != digest(&expected.objective_digest)?
        || manifest.encoded_size_bytes == 0
        || manifest.encoded_size_bytes > 16 * 1024 * 1024
    {
        return Err("original current successor artifact differs from authorized tuple".into());
    }
    Ok(())
}

#[cfg(test)]
#[path = "initial_cpu_iteration_selection_tests.rs"]
mod tests;
