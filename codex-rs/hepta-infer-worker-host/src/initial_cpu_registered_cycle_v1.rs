//! Separate registered-model E/S/O purpose, over original S3 admissions.
//! The generation-one and non-root purposes keep their existing parsers.
use super::*;
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger as ledger;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_agentd::CanonicalIterationEnvelopeV1;
use serde::Serialize;
use std::path::PathBuf;

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegisteredCycleAdmissionSourcesV1 {
    pub configuration: Source,
    pub selection: Source,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegisteredCycleCandidateSourcesV1 {
    pub candidate_id: String,
    pub successor: RegisteredCycleAdmissionSourcesV1,
    pub rollback: RegisteredCycleAdmissionSourcesV1,
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegisteredCycleRoleInputV1 {
    pub path: PathBuf,
    pub uid: u32,
}
impl RegisteredCycleRoleInputV1 {
    fn read(&self, maximum: usize) -> HostResult<Vec<u8>> {
        read_self_iteration_role_input_v1(&self.path, self.uid, maximum)
    }
}
#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegisteredCycleObserverCustodyV1 {
    pub trust_configuration: Source,
    pub cycle_approval: Option<Source>,
}
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RegisteredSelfIterationOwnerConfigurationV1 {
    pub schema: String,
    pub purpose: String,
    pub program: Source,
    pub actor: Role,
    pub learning_trust: Source,
    pub canonical_envelope_digest: String,
    pub consumer: RegisteredCycleRoleInputV1,
    pub evaluation: RegisteredCycleRoleInputV1,
    pub candidates: Vec<RegisteredCycleCandidateSourcesV1>,
    pub inaccessible_paths: Vec<PathBuf>,
    pub observer_custody: Option<RegisteredCycleObserverCustodyV1>,
    pub selection: Option<Source>,
    pub canary: Option<Source>,
}
struct Loaded {
    source: Source,
    bytes: Vec<u8>,
    config: RegisteredSelfIterationOwnerConfigurationV1,
    trust_bytes: Vec<u8>,
    trust: ledger::ActivatedLearningTrustV1,
    actor: ledger::TrustedLearningSignerV1,
    consumer_bytes: Vec<u8>,
    evaluation_bytes: Vec<u8>,
    frozen: VerifiedSelfIterationFrozenConsumerV1,
    canonical: CanonicalIterationEnvelopeV1,
    round: AgentdSelfIterationRoundV1,
    evaluation_digest: Digest32,
    evaluator_evidence: ledger::SignedLearningEvidenceV1,
    successor: VerifiedParameterPreRegisteredAdmissionV1,
    rollback: VerifiedParameterPreRegisteredAdmissionV1,
    expiry: u64,
    clock_floor: std::sync::atomic::AtomicU64,
}
impl Loaded {
    fn read(path: &Path, pin: Digest32, observer: bool) -> HostResult<Self> {
        let source = Source { path: path.to_owned(), digest: pin.to_string() };
        let bytes = source.read(64 * 1024)?;
        let config: RegisteredSelfIterationOwnerConfigurationV1 = serde_json::from_slice(&bytes)?;
        validate_purpose(&config, observer)?;
        if observer { verify_original_observer_process_boundary_v1()?; }
        role::require_actual_program(&config.program, &config.actor)?;
        for denied in &config.inaccessible_paths {
            match std::fs::File::open(denied) {
                Err(error) if error.kind() == std::io::ErrorKind::PermissionDenied => (),
                _ => return Err("registered S can read private custody/another key or denial is not physical".into()),
            }
        }
        let trust_bytes = config.learning_trust.read(64 * 1024)?;
        let wire: ledger::ReviewTrustWireV1 = serde_json::from_slice(&trust_bytes)?;
        let (root, distribution) = wire.native()?;
        let expected_role = if observer { ledger::LearningEvidenceRoleV1::Observer }
            else { ledger::LearningEvidenceRoleV1::Selector };
        let actor = distribution.distribution.trust.signers.iter().find(|actor|
            actor.principal.principal_id.as_str() == config.actor.id && actor.roles.contains(&expected_role))
            .ok_or("original installed registered role roster")?.clone();
        if actor.verifying_key != public(&config.actor.public_key_hex)?
            || actor.principal.signing_key_digest != Digest32::of_bytes(&actor.verifying_key)
            || actor.principal.credential_chain_digest != digest(&config.actor.credential_digest)? {
            return Err("registered role differs from original actual credential/key".into());
        }
        if let Some(custody) = &config.observer_custody {
            verify_original_observer_controller(digest(&config.program.digest)?,
                &custody.trust_configuration.read(64 * 1024)?,
                custody.cycle_approval.as_ref().map(|source| source.read(64 * 1024)).transpose()?.as_deref(), &actor)?;
        }
        let now = now_ms()?;
        let trust = ledger::activate_learning_trust(&root, distribution, None, now)?;
        let consumer_bytes = config.consumer.read(MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES)?;
        let evaluation_bytes = config.evaluation.read(MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES)?;
        let frozen = inspect_signed_self_iteration_frozen_consumer_v1(&consumer_bytes, &trust, now)?;
        let canonical = CanonicalIterationEnvelopeV1::decode(frozen.canonical_envelope_bytes().ok_or("registered role requires whole canonical policy")?)?;
        let round = AgentdSelfIterationRoundV1::decode(frozen.generator_round_bytes().ok_or("registered role requires sealed round")?)?;
        if canonical.digest() != digest(&config.canonical_envelope_digest)?
            || round.canonical_policy_digest() != canonical.digest() || now >= round.deadline_ms() {
            return Err("actual canonical policy/round differs from registered role window".into());
        }
        let evaluated = decode_self_iteration_evaluation_transport_v1(&evaluation_bytes, frozen.frozen_digest(), &trust, now)?;
        if evaluated.admission().decision.decision.disposition != IndependentEvaluationDispositionV1::EligibleForIndependentSelection {
            return Err("registered role requires actual independently eligible evaluation".into());
        }
        let evaluation_digest = evaluated.admission().decision.authentication_digest;
        let (bundle, _, _, evaluator_evidence) = evaluated.into_parts();
        decode_self_iteration_frozen_consumer_v1(&consumer_bytes, &bundle, &trust, now)?;
        let candidate = config.candidates.iter().find(|candidate| candidate.candidate_id == frozen.candidate_id().as_str())
            .ok_or("actual full candidate absent from registered window")?;
        let successor = admission(&candidate.successor)?;
        let rollback = admission(&candidate.rollback)?;
        verify_pair(&successor, &rollback, &frozen, &round)?;
        let selector_role = successor.selector_identity();
        if selector_role.uid != 0 || selector_role.gid != 0
            || successor.selector_program() != rollback.selector_program()
            || successor.selector_identity().id != rollback.selector_identity().id {
            return Err("candidate/rollback used different original S3 selector programs".into());
        }
        if observer {
            if config.program.path == successor.selector_program().path
                || config.program.digest == successor.selector_program().digest {
                return Err("registered O and S must execute different original programs".into());
            }
        } else if config.program != *successor.selector_program()
            || config.actor.id != selector_role.id
            || config.actor.public_key_hex != selector_role.public_key_hex
            || config.actor.credential_digest != selector_role.credential_digest {
            return Err("actual cycle S differs from independently sealed S3".into());
        }
        let expiry = frozen.expires_at().min(round.deadline_ms()).min(canonical.policy().expires_unix_ms)
            .min(evaluator_evidence.expires_at).min(trust.expires_at())
            .min(successor.expires_at_ms()).min(rollback.expires_at_ms())
            .min(actor.principal.expires_at).min(actor.revoked_at.unwrap_or(u64::MAX));
        let loaded = Self { source, bytes, config, trust_bytes, trust, actor, consumer_bytes, evaluation_bytes,
            frozen, canonical, round, evaluation_digest, evaluator_evidence, successor, rollback, expiry,
            clock_floor: std::sync::atomic::AtomicU64::new(now) };
        loaded.revalidate()?;
        Ok(loaded)
    }
    fn revalidate(&self) -> HostResult<u64> {
        self.successor.revalidate_current()?; self.rollback.revalidate_current()?;
        if self.source.read(64 * 1024)? != self.bytes
            || self.config.learning_trust.read(64 * 1024)? != self.trust_bytes
            || self.config.consumer.read(MAX_SELF_ITERATION_FROZEN_CONSUMER_BYTES)? != self.consumer_bytes
            || self.config.evaluation.read(MAX_SELF_ITERATION_EVALUATION_TRANSPORT_BYTES)? != self.evaluation_bytes {
            return Err("whole registered role sources changed".into());
        }
        role::require_actual_program(&self.config.program, &self.config.actor)?;
        if let Some(custody) = &self.config.observer_custody {
            verify_original_observer_process_boundary_v1()?;
            verify_original_observer_controller(digest(&self.config.program.digest)?, &custody.trust_configuration.read(64 * 1024)?,
                custody.cycle_approval.as_ref().map(|s| s.read(64 * 1024)).transpose()?.as_deref(), &self.actor)?;
        }
        let now = now_ms()?;
        self.trust.revalidate_at(now)?;
        if now < self.clock_floor.fetch_max(now, std::sync::atomic::Ordering::AcqRel)
            || now < self.round.admitted_at_ms() || now >= self.expiry {
            return Err("actual registered role expired or clock regressed".into());
        }
        self.actor.principal.validate(now)?;
        let generator = inspect_signed_self_iteration_frozen_consumer_v1(&self.consumer_bytes, &self.trust, now)?;
        let evaluator = self.trust.verifier().verify(ledger::LearningEvidenceRoleV1::Evaluator,
            &self.evaluator_evidence, &self.stage_payload(), now)?;
        ledger::verify_signed_independent_roles_v1(generator.generator(), &evaluator, now)?;
        for original in [generator.generator(), &evaluator] {
            ledger::verify_independent_roles(original.principal(), &self.actor.principal, now)?;
            if original.controller_id() == &self.actor.controller_id { return Err("registered role shares G/E controller".into()); }
        }
        Ok(now)
    }
    fn stage_payload(&self) -> Vec<u8> {
        self_iteration_evaluation_use_payload_v1(self.frozen.frozen_digest(), self.evaluation_digest)
    }
    fn evidence(&self, role: ledger::LearningEvidenceRoleV1, payload: &[u8], now: u64)
        -> HostResult<ledger::SignedLearningEvidenceV1> {
        let allowed = match self.config.purpose.as_str() {
            "cycle-selection" => ledger::LearningEvidenceRoleV1::Selector,
            "canary-observation" => ledger::LearningEvidenceRoleV1::Observer,
            _ => return Err("original finite registered role purpose".into()),
        };
        if role != allowed || now >= self.expiry { return Err("finite registered role/payload expiry".into()); }
        let identity = evidence_identity(&self.config.purpose, self.round.identity_digest(),
            self.frozen.frozen_digest(), self.evaluation_digest, Digest32::of_bytes(payload));
        Ok(ledger::SignedLearningEvidenceV1 {
            evidence_id: id(&format!("cpu.registered.cycle.{identity}"))?,
            principal_id: id(&self.config.actor.id)?, role,
            trust_digest: self.trust.verifier().trust_digest(), scope_digest: self.trust.verifier().scope_digest(),
            objective_digest: self.trust.verifier().objective_digest(), authority_epoch: self.trust.verifier().authority_epoch(),
            issued_at: now, expires_at: self.expiry, payload_digest: Digest32::of_bytes(payload), signature: [0; 64],
        })
    }
}
fn validate_purpose(config: &RegisteredSelfIterationOwnerConfigurationV1, observer: bool) -> HostResult<()> {
    if config.schema != "hepta.cpu-neuron.registered-self-iteration-owner.v1"
            || config.purpose != if observer { "canary-observation" } else { "cycle-selection" }
            || config.actor.uid != 0 || config.actor.gid != 0
            || config.consumer.uid == 0 || config.evaluation.uid == 0
            || config.consumer.uid == config.evaluation.uid
            || !(1..=32).contains(&config.candidates.len())
            || config.observer_custody.is_some() != observer
            || config.selection.is_some() != observer || config.canary.is_some() != observer
            || config.inaccessible_paths.len() != if observer { 0 } else { 5 } {
            return Err("explicit registered S/O process and finite purpose".into());
        }
    let mut ids = std::collections::BTreeSet::new();
    for candidate in &config.candidates {
        if id(&candidate.candidate_id).is_err() || !ids.insert(&candidate.candidate_id) {
            return Err("registered candidate window contains repeated or invalid identities".into());
        }
    }
    Ok(())
}
fn admission(sources: &RegisteredCycleAdmissionSourcesV1) -> HostResult<VerifiedParameterPreRegisteredAdmissionV1> {
    inspect_parameter_pre_registered_admission_v1(&sources.configuration.path, digest(&sources.configuration.digest)?,
        &sources.selection.path, digest(&sources.selection.digest)?)
}
fn verify_pair(successor: &VerifiedParameterPreRegisteredAdmissionV1, rollback: &VerifiedParameterPreRegisteredAdmissionV1,
    frozen: &VerifiedSelfIterationFrozenConsumerV1, round: &AgentdSelfIterationRoundV1) -> HostResult<()> {
    if successor.purpose() != ParameterPreRegistrationPurposeV1::Candidate
        || rollback.purpose() != ParameterPreRegistrationPurposeV1::ExactRollback
        || successor.round() != rollback.round()
        || successor.round().round_digest != round.identity_digest().to_string()
        || successor.round().round_payload_digest != Digest32::of_bytes(&round.canonical_bytes()?).to_string()
        || successor.round().canonical_policy_digest != round.canonical_policy_digest().to_string()
        || successor.round().execution_digest != round.execution_envelope_digest().to_string()
        || successor.round().admitted_at_ms != round.admitted_at_ms()
        || successor.round().deadline_ms != round.deadline_ms()
        || successor.candidate_id() != frozen.candidate_id() || rollback.candidate_id() != frozen.candidate_id()
        || successor.material().runtime.generation.get() != frozen.base_generation().checked_add(1).ok_or("successor overflow")?
        || rollback.material().runtime.generation.get() != frozen.base_generation().checked_add(2).ok_or("rollback overflow")?
        || successor.material().runtime.semantic_digest()? != frozen.successor_configuration()
        || rollback.material().runtime.semantic_digest()? != frozen.rollback_configuration()
        || successor.material().body.semantic_digest()? != frozen.successor_body()
        || rollback.material().body.semantic_digest()? != frozen.rollback_body()
        || successor.material().scope.objective_digest != frozen.objective_digest()
        || rollback.material().scope != successor.material().scope {
        return Err("actual sealed S3 candidate/rollback full material differs from signed G/round".into());
    }
    Ok(())
}

#[path = "initial_cpu_registered_cycle_selection_v1.rs"]
mod selection;
#[path = "initial_cpu_registered_cycle_observation_v1.rs"]
mod observation;
pub use selection::select_registered_cpu_self_iteration_stage_v1;
pub use observation::observe_registered_cpu_self_iteration_canary_v1;

fn evidence_identity(purpose: &str, round: Digest32, frozen: Digest32, evaluation: Digest32, payload: Digest32) -> Digest32 {
    Digest32::of_parts(&[b"hepta.cpu-neuron.registered-cycle-role-identity.v1\0", purpose.as_bytes(),
        round.as_array(), frozen.as_array(), evaluation.as_array(), payload.as_array()])
}
#[cfg(test)]
#[path = "initial_cpu_registered_cycle_tests_v1.rs"]
mod tests;
