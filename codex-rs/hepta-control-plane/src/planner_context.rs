//! Request-local planning over a completed, authenticated cognitive read.
//! The host measures records/bytes itself and enforces its existing scope and
//! generation fence. These observations say nothing about model quality,
//! memory capacity, future utility, or permission to execute effects.

use codex_hepta_ndu::AxisDirection;
use codex_hepta_ndu::AxisLimit;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::ContributionSet;
use codex_hepta_ndu::FeasibilityPosture;
use codex_hepta_ndu::RequiredOrganSet;
use codex_hepta_ndu::UtilityContribution;
use codex_hepta_ndu::UtilityProfile;
use codex_hepta_ndu::legacy_evaluation_policy;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

use crate::AuthenticatedOwnerPortV1;
use crate::EvaluatedPlanV1;
use crate::GlobalPlanningErrorV1;
use crate::GlobalPlanningRequestV1;
use crate::GlobalStateSnapshotV1;
use crate::NduPlanningError;
use crate::NduPlanningInputV1;
use crate::NduPlanningPortV1;
use crate::OwnerPortErrorV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::canonical_ndu_planning_policy_digest;
use crate::canonical_resource_profile_digest;
use crate::evaluate_prepared_plan_with_ndu;
use crate::plan_global_v1;

/// Host-only measurements after verifying the canonical read and local scope.
/// `encoded_context` excludes planning metadata to avoid self-referential
/// digests. The host must also bound the final response envelope independently.
pub struct ObservedContextV1<'a> {
    pub owner_id: StableId,
    pub body_generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub read_digest: Digest32,
    pub verified_item_count: u32,
    pub encoded_context: &'a [u8],
    pub maximum_context_bytes: u32,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedContextPlanV1 {
    pub read_allowed: bool,
    pub context_digest: Digest32,
    pub evaluation: EvaluatedPlanV1,
}

struct ObservedContextOwnerPortV1 {
    summary: OwnerSummaryV1,
}

impl AuthenticatedOwnerPortV1 for ObservedContextOwnerPortV1 {
    fn owner_id(&self) -> &StableId {
        &self.summary.owner_id
    }

    fn snapshot_summary(
        &self,
        _request: &SnapshotRequestV1,
    ) -> Result<OwnerSummaryV1, OwnerPortErrorV1> {
        Ok(self.summary.clone())
    }
}

struct ObservedContextNduPortV1 {
    input: NduPlanningInputV1,
    read_id: StableId,
    owner_id: StableId,
    count_axis: StableId,
    bytes_axis: StableId,
    objective_digest: Digest32,
    body_generation: Generation,
    verified_items: FixedQ32,
    encoded_bytes: FixedQ32,
    support_digest: Digest32,
}

impl NduPlanningPortV1 for ObservedContextNduPortV1 {
    fn evaluate(
        &self,
        snapshot: &GlobalStateSnapshotV1,
        prepared: &PreparedPlanInputV1,
        now_micros: u64,
    ) -> Result<EvaluatedPlanV1, NduPlanningError> {
        let mut input = self.input.clone();
        input.contributions.contributions = prepared
            .feasible_candidates()
            .iter()
            .map(|candidate| {
                let is_read = candidate.candidate_id == self.read_id;
                UtilityContribution {
                    candidate_id: candidate.candidate_id.clone(),
                    organ_id: self.owner_id.clone(),
                    objective_digest: self.objective_digest,
                    generation: self.body_generation,
                    feasibility: FeasibilityPosture::Feasible,
                    utility: vec![AxisValue {
                        axis: self.count_axis.clone(),
                        value: if is_read {
                            self.verified_items
                        } else {
                            FixedQ32::ZERO
                        },
                    }],
                    risk: vec![],
                    resource: vec![AxisValue {
                        axis: self.bytes_axis.clone(),
                        value: if is_read {
                            self.encoded_bytes
                        } else {
                            FixedQ32::ZERO
                        },
                    }],
                    uncertainty: vec![AxisValue {
                        axis: self.count_axis.clone(),
                        value: FixedQ32::ZERO,
                    }],
                    support_digest: self.support_digest,
                }
            })
            .collect();
        evaluate_prepared_plan_with_ndu(snapshot, prepared, input, now_micros)
    }
}

