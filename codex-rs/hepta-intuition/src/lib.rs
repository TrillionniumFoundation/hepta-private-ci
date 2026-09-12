//! Calibrated, deterministic intuition policy over a complete candidate set.
//!
//! The result is advisory. This crate cannot dispatch a model or tool, override
//! a hard veto, write memory, select for production, promote or release.

#![forbid(unsafe_code)]

// Retain the historical module path as well as explicit root exports.
pub mod calibrated;

pub use calibrated::AbstentionReasonV1;
pub use calibrated::AssignmentModeV1;
pub use calibrated::CalibratedActionCandidateV1;
pub use calibrated::CalibratedCandidatePropensityV1;
pub use calibrated::CalibratedDecisionRequestV1;
pub use calibrated::CalibratedDispositionV1;
pub use calibrated::CalibratedError;
pub use calibrated::CalibratedIntuitionReceiptV1;
pub use calibrated::CalibrationArtifactV1;
pub use calibrated::CandidateSetCompletenessBindingV1;
pub use calibrated::OodArtifactV1;
pub use calibrated::RiskClass;
pub use calibrated::SlowPathReasonV1;
pub use calibrated::canonical_calibrated_request_digest_v1;
pub use calibrated::canonical_candidate_order_digest_v1;
pub use calibrated::canonical_candidate_set_digest_v1;
pub use calibrated::decide_calibrated;
pub use calibrated::decide_calibrated_v2;

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

const MAX_CANDIDATES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ActionCandidate {
    pub candidate_id: StableId,
    pub legal: bool,
    pub hard_veto: bool,
    pub utility: FixedQ32,
    pub confidence: ProbabilityQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionRequest {
    pub decision_id: StableId,
    pub objective_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub minimum_confidence: ProbabilityQ32,
    pub candidates: Vec<ActionCandidate>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AbstentionReason {
    NoLegalCandidate,
    LowConfidence,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Decision {
    Selected(StableId),
    Abstained(AbstentionReason),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CandidatePropensity {
    pub candidate_id: StableId,
    pub probability: ProbabilityQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntuitionDecisionReceipt {
    pub decision_id: StableId,
    pub decision: Decision,
    pub propensities: Vec<CandidatePropensity>,
    pub abstain_probability: ProbabilityQ32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    CandidateLimitExceeded,
    DuplicateCandidate(String),
    EmptyDigest(&'static str),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn decide(mut request: DecisionRequest) -> Result<IntuitionDecisionReceipt, Error> {
    if request.candidates.len() > MAX_CANDIDATES {
        return Err(Error::CandidateLimitExceeded);
    }
    if request.objective_digest.is_zero() {
        return Err(Error::EmptyDigest("objective"));
    }
    if request.candidate_set_digest.is_zero() {
        return Err(Error::EmptyDigest("candidate set"));
    }

    request
        .candidates
        .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut seen = BTreeSet::new();
    for candidate in &request.candidates {
        if !seen.insert(candidate.candidate_id.clone()) {
            return Err(Error::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.support_digest.is_zero() {
            return Err(Error::EmptyDigest("candidate support"));
        }
    }

    let mut best: Option<&ActionCandidate> = None;
    for candidate in &request.candidates {
        if !candidate.legal || candidate.hard_veto {
            continue;
        }
        let replace = match best {
            None => true,
            Some(current) => {
                candidate.utility > current.utility
                    || (candidate.utility == current.utility
                        && (candidate.confidence > current.confidence
                            || (candidate.confidence == current.confidence
                                && candidate.candidate_id < current.candidate_id)))
            }
        };
        if replace {
            best = Some(candidate);
        }
    }

    let decision = match best {
        None => Decision::Abstained(AbstentionReason::NoLegalCandidate),
        Some(candidate) if candidate.confidence < request.minimum_confidence => {
            Decision::Abstained(AbstentionReason::LowConfidence)
        }
        Some(candidate) => Decision::Selected(candidate.candidate_id.clone()),
    };

    let propensities = request
        .candidates
        .iter()
        .map(|candidate| CandidatePropensity {
            candidate_id: candidate.candidate_id.clone(),
            probability: match &decision {
                Decision::Selected(selected) if selected == &candidate.candidate_id => {
                    ProbabilityQ32::ONE
                }
                _ => ProbabilityQ32::ZERO,
            },
        })
        .collect::<Vec<_>>();
    let abstain_probability = match decision {
        Decision::Selected(_) => ProbabilityQ32::ZERO,
        Decision::Abstained(_) => ProbabilityQ32::ONE,
    };
    let receipt_digest = digest_receipt(&request, &decision, &propensities, abstain_probability);

    Ok(IntuitionDecisionReceipt {
        decision_id: request.decision_id,
        decision,
        propensities,
        abstain_probability,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn digest_receipt(
    request: &DecisionRequest,
    decision: &Decision,
    propensities: &[CandidatePropensity],
    abstain_probability: ProbabilityQ32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intuition.decision.v1");
    push_id(&mut bytes, &request.decision_id);
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.candidate_set_digest.as_array());
    bytes.extend_from_slice(&request.minimum_confidence.raw().to_be_bytes());
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.hard_veto));
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.confidence.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    match decision {
        Decision::Selected(candidate_id) => {
            bytes.push(0);
            push_id(&mut bytes, candidate_id);
        }
        Decision::Abstained(AbstentionReason::NoLegalCandidate) => bytes.push(1),
        Decision::Abstained(AbstentionReason::LowConfidence) => bytes.push(2),
    }
    for propensity in propensities {
        push_id(&mut bytes, &propensity.candidate_id);
        bytes.extend_from_slice(&propensity.probability.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&abstain_probability.raw().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
