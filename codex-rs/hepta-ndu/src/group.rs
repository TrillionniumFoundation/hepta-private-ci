use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

pub const MAX_GROUP_CELLS_V1: usize = 4096;
pub const MAX_GROUP_CANDIDATES_V1: usize = 128;
pub const MAX_GROUP_ID_BYTES_V1: usize = 256;
pub const MAX_GROUP_RUN_ID_BYTES_V1: usize = 256;

/// The owner-local scope in which a group System2 decision is evaluated.
#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum GroupSubjectClassV1 {
    Domain,
    Agent,
}

impl GroupSubjectClassV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Domain => 0,
            Self::Agent => 1,
        }
    }
}

/// Immutable identity and resource fence for one group NDU owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GroupNduSubjectV1 {
    pub subject_id: String,
    pub subject_class: GroupSubjectClassV1,
    pub group_id: String,
    pub generation: u64,
    pub objective_digest: Digest32,
    pub encoder_digest: Digest32,
    pub utility_profile_digest: Digest32,
    pub resource_ceiling_micros: u64,
}

/// One cell's local evidence supplied to the group owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GroupCellObservationV1 {
    pub cell_id: String,
    pub head_digest: Digest32,
    pub action_digest: Digest32,
    pub evidence_digest: Digest32,
    pub value_q32: i64,
    pub cost_micros: u64,
    pub uncertainty_q32: i64,
    pub abstain: bool,
}

/// Complete evidence binding for one owner-local decision run.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GroupDecisionTraceV1 {
    pub run_id: String,
    pub subject_id: String,
    pub input_digest: Digest32,
    pub generation: u64,
    pub route_digest: Digest32,
    pub complete_candidate_set_digest: Digest32,
    pub behavior_digest: Digest32,
    pub terminal_outcome_digest: Digest32,
    pub cells: Vec<GroupCellObservationV1>,
}

/// A candidate continuation proposed to the group owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GroupContinuationCandidateV1 {
    pub candidate_id: String,
    pub current_value_q32: i64,
    pub continuation_value_q32: i64,
    pub cost_q32: i64,
    pub risk_q32: i64,
    pub legal: bool,
    pub abstain: bool,
}