/// Compute a two-candidate read/abstain plan using the same authenticated global
/// composition path used by multi-owner control planning. Utility is the
/// observed count of verified records; resource cost is their encoded delivery
/// size. Zero records, ties, and exceeded budgets abstain.
pub fn plan_observed_context(
    observed: ObservedContextV1<'_>,
) -> Result<ObservedContextPlanV1, NduPlanningError> {
    use NduPlanningError as E;
    if observed.verified_item_count > 4
        || observed.encoded_context.len() > 24 * 1024
        || observed.maximum_context_bytes > 24 * 1024
    {
        return Err(E::Planner(PlannerError::LimitExceeded("observed_context")));
    }
    let id = |name: &str| StableId::new(name).map_err(|_| E::Planner(PlannerError::Arithmetic));
    let count_axis = id("verified-context-items")?;
    let bytes_axis = id("context-bytes")?;
    let read_id = id("read-context")?;
    let context_digest = Digest32::of_bytes(observed.encoded_context);
    let q32 = |value: u32| FixedQ32::from_raw(i64::from(value) << 32);
    let budget = q32(observed.maximum_context_bytes);
    let bytes = q32(observed.encoded_context.len() as u32);
    let verified_items = q32(observed.verified_item_count);
    let mut objective = b"hepta.control.deliver-verified-context.v1\0".to_vec();
    objective.extend_from_slice(&observed.maximum_context_bytes.to_be_bytes());
    let objective_digest = Digest32::of_bytes(&objective);
    let profile = UtilityProfile {
        profile_id: id("verified-context-delivery-v1")?,
        dimensions: vec![(count_axis.clone(), AxisDirection::Maximize)],
        risk_ceilings: vec![],
        resource_ceilings: vec![AxisLimit {
            axis: bytes_axis.clone(),
            maximum: budget,
        }],
        required_organs: RequiredOrganSet {
            organ_ids: vec![observed.owner_id.clone()],
        },
    };
    let input = NduPlanningInputV1 {
        policy: legacy_evaluation_policy(&profile).map_err(E::Ndu)?,
        profile,
        scalarization: None,
        contributions: ContributionSet {
            objective_digest,
            generation: observed.body_generation,
            contributions: vec![],
        },
    };
    let configuration_digest = canonical_ndu_planning_policy_digest(&input).map_err(E::Ndu)?;
    let mut fence = b"hepta.control.context-read-generation.v1\0".to_vec();
    fence.extend_from_slice(observed.owner_id.as_str().as_bytes());
    fence.extend_from_slice(&observed.body_generation.get().to_be_bytes());

    let snapshot_request = SnapshotRequestV1 {
        objective_digest,
        body_generation: observed.body_generation,
        configuration_digest,
        revocation_frontier_digest: Digest32::of_bytes(&fence),
        snapshot_policy_digest: Digest32::of_bytes(
            b"hepta.control.immutable-context-observation.v1",
        ),
        collected_at_micros: observed.observed_at_micros,
        maximum_owner_age_micros: 1,
        expires_at_micros: observed.expires_at_micros,
        required_owner_ids: vec![observed.owner_id.clone()],
    };
    let owner_port = ObservedContextOwnerPortV1 {
        summary: OwnerSummaryV1 {
            owner_id: observed.owner_id.clone(),
            revision: Revision::new(1).map_err(|_| E::Planner(PlannerError::Arithmetic))?,
            objective_digest,
            body_generation: observed.body_generation,
            configuration_digest,
            observed_at_micros: observed.observed_at_micros,
            expires_at_micros: observed.expires_at_micros,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: observed.source_snapshot_digest,
            support_digest: observed.read_digest,
        },
    };
    let candidates = [id("abstain")?, read_id.clone()]
        .into_iter()
        .map(|candidate_id| {
            let is_read = candidate_id == read_id;
            PlanCandidateV1 {
                operation_id: candidate_id.clone(),
                candidate_id,
                plan_digest: if is_read {
                    context_digest
                } else {
                    Digest32::of_bytes(b"hepta.control.context-abstain.v1")
                },
                required_owner_ids: vec![observed.owner_id.clone()],
                final_payload_digests: vec![],
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: bytes_axis.clone(),
                    value: if is_read { bytes } else { FixedQ32::ZERO },
                }],
            }
        })
        .collect();
    let resource_reservations = vec![ResourceReservationV1 {
        axis: bytes_axis.clone(),
        endowment: budget,
        essential_floor: FixedQ32::ZERO,
    }];
    let resource_profile_digest =
        canonical_resource_profile_digest(&resource_reservations).map_err(E::Planner)?;
    let planning_request = PlanningRequestV1 {
        plan_id: id("context-delivery")?,
        now_micros: observed.observed_at_micros,
        deadline_micros: observed.expires_at_micros,
        evaluation_policy_digest: configuration_digest,
        resource_profile_digest,
        candidates,
        resource_reservations,
    };
    let ndu_port = ObservedContextNduPortV1 {
        input,
        read_id: read_id.clone(),
        owner_id: observed.owner_id,
        count_axis,
        bytes_axis,
        objective_digest,
        body_generation: observed.body_generation,
        verified_items,
        encoded_bytes: bytes,
        support_digest: observed.read_digest,
    };
    let global = plan_global_v1(
        &[&owner_port],
        &ndu_port,
        GlobalPlanningRequestV1 {
            snapshot_request,
            planning_request,
            now_micros: observed.observed_at_micros,
        },
    )
    .map_err(map_global_error)?;
    debug_assert!(global.grant_requests.requests().is_empty());

    Ok(ObservedContextPlanV1 {
        read_allowed: global.evaluation.plan.chosen_candidate_id() == Some(&read_id),
        context_digest,
        evaluation: global.evaluation,
    })
}

fn map_global_error(error: GlobalPlanningErrorV1) -> NduPlanningError {
    match error {
        GlobalPlanningErrorV1::Planner(error) => NduPlanningError::Planner(error),
        GlobalPlanningErrorV1::Ndu(error) => error,
        GlobalPlanningErrorV1::TimeBindingMismatch => {
            NduPlanningError::Planner(PlannerError::InvalidTime("global planning clock"))
        }
        GlobalPlanningErrorV1::DuplicateOwnerPort(_)
        | GlobalPlanningErrorV1::MissingOwnerPort(_)
        | GlobalPlanningErrorV1::OwnerIdentityMismatch { .. }
        | GlobalPlanningErrorV1::OwnerPort { .. } => {
            NduPlanningError::Planner(PlannerError::IncompleteSnapshot)
        }
    }
}

#[cfg(test)]
#[path = "planner_context_tests.rs"]
mod tests;
