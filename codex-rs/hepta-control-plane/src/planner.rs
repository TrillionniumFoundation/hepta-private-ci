use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

const MAX_OWNERS: usize = 32;
const MAX_CANDIDATES: usize = 128;
const MAX_REQUIRED_OWNERS_PER_CANDIDATE: usize = 32;
const MAX_PAYLOADS_PER_CANDIDATE: usize = 64;
const MAX_RESOURCE_RESERVATIONS: usize = 32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum OwnerReadinessV1 {
    Ready,
    Degraded,
    Unavailable,
}

impl OwnerReadinessV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Ready => 0,
            Self::Degraded => 1,
            Self::Unavailable => 2,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OwnerSummaryV1 {
    pub owner_id: StableId,
    pub revision: Revision,
    pub objective_digest: Digest32,
    pub body_generation: Generation,
    pub configuration_digest: Digest32,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
    pub readiness: OwnerReadinessV1,
    pub source_frontier_digest: Digest32,
    pub support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SnapshotRequestV1 {
    pub objective_digest: Digest32,
    pub body_generation: Generation,
    pub configuration_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub collected_at_micros: u64,
    pub maximum_owner_age_micros: u64,
    pub expires_at_micros: u64,
    pub required_owner_ids: Vec<StableId>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GlobalStateSnapshotV1 {
    pub objective_digest: Digest32,
    pub body_generation: Generation,
    pub configuration_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub collected_at_micros: u64,
    pub expires_at_micros: u64,
    pub owner_summaries: Vec<OwnerSummaryV1>,
    pub missing_owner_ids: Vec<StableId>,
    pub stale_owner_ids: Vec<StableId>,
    pub unavailable_owner_ids: Vec<StableId>,
    pub snapshot_digest: Digest32,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct PlannerAxisValueV1 {
    pub axis: StableId,
    pub value: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanCandidateV1 {
    pub candidate_id: StableId,
    pub operation_id: StableId,
    pub plan_digest: Digest32,
    pub required_owner_ids: Vec<StableId>,
    pub final_payload_digests: Vec<Digest32>,
    pub resource_costs: Vec<PlannerAxisValueV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceReservationV1 {
    pub axis: StableId,
    pub endowment: FixedQ32,
    pub essential_floor: FixedQ32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PlanningRequestV1 {
    pub plan_id: StableId,
    pub now_micros: u64,
    pub deadline_micros: u64,
    pub candidates: Vec<PlanCandidateV1>,
    pub resource_reservations: Vec<ResourceReservationV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PreparedPlanInputV1 {
    pub plan_id: StableId,
    pub objective_digest: Digest32,
    pub body_generation: Generation,
    pub configuration_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub source_candidate_set_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub feasible_candidates: Vec<PlanCandidateV1>,
    pub resource_rejected_candidate_ids: Vec<StableId>,
    pub expires_at_micros: u64,
    pub prepared_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PlanningEvaluationDispositionV1 {
    InfeasibleExplicitAbstain,
    UniqueParetoRecommendation,
    ParetoSetRequiresSlowPath,
    ScalarizedRecommendation,
    ScalarizationTieRequiresSlowPath,
}

impl PlanningEvaluationDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::InfeasibleExplicitAbstain => 0,
            Self::UniqueParetoRecommendation => 1,
            Self::ParetoSetRequiresSlowPath => 2,
            Self::ScalarizedRecommendation => 3,
            Self::ScalarizationTieRequiresSlowPath => 4,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduPlanEvaluationInputV1 {
    pub objective_digest: Digest32,
    pub body_generation: Generation,
    pub evaluation_policy_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub evaluated_candidate_ids: Vec<StableId>,
    pub rejected_candidate_ids: Vec<StableId>,
    pub pareto_candidate_ids: Vec<StableId>,
    pub advisory_candidate_id: Option<StableId>,
    pub uncertainty_digest: Digest32,
    pub disposition: PlanningEvaluationDispositionV1,
}

/// Typed owner-port view of an NDU evaluation. The NDU owner computes its
/// opaque evaluation digest. This binding covers the complete candidate and
/// disposition projection consumed by control.runtime and carries no authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduPlanEvaluationV1 {
    pub objective_digest: Digest32,
    pub body_generation: Generation,
    pub evaluation_policy_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub evaluated_candidate_ids: Vec<StableId>,
    pub rejected_candidate_ids: Vec<StableId>,
    pub pareto_candidate_ids: Vec<StableId>,
    pub advisory_candidate_id: Option<StableId>,
    pub uncertainty_digest: Digest32,
    pub disposition: PlanningEvaluationDispositionV1,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SearchDisclosureV1 {
    BoundedCandidateSetOnly,
    UniqueParetoOnBoundedSet,
    ScalarizedBoundedSet,
    UnresolvedParetoFrontier,
}

impl SearchDisclosureV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::BoundedCandidateSetOnly => 0,
            Self::UniqueParetoOnBoundedSet => 1,
            Self::ScalarizedBoundedSet => 2,
            Self::UnresolvedParetoFrontier => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FeasiblePlanReceiptV1 {
    pub plan_id: StableId,
    pub objective_digest: Digest32,
    pub body_generation: Generation,
    pub configuration_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub source_candidate_set_digest: Digest32,
    pub candidate_set_digest: Digest32,
    pub resource_rejected_candidate_ids: Vec<StableId>,
    pub evaluation_policy_digest: Digest32,
    pub ndu_evaluation_digest: Digest32,
    pub ndu_binding_digest: Digest32,
    pub evaluation_disposition: PlanningEvaluationDispositionV1,
    pub chosen_candidate_id: Option<StableId>,
    pub chosen_plan_digest: Option<Digest32>,
    pub uncertainty_digest: Digest32,
    pub expires_at_micros: u64,
    pub search_disclosure: SearchDisclosureV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GrantRequestV1 {
    pub operation_id: StableId,
    pub candidate_id: StableId,
    pub plan_digest: Digest32,
    pub final_payload_digest: Digest32,
    pub objective_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub expires_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct GrantRequestSetV1 {
    pub plan_receipt_digest: Digest32,
    pub requests: Vec<GrantRequestV1>,
    pub request_set_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PlannerError {
    EmptyDigest(&'static str),
    InvalidTime(&'static str),
    LimitExceeded(&'static str),
    DuplicateOwner(String),
    DuplicateCandidate(String),
    DuplicateResourceAxis(String),
    MixedObjective,
    MixedBodyGeneration,
    MixedConfiguration,
    FutureOwnerSummary(String),
    IncompleteSnapshot,
    SnapshotExpired,
    UnknownCandidateOwner { candidate: String, owner: String },
    InvalidResourceReservation(String),
    MissingResourceAxis { candidate: String, axis: String },
    UnknownResourceAxis { candidate: String, axis: String },
    AbstainUnavailable,
    EvaluationBindingMismatch,
    EvaluationCandidateSetMismatch,
    EvaluationDispositionMismatch,
    NoAdvisoryChoice,
    PreparedPlanMismatch,
    Arithmetic,
}

impl fmt::Display for PlannerError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::EmptyDigest(field) => write!(formatter, "empty planner digest: {field}"),
            Self::InvalidTime(field) => write!(formatter, "invalid planner time: {field}"),
            Self::LimitExceeded(field) => write!(formatter, "planner limit exceeded: {field}"),
            Self::DuplicateOwner(owner) => write!(formatter, "duplicate owner summary: {owner}"),
            Self::DuplicateCandidate(candidate) => {
                write!(formatter, "duplicate plan candidate: {candidate}")
            }
            Self::DuplicateResourceAxis(axis) => {
                write!(formatter, "duplicate planner resource axis: {axis}")
            }
            Self::MixedObjective => formatter.write_str("planner inputs bind different objectives"),
            Self::MixedBodyGeneration => {
                formatter.write_str("planner inputs bind different body generations")
            }
            Self::MixedConfiguration => {
                formatter.write_str("planner inputs bind different configurations")
            }
            Self::FutureOwnerSummary(owner) => {
                write!(formatter, "owner summary is from the future: {owner}")
            }
            Self::IncompleteSnapshot => formatter.write_str(
                "required owner snapshot contains missing, stale or unavailable summaries",
            ),
            Self::SnapshotExpired => formatter.write_str("global state snapshot is expired"),
            Self::UnknownCandidateOwner { candidate, owner } => write!(
                formatter,
                "candidate {candidate} requires unknown or unready owner {owner}"
            ),
            Self::InvalidResourceReservation(axis) => {
                write!(
                    formatter,
                    "invalid essential resource reservation for {axis}"
                )
            }
            Self::MissingResourceAxis { candidate, axis } => {
                write!(
                    formatter,
                    "candidate {candidate} is missing resource axis {axis}"
                )
            }
            Self::UnknownResourceAxis { candidate, axis } => write!(
                formatter,
                "candidate {candidate} has unregistered resource axis {axis}"
            ),
            Self::AbstainUnavailable => {
                formatter.write_str("abstain must be present and feasible after resource floors")
            }
            Self::EvaluationBindingMismatch => {
                formatter.write_str("NDU evaluation binding digest mismatch")
            }
            Self::EvaluationCandidateSetMismatch => formatter.write_str(
                "NDU evaluated/rejected candidate union differs from the prepared candidate set",
            ),
            Self::EvaluationDispositionMismatch => {
                formatter.write_str("NDU advisory candidate conflicts with its disposition")
            }
            Self::NoAdvisoryChoice => {
                formatter.write_str("plan has no unique advisory candidate for grant request")
            }
            Self::PreparedPlanMismatch => {
                formatter.write_str("prepared plan no longer matches current snapshot or payload")
            }
            Self::Arithmetic => formatter.write_str("planner arithmetic failed"),
        }
    }
}

impl StdError for PlannerError {}

pub fn collect_snapshot(
    mut request: SnapshotRequestV1,
    mut owner_summaries: Vec<OwnerSummaryV1>,
) -> Result<GlobalStateSnapshotV1, PlannerError> {
    require_digest(request.objective_digest, "objective")?;
    require_digest(request.configuration_digest, "configuration")?;
    require_digest(request.revocation_frontier_digest, "revocation frontier")?;
    if request.maximum_owner_age_micros == 0 {
        return Err(PlannerError::InvalidTime("maximum owner age"));
    }
    if request.expires_at_micros <= request.collected_at_micros {
        return Err(PlannerError::InvalidTime("snapshot expiry"));
    }
    if request.required_owner_ids.len() > MAX_OWNERS || owner_summaries.len() > MAX_OWNERS {
        return Err(PlannerError::LimitExceeded("owners"));
    }

    request.required_owner_ids.sort();
    reject_duplicate_ids(&request.required_owner_ids, PlannerError::DuplicateOwner)?;
    owner_summaries.sort_by(|left, right| left.owner_id.cmp(&right.owner_id));
    for window in owner_summaries.windows(2) {
        if window[0].owner_id == window[1].owner_id {
            return Err(PlannerError::DuplicateOwner(window[0].owner_id.to_string()));
        }
    }

    let mut stale_owner_ids = Vec::new();
    let mut unavailable_owner_ids = Vec::new();
    let mut expiry = request.expires_at_micros;
    for summary in &owner_summaries {
        require_digest(summary.configuration_digest, "owner configuration")?;
        require_digest(summary.source_frontier_digest, "owner source frontier")?;
        require_digest(summary.support_digest, "owner support")?;
        if summary.objective_digest != request.objective_digest {
            return Err(PlannerError::MixedObjective);
        }
        if summary.body_generation != request.body_generation {
            return Err(PlannerError::MixedBodyGeneration);
        }
        if summary.configuration_digest != request.configuration_digest {
            return Err(PlannerError::MixedConfiguration);
        }
        if summary.observed_at_micros > request.collected_at_micros {
            return Err(PlannerError::FutureOwnerSummary(
                summary.owner_id.to_string(),
            ));
        }
        let age = request
            .collected_at_micros
            .checked_sub(summary.observed_at_micros)
            .ok_or(PlannerError::Arithmetic)?;
        if summary.expires_at_micros <= request.collected_at_micros
            || age > request.maximum_owner_age_micros
        {
            stale_owner_ids.push(summary.owner_id.clone());
        }
        if summary.readiness != OwnerReadinessV1::Ready {
            unavailable_owner_ids.push(summary.owner_id.clone());
        }
        expiry = expiry.min(summary.expires_at_micros);
    }

    let present: BTreeSet<_> = owner_summaries
        .iter()
        .map(|summary| summary.owner_id.clone())
        .collect();
    let missing_owner_ids: Vec<_> = request
        .required_owner_ids
        .iter()
        .filter(|owner| !present.contains(*owner))
        .cloned()
        .collect();
    stale_owner_ids.sort();
    stale_owner_ids.dedup();
    unavailable_owner_ids.sort();
    unavailable_owner_ids.dedup();

    let mut snapshot = GlobalStateSnapshotV1 {
        objective_digest: request.objective_digest,
        body_generation: request.body_generation,
        configuration_digest: request.configuration_digest,
        revocation_frontier_digest: request.revocation_frontier_digest,
        collected_at_micros: request.collected_at_micros,
        expires_at_micros: expiry,
        owner_summaries,
        missing_owner_ids,
        stale_owner_ids,
        unavailable_owner_ids,
        snapshot_digest: Digest32::ZERO,
    };
    snapshot.snapshot_digest = digest_snapshot(&snapshot);
    Ok(snapshot)
}

pub fn prepare_plan(
    snapshot: &GlobalStateSnapshotV1,
    mut request: PlanningRequestV1,
) -> Result<PreparedPlanInputV1, PlannerError> {
    validate_snapshot_for_planning(snapshot, request.now_micros)?;
    if request.deadline_micros <= request.now_micros {
        return Err(PlannerError::InvalidTime("planning deadline"));
    }
    if request.candidates.is_empty() || request.candidates.len() > MAX_CANDIDATES {
        return Err(PlannerError::LimitExceeded("plan candidates"));
    }
    if request.resource_reservations.len() > MAX_RESOURCE_RESERVATIONS {
        return Err(PlannerError::LimitExceeded("resource reservations"));
    }

    request
        .candidates
        .sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    validate_candidates(snapshot, &mut request.candidates)?;
    request
        .resource_reservations
        .sort_by(|left, right| left.axis.cmp(&right.axis));
    validate_reservations(&request.resource_reservations)?;

    let source_candidate_set_digest = digest_candidates(&request.candidates);
    let reservation_map: BTreeMap<_, _> = request
        .resource_reservations
        .iter()
        .map(|reservation| {
            let available = reservation
                .endowment
                .checked_sub(reservation.essential_floor)
                .map_err(|_| PlannerError::Arithmetic)?;
            Ok((reservation.axis.clone(), available))
        })
        .collect::<Result<_, PlannerError>>()?;

    let mut feasible_candidates = Vec::new();
    let mut resource_rejected_candidate_ids = Vec::new();
    for candidate in request.candidates {
        if candidate_within_resources(&candidate, &reservation_map)? {
            feasible_candidates.push(candidate);
        } else {
            resource_rejected_candidate_ids.push(candidate.candidate_id);
        }
    }
    let abstain = stable_id("abstain")?;
    if !feasible_candidates
        .iter()
        .any(|candidate| candidate.candidate_id == abstain)
    {
        return Err(PlannerError::AbstainUnavailable);
    }
    let candidate_set_digest = digest_candidates(&feasible_candidates);
    let expires_at_micros = snapshot.expires_at_micros.min(request.deadline_micros);
    let mut prepared = PreparedPlanInputV1 {
        plan_id: request.plan_id,
        objective_digest: snapshot.objective_digest,
        body_generation: snapshot.body_generation,
        configuration_digest: snapshot.configuration_digest,
        revocation_frontier_digest: snapshot.revocation_frontier_digest,
        snapshot_digest: snapshot.snapshot_digest,
        source_candidate_set_digest,
        candidate_set_digest,
        feasible_candidates,
        resource_rejected_candidate_ids,
        expires_at_micros,
        prepared_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    prepared.prepared_digest = digest_prepared_plan(&prepared);
    Ok(prepared)
}

pub fn bind_ndu_plan_evaluation_v1(
    mut input: NduPlanEvaluationInputV1,
) -> Result<NduPlanEvaluationV1, PlannerError> {
    require_digest(input.objective_digest, "NDU objective")?;
    require_digest(input.evaluation_policy_digest, "NDU policy")?;
    require_digest(input.evaluation_digest, "NDU evaluation")?;
    require_digest(input.uncertainty_digest, "NDU uncertainty")?;
    input.evaluated_candidate_ids.sort();
    input.rejected_candidate_ids.sort();
    input.pareto_candidate_ids.sort();
    reject_duplicate_ids(
        &input.evaluated_candidate_ids,
        PlannerError::DuplicateCandidate,
    )?;
    reject_duplicate_ids(
        &input.rejected_candidate_ids,
        PlannerError::DuplicateCandidate,
    )?;
    reject_duplicate_ids(
        &input.pareto_candidate_ids,
        PlannerError::DuplicateCandidate,
    )?;
    let evaluated: BTreeSet<_> = input.evaluated_candidate_ids.iter().cloned().collect();
    let rejected: BTreeSet<_> = input.rejected_candidate_ids.iter().cloned().collect();
    if !evaluated.is_disjoint(&rejected)
        || input
            .pareto_candidate_ids
            .iter()
            .any(|candidate| !evaluated.contains(candidate))
    {
        return Err(PlannerError::EvaluationCandidateSetMismatch);
    }
    validate_evaluation_disposition(
        input.disposition,
        input.advisory_candidate_id.as_ref(),
        &input.pareto_candidate_ids,
    )?;

    let mut evaluation = NduPlanEvaluationV1 {
        objective_digest: input.objective_digest,
        body_generation: input.body_generation,
        evaluation_policy_digest: input.evaluation_policy_digest,
        evaluation_digest: input.evaluation_digest,
        evaluated_candidate_ids: input.evaluated_candidate_ids,
        rejected_candidate_ids: input.rejected_candidate_ids,
        pareto_candidate_ids: input.pareto_candidate_ids,
        advisory_candidate_id: input.advisory_candidate_id,
        uncertainty_digest: input.uncertainty_digest,
        disposition: input.disposition,
        binding_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    evaluation.binding_digest = digest_ndu_evaluation(&evaluation);
    Ok(evaluation)
}

pub fn finalize_plan(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    evaluation: &NduPlanEvaluationV1,
    now_micros: u64,
) -> Result<FeasiblePlanReceiptV1, PlannerError> {
    validate_snapshot_for_planning(snapshot, now_micros)?;
    if now_micros >= prepared.expires_at_micros {
        return Err(PlannerError::SnapshotExpired);
    }
    if prepared.prepared_digest != digest_prepared_plan(prepared)
        || prepared.authority.grants_any()
        || prepared.snapshot_digest != snapshot.snapshot_digest
        || prepared.objective_digest != snapshot.objective_digest
        || prepared.body_generation != snapshot.body_generation
        || prepared.configuration_digest != snapshot.configuration_digest
        || prepared.revocation_frontier_digest != snapshot.revocation_frontier_digest
    {
        return Err(PlannerError::PreparedPlanMismatch);
    }
    if evaluation.binding_digest != digest_ndu_evaluation(evaluation)
        || evaluation.authority.grants_any()
    {
        return Err(PlannerError::EvaluationBindingMismatch);
    }
    if evaluation.objective_digest != prepared.objective_digest {
        return Err(PlannerError::MixedObjective);
    }
    if evaluation.body_generation != prepared.body_generation {
        return Err(PlannerError::MixedBodyGeneration);
    }
    validate_evaluation_candidate_set(prepared, evaluation)?;
    validate_evaluation_disposition(
        evaluation.disposition,
        evaluation.advisory_candidate_id.as_ref(),
        &evaluation.pareto_candidate_ids,
    )?;

    let candidate_map: BTreeMap<_, _> = prepared
        .feasible_candidates
        .iter()
        .map(|candidate| (candidate.candidate_id.clone(), candidate))
        .collect();
    let chosen_candidate_id = evaluation.advisory_candidate_id.clone();
    let chosen_plan_digest = chosen_candidate_id
        .as_ref()
        .and_then(|candidate_id| candidate_map.get(candidate_id))
        .map(|candidate| candidate.plan_digest);
    if chosen_candidate_id.is_some() != chosen_plan_digest.is_some() {
        return Err(PlannerError::EvaluationCandidateSetMismatch);
    }

    let search_disclosure = match evaluation.disposition {
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation => {
            SearchDisclosureV1::UniqueParetoOnBoundedSet
        }
        PlanningEvaluationDispositionV1::ScalarizedRecommendation => {
            SearchDisclosureV1::ScalarizedBoundedSet
        }
        PlanningEvaluationDispositionV1::ParetoSetRequiresSlowPath
        | PlanningEvaluationDispositionV1::ScalarizationTieRequiresSlowPath => {
            SearchDisclosureV1::UnresolvedParetoFrontier
        }
        PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain => {
            SearchDisclosureV1::BoundedCandidateSetOnly
        }
    };
    let mut receipt = FeasiblePlanReceiptV1 {
        plan_id: prepared.plan_id.clone(),
        objective_digest: prepared.objective_digest,
        body_generation: prepared.body_generation,
        configuration_digest: prepared.configuration_digest,
        revocation_frontier_digest: prepared.revocation_frontier_digest,
        snapshot_digest: prepared.snapshot_digest,
        source_candidate_set_digest: prepared.source_candidate_set_digest,
        candidate_set_digest: prepared.candidate_set_digest,
        resource_rejected_candidate_ids: prepared.resource_rejected_candidate_ids.clone(),
        evaluation_policy_digest: evaluation.evaluation_policy_digest,
        ndu_evaluation_digest: evaluation.evaluation_digest,
        ndu_binding_digest: evaluation.binding_digest,
        evaluation_disposition: evaluation.disposition,
        chosen_candidate_id,
        chosen_plan_digest,
        uncertainty_digest: evaluation.uncertainty_digest,
        expires_at_micros: prepared.expires_at_micros,
        search_disclosure,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_plan_receipt(&receipt);
    Ok(receipt)
}

pub fn request_execution_grants(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    receipt: &FeasiblePlanReceiptV1,
    now_micros: u64,
) -> Result<GrantRequestSetV1, PlannerError> {
    if receipt.receipt_digest != digest_plan_receipt(receipt)
        || receipt.authority.grants_any()
        || prepared.prepared_digest != digest_prepared_plan(prepared)
        || prepared.authority.grants_any()
        || receipt.snapshot_digest != snapshot.snapshot_digest
        || prepared.snapshot_digest != snapshot.snapshot_digest
        || receipt.candidate_set_digest != prepared.candidate_set_digest
        || receipt.objective_digest != snapshot.objective_digest
        || receipt.body_generation != snapshot.body_generation
        || receipt.configuration_digest != snapshot.configuration_digest
        || receipt.revocation_frontier_digest != snapshot.revocation_frontier_digest
    {
        return Err(PlannerError::PreparedPlanMismatch);
    }
    if now_micros >= receipt.expires_at_micros || now_micros >= snapshot.expires_at_micros {
        return Err(PlannerError::SnapshotExpired);
    }
    let chosen_candidate_id = receipt
        .chosen_candidate_id
        .as_ref()
        .ok_or(PlannerError::NoAdvisoryChoice)?;
    let chosen_plan_digest = receipt
        .chosen_plan_digest
        .ok_or(PlannerError::PreparedPlanMismatch)?;
    let candidate = prepared
        .feasible_candidates
        .iter()
        .find(|candidate| {
            &candidate.candidate_id == chosen_candidate_id
                && candidate.plan_digest == chosen_plan_digest
        })
        .ok_or(PlannerError::PreparedPlanMismatch)?;

    let requests: Vec<_> = candidate
        .final_payload_digests
        .iter()
        .map(|payload_digest| GrantRequestV1 {
            operation_id: candidate.operation_id.clone(),
            candidate_id: candidate.candidate_id.clone(),
            plan_digest: candidate.plan_digest,
            final_payload_digest: *payload_digest,
            objective_digest: receipt.objective_digest,
            snapshot_digest: receipt.snapshot_digest,
            revocation_frontier_digest: receipt.revocation_frontier_digest,
            expires_at_micros: receipt.expires_at_micros,
        })
        .collect();
    let request_set_digest = digest_grant_requests(receipt.receipt_digest, &requests);
    Ok(GrantRequestSetV1 {
        plan_receipt_digest: receipt.receipt_digest,
        requests,
        request_set_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_snapshot_for_planning(
    snapshot: &GlobalStateSnapshotV1,
    now_micros: u64,
) -> Result<(), PlannerError> {
    if snapshot.snapshot_digest != digest_snapshot(snapshot) {
        return Err(PlannerError::PreparedPlanMismatch);
    }
    if now_micros >= snapshot.expires_at_micros {
        return Err(PlannerError::SnapshotExpired);
    }
    if !snapshot.missing_owner_ids.is_empty()
        || !snapshot.stale_owner_ids.is_empty()
        || !snapshot.unavailable_owner_ids.is_empty()
    {
        return Err(PlannerError::IncompleteSnapshot);
    }
    Ok(())
}

fn validate_candidates(
    snapshot: &GlobalStateSnapshotV1,
    candidates: &mut [PlanCandidateV1],
) -> Result<(), PlannerError> {
    let ready_owners: BTreeSet<_> = snapshot
        .owner_summaries
        .iter()
        .filter(|summary| summary.readiness == OwnerReadinessV1::Ready)
        .map(|summary| summary.owner_id.clone())
        .collect();
    let mut candidate_ids = BTreeSet::new();
    for candidate in candidates {
        require_digest(candidate.plan_digest, "candidate plan")?;
        if !candidate_ids.insert(candidate.candidate_id.clone()) {
            return Err(PlannerError::DuplicateCandidate(
                candidate.candidate_id.to_string(),
            ));
        }
        if candidate.required_owner_ids.len() > MAX_REQUIRED_OWNERS_PER_CANDIDATE {
            return Err(PlannerError::LimitExceeded("candidate required owners"));
        }
        if candidate.final_payload_digests.len() > MAX_PAYLOADS_PER_CANDIDATE {
            return Err(PlannerError::LimitExceeded("candidate payloads"));
        }
        if candidate
            .final_payload_digests
            .iter()
            .any(|digest| digest.is_zero())
        {
            return Err(PlannerError::EmptyDigest("candidate final payload"));
        }
        candidate.required_owner_ids.sort();
        reject_duplicate_ids(&candidate.required_owner_ids, PlannerError::DuplicateOwner)?;
        candidate.final_payload_digests.sort();
        candidate.final_payload_digests.dedup();
        candidate.resource_costs.sort();
        for window in candidate.resource_costs.windows(2) {
            if window[0].axis == window[1].axis {
                return Err(PlannerError::DuplicateResourceAxis(
                    window[0].axis.to_string(),
                ));
            }
        }
        if candidate
            .resource_costs
            .iter()
            .any(|value| value.value < FixedQ32::ZERO)
        {
            return Err(PlannerError::InvalidResourceReservation(
                candidate.candidate_id.to_string(),
            ));
        }
        for owner in &candidate.required_owner_ids {
            if !ready_owners.contains(owner) {
                return Err(PlannerError::UnknownCandidateOwner {
                    candidate: candidate.candidate_id.to_string(),
                    owner: owner.to_string(),
                });
            }
        }
    }
    Ok(())
}

fn validate_reservations(reservations: &[ResourceReservationV1]) -> Result<(), PlannerError> {
    for window in reservations.windows(2) {
        if window[0].axis == window[1].axis {
            return Err(PlannerError::DuplicateResourceAxis(
                window[0].axis.to_string(),
            ));
        }
    }
    for reservation in reservations {
        if reservation.endowment < FixedQ32::ZERO
            || reservation.essential_floor < FixedQ32::ZERO
            || reservation.essential_floor > reservation.endowment
        {
            return Err(PlannerError::InvalidResourceReservation(
                reservation.axis.to_string(),
            ));
        }
    }
    Ok(())
}

fn candidate_within_resources(
    candidate: &PlanCandidateV1,
    available: &BTreeMap<StableId, FixedQ32>,
) -> Result<bool, PlannerError> {
    let costs: BTreeMap<_, _> = candidate
        .resource_costs
        .iter()
        .map(|value| (value.axis.clone(), value.value))
        .collect();
    for axis in available.keys() {
        if !costs.contains_key(axis) {
            return Err(PlannerError::MissingResourceAxis {
                candidate: candidate.candidate_id.to_string(),
                axis: axis.to_string(),
            });
        }
    }
    for axis in costs.keys() {
        if !available.contains_key(axis) {
            return Err(PlannerError::UnknownResourceAxis {
                candidate: candidate.candidate_id.to_string(),
                axis: axis.to_string(),
            });
        }
    }
    Ok(costs
        .iter()
        .all(|(axis, cost)| available.get(axis).is_some_and(|limit| cost <= limit)))
}

fn validate_evaluation_candidate_set(
    prepared: &PreparedPlanInputV1,
    evaluation: &NduPlanEvaluationV1,
) -> Result<(), PlannerError> {
    let expected: BTreeSet<_> = prepared
        .feasible_candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect();
    let mut actual: BTreeSet<_> = evaluation.evaluated_candidate_ids.iter().cloned().collect();
    actual.extend(evaluation.rejected_candidate_ids.iter().cloned());
    if expected != actual {
        return Err(PlannerError::EvaluationCandidateSetMismatch);
    }
    Ok(())
}

fn validate_evaluation_disposition(
    disposition: PlanningEvaluationDispositionV1,
    advisory: Option<&StableId>,
    pareto: &[StableId],
) -> Result<(), PlannerError> {
    let abstain = stable_id("abstain")?;
    match disposition {
        PlanningEvaluationDispositionV1::InfeasibleExplicitAbstain
            if advisory == Some(&abstain) && pareto == [abstain] =>
        {
            Ok(())
        }
        PlanningEvaluationDispositionV1::UniqueParetoRecommendation
            if pareto.len() == 1 && advisory == pareto.first() =>
        {
            Ok(())
        }
        PlanningEvaluationDispositionV1::ScalarizedRecommendation
            if advisory.is_some() && advisory.is_some_and(|value| pareto.contains(value)) =>
        {
            Ok(())
        }
        PlanningEvaluationDispositionV1::ParetoSetRequiresSlowPath
        | PlanningEvaluationDispositionV1::ScalarizationTieRequiresSlowPath
            if advisory.is_none() && !pareto.is_empty() =>
        {
            Ok(())
        }
        _ => Err(PlannerError::EvaluationDispositionMismatch),
    }
}

fn reject_duplicate_ids<F>(values: &[StableId], error: F) -> Result<(), PlannerError>
where
    F: Fn(String) -> PlannerError,
{
    for window in values.windows(2) {
        if window[0] == window[1] {
            return Err(error(window[0].to_string()));
        }
    }
    Ok(())
}

fn require_digest(value: Digest32, field: &'static str) -> Result<(), PlannerError> {
    if value.is_zero() {
        return Err(PlannerError::EmptyDigest(field));
    }
    Ok(())
}

fn stable_id(value: &str) -> Result<StableId, PlannerError> {
    StableId::new(value).map_err(|_| PlannerError::Arithmetic)
}

fn digest_snapshot(snapshot: &GlobalStateSnapshotV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.global-state-snapshot.v1");
    push_digest(&mut bytes, snapshot.objective_digest);
    push_u64(&mut bytes, snapshot.body_generation.get());
    push_digest(&mut bytes, snapshot.configuration_digest);
    push_digest(&mut bytes, snapshot.revocation_frontier_digest);
    push_u64(&mut bytes, snapshot.collected_at_micros);
    push_u64(&mut bytes, snapshot.expires_at_micros);
    push_len(&mut bytes, snapshot.owner_summaries.len());
    for summary in &snapshot.owner_summaries {
        push_id(&mut bytes, &summary.owner_id);
        push_u64(&mut bytes, summary.revision.get());
        push_digest(&mut bytes, summary.objective_digest);
        push_u64(&mut bytes, summary.body_generation.get());
        push_digest(&mut bytes, summary.configuration_digest);
        push_u64(&mut bytes, summary.observed_at_micros);
        push_u64(&mut bytes, summary.expires_at_micros);
        bytes.push(summary.readiness.tag());
        push_digest(&mut bytes, summary.source_frontier_digest);
        push_digest(&mut bytes, summary.support_digest);
    }
    push_ids(&mut bytes, &snapshot.missing_owner_ids);
    push_ids(&mut bytes, &snapshot.stale_owner_ids);
    push_ids(&mut bytes, &snapshot.unavailable_owner_ids);
    Digest32::of_bytes(&bytes)
}

fn digest_candidates(candidates: &[PlanCandidateV1]) -> Digest32 {
    let mut normalized = candidates.to_vec();
    normalized.sort_by(|left, right| left.candidate_id.cmp(&right.candidate_id));
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.plan-candidate-set.v1");
    push_len(&mut bytes, normalized.len());
    for mut candidate in normalized {
        push_id(&mut bytes, &candidate.candidate_id);
        push_id(&mut bytes, &candidate.operation_id);
        push_digest(&mut bytes, candidate.plan_digest);
        candidate.required_owner_ids.sort();
        push_ids(&mut bytes, &candidate.required_owner_ids);
        candidate.final_payload_digests.sort();
        push_len(&mut bytes, candidate.final_payload_digests.len());
        for payload in candidate.final_payload_digests {
            push_digest(&mut bytes, payload);
        }
        candidate.resource_costs.sort();
        push_axis_values(&mut bytes, &candidate.resource_costs);
    }
    Digest32::of_bytes(&bytes)
}

fn digest_prepared_plan(prepared: &PreparedPlanInputV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.prepared-plan.v1");
    push_id(&mut bytes, &prepared.plan_id);
    push_digest(&mut bytes, prepared.objective_digest);
    push_u64(&mut bytes, prepared.body_generation.get());
    push_digest(&mut bytes, prepared.configuration_digest);
    push_digest(&mut bytes, prepared.revocation_frontier_digest);
    push_digest(&mut bytes, prepared.snapshot_digest);
    push_digest(&mut bytes, prepared.source_candidate_set_digest);
    push_digest(&mut bytes, prepared.candidate_set_digest);
    push_ids(&mut bytes, &prepared.resource_rejected_candidate_ids);
    push_u64(&mut bytes, prepared.expires_at_micros);
    Digest32::of_bytes(&bytes)
}

fn digest_ndu_evaluation(evaluation: &NduPlanEvaluationV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.ndu-plan-evaluation-binding.v1");
    push_digest(&mut bytes, evaluation.objective_digest);
    push_u64(&mut bytes, evaluation.body_generation.get());
    push_digest(&mut bytes, evaluation.evaluation_policy_digest);
    push_digest(&mut bytes, evaluation.evaluation_digest);
    push_ids(&mut bytes, &evaluation.evaluated_candidate_ids);
    push_ids(&mut bytes, &evaluation.rejected_candidate_ids);
    push_ids(&mut bytes, &evaluation.pareto_candidate_ids);
    push_optional_id(&mut bytes, evaluation.advisory_candidate_id.as_ref());
    push_digest(&mut bytes, evaluation.uncertainty_digest);
    bytes.push(evaluation.disposition.tag());
    Digest32::of_bytes(&bytes)
}

fn digest_plan_receipt(receipt: &FeasiblePlanReceiptV1) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.feasible-plan-receipt.v1");
    push_id(&mut bytes, &receipt.plan_id);
    push_digest(&mut bytes, receipt.objective_digest);
    push_u64(&mut bytes, receipt.body_generation.get());
    push_digest(&mut bytes, receipt.configuration_digest);
    push_digest(&mut bytes, receipt.revocation_frontier_digest);
    push_digest(&mut bytes, receipt.snapshot_digest);
    push_digest(&mut bytes, receipt.source_candidate_set_digest);
    push_digest(&mut bytes, receipt.candidate_set_digest);
    push_ids(&mut bytes, &receipt.resource_rejected_candidate_ids);
    push_digest(&mut bytes, receipt.evaluation_policy_digest);
    push_digest(&mut bytes, receipt.ndu_evaluation_digest);
    push_digest(&mut bytes, receipt.ndu_binding_digest);
    bytes.push(receipt.evaluation_disposition.tag());
    push_optional_id(&mut bytes, receipt.chosen_candidate_id.as_ref());
    push_optional_digest(&mut bytes, receipt.chosen_plan_digest);
    push_digest(&mut bytes, receipt.uncertainty_digest);
    push_u64(&mut bytes, receipt.expires_at_micros);
    bytes.push(receipt.search_disclosure.tag());
    Digest32::of_bytes(&bytes)
}

fn digest_grant_requests(plan_receipt_digest: Digest32, requests: &[GrantRequestV1]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.control.grant-request-set.v1");
    push_digest(&mut bytes, plan_receipt_digest);
    push_len(&mut bytes, requests.len());
    for request in requests {
        push_id(&mut bytes, &request.operation_id);
        push_id(&mut bytes, &request.candidate_id);
        push_digest(&mut bytes, request.plan_digest);
        push_digest(&mut bytes, request.final_payload_digest);
        push_digest(&mut bytes, request.objective_digest);
        push_digest(&mut bytes, request.snapshot_digest);
        push_digest(&mut bytes, request.revocation_frontier_digest);
        push_u64(&mut bytes, request.expires_at_micros);
    }
    Digest32::of_bytes(&bytes)
}

fn push_axis_values(bytes: &mut Vec<u8>, values: &[PlannerAxisValueV1]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, &value.axis);
        bytes.extend_from_slice(&value.value.raw().to_be_bytes());
    }
}

fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

fn push_optional_id(bytes: &mut Vec<u8>, value: Option<&StableId>) {
    if let Some(value) = value {
        bytes.push(1);
        push_id(bytes, value);
    } else {
        bytes.push(0);
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    if let Some(value) = value {
        bytes.push(1);
        push_digest(bytes, value);
    } else {
        bytes.push(0);
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u32::try_from(value).unwrap_or(u32::MAX).to_be_bytes());
}

#[cfg(test)]
#[path = "planner_tests.rs"]
mod tests;
