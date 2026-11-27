//! NDU-driven selection boundary for one Cell candidate.
//!
//! The evaluator records the complete candidate set and the frozen no-change
//! baseline.  The selector may only consume the evaluator receipt and the NDU
//! recommendation.  The executor consumes a private selection token exactly
//! once.  None of these stages owns model loading, topology application or
//! external-effect authority.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_ndu::CandidateRejectionReason;
use codex_hepta_ndu::CandidateUtility;
use codex_hepta_ndu::NduEvaluationReceiptV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_CANDIDATES: usize = 128;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellNduCandidateEvidenceV1 {
    pub candidate_id: StableId,
    pub artifact_digest: Digest32,
    pub future_window_digest: Digest32,
    /// Independent measured utility delta against the no-change baseline.
    pub utility_delta_q32: i64,
    /// Resource cost is recorded in the same fixed-point domain as utility.
    pub resource_cost_q32: i64,
    /// Negative migration is a non-negative penalty; it is never hidden by
    /// averaging utility across candidates.
    pub negative_migration_q32: i64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellNduEvaluationRequestV1 {
    pub evaluator_id: StableId,
    pub selector_id: StableId,
    pub executor_id: StableId,
    pub baseline_id: StableId,
    pub baseline_artifact_digest: Digest32,
    pub generation: Generation,
    pub ndu: NduEvaluationReceiptV2,
    pub candidates: Vec<CellNduCandidateEvidenceV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellNduEvaluationReceiptV1 {
    pub evaluator_id: StableId,
    pub selector_id: StableId,
    pub executor_id: StableId,
    pub baseline_id: StableId,
    pub baseline_artifact_digest: Digest32,
    pub generation: Generation,
    pub ndu_evaluation_digest: Digest32,
    pub candidate_set_digest: Digest32,
    /// Exact artifact binding for every candidate accepted by the evaluator.
    /// The selector cannot substitute a digest supplied out of band.
    pub candidate_artifact_digests: BTreeMap<StableId, Digest32>,
    /// The complete evaluator evidence is retained in the receipt.  Keeping
    /// this immutable projection here lets the selector recompute the binding
    /// digest instead of trusting a caller supplied candidate set or utility
    /// summary.  It also preserves the measured future-window and migration
    /// values for independent observers and the executor hand-off.
    pub candidate_evidence: BTreeMap<StableId, CellNduCandidateEvidenceV1>,
    pub eligible_candidate_ids: Vec<StableId>,
    pub rejected_candidate_ids: Vec<StableId>,
    pub no_change_only: bool,
    pub authority: AuthorityPosture,
}

#[derive(Debug, Eq, PartialEq)]
pub enum CellNduSelectionDecisionV1 {
    NoChange { reason_digest: Digest32 },
    Candidate(CellSelectionTokenV1),
}

#[derive(Debug, Eq, PartialEq)]
pub struct CellSelectionTokenV1 {
    selector_id: StableId,
    executor_id: StableId,
    baseline_id: StableId,
    candidate_id: StableId,
    generation: Generation,
    candidate_artifact_digest: Digest32,
    evaluation_digest: Digest32,
    selection_digest: Digest32,
}

impl CellSelectionTokenV1 {
    #[must_use]
    pub fn candidate_id(&self) -> &StableId {
        &self.candidate_id
    }

    #[must_use]
    pub fn generation(&self) -> Generation {
        self.generation
    }

    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellNduExecutionReceiptV1 {
    pub executor_id: StableId,
    pub baseline_id: StableId,
    pub candidate_id: StableId,
    pub generation: Generation,
    pub candidate_artifact_digest: Digest32,
    pub selection_digest: Digest32,
    pub execution_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellNduSelectionErrorV1 {
    EmptyDigest(&'static str),
    InvalidGeneration,
    RoleCollision,
    CandidateLimit,
    DuplicateCandidate(String),
    MissingBaseline,
    BaselineBinding,
    NduBinding,
    GenerationMismatch,
    FutureWindowMissing(String),
    NegativeMigration,
    ResourceCost,
    RecommendationUnavailable,
    RecommendationRejected,
    TokenBinding,
}

impl fmt::Display for CellNduSelectionErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for CellNduSelectionErrorV1 {}

/// Evaluator-owned admission. It validates the complete candidate set and
/// emits no selection token.
pub fn evaluate_cell_ndu_v1(
    request: CellNduEvaluationRequestV1,
) -> Result<CellNduEvaluationReceiptV1, CellNduSelectionErrorV1> {
    if request.evaluator_id == request.selector_id
        || request.evaluator_id == request.executor_id
        || request.selector_id == request.executor_id
    {
        return Err(CellNduSelectionErrorV1::RoleCollision);
    }
    if request.generation.get() == 0 {
        return Err(CellNduSelectionErrorV1::InvalidGeneration);
    }
    if request.generation != request.ndu.base.generation {
        return Err(CellNduSelectionErrorV1::GenerationMismatch);
    }
    require_digest(request.baseline_artifact_digest, "baseline artifact")?;
    if request.candidates.is_empty() || request.candidates.len() > MAX_CANDIDATES {
        return Err(CellNduSelectionErrorV1::CandidateLimit);
    }
    if request.ndu.base.objective_digest.is_zero()
        || request.ndu.base.utility_profile_digest.is_zero()
        || request.ndu.base.evaluation_digest.is_zero()
        || request.ndu.evaluation_policy_digest.is_zero()
        || request.ndu.evaluation_digest_v2.is_zero()
    {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }

    let mut by_id = BTreeMap::new();
    for candidate in &request.candidates {
        require_digest(candidate.artifact_digest, "candidate artifact")?;
        require_digest(candidate.future_window_digest, "future window")?;
        // A candidate can legitimately have negative measured utility.  Keep
        // it in the complete evaluator receipt so retention and negative
        // transfer remain observable; the eligibility pass below rejects it
        // against the no-change baseline.  Resource and migration penalties
        // are costs and therefore remain non-negative invariants.
        if candidate.resource_cost_q32 < 0 || candidate.negative_migration_q32 < 0 {
            return Err(if candidate.resource_cost_q32 < 0 {
                CellNduSelectionErrorV1::ResourceCost
            } else {
                CellNduSelectionErrorV1::NegativeMigration
            });
        }
        if by_id
            .insert(candidate.candidate_id.clone(), candidate)
            .is_some()
        {
            return Err(CellNduSelectionErrorV1::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
    }
    let Some(baseline) = by_id.get(&request.baseline_id) else {
        return Err(CellNduSelectionErrorV1::MissingBaseline);
    };
    if baseline.artifact_digest != request.baseline_artifact_digest
        || baseline.utility_delta_q32 != 0
        || baseline.resource_cost_q32 != 0
        || baseline.negative_migration_q32 != 0
    {
        return Err(CellNduSelectionErrorV1::BaselineBinding);
    }

    let ndu_ids: BTreeMap<_, _> = request
        .ndu
        .base
        .evaluated_candidates
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate))
        .collect();
    if request
        .ndu
        .base
        .evaluated_candidates
        .iter()
        .any(|candidate| candidate.support_digest.is_zero())
    {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    if ndu_ids.len() != request.ndu.base.evaluated_candidates.len() {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    let mut ndu_rejected_ids = BTreeSet::new();
    for rejected in &request.ndu.base.rejected_candidates {
        if rejected.reasons.is_empty()
            || !ndu_rejected_ids.insert(rejected.candidate_id.clone())
            || ndu_ids.contains_key(&rejected.candidate_id)
            || !by_id.contains_key(&rejected.candidate_id)
        {
            return Err(CellNduSelectionErrorV1::NduBinding);
        }
    }
    if ndu_ids.len() + ndu_rejected_ids.len() != by_id.len()
        || by_id.keys().any(|candidate_id| {
            !ndu_ids.contains_key(candidate_id) && !ndu_rejected_ids.contains(candidate_id)
        })
    {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    if ndu_rejected_ids.contains(&request.baseline_id) {
        return Err(CellNduSelectionErrorV1::BaselineBinding);
    }
    if request
        .ndu
        .base
        .advisory_recommendation
        .as_ref()
        .is_some_and(|candidate_id| {
            ndu_rejected_ids.contains(candidate_id) || !ndu_ids.contains_key(candidate_id)
        })
    {
        return Err(CellNduSelectionErrorV1::RecommendationRejected);
    }

    let mut eligible_candidate_ids = Vec::new();
    let mut rejected_candidate_ids = Vec::new();
    for candidate in &request.candidates {
        let penalty = candidate
            .resource_cost_q32
            .checked_add(candidate.negative_migration_q32)
            .ok_or(CellNduSelectionErrorV1::ResourceCost)?;
        let eligible = candidate.candidate_id == request.baseline_id
            || (!ndu_rejected_ids.contains(&candidate.candidate_id)
                && candidate.utility_delta_q32 > penalty);
        if eligible {
            eligible_candidate_ids.push(candidate.candidate_id.clone());
        } else {
            rejected_candidate_ids.push(candidate.candidate_id.clone());
        }
    }
    eligible_candidate_ids.sort();
    rejected_candidate_ids.sort();
    let candidate_artifact_digests = request
        .candidates
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate.artifact_digest))
        .collect();
    let candidate_evidence = request
        .candidates
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate.clone()))
        .collect();
    let candidate_set_digest = canonical_candidate_set_digest(
        &request.ndu,
        &request.baseline_id,
        request.baseline_artifact_digest,
        request.generation,
        &candidate_evidence,
        &eligible_candidate_ids,
        &rejected_candidate_ids,
    );
    let baseline_id = request.baseline_id.clone();
    Ok(CellNduEvaluationReceiptV1 {
        evaluator_id: request.evaluator_id,
        selector_id: request.selector_id,
        executor_id: request.executor_id,
        baseline_id,
        baseline_artifact_digest: request.baseline_artifact_digest,
        generation: request.generation,
        ndu_evaluation_digest: request.ndu.evaluation_digest_v2,
        candidate_set_digest,
        candidate_artifact_digests,
        candidate_evidence,
        eligible_candidate_ids,
        rejected_candidate_ids,
        no_change_only: request
            .ndu
            .base
            .advisory_recommendation
            .as_ref()
            .is_none_or(|id| id == &request.baseline_id),
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Selector-owned decision. The NDU recommendation is the only candidate the
/// selector may select; a missing recommendation yields a no-change decision.
pub fn select_cell_ndu_v1(
    receipt: &CellNduEvaluationReceiptV1,
    ndu: &NduEvaluationReceiptV2,
    candidate_artifact_digest: Digest32,
) -> Result<CellNduSelectionDecisionV1, CellNduSelectionErrorV1> {
    require_digest(candidate_artifact_digest, "selected artifact")?;
    validate_selector_binding(receipt, ndu)?;
    let Some(candidate_id) = ndu.base.advisory_recommendation.as_ref() else {
        if receipt.candidate_artifact_digests.get(&receipt.baseline_id)
            != Some(&candidate_artifact_digest)
        {
            return Err(CellNduSelectionErrorV1::TokenBinding);
        }
        return Ok(CellNduSelectionDecisionV1::NoChange {
            reason_digest: Digest32::of_bytes(b"ndu-no-recommendation"),
        });
    };
    if receipt.candidate_artifact_digests.get(candidate_id) != Some(&candidate_artifact_digest) {
        return Err(CellNduSelectionErrorV1::TokenBinding);
    }
    if candidate_id == &receipt.baseline_id {
        return Ok(CellNduSelectionDecisionV1::NoChange {
            reason_digest: Digest32::of_bytes(b"ndu-baseline-recommended"),
        });
    }
    if !receipt
        .eligible_candidate_ids
        .iter()
        .any(|value| value == candidate_id)
    {
        return Err(CellNduSelectionErrorV1::RecommendationRejected);
    }
    let selection_digest = Digest32::of_parts(&[
        b"hepta.intelligence.cell-ndu-selection.v1\0",
        receipt.candidate_set_digest.as_array(),
        candidate_id.as_str().as_bytes(),
        candidate_artifact_digest.as_array(),
    ]);
    Ok(CellNduSelectionDecisionV1::Candidate(
        CellSelectionTokenV1 {
            selector_id: receipt.selector_id.clone(),
            executor_id: receipt.executor_id.clone(),
            baseline_id: receipt.baseline_id.clone(),
            candidate_id: candidate_id.clone(),
            generation: receipt.generation,
            candidate_artifact_digest,
            evaluation_digest: receipt.ndu_evaluation_digest,
            selection_digest,
        },
    ))
}

/// Executor-owned final step. The token is consumed by value and cannot be
/// replayed through this method.
pub fn execute_cell_ndu_v1(
    token: CellSelectionTokenV1,
    executor_id: &StableId,
) -> Result<CellNduExecutionReceiptV1, CellNduSelectionErrorV1> {
    if executor_id != &token.executor_id || token.candidate_id == token.baseline_id {
        return Err(CellNduSelectionErrorV1::TokenBinding);
    }
    let execution_digest = Digest32::of_parts(&[
        b"hepta.intelligence.cell-ndu-execution.v1\0",
        token.selection_digest.as_array(),
        token.candidate_id.as_str().as_bytes(),
        token.candidate_artifact_digest.as_array(),
        token.evaluation_digest.as_array(),
    ]);
    Ok(CellNduExecutionReceiptV1 {
        executor_id: executor_id.clone(),
        baseline_id: token.baseline_id,
        candidate_id: token.candidate_id,
        generation: token.generation,
        candidate_artifact_digest: token.candidate_artifact_digest,
        selection_digest: token.selection_digest,
        execution_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), CellNduSelectionErrorV1> {
    if value.is_zero() {
        Err(CellNduSelectionErrorV1::EmptyDigest(field))
    } else {
        Ok(())
    }
}

/// Validate the evaluator receipt against the exact NDU receipt consumed by
/// the selector.  The receipt is caller-visible data, so checking only its
/// authority posture or only the V2 digest is insufficient: roles, generation,
/// candidate coverage and the no-change claim must all agree before any
/// caller-supplied artifact digest is considered.
fn validate_selector_binding(
    receipt: &CellNduEvaluationReceiptV1,
    ndu: &NduEvaluationReceiptV2,
) -> Result<(), CellNduSelectionErrorV1> {
    if receipt.authority != AuthorityPosture::DENY_ALL {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    if receipt.evaluator_id == receipt.selector_id
        || receipt.evaluator_id == receipt.executor_id
        || receipt.selector_id == receipt.executor_id
    {
        return Err(CellNduSelectionErrorV1::RoleCollision);
    }
    if receipt.generation.get() == 0 || ndu.base.generation.get() == 0 {
        return Err(CellNduSelectionErrorV1::InvalidGeneration);
    }
    if receipt.generation != ndu.base.generation {
        return Err(CellNduSelectionErrorV1::GenerationMismatch);
    }
    if receipt.ndu_evaluation_digest.is_zero()
        || ndu.base.objective_digest.is_zero()
        || ndu.base.utility_profile_digest.is_zero()
        || ndu.base.evaluation_digest.is_zero()
        || ndu.evaluation_policy_digest.is_zero()
        || ndu.evaluation_digest_v2.is_zero()
        || receipt.ndu_evaluation_digest != ndu.evaluation_digest_v2
        || receipt.candidate_set_digest.is_zero()
    {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    require_digest(receipt.baseline_artifact_digest, "baseline artifact")?;

    let ndu_ids: BTreeSet<_> = ndu
        .base
        .evaluated_candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    if ndu
        .base
        .evaluated_candidates
        .iter()
        .any(|candidate| candidate.support_digest.is_zero())
    {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    let mut ndu_rejected_ids = BTreeSet::new();
    for rejected in &ndu.base.rejected_candidates {
        if rejected.reasons.is_empty()
            || !ndu_rejected_ids.insert(rejected.candidate_id.clone())
            || ndu_ids.contains(&rejected.candidate_id)
        {
            return Err(CellNduSelectionErrorV1::NduBinding);
        }
    }
    let all_ndu_ids = ndu_ids
        .union(&ndu_rejected_ids)
        .cloned()
        .collect::<BTreeSet<_>>();
    if ndu_ids.len() != ndu.base.evaluated_candidates.len()
        || receipt.candidate_artifact_digests.len() != all_ndu_ids.len()
        || receipt.candidate_evidence.len() != all_ndu_ids.len()
        || all_ndu_ids.iter().any(|candidate_id| {
            !receipt
                .candidate_artifact_digests
                .contains_key(candidate_id)
                || !receipt.candidate_evidence.contains_key(candidate_id)
        })
    {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    if receipt
        .candidate_artifact_digests
        .iter()
        .any(|(_, digest)| digest.is_zero())
    {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    if receipt.candidate_artifact_digests.get(&receipt.baseline_id)
        != Some(&receipt.baseline_artifact_digest)
        || ndu_rejected_ids.contains(&receipt.baseline_id)
    {
        return Err(CellNduSelectionErrorV1::BaselineBinding);
    }

    for (candidate_id, evidence) in &receipt.candidate_evidence {
        if &evidence.candidate_id != candidate_id
            || receipt.candidate_artifact_digests.get(candidate_id)
                != Some(&evidence.artifact_digest)
            || evidence.future_window_digest.is_zero()
            || evidence.resource_cost_q32 < 0
            || evidence.negative_migration_q32 < 0
        {
            return Err(CellNduSelectionErrorV1::NduBinding);
        }
    }

    let eligible: BTreeSet<_> = receipt.eligible_candidate_ids.iter().cloned().collect();
    let rejected: BTreeSet<_> = receipt.rejected_candidate_ids.iter().cloned().collect();
    if eligible.len() != receipt.eligible_candidate_ids.len()
        || rejected.len() != receipt.rejected_candidate_ids.len()
        || eligible.intersection(&rejected).next().is_some()
        || eligible.union(&rejected).cloned().collect::<BTreeSet<_>>() != all_ndu_ids
        || !eligible.contains(&receipt.baseline_id)
    {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    let expected_no_change_only = ndu
        .base
        .advisory_recommendation
        .as_ref()
        .is_none_or(|candidate_id| candidate_id == &receipt.baseline_id);
    if receipt.no_change_only != expected_no_change_only {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    let expected_digest = canonical_candidate_set_digest(
        ndu,
        &receipt.baseline_id,
        receipt.baseline_artifact_digest,
        receipt.generation,
        &receipt.candidate_evidence,
        &receipt.eligible_candidate_ids,
        &receipt.rejected_candidate_ids,
    );
    if expected_digest != receipt.candidate_set_digest {
        return Err(CellNduSelectionErrorV1::NduBinding);
    }
    Ok(())
}

/// Produce a deterministic binding over the exact NDU recommendation, all
/// measured candidate evidence, and the evaluator's complete partition.  The
/// selector recomputes this digest from its inputs, so changing a recommendation
/// while retaining the same NDU evaluation digest cannot silently alter the
/// selected Cell.
fn canonical_candidate_set_digest(
    ndu: &NduEvaluationReceiptV2,
    baseline_id: &StableId,
    baseline_artifact_digest: Digest32,
    generation: Generation,
    evidence: &BTreeMap<StableId, CellNduCandidateEvidenceV1>,
    eligible: &[StableId],
    rejected: &[StableId],
) -> Digest32 {
    let mut bytes = b"hepta.intelligence.cell-ndu-evaluation.v2\0".to_vec();
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    push_id(&mut bytes, baseline_id);
    bytes.extend_from_slice(baseline_artifact_digest.as_array());
    bytes.extend_from_slice(ndu.base.objective_digest.as_array());
    bytes.extend_from_slice(&ndu.base.generation.get().to_be_bytes());
    bytes.extend_from_slice(ndu.base.utility_profile_digest.as_array());
    match ndu.base.scalarization_profile_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(ndu.base.evaluation_digest.as_array());
    bytes.extend_from_slice(ndu.evaluation_policy_digest.as_array());
    bytes.extend_from_slice(ndu.evaluation_digest_v2.as_array());
    match ndu.base.advisory_recommendation.as_ref() {
        Some(id) => {
            bytes.push(1);
            push_id(&mut bytes, id);
        }
        None => bytes.push(0),
    }
    bytes.push(match ndu.base.disposition {
        codex_hepta_ndu::EvaluationDisposition::InfeasibleExplicitAbstain => 0,
        codex_hepta_ndu::EvaluationDisposition::UniqueParetoRecommendation => 1,
        codex_hepta_ndu::EvaluationDisposition::ParetoSetRequiresSlowPath => 2,
        codex_hepta_ndu::EvaluationDisposition::ScalarizedRecommendation => 3,
        codex_hepta_ndu::EvaluationDisposition::ScalarizationTieRequiresSlowPath => 4,
    });
    let mut evaluated = ndu.base.evaluated_candidates.iter().collect::<Vec<_>>();
    evaluated.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    bytes.extend_from_slice(&(evaluated.len() as u32).to_be_bytes());
    for candidate in evaluated {
        push_candidate_utility(&mut bytes, candidate);
    }
    let mut pareto = ndu.base.pareto_frontier.iter().collect::<Vec<_>>();
    pareto.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    bytes.extend_from_slice(&(pareto.len() as u32).to_be_bytes());
    for candidate in pareto {
        push_candidate_utility(&mut bytes, candidate);
    }
    let mut ndu_rejected = ndu.base.rejected_candidates.iter().collect::<Vec<_>>();
    ndu_rejected.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    bytes.extend_from_slice(&(ndu_rejected.len() as u32).to_be_bytes());
    for candidate in ndu_rejected {
        push_id(&mut bytes, &candidate.candidate_id);
        bytes.extend_from_slice(&(candidate.reasons.len() as u32).to_be_bytes());
        for reason in &candidate.reasons {
            bytes.push(match reason {
                CandidateRejectionReason::HardConstraintViolation => 0,
                CandidateRejectionReason::RiskCeilingExceeded => 1,
                CandidateRejectionReason::ResourceCeilingExceeded => 2,
            });
        }
    }
    bytes.extend_from_slice(&(evidence.len() as u32).to_be_bytes());
    for (candidate_id, candidate) in evidence {
        push_id(&mut bytes, candidate_id);
        bytes.extend_from_slice(candidate.artifact_digest.as_array());
        bytes.extend_from_slice(candidate.future_window_digest.as_array());
        bytes.extend_from_slice(&candidate.utility_delta_q32.to_be_bytes());
        bytes.extend_from_slice(&candidate.resource_cost_q32.to_be_bytes());
        bytes.extend_from_slice(&candidate.negative_migration_q32.to_be_bytes());
    }
    push_ids(&mut bytes, eligible);
    push_ids(&mut bytes, rejected);
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let value = value.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
    bytes.extend_from_slice(value);
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    bytes.extend_from_slice(&(values.len() as u32).to_be_bytes());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_axis_values(bytes: &mut Vec<u8>, values: &[codex_hepta_ndu::AxisValue]) {
    bytes.extend_from_slice(&(values.len() as u32).to_be_bytes());
    for value in values {
        push_id(bytes, &value.axis);
        bytes.extend_from_slice(&value.value.raw().to_be_bytes());
    }
}

fn push_candidate_utility(bytes: &mut Vec<u8>, candidate: &CandidateUtility) {
    push_id(bytes, &candidate.candidate_id);
    bytes.extend_from_slice(candidate.support_digest.as_array());
    push_axis_values(bytes, &candidate.utility);
    push_axis_values(bytes, &candidate.risk);
    push_axis_values(bytes, &candidate.resource);
    push_axis_values(bytes, &candidate.uncertainty);
    match candidate.scalar_score {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.raw().to_be_bytes());
        }
        None => bytes.push(0),
    }
}

#[cfg(test)]
#[path = "cell_ndu_selection_tests.rs"]
mod tests;
