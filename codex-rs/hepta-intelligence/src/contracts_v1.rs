use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_LEGAL_CANDIDATES: usize = 128;
const MAX_SUPPORT_FLOOR_PPM: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateV1 {
    pub candidate_id: StableId,
    pub action_digest: Digest32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetInputV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub grammar_digest: Digest32,
    pub candidates: Vec<LegalActionCandidateV1>,
    pub support_floor_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LegalActionCandidateSetV1 {
    pub candidate_set_id: StableId,
    pub state_digest: Digest32,
    pub generator_id: StableId,
    pub grammar_digest: Digest32,
    pub candidates: Vec<LegalActionCandidateV1>,
    pub support_floor_ppm: u32,
    digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeInputV1 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub legal_candidate_set_digest: Digest32,
    pub utility_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub intuition_digest: Digest32,
    pub context_digest: Digest32,
    pub composition_trace_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceHostEnvelopeV1 {
    pub run_id: StableId,
    pub request_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub objective_digest: Digest32,
    pub legal_candidate_set_digest: Digest32,
    pub utility_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub intuition_digest: Digest32,
    pub context_digest: Digest32,
    pub composition_trace_digest: Digest32,
    pub envelope_digest: Digest32,
    pub effect_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum IntelligenceContractErrorV1 {
    EmptyDigest(&'static str),
    CandidateLimitExceeded,
    DuplicateCandidate(String),
    SupportFloorExceeded,
    AuthorityWidening,
    DigestMismatch,
}

impl fmt::Display for IntelligenceContractErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for IntelligenceContractErrorV1 {}

impl LegalActionCandidateSetV1 {
    pub fn new(
        mut input: LegalActionCandidateSetInputV1,
    ) -> Result<Self, IntelligenceContractErrorV1> {
        ensure_digest("state", input.state_digest)?;
        ensure_digest("grammar", input.grammar_digest)?;
        if input.candidates.len() > MAX_LEGAL_CANDIDATES {
            return Err(IntelligenceContractErrorV1::CandidateLimitExceeded);
        }
        if input.support_floor_ppm > MAX_SUPPORT_FLOOR_PPM {
            return Err(IntelligenceContractErrorV1::SupportFloorExceeded);
        }
        input
            .candidates
            .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
        let mut seen = BTreeSet::new();
        for candidate in &input.candidates {
            if !seen.insert(candidate.candidate_id.clone()) {
                return Err(IntelligenceContractErrorV1::DuplicateCandidate(
                    candidate.candidate_id.to_string(),
                ));
            }
            ensure_digest("candidate action", candidate.action_digest)?;
            ensure_digest("candidate support", candidate.support_digest)?;
        }
        let digest = legal_candidate_set_digest(&input);
        Ok(Self {
            candidate_set_id: input.candidate_set_id,
            state_digest: input.state_digest,
            generator_id: input.generator_id,
            grammar_digest: input.grammar_digest,
            candidates: input.candidates,
            support_floor_ppm: input.support_floor_ppm,
            digest,
        })
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn validate(&self) -> Result<(), IntelligenceContractErrorV1> {
        let rebuilt = Self::new(LegalActionCandidateSetInputV1 {
            candidate_set_id: self.candidate_set_id.clone(),
            state_digest: self.state_digest,
            generator_id: self.generator_id.clone(),
            grammar_digest: self.grammar_digest,
            candidates: self.candidates.clone(),
            support_floor_ppm: self.support_floor_ppm,
        })?;
        if rebuilt.digest != self.digest {
            return Err(IntelligenceContractErrorV1::DigestMismatch);
        }
        Ok(())
    }
}

impl IntelligenceHostEnvelopeV1 {
    pub fn new(
        input: IntelligenceHostEnvelopeInputV1,
    ) -> Result<Self, IntelligenceContractErrorV1> {
        for (name, digest) in [
            ("request", input.request_digest),
            ("snapshot", input.snapshot_digest),
            ("objective", input.objective_digest),
            ("legal candidate set", input.legal_candidate_set_digest),
            ("utility", input.utility_digest),
            ("evaluation", input.evaluation_digest),
            ("intuition", input.intuition_digest),
            ("context", input.context_digest),
            ("composition trace", input.composition_trace_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        let envelope_digest = host_envelope_digest(&input);
        Ok(Self {
            run_id: input.run_id,
            request_digest: input.request_digest,
            snapshot_digest: input.snapshot_digest,
            objective_digest: input.objective_digest,
            legal_candidate_set_digest: input.legal_candidate_set_digest,
            utility_digest: input.utility_digest,
            evaluation_digest: input.evaluation_digest,
            intuition_digest: input.intuition_digest,
            context_digest: input.context_digest,
            composition_trace_digest: input.composition_trace_digest,
            envelope_digest,
            effect_authority: false,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn validate(&self) -> Result<(), IntelligenceContractErrorV1> {
        if self.effect_authority || self.authority.grants_any() {
            return Err(IntelligenceContractErrorV1::AuthorityWidening);
        }
        let rebuilt = Self::new(IntelligenceHostEnvelopeInputV1 {
            run_id: self.run_id.clone(),
            request_digest: self.request_digest,
            snapshot_digest: self.snapshot_digest,
            objective_digest: self.objective_digest,
            legal_candidate_set_digest: self.legal_candidate_set_digest,
            utility_digest: self.utility_digest,
            evaluation_digest: self.evaluation_digest,
            intuition_digest: self.intuition_digest,
            context_digest: self.context_digest,
            composition_trace_digest: self.composition_trace_digest,
        })?;
        if rebuilt.envelope_digest != self.envelope_digest {
            return Err(IntelligenceContractErrorV1::DigestMismatch);
        }
        Ok(())
    }
}

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), IntelligenceContractErrorV1> {
    if digest.is_zero() {
        return Err(IntelligenceContractErrorV1::EmptyDigest(name));
    }
    Ok(())
}

fn legal_candidate_set_digest(input: &LegalActionCandidateSetInputV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence.legal-action-candidate-set.v1\0".to_vec();
    crate::push_id(&mut bytes, &input.candidate_set_id);
    bytes.extend_from_slice(input.state_digest.as_array());
    crate::push_id(&mut bytes, &input.generator_id);
    bytes.extend_from_slice(input.grammar_digest.as_array());
    bytes.extend_from_slice(&input.support_floor_ppm.to_be_bytes());
    bytes.extend_from_slice(
        &u32::try_from(input.candidates.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for candidate in &input.candidates {
        crate::push_id(&mut bytes, &candidate.candidate_id);
        bytes.extend_from_slice(candidate.action_digest.as_array());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn host_envelope_digest(input: &IntelligenceHostEnvelopeInputV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
    crate::push_id(&mut bytes, &input.run_id);
    for digest in [
        input.request_digest,
        input.snapshot_digest,
        input.objective_digest,
        input.legal_candidate_set_digest,
        input.utility_digest,
        input.evaluation_digest,
        input.intuition_digest,
        input.context_digest,
        input.composition_trace_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}