/// Deterministic, advisory result of the group continuation policy.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GroupSystem2DecisionV1 {
    pub selected_candidate_id: String,
    pub net_value_q32: i64,
    pub trace_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum GroupSystem2Error {
    EmptyId(&'static str),
    IdTooLarge(&'static str),
    InvalidId(&'static str),
    ZeroDigest(&'static str),
    ZeroGeneration,
    TraceBindingMismatch(&'static str),
    ZeroResourceCeiling,
    TooManyCells(usize),
    TooManyCandidates(usize),
    NoCells,
    MissingAbstainCandidate,
    MultipleAbstainCandidates,
    IllegalAbstainCandidate,
    DuplicateCandidateId(String),
    DuplicateCellId(String),
    NegativeUncertainty,
    NegativeCost,
    NegativeRisk,
    ResourceCeilingExceeded { used: u64, ceiling: u64 },
    CandidateSetDigestMismatch,
    ArithmeticOverflow,
}

impl fmt::Display for GroupSystem2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GroupSystem2Error {}

/// Decide whether the owner should continue with one legal candidate or
/// abstain. This is a deterministic advisory boundary; it does not claim a
/// learned FBSDE, model execution, authority grant, or durable mutation.
pub fn decide_group_continuation_v1(
    subject: &GroupNduSubjectV1,
    trace: &GroupDecisionTraceV1,
    candidates: &[GroupContinuationCandidateV1],
) -> Result<GroupSystem2DecisionV1, GroupSystem2Error> {
    validate_subject(subject)?;
    validate_trace(subject, trace)?;
    validate_candidates(subject, candidates)?;

    let candidate_digest = group_candidate_set_digest(candidates)?;
    if candidate_digest != trace.complete_candidate_set_digest {
        return Err(GroupSystem2Error::CandidateSetDigestMismatch);
    }

    let abstain = candidates
        .iter()
        .find(|candidate| candidate.abstain)
        .ok_or(GroupSystem2Error::MissingAbstainCandidate)?;

    // Validate the abstain baseline before considering any continuation:
    // it is an actual legal alternative, not an assumed zero-utility action.
    let abstain_net = candidate_net_value(abstain)?;

    let mut best_non_abstain: Option<(&GroupContinuationCandidateV1, i64)> = None;
    for candidate in candidates
        .iter()
        .filter(|candidate| candidate.legal && !candidate.abstain)
    {
        let net = candidate_net_value(candidate)?;
        let replace = match best_non_abstain {
            None => true,
            Some((current, current_net)) => {
                net > current_net
                    || (net == current_net && candidate.candidate_id < current.candidate_id)
            }
        };
        if replace {
            best_non_abstain = Some((candidate, net));
        }
    }

    let (selected_candidate, selected_net) = match best_non_abstain {
        Some((candidate, net))
            if trace.cells.iter().try_fold(0_u64, |total, cell| {
                total.checked_add(cell.cost_micros)
            }) == Some(subject.resource_ceiling_micros) =>
        {
            (abstain, abstain_net)
        }
        Some((candidate, net)) if net > 0 && net > abstain_net => (candidate, net),
        _ => (abstain, abstain_net),
    };

    let trace_digest = decision_trace_digest(subject, trace, candidate_digest);
    Ok(GroupSystem2DecisionV1 {
        selected_candidate_id: selected_candidate.candidate_id.clone(),
        net_value_q32: selected_net,
        trace_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_subject(subject: &GroupNduSubjectV1) -> Result<(), GroupSystem2Error> {
    validate_id("subject_id", &subject.subject_id)?;
    validate_id("group_id", &subject.group_id)?;
    if subject.generation == 0 {
        return Err(GroupSystem2Error::ZeroGeneration);
    }
    for (name, digest) in [
        ("objective_digest", subject.objective_digest),
        ("encoder_digest", subject.encoder_digest),
        ("utility_profile_digest", subject.utility_profile_digest),
    ] {
        if digest.is_zero() {
            return Err(GroupSystem2Error::ZeroDigest(name));
        }
    }
    if subject.resource_ceiling_micros == 0 {
        return Err(GroupSystem2Error::ZeroResourceCeiling);
    }
    Ok(())
}

fn validate_trace(
    subject: &GroupNduSubjectV1,
    trace: &GroupDecisionTraceV1,
) -> Result<(), GroupSystem2Error> {
    validate_id("run_id", &trace.run_id)?;
    if trace.run_id.len() > MAX_GROUP_RUN_ID_BYTES_V1 {
        return Err(GroupSystem2Error::IdTooLarge("run_id"));
    }
    if trace.subject_id != subject.subject_id {
        return Err(GroupSystem2Error::TraceBindingMismatch("subject_id"));
    }
    if trace.generation != subject.generation {
        return Err(GroupSystem2Error::TraceBindingMismatch("generation"));
    }
    for (name, digest) in [
        ("input_digest", trace.input_digest),
        ("route_digest", trace.route_digest),
        (
            "complete_candidate_set_digest",
            trace.complete_candidate_set_digest,
        ),
        ("behavior_digest", trace.behavior_digest),
        ("terminal_outcome_digest", trace.terminal_outcome_digest),
    ] {
        if digest.is_zero() {
            return Err(GroupSystem2Error::ZeroDigest(name));
        }
    }
    if trace.cells.is_empty() {
        return Err(GroupSystem2Error::NoCells);
    }
    if trace.cells.len() > MAX_GROUP_CELLS_V1 {
        return Err(GroupSystem2Error::TooManyCells(trace.cells.len()));
    }

    let mut used = 0_u64;
    let mut cell_ids = BTreeSet::new();
    for cell in &trace.cells {
        validate_id("cell_id", &cell.cell_id)?;
        if !cell_ids.insert(cell.cell_id.as_str()) {
            return Err(GroupSystem2Error::DuplicateCellId(cell.cell_id.clone()));
        }
        for (name, digest) in [
            ("head_digest", cell.head_digest),
            ("action_digest", cell.action_digest),
            ("evidence_digest", cell.evidence_digest),
        ] {
            if digest.is_zero() {
                return Err(GroupSystem2Error::ZeroDigest(name));
            }
        }
        if cell.uncertainty_q32 < 0 {
            return Err(GroupSystem2Error::NegativeUncertainty);
        }
        used = used
            .checked_add(cell.cost_micros)
            .ok_or(GroupSystem2Error::ArithmeticOverflow)?;
    }
    if used > subject.resource_ceiling_micros {
        return Err(GroupSystem2Error::ResourceCeilingExceeded {
            used,
            ceiling: subject.resource_ceiling_micros,
        });
    }
    Ok(())
}

fn validate_candidates(
    _subject: &GroupNduSubjectV1,
    candidates: &[GroupContinuationCandidateV1],
) -> Result<(), GroupSystem2Error> {
    if candidates.is_empty() {
        return Err(GroupSystem2Error::TooManyCandidates(0));
    }
    if candidates.len() > MAX_GROUP_CANDIDATES_V1 {
        return Err(GroupSystem2Error::TooManyCandidates(candidates.len()));
    }

    let mut abstain_count = 0_usize;
    for (index, candidate) in candidates.iter().enumerate() {
        validate_id("candidate_id", &candidate.candidate_id)?;
        if candidate.cost_q32 < 0 {
            return Err(GroupSystem2Error::NegativeCost);
        }
        if candidate.risk_q32 < 0 {
            return Err(GroupSystem2Error::NegativeRisk);
        }
        if candidate.abstain {
            abstain_count += 1;
            if !candidate.legal {
                return Err(GroupSystem2Error::IllegalAbstainCandidate);
            }
        }
        if candidates[..index]
            .iter()
            .any(|previous| previous.candidate_id == candidate.candidate_id)
        {
            return Err(GroupSystem2Error::DuplicateCandidateId(
                candidate.candidate_id.clone(),
            ));
        }
    }
    match abstain_count {
        0 => Err(GroupSystem2Error::MissingAbstainCandidate),
        1 => Ok(()),
        _ => Err(GroupSystem2Error::MultipleAbstainCandidates),
    }
}

fn validate_id(name: &'static str, value: &str) -> Result<(), GroupSystem2Error> {
    if value.is_empty() {
        return Err(GroupSystem2Error::EmptyId(name));
    }
    if value.len() > MAX_GROUP_ID_BYTES_V1 {
        return Err(GroupSystem2Error::IdTooLarge(name));
    }
    // Stable identifiers must not carry control text, path separators, or
    // visually ambiguous non-ASCII characters into receipt and trace fields.
    if !value
        .bytes()
        .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(GroupSystem2Error::InvalidId(name));
    }
    Ok(())
}

fn candidate_net_value(candidate: &GroupContinuationCandidateV1) -> Result<i64, GroupSystem2Error> {
    let net = i128::from(candidate.continuation_value_q32)
        - i128::from(candidate.current_value_q32)
        - i128::from(candidate.cost_q32)
        - i128::from(candidate.risk_q32);
    i64::try_from(net).map_err(|_| GroupSystem2Error::ArithmeticOverflow)
}

fn group_candidate_set_digest(
    candidates: &[GroupContinuationCandidateV1],
) -> Result<Digest32, GroupSystem2Error> {
    let mut bytes = b"hepta.ndu.group-candidate-set.v1\0".to_vec();
    for candidate in candidates {
        push_text(&mut bytes, &candidate.candidate_id)?;
        push_i64(&mut bytes, candidate.current_value_q32);
        push_i64(&mut bytes, candidate.continuation_value_q32);
        push_i64(&mut bytes, candidate.cost_q32);
        push_i64(&mut bytes, candidate.risk_q32);
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.abstain));
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn decision_trace_digest(
    subject: &GroupNduSubjectV1,
    trace: &GroupDecisionTraceV1,
    candidate_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.ndu.group-decision-trace.v1\0".to_vec();
    push_text_unchecked(&mut bytes, &subject.subject_id);
    bytes.push(subject.subject_class.tag());
    push_text_unchecked(&mut bytes, &subject.group_id);
    bytes.extend_from_slice(&subject.generation.to_be_bytes());
    bytes.extend_from_slice(subject.objective_digest.as_array());
    bytes.extend_from_slice(subject.encoder_digest.as_array());
    bytes.extend_from_slice(subject.utility_profile_digest.as_array());
    bytes.extend_from_slice(&subject.resource_ceiling_micros.to_be_bytes());
    push_text_unchecked(&mut bytes, &trace.run_id);
    push_text_unchecked(&mut bytes, &trace.subject_id);
    bytes.extend_from_slice(trace.input_digest.as_array());
    bytes.extend_from_slice(&trace.generation.to_be_bytes());
    bytes.extend_from_slice(trace.route_digest.as_array());
    bytes.extend_from_slice(candidate_digest.as_array());
    bytes.extend_from_slice(trace.behavior_digest.as_array());
    bytes.extend_from_slice(trace.terminal_outcome_digest.as_array());
    for cell in &trace.cells {
        push_text_unchecked(&mut bytes, &cell.cell_id);
        bytes.extend_from_slice(cell.head_digest.as_array());
        bytes.extend_from_slice(cell.action_digest.as_array());
        bytes.extend_from_slice(cell.evidence_digest.as_array());
        bytes.extend_from_slice(&cell.value_q32.to_be_bytes());
        bytes.extend_from_slice(&cell.cost_micros.to_be_bytes());
        bytes.extend_from_slice(&cell.uncertainty_q32.to_be_bytes());
        bytes.push(u8::from(cell.abstain));
    }
    Digest32::of_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) -> Result<(), GroupSystem2Error> {
    validate_id("digest_text", value)?;
    push_text_unchecked(bytes, value);
    Ok(())
}

fn push_text_unchecked(bytes: &mut Vec<u8>, value: &str) {
    let length = u64::try_from(value.len()).unwrap_or(u64::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_i64(bytes: &mut Vec<u8>, value: i64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "group_tests.rs"]
mod tests;
