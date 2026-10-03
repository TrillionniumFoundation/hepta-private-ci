//! Independent O signs only an actual original acknowledged physical canary.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger as ledger;
use codex_hepta_agent_components::neuron::MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2;
use codex_hepta_agent_components::neuron::NeuronAcknowledgedOperationV2;
use codex_hepta_agent_components::neuron::NeuronCommitDispositionV1;
use codex_hepta_agentd::AgentdSelfIterationCanaryObservationV1;
use codex_hepta_agentd::AgentdSelfIterationCanaryVerdictV1;
use codex_hepta_agentd::AgentdSelfIterationPhaseV1;
use codex_hepta_agentd::AgentdSelfIterationRecordV1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_agentd::CanonicalIterationEnvelopeV1;
use codex_hepta_agentd::self_iteration_canary_payload_v1;
use ed25519_dalek::Signer;
use std::path::PathBuf;

#[path = "initial_cpu_iteration_observation_root.rs"]
mod root_custody;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Configuration {
    schema: String,
    baseline_deployment: Source,
    learning_trust: Source,
    canonical_envelope_digest: String,
    observer: Role,
    consumer: RoleInput,
    evaluation: RoleInput,
    selection: RoleInput,
    canary: Source,
    inaccessible_paths: Vec<PathBuf>,
    #[serde(default)]
    root_custody: Option<root_custody::RootCustody>,
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

pub(super) fn observe(path: &Path, pin: Digest32) -> HostResult<Value> {
    observe_inner(path, pin, false)
}
pub(super) fn observe_root(path: &Path, pin: Digest32) -> HostResult<Value> {
    observe_inner(path, pin, true)
}
fn observe_inner(path: &Path, pin: Digest32, root_purpose: bool) -> HostResult<Value> {
    let source = Source {
        path: path.to_owned(),
        digest: pin.to_string(),
    };
    let bytes = source.read(64 * 1024)?;
    let config: Configuration = serde_json::from_slice(&bytes)?;
    root_custody::validate_purpose(&config, root_purpose)?;
    let inputs = Inputs::read(
        &config.baseline_deployment.path,
        digest(&config.baseline_deployment.digest)?,
    )?;
    if config.selection.uid != inputs.profile.selector.uid {
        return Err("original Selector UID changed".into());
    }
    for private in &config.inaccessible_paths {
        match std::fs::File::open(private) {
            Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => (),
            _ => return Err("O can read Gold/another key or denial is not physical".into()),
        }
    }
    let key = if let Some(custody) = &config.root_custody {
        root_custody::key(custody, &inputs, &config.observer)?
    } else {
        role::actual_role(&inputs, &config.observer)?
    };
    let trust_bytes = config.learning_trust.read(64 * 1024)?;
    let wire: ledger::ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
    let (root, distribution) = wire.native()?;
    let observer = distribution
        .distribution
        .trust
        .signers
        .iter()
        .find(|signer| {
            signer.principal.principal_id.as_str() == config.observer.id
                && signer
                    .roles
                    .contains(&ledger::LearningEvidenceRoleV1::Observer)
        })
        .ok_or("original Observer not admitted")?
        .clone();
    if observer.verifying_key != key.verifying_key().to_bytes()
        || observer.principal.credential_chain_digest != digest(&config.observer.credential_digest)?
        || observer.principal.signing_key_digest
            != Digest32::of_bytes(&key.verifying_key().to_bytes())
    {
        return Err("physical O does not own original admitted Observer".into());
    }
    if let Some(custody) = &config.root_custody {
        root_custody::verify(custody, &observer)?;
    }
    let now = now_ms()?;
    let trust = ledger::activate_learning_trust(&root, distribution, None, now)?;
    let consumer_bytes = config
        .consumer
        .read(MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES)?;
    let evaluation_bytes = config
        .evaluation
        .read(MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES)?;
    let selection_bytes = root_custody::selection(&config, 32 * 1024)?;
    let canary_bytes = config
        .canary
        .read(MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2 as u64)?;
    let frozen = inspect_signed_self_iteration_frozen_consumer_v1(&consumer_bytes, &trust, now)?;
    if frozen.canonical_envelope_digest() != Some(digest(&config.canonical_envelope_digest)?) {
        return Err("O canonical policy window changed".into());
    }
    let canonical = CanonicalIterationEnvelopeV1::decode(
        frozen
            .canonical_envelope_bytes()
            .ok_or("O requires full canonical bytes")?,
    )?;
    let round = AgentdSelfIterationRoundV1::decode(
        frozen
            .generator_round_bytes()
            .ok_or("O requires sealed original round")?,
    )?;
    if canonical.digest() != round.canonical_policy_digest()
        || canonical.digest() != digest(&config.canonical_envelope_digest)?
        || now >= round.deadline_ms()
        || now >= canonical.policy().expires_unix_ms
    {
        return Err("O original policy or admitted round expired".into());
    }
    let evaluated = decode_self_iteration_evaluation_transport_v1(
        &evaluation_bytes,
        frozen.frozen_digest(),
        &trust,
        now,
    )?;
    if evaluated.admission().decision.decision.disposition
        != IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    {
        return Err("O requires actual independently eligible evaluation".into());
    }
    let authentication = evaluated.admission().decision.authentication_digest;
    let (bundle, _, _, evaluator_evidence) = evaluated.into_parts();
    decode_self_iteration_frozen_consumer_v1(&consumer_bytes, &bundle, &trust, now)?;
    let selected: Selection = serde_json::from_slice(&selection_bytes)?;
    if selected.schema != "hepta.cpu-neuron.self-iteration-stage-selection.v1"
        || digest(&selected.configuration_digest)?.is_zero()
        || digest(&selected.frozen_digest)? != frozen.frozen_digest()
        || digest(&selected.evaluation_digest)? != authentication
        || selected.selector_uid != config.selection.uid
        || selected.artifact_publication
        || selected.production_activation
    {
        return Err("O actual Selector result changed".into());
    }
    let selector_evidence = selected.selector_evidence.native()?;
    let stage_payload =
        self_iteration_evaluation_use_payload_v1(frozen.frozen_digest(), authentication);
    let selector = trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Selector,
        &selector_evidence,
        &stage_payload,
        now,
    )?;
    let evaluator = trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Evaluator,
        &evaluator_evidence,
        &stage_payload,
        now,
    )?;
    if selector.principal().principal_id.as_str() != inputs.profile.selector.id
        || selector.principal().credential_chain_digest
            != digest(&inputs.profile.selector.credential_digest)?
        || selector.principal().signing_key_digest
            != Digest32::of_bytes(&public(&inputs.profile.selector.public_key_hex)?)
    {
        return Err("O received a different independently installed Selector".into());
    }
    require_independent_actors(frozen.generator(), &evaluator, &selector, now)?;
    for actor in [frozen.generator(), &evaluator, &selector] {
        ledger::verify_independent_roles(actor.principal(), &observer.principal, now)?;
        if actor.controller_id() == &observer.controller_id {
            return Err("O shares a G/E/S controller".into());
        }
    }
    let canary = NeuronAcknowledgedOperationV2::from_bytes(
        canary_bytes.clone(),
        digest(&config.canary.digest)?,
    )?;
    let record = observed_record(
        &frozen,
        authentication,
        &selector_evidence,
        &canary,
        round.deadline_ms(),
    )?;
    let observation = record
        .canary_observation
        .as_ref()
        .ok_or("original physical observation missing")?;
    let verdict = physical_verdict(
        observation,
        &canary,
        &inputs,
        canonical.policy().compute_budget.maximum_memory_bytes,
    );
    let payload = self_iteration_canary_payload_v1(&record, verdict)?;
    let mut evidence = ledger::SignedLearningEvidenceV1 {
        evidence_id: id(&format!("cpu.cycle.observation.{}", frozen.frozen_digest()))?,
        principal_id: id(&config.observer.id)?,
        role: ledger::LearningEvidenceRoleV1::Observer,
        trust_digest: trust.verifier().trust_digest(),
        scope_digest: trust.verifier().scope_digest(),
        objective_digest: trust.verifier().objective_digest(),
        authority_epoch: trust.verifier().authority_epoch(),
        issued_at: now,
        expires_at: frozen
            .expires_at()
            .min(round.deadline_ms())
            .min(selector_evidence.expires_at)
            .min(trust.expires_at()),
        payload_digest: Digest32::of_bytes(&payload),
        signature: [0; 64],
    };
    // Current protected source identities and current trust are re-read after
    // the whole native receipt, immediately before this single purpose sign.
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
        || root_custody::selection(&config, 32 * 1024)? != selection_bytes
        || config
            .canary
            .read(MAX_NEURON_OPERATION_OBSERVATION_BYTES_V2 as u64)?
            != canary_bytes
    {
        return Err("original O sources changed before signing".into());
    }
    let final_now = now_ms()?;
    trust.revalidate_at(final_now)?;
    if let Some(custody) = &config.root_custody {
        root_custody::key_boundary(custody, &inputs, &config.observer)?;
        root_custody::verify(custody, &observer)?;
    } else {
        role::require_actual_program(&inputs.profile.program, &config.observer)?;
    }
    if observer.revoked_at.is_some_and(|at| final_now >= at)
        || final_now >= observer.principal.expires_at
        || final_now >= evidence.expires_at
    {
        return Err("original O authority expired or revoked".into());
    }
    let generator =
        inspect_signed_self_iteration_frozen_consumer_v1(&consumer_bytes, &trust, final_now)?;
    let evaluator = trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Evaluator,
        &evaluator_evidence,
        &stage_payload,
        final_now,
    )?;
    let selector = trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Selector,
        &selector_evidence,
        &stage_payload,
        final_now,
    )?;
    require_independent_actors(generator.generator(), &evaluator, &selector, final_now)?;
    evidence.issued_at = final_now;
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    let signed = trust.verifier().verify(
        ledger::LearningEvidenceRoleV1::Observer,
        &evidence,
        &payload,
        final_now,
    )?;
    for actor in [generator.generator(), &evaluator, &selector] {
        ledger::verify_signed_independent_roles_v1(actor, &signed, final_now)?;
    }
    Ok(
        serde_json::json!({"schema":"hepta.cpu-neuron.self-iteration-canary-observation.v1",
        "configuration_digest":pin.to_string(),"frozen_digest":frozen.frozen_digest().to_string(),
        "canary_receipt_digest":config.canary.digest,"canary_operation_digest":record.canary_operation_digest.map(|value| value.to_string()),
        "canary_checkpoint_digest":record.canary_checkpoint_digest.map(|value| value.to_string()),
        "physical_observation":observation,"verdict":match verdict { AgentdSelfIterationCanaryVerdictV1::Accept=>"accept", AgentdSelfIterationCanaryVerdictV1::RollBack=>"rollback" },
        "observer_evidence":ledger::ReviewEvidenceWireV1::from_native(&evidence),"production_activation":false}),
    )
}

