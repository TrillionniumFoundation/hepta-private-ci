//! Shadow-decision adapter from the calibrated intuition policy into the
//! append-only causal learning ledger.
//!
//! The adapter recomputes the candidate-set digest and policy receipt. Callers
//! cannot inject a selected propensity or label an outcome through this path.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_intuition::Decision;
use codex_hepta_intuition::DecisionRequest;
use codex_hepta_intuition::Error as IntuitionError;
use codex_hepta_intuition::IntuitionDecisionReceipt;
use codex_hepta_intuition::decide;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AppendReceipt;
use crate::CandidateSetCompleteness;
use crate::EpisodeDecision;
use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;

const ABSTAIN_ID: &str = "abstain";
const MAX_CANDIDATES_WITH_ABSTAIN: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowDecisionRequest {
    pub record_id: StableId,
    pub episode_id: StableId,
    pub policy_id: StableId,
    pub decision: DecisionRequest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowDecisionArtifact {
    pub decision_request: DecisionRequest,
    pub intuition_receipt: IntuitionDecisionReceipt,
    pub ledger_decision: EpisodeDecision,
    pub candidate_set_digest: Digest32,
    pub artifact_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ShadowAppendReceipt {
    pub artifact: ShadowDecisionArtifact,
    pub ledger_receipt: AppendReceipt,
}

#[derive(Debug)]
pub enum ShadowDecisionError {
    CandidateLimitExceeded,
    CandidateSetDigestMismatch {
        expected: Digest32,
        provided: Digest32,
    },
    ReservedAbstainCandidate,
    SelectedPropensityMissing(String),
    ZeroSelectedPropensity,
    AuthorityEscalation,
    Intuition(IntuitionError),
    Ledger(LedgerError),
    InternalInvariant,
}

impl fmt::Display for ShadowDecisionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::CandidateLimitExceeded => {
                formatter.write_str("shadow candidate set plus abstain exceeds 128 entries")
            }
            Self::CandidateSetDigestMismatch { expected, provided } => write!(
                formatter,
                "candidate set digest mismatch: expected {expected}, provided {provided}"
            ),
            Self::ReservedAbstainCandidate => formatter.write_str(
                "the policy candidate set must not contain the reserved explicit abstain id",
            ),
            Self::SelectedPropensityMissing(candidate_id) => write!(
                formatter,
                "intuition receipt omitted selected candidate propensity: {candidate_id}"
            ),
            Self::ZeroSelectedPropensity => {
                formatter.write_str("selected shadow propensity must be greater than zero")
            }
            Self::AuthorityEscalation => {
                formatter.write_str("intuition receipt unexpectedly grants authority")
            }
            Self::Intuition(error) => write!(formatter, "intuition decision failed: {error}"),
            Self::Ledger(error) => write!(formatter, "learning ledger append failed: {error}"),
            Self::InternalInvariant => formatter.write_str("shadow adapter internal invariant failed"),
        }
    }
}

impl StdError for ShadowDecisionError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Intuition(error) => Some(error),
            Self::Ledger(error) => Some(error),
            Self::CandidateLimitExceeded
            | Self::CandidateSetDigestMismatch { .. }
            | Self::ReservedAbstainCandidate
            | Self::SelectedPropensityMissing(_)
            | Self::ZeroSelectedPropensity
            | Self::AuthorityEscalation
            | Self::InternalInvariant => None,
        }
    }
}

