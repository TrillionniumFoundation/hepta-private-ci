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
        candidate_set_id: StableId,
        state_digest: Digest32,
        generator_id: StableId,
        grammar_digest: Digest32,
        mut candidates: Vec<LegalActionCandidateV1>,
        support_floor_ppm: u32,
    ) -> Result<Self, IntelligenceContractErrorV1> {
        ensure_digest("state", state_digest)?;
        ensure_digest("grammar", grammar_digest)?;
        if candidates.len() > MAX_LEGAL_CANDIDATES {
            return Err(IntelligenceContractErrorV1::CandidateLimitExceeded);
        }
        if support_floor_ppm > MAX_SUPPORT_FLOOR_PPM {
            return Err(IntelligenceContractErrorV1::SupportFloorExceeded);
        }
        candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
        let mut seen = BTreeSet::new();
        for candidate in &candidates {
            if !seen.insert(candidate.candidate_id.clone()) {
                return Err(IntelligenceContractErrorV1::DuplicateCandidate(
                    candidate.candidate_id.to_string(),
                ));
            }
            ensure_digest("candidate action", candidate.action_digest)?;
            ensure_digest("candidate support", candidate.support_digest)?;
        }
        let digest = legal_candidate_set_digest(
            &candidate_set_id,
            state_digest,
            &generator_id,
            grammar_digest,
            &candidates,
            support_floor_ppm,
        );
        Ok(Self {
            candidate_set_id,
            state_digest,
            generator_id,
            grammar_digest,
            candidates,
            support_floor_ppm,
            digest,
        })
    }

    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn validate(&self) -> Result<(), IntelligenceContractErrorV1> {
        let rebuilt = Self::new(
            self.candidate_set_id.clone(),
            self.state_digest,
            self.generator_id.clone(),
            self.grammar_digest,
            self.candidates.clone(),
            self.support_floor_ppm,
        )?;
        if rebuilt.digest != self.digest {
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
        legal_candidate_set_digest: Digest32,
        utility_digest: Digest32,
        evaluation_digest: Digest32,
        intuition_digest: Digest32,
        context_digest: Digest32,
        composition_trace_digest: Digest32,
    ) -> Result<Self, IntelligenceContractErrorV1> {
        for (name, digest) in [
            ("request", request_digest),
            ("snapshot", snapshot_digest),
            ("objective", objective_digest),
            ("legal candidate set", legal_candidate_set_digest),
            ("utility", utility_digest),
            ("evaluation", evaluation_digest),
            ("intuition", intuition_digest),
            ("context", context_digest),
            ("composition trace", composition_trace_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        let envelope_digest = host_envelope_digest(
            &run_id,
            request_digest,
            snapshot_digest,
            objective_digest,
            legal_candidate_set_digest,
            utility_digest,
            evaluation_digest,
            intuition_digest,
            context_digest,
            composition_trace_digest,
        );
        Ok(Self {
            run_id,
            request_digest,
            snapshot_digest,
            objective_digest,
            legal_candidate_set_digest,
            utility_digest,
            evaluation_digest,
            intuition_digest,
            context_digest,
            composition_trace_digest,
            envelope_digest,
            effect_authority: false,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn validate(&self) -> Result<(), IntelligenceContractErrorV1> {
        if self.effect_authority || self.authority.grants_any() {
            return Err(IntelligenceContractErrorV1::AuthorityWidening);
        }
        let rebuilt = Self::new(
            self.run_id.clone(),
            self.request_digest,
            self.snapshot_digest,
            self.objective_digest,
            self.legal_candidate_set_digest,
            self.utility_digest,
            self.evaluation_digest,
            self.intuition_digest,
            self.context_digest,
            self.composition_trace_digest,
        )?;
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

fn legal_candidate_set_digest(
    candidate_set_id: &StableId,
    state_digest: Digest32,
    generator_id: &StableId,
    grammar_digest: Digest32,
    candidates: &[LegalActionCandidateV1],
    support_floor_ppm: u32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.legal-action-candidate-set.v1\0".to_vec();
    crate::push_id(&mut bytes, candidate_set_id);
    bytes.extend_from_slice(state_digest.as_array());
    crate::push_id(&mut bytes, generator_id);
    bytes.extend_from_slice(grammar_digest.as_array());
    bytes.extend_from_slice(&support_floor_ppm.to_be_bytes());
    bytes.extend_from_slice(&u32::try_from(candidates.len()).unwrap_or(u32::MAX).to_be_bytes());
    for candidate in candidates {
        crate::push_id(&mut bytes, &candidate.candidate_id);
        bytes.extend_from_slice(candidate.action_digest.as_array());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
fn host_envelope_digest(
    run_id: &StableId,
    request_digest: Digest32,
    snapshot_digest: Digest32,
    objective_digest: Digest32,
    legal_candidate_set_digest: Digest32,
    utility_digest: Digest32,
    evaluation_digest: Digest32,
    intuition_digest: Digest32,
    context_digest: Digest32,
    composition_trace_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.host-envelope.v1\0".to_vec();
    crate::push_id(&mut bytes, run_id);
    for digest in [
        request_digest,
        snapshot_digest,
        objective_digest,
        legal_candidate_set_digest,
        utility_digest,
        evaluation_digest,
        intuition_digest,
        context_digest,
        composition_trace_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}
