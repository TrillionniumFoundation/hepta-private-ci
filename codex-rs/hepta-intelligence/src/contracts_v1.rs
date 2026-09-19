use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_LEGAL_CANDIDATES_V1: usize = 128;
const MAX_SUPPORT_PPM: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateV1 {
    pub candidate_id: StableId,
    pub action_digest: Digest32,
    pub support_digest: Digest32,
    pub support_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub grammar_digest: Digest32,
    pub candidates: Vec<LegalActionCandidateV1>,
    pub support_floor_ppm: u32,
    pub candidate_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeV1 {
    pub run_id: StableId,
    pub producer_id: StableId,
    pub consumer_id: StableId,
    pub request_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub authority_epoch: u64,
    pub body_digest: Digest32,
    pub artifact_set_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub utility_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub neural_digest: Option<Digest32>,
    pub prompt_digest: Option<Digest32>,
    pub intuition_digest: Digest32,
    pub context_digest: Digest32,
    pub pre_handoff_digest: Digest32,
    pub deadline_unix_micros: u64,
    pub total_budget_micros: u64,
    pub envelope_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntelligenceContractErrorV1 {
    EmptyDigest(&'static str),
    InvalidSupportFloor,
    CandidateLimitExceeded,
    EmptyCandidateSet,
    DuplicateCandidate(String),
    InvalidCandidate(String),
    InvalidProducer,
    InvalidConsumer,
    InvalidAuthorityEpoch,
    InvalidDeadline,
    InvalidBudget,
    DigestMismatch,
    AuthorityWidening,
    Arithmetic,
}

impl fmt::Display for IntelligenceContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for IntelligenceContractErrorV1 {}

pub fn build_legal_candidates_v1(
    candidate_set_id: StableId,
    state_digest: Digest32,
    grammar_digest: Digest32,
    support_floor_ppm: u32,
    mut candidates: Vec<LegalActionCandidateV1>,
) -> Result<LegalActionCandidateSetV1, IntelligenceContractErrorV1> {
    if state_digest.is_zero() {
        return Err(IntelligenceContractErrorV1::EmptyDigest("state"));
    }
    if grammar_digest.is_zero() {
        return Err(IntelligenceContractErrorV1::EmptyDigest("grammar"));
    }
    if support_floor_ppm > MAX_SUPPORT_PPM {
        return Err(IntelligenceContractErrorV1::InvalidSupportFloor);
    }
    if candidates.is_empty() {
        return Err(IntelligenceContractErrorV1::EmptyCandidateSet);
    }
    if candidates.len() > MAX_LEGAL_CANDIDATES_V1 {
        return Err(IntelligenceContractErrorV1::CandidateLimitExceeded);
    }
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    for candidate in &candidates {
        if !seen.insert(candidate.candidate_id.clone()) {
            return Err(IntelligenceContractErrorV1::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.action_digest.is_zero()
            || candidate.support_digest.is_zero()
            || candidate.support_ppm > MAX_SUPPORT_PPM
            || candidate.support_ppm < support_floor_ppm
        {
            return Err(IntelligenceContractErrorV1::InvalidCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
    }
    let generator_id = stable_id("intelligence.control")?;
    let candidate_set_digest = digest_candidate_set(
        &candidate_set_id,
        state_digest,
        &generator_id,
        grammar_digest,
        &candidates,
        support_floor_ppm,
    )?;
    Ok(LegalActionCandidateSetV1 {
        candidate_set_id,
        state_digest,
        generator_id,
        grammar_digest,
        candidates,
        support_floor_ppm,
        candidate_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

impl LegalActionCandidateSetV1 {
    pub fn validate(&self) -> Result<(), IntelligenceContractErrorV1> {
        if self.authority.grants_any() {
            return Err(IntelligenceContractErrorV1::AuthorityWidening);
        }
        if self.generator_id.as_str() != "intelligence.control" {
            return Err(IntelligenceContractErrorV1::InvalidProducer);
        }
        let rebuilt = build_legal_candidates_v1(
            self.candidate_set_id.clone(),
            self.state_digest,
            self.grammar_digest,
            self.support_floor_ppm,
            self.candidates.clone(),
        )?;
        if rebuilt.candidates != self.candidates
            || rebuilt.candidate_set_digest != self.candidate_set_digest
        {
            return Err(IntelligenceContractErrorV1::DigestMismatch);
        }
        Ok(())
    }
}

impl IntelligenceHostEnvelopeV1 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        run_id: StableId,
        request_digest: Digest32,
        snapshot_digest: Digest32,
        objective_digest: Digest32,
        authority_epoch: u64,
        body_digest: Digest32,
        artifact_set_digest: Digest32,
        candidate_set_digest: Digest32,
        utility_digest: Digest32,
        evaluation_digest: Digest32,
        neural_digest: Option<Digest32>,
        prompt_digest: Option<Digest32>,
        intuition_digest: Digest32,
        context_digest: Digest32,
        pre_handoff_digest: Digest32,
        deadline_unix_micros: u64,
        total_budget_micros: u64,
    ) -> Result<Self, IntelligenceContractErrorV1> {
        for (name, digest) in [
            ("request", request_digest),
            ("snapshot", snapshot_digest),
            ("objective", objective_digest),
            ("body", body_digest),
            ("artifact set", artifact_set_digest),
            ("candidate set", candidate_set_digest),
            ("utility", utility_digest),
            ("evaluation", evaluation_digest),
            ("intuition", intuition_digest),
            ("context", context_digest),
            ("pre-handoff", pre_handoff_digest),
        ] {
            if digest.is_zero() {
                return Err(IntelligenceContractErrorV1::EmptyDigest(name));
            }
        }
        if neural_digest.is_some_and(|value| value.is_zero())
            || prompt_digest.is_some_and(|value| value.is_zero())
        {
            return Err(IntelligenceContractErrorV1::EmptyDigest("optional stage"));
        }
        if authority_epoch == 0 {
            return Err(IntelligenceContractErrorV1::InvalidAuthorityEpoch);
        }
        if deadline_unix_micros == 0 {
            return Err(IntelligenceContractErrorV1::InvalidDeadline);
        }
        if total_budget_micros == 0 {
            return Err(IntelligenceContractErrorV1::InvalidBudget);
        }
        let producer_id = stable_id("intelligence.control")?;
        let consumer_id = stable_id("runtime.agentd")?;
        let envelope_digest = digest_host_envelope(
            &run_id,
            &producer_id,
            &consumer_id,
            request_digest,
            snapshot_digest,
            objective_digest,
            authority_epoch,
            body_digest,
            artifact_set_digest,
            candidate_set_digest,
            utility_digest,
            evaluation_digest,
            neural_digest,
            prompt_digest,
            intuition_digest,
            context_digest,
            pre_handoff_digest,
            deadline_unix_micros,
            total_budget_micros,
        )?;
        Ok(Self {
            run_id,
            producer_id,
            consumer_id,
            request_digest,
            snapshot_digest,
            objective_digest,
            authority_epoch,
            body_digest,
            artifact_set_digest,
            candidate_set_digest,
            utility_digest,
            evaluation_digest,
            neural_digest,
            prompt_digest,
            intuition_digest,
            context_digest,
            pre_handoff_digest,
            deadline_unix_micros,
            total_budget_micros,
            envelope_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn validate(&self) -> Result<(), IntelligenceContractErrorV1> {
        if self.authority.grants_any() {
            return Err(IntelligenceContractErrorV1::AuthorityWidening);
        }
        if self.producer_id.as_str() != "intelligence.control" {
            return Err(IntelligenceContractErrorV1::InvalidProducer);
        }
        if self.consumer_id.as_str() != "runtime.agentd" {
            return Err(IntelligenceContractErrorV1::InvalidConsumer);
        }
        let rebuilt = Self::new(
            self.run_id.clone(),
            self.request_digest,
            self.snapshot_digest,
            self.objective_digest,
            self.authority_epoch,
            self.body_digest,
            self.artifact_set_digest,
            self.candidate_set_digest,
            self.utility_digest,
            self.evaluation_digest,
            self.neural_digest,
            self.prompt_digest,
            self.intuition_digest,
            self.context_digest,
            self.pre_handoff_digest,
            self.deadline_unix_micros,
            self.total_budget_micros,
        )?;
        if rebuilt.envelope_digest != self.envelope_digest {
            return Err(IntelligenceContractErrorV1::DigestMismatch);
        }
        Ok(())
    }
}

fn digest_candidate_set(
    candidate_set_id: &StableId,
    state_digest: Digest32,
    generator_id: &StableId,
    grammar_digest: Digest32,
    candidates: &[LegalActionCandidateV1],
    support_floor_ppm: u32,
) -> Result<Digest32, IntelligenceContractErrorV1> {
    let mut bytes = b"hepta.intelligence.legal-action-candidate-set.v1\0".to_vec();
    push_id(&mut bytes, candidate_set_id)?;
    bytes.extend_from_slice(state_digest.as_array());
    push_id(&mut bytes, generator_id)?;
    bytes.extend_from_slice(grammar_digest.as_array());
    bytes.extend_from_slice(&support_floor_ppm.to_be_bytes());
    let count =
        u32::try_from(candidates.len()).map_err(|_| IntelligenceContractErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(candidate.action_digest.as_array());
        bytes.extend_from_slice(candidate.support_digest.as_array());
        bytes.extend_from_slice(&candidate.support_ppm.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

#[allow(clippy::too_many_arguments)]
fn digest_host_envelope(
    run_id: &StableId,
    producer_id: &StableId,
    consumer_id: &StableId,
    request_digest: Digest32,
    snapshot_digest: Digest32,
    objective_digest: Digest32,
    authority_epoch: u64,
    body_digest: Digest32,
    artifact_set_digest: Digest32,
    candidate_set_digest: Digest32,
    utility_digest: Digest32,
    evaluation_digest: Digest32,
    neural_digest: Option<Digest32>,
    prompt_digest: Option<Digest32>,
    intuition_digest: Digest32,
    context_digest: Digest32,
    pre_handoff_digest: Digest32,
    deadline_unix_micros: u64,
    total_budget_micros: u64,
) -> Result<Digest32, IntelligenceContractErrorV1> {
    let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
    push_id(&mut bytes, run_id)?;
    push_id(&mut bytes, producer_id)?;
    push_id(&mut bytes, consumer_id)?;
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(snapshot_digest.as_array());
    bytes.extend_from_slice(objective_digest.as_array());
    bytes.extend_from_slice(&authority_epoch.to_be_bytes());
    for digest in [
        body_digest,
        artifact_set_digest,
        candidate_set_digest,
        utility_digest,
        evaluation_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_optional_digest(&mut bytes, neural_digest);
    push_optional_digest(&mut bytes, prompt_digest);
    for digest in [intuition_digest, context_digest, pre_handoff_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&deadline_unix_micros.to_be_bytes());
    bytes.extend_from_slice(&total_budget_micros.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<Digest32>) {
    match digest {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

fn stable_id(value: &str) -> Result<StableId, IntelligenceContractErrorV1> {
    StableId::new(value).map_err(|_| IntelligenceContractErrorV1::Arithmetic)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), IntelligenceContractErrorV1> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| IntelligenceContractErrorV1::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("fixture id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn legal_candidate_set_is_order_independent_and_fail_closed() {
        let candidate = |name: &str| LegalActionCandidateV1 {
            candidate_id: id(name),
            action_digest: digest(&format!("action:{name}")),
            support_digest: digest(&format!("support:{name}")),
            support_ppm: 900_000,
        };
        let first = build_legal_candidates_v1(
            id("set"),
            digest("state"),
            digest("grammar"),
            800_000,
            vec![candidate("b"), candidate("a")],
        )
        .expect("candidate set");
        let second = build_legal_candidates_v1(
            id("set"),
            digest("state"),
            digest("grammar"),
            800_000,
            vec![candidate("a"), candidate("b")],
        )
        .expect("candidate set");
        assert_eq!(first, second);
        first.validate().expect("valid candidate set");

        let mut bad = first.clone();
        bad.candidates[0].support_ppm = 10;
        assert!(bad.validate().is_err());
    }

    #[test]
    fn host_envelope_binds_every_composition_digest() {
        let envelope = IntelligenceHostEnvelopeV1::new(
            id("run"),
            digest("request"),
            digest("snapshot"),
            digest("objective"),
            7,
            digest("body"),
            digest("artifact-set"),
            digest("candidates"),
            digest("utility"),
            digest("evaluation"),
            Some(digest("neural")),
            Some(digest("prompt")),
            digest("intuition"),
            digest("context"),
            digest("prefix"),
            2_000_000,
            10_000,
        )
        .expect("envelope");
        envelope.validate().expect("valid envelope");
        let mut tampered = envelope.clone();
        tampered.context_digest = digest("other-context");
        assert_eq!(
            tampered.validate(),
            Err(IntelligenceContractErrorV1::DigestMismatch)
        );
        assert!(!envelope.authority.grants_any());
    }
}
