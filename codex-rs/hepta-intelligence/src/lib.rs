//! Bounded intelligence composition and abstention.
//!
//! The output is a plan receipt. It cannot invoke a model, tool or provider,
//! execute an effect, activate a learned artifact, promote or release. The opt-in
//! evaluated shadow adapter can append Decisions to a host-owned durable ledger.

#![forbid(unsafe_code)]

mod evaluated_shadow;

pub use evaluated_shadow::EvaluatedShadowError;
pub use evaluated_shadow::EvaluatedShadowReceiptV1;
pub use evaluated_shadow::EvaluatedShadowRequestV1;
pub use evaluated_shadow::evaluated_candidate_signing_payload_v1;
pub use evaluated_shadow::run_evaluated_shadow_v1;

mod pipeline;

pub use pipeline::CoherentLaneFSnapshotV1;
pub use pipeline::LaneFBudgetV1;
pub use pipeline::LaneFRunRequestV1;
pub use pipeline::LaneFShadowPipelineReceiptV1;
pub use pipeline::LaneFShadowPortsV1;
pub use pipeline::LaneFStageV1;
pub use pipeline::PipelineDispositionV1;
pub use pipeline::PipelineErrorV1;
pub use pipeline::PortDecisionV1;
pub use pipeline::PortFailureClassV1;
pub use pipeline::PortFailureV1;
pub use pipeline::PortInputV1;
pub use pipeline::PortReceiptV1;
pub use pipeline::StageOutcomeV1;
pub use pipeline::StageTraceV1;
pub use pipeline::run_shadow_pipeline;

mod vertical;

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

pub use vertical::ReadOnlyUtilityContribution;
pub use vertical::ReadOnlyVerticalError;
pub use vertical::ReadOnlyVerticalReceipt;
pub use vertical::ReadOnlyVerticalRequest;
pub use vertical::run_read_only_vertical;

const MAX_CANDIDATES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanCandidate {
    pub candidate_id: StableId,
    pub legal: bool,
    pub hard_veto: bool,
    pub score: FixedQ32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanningRequest {
    pub plan_id: StableId,
    pub objective_digest: Digest32,
    pub context_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub candidates: Vec<PlanCandidate>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AbstentionReason {
    NoEligibleCandidate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlanDecision {
    Selected(StableId),
    Abstained(AbstentionReason),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligencePlanReceipt {
    pub plan_id: StableId,
    pub decision: PlanDecision,
    pub considered_candidates: Vec<StableId>,
    pub plan_digest: Digest32,
    pub effect_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    CandidateLimitExceeded,
    DuplicateCandidate(String),
    EmptySupport(String),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn compose(mut request: PlanningRequest) -> Result<IntelligencePlanReceipt, Error> {
    for (name, digest) in [
        ("objective", request.objective_digest),
        ("context", request.context_digest),
        ("snapshot", request.snapshot_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if request.candidates.len() > MAX_CANDIDATES {
        return Err(Error::CandidateLimitExceeded);
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
            return Err(Error::EmptySupport(candidate.candidate_id.to_string()));
        }
    }
    let selected = request
        .candidates
        .iter()
        .filter(|candidate| candidate.legal && !candidate.hard_veto)
        .max_by(|left, right| {
            left.score
                .cmp(&right.score)
                .then_with(|| right.candidate_id.cmp(&left.candidate_id))
        });
    let decision = selected.map_or(
        PlanDecision::Abstained(AbstentionReason::NoEligibleCandidate),
        |candidate| PlanDecision::Selected(candidate.candidate_id.clone()),
    );
    let considered_candidates = request
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.intelligence.plan.v1");
    push_id(&mut bytes, &request.plan_id);
    bytes.extend_from_slice(request.objective_digest.as_array());
    bytes.extend_from_slice(request.context_digest.as_array());
    bytes.extend_from_slice(request.snapshot_digest.as_array());
    for candidate in &request.candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.hard_veto));
        bytes.extend_from_slice(&candidate.score.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(IntelligencePlanReceipt {
        plan_id: request.plan_id,
        decision,
        considered_candidates,
        plan_digest: Digest32::of_bytes(&bytes),
        effect_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "vertical_tests.rs"]
mod vertical_tests;