pub fn canonical_candidate_set_digest(request: &DecisionRequest) -> Digest32 {
    let mut candidates = request.candidates.clone();
    candidates.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.learning-ledger.shadow-candidate-set.v1");
    bytes.extend_from_slice(
        &u32::try_from(candidates.len())
            .unwrap_or(u32::MAX)
            .to_be_bytes(),
    );
    for candidate in candidates {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.push(u8::from(candidate.legal));
        bytes.push(u8::from(candidate.hard_veto));
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.confidence.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

pub fn prepare_shadow_decision(
    request: ShadowDecisionRequest,
) -> Result<ShadowDecisionArtifact, ShadowDecisionError> {
    if request.decision.candidates.len() >= MAX_CANDIDATES_WITH_ABSTAIN {
        return Err(ShadowDecisionError::CandidateLimitExceeded);
    }
    if request
        .decision
        .candidates
        .iter()
        .any(|candidate| candidate.candidate_id.as_str() == ABSTAIN_ID)
    {
        return Err(ShadowDecisionError::ReservedAbstainCandidate);
    }

    let candidate_set_digest = canonical_candidate_set_digest(&request.decision);
    if request.decision.candidate_set_digest != candidate_set_digest {
        return Err(ShadowDecisionError::CandidateSetDigestMismatch {
            expected: candidate_set_digest,
            provided: request.decision.candidate_set_digest,
        });
    }

    let intuition_receipt =
        decide(request.decision.clone()).map_err(ShadowDecisionError::Intuition)?;
    if intuition_receipt.authority.grants_any() {
        return Err(ShadowDecisionError::AuthorityEscalation);
    }

    let abstain_id = StableId::new(ABSTAIN_ID.to_string())
        .map_err(|_| ShadowDecisionError::InternalInvariant)?;
    let (selected_candidate_id, selected_propensity) = match &intuition_receipt.decision {
        Decision::Selected(candidate_id) => {
            let propensity = intuition_receipt
                .propensities
                .iter()
                .find(|row| &row.candidate_id == candidate_id)
                .map(|row| row.probability)
                .ok_or_else(|| {
                    ShadowDecisionError::SelectedPropensityMissing(candidate_id.to_string())
                })?;
            (candidate_id.clone(), propensity)
        }
        Decision::Abstained(_) => (abstain_id.clone(), intuition_receipt.abstain_probability),
    };
    if selected_propensity.raw() == 0 {
        return Err(ShadowDecisionError::ZeroSelectedPropensity);
    }

    let mut candidate_ids = request
        .decision
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    candidate_ids.push(abstain_id);
    candidate_ids.sort();

    let support_digest = decision_support_digest(
        &request,
        candidate_set_digest,
        intuition_receipt.receipt_digest,
        selected_propensity,
    );
    let ledger_decision = EpisodeDecision {
        record_id: request.record_id.clone(),
        episode_id: request.episode_id.clone(),
        objective_digest: request.decision.objective_digest,
        policy_id: request.policy_id.clone(),
        candidate_ids,
        selected_candidate_id,
        selected_propensity,
        completeness: CandidateSetCompleteness::Complete,
        support_digest,
    };
    let artifact_digest = shadow_artifact_digest(
        &request,
        &ledger_decision,
        intuition_receipt.receipt_digest,
        candidate_set_digest,
    );

    Ok(ShadowDecisionArtifact {
        decision_request: request.decision,
        intuition_receipt,
        ledger_decision,
        candidate_set_digest,
        artifact_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn append_shadow_decision(
    ledger: &mut LearningLedger,
    request: ShadowDecisionRequest,
) -> Result<ShadowAppendReceipt, ShadowDecisionError> {
    let artifact = prepare_shadow_decision(request)?;
    let ledger_receipt = ledger
        .append(LedgerEvent::Decision(artifact.ledger_decision.clone()))
        .map_err(ShadowDecisionError::Ledger)?;
    Ok(ShadowAppendReceipt {
        artifact,
        ledger_receipt,
    })
}

fn decision_support_digest(
    request: &ShadowDecisionRequest,
    candidate_set_digest: Digest32,
    intuition_receipt_digest: Digest32,
    selected_propensity: ProbabilityQ32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.learning-ledger.shadow-decision-support.v1");
    push_id(&mut bytes, &request.record_id);
    push_id(&mut bytes, &request.episode_id);
    push_id(&mut bytes, &request.policy_id);
    bytes.extend_from_slice(request.decision.objective_digest.as_array());
    bytes.extend_from_slice(candidate_set_digest.as_array());
    bytes.extend_from_slice(intuition_receipt_digest.as_array());
    bytes.extend_from_slice(&selected_propensity.raw().to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn shadow_artifact_digest(
    request: &ShadowDecisionRequest,
    decision: &EpisodeDecision,
    intuition_receipt_digest: Digest32,
    candidate_set_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.learning-ledger.shadow-artifact.v1");
    push_id(&mut bytes, &request.record_id);
    push_id(&mut bytes, &request.episode_id);
    push_id(&mut bytes, &request.policy_id);
    push_id(&mut bytes, &request.decision.decision_id);
    bytes.extend_from_slice(request.decision.objective_digest.as_array());
    bytes.extend_from_slice(candidate_set_digest.as_array());
    bytes.extend_from_slice(intuition_receipt_digest.as_array());
    push_id(&mut bytes, &decision.selected_candidate_id);
    bytes.extend_from_slice(&decision.selected_propensity.raw().to_be_bytes());
    bytes.extend_from_slice(decision.support_digest.as_array());
    for candidate_id in &decision.candidate_ids {
        push_id(&mut bytes, candidate_id);
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