pub(super) fn require_independent_actors(
    generator: &ledger::VerifiedLearningEvidenceV1,
    evaluator: &ledger::VerifiedLearningEvidenceV1,
    selector: &ledger::VerifiedLearningEvidenceV1,
    now: u64,
) -> HostResult<()> {
    for (left, right) in [
        (generator, evaluator),
        (generator, selector),
        (evaluator, selector),
    ] {
        ledger::verify_signed_independent_roles_v1(left, right, now)?;
    }
    Ok(())
}

pub(super) fn observed_record(
    frozen: &VerifiedSelfIterationFrozenConsumerV1,
    evaluation: Digest32,
    selector: &ledger::SignedLearningEvidenceV1,
    canary: &NeuronAcknowledgedOperationV2,
    deadline: u64,
) -> HostResult<AgentdSelfIterationRecordV1> {
    let native = canary.record();
    let output = &canary.commit().output;
    let successor = frozen
        .base_generation()
        .checked_add(1)
        .ok_or("O generation overflow")?;
    if canary.generation() != successor
        || native.config_semantic_digest != frozen.successor_configuration()
        || native.body_bundle_digest != frozen.successor_body()
        || native.key.tick_id != *frozen.canary_tick_id()
        || native.key.input_semantic_digest != frozen.canary_input_digest()
        || canary.scope().objective_digest != frozen.objective_digest()
        || !native.witness_acknowledged
        || output.tick.checkpoint_after != native.next_anchor.checkpoint_digest
        || output.signal.authority.grants_any()
    {
        return Err("O received substituted physical canary".into());
    }
    Ok(AgentdSelfIterationRecordV1 {
        candidate_id: frozen.candidate_id().to_string(),
        frozen_digest: frozen.frozen_digest(),
        objective_digest: frozen.objective_digest(),
        base_generation: frozen.base_generation(),
        successor_generation: successor,
        rollback_generation: successor.checked_add(1).ok_or("O rollback overflow")?,
        successor_configuration: frozen.successor_configuration(),
        successor_body: frozen.successor_body(),
        rollback_configuration: frozen.rollback_configuration(),
        rollback_body: frozen.rollback_body(),
        expires_at: (frozen.expires_at() / 1000).min(deadline / 1000),
        phase: AgentdSelfIterationPhaseV1::Canary,
        evaluation_digest: Some(evaluation),
        selection_digest: Some(Digest32::of_parts(&[
            &selector.signing_bytes(),
            &selector.signature,
        ])),
        canary_operation_digest: Some(native.operation_digest),
        canary_checkpoint_digest: Some(output.tick.checkpoint_after),
        canary_observation: Some(AgentdSelfIterationCanaryObservationV1 {
            latency_micros: output.model_runtime.latency_micros,
            resident_bytes: output.model_runtime.resident_bytes,
            confidence_ppm: output.tick.confidence_ppm,
            ood_ppm: output.tick.ood_ppm,
            abstain: output.tick.abstain,
        }),
        observer_digest: None,
    })
}
fn physical_verdict(
    observation: &AgentdSelfIterationCanaryObservationV1,
    canary: &NeuronAcknowledgedOperationV2,
    inputs: &Inputs,
    memory: u64,
) -> AgentdSelfIterationCanaryVerdictV1 {
    physical_verdict_with_bounds(
        observation,
        canary,
        inputs.profile.calibration.minimum_confidence_ppm,
        inputs.profile.calibration.maximum_ood_ppm,
        inputs.profile.resources.p99_latency_micros,
        memory,
    )
}

pub(super) fn physical_verdict_with_bounds(
    observation: &AgentdSelfIterationCanaryObservationV1,
    canary: &NeuronAcknowledgedOperationV2,
    minimum_confidence_ppm: u32,
    maximum_ood_ppm: u32,
    maximum_latency_micros: u64,
    memory: u64,
) -> AgentdSelfIterationCanaryVerdictV1 {
    if canary.commit().disposition == NeuronCommitDispositionV1::CommittedReady
        && !observation.abstain
        && observation.confidence_ppm >= minimum_confidence_ppm
        && observation.ood_ppm <= maximum_ood_ppm
        && observation.latency_micros <= maximum_latency_micros
        && observation.resident_bytes <= memory
    {
        AgentdSelfIterationCanaryVerdictV1::Accept
    } else {
        AgentdSelfIterationCanaryVerdictV1::RollBack
    }
}
