//! Request-local planning over a completed, authenticated cognitive read.
//! The host supplies canonical record bindings and enforces its existing scope
//! and generation fence. These observations say nothing about model quality,
//! memory capacity, future utility, or permission to execute effects.

use std::collections::BTreeSet;

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

use crate::EvaluatedPlanV1;
use crate::NduPlanningError;
use crate::NduPlanningInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlannerError;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::canonical_ndu_planning_policy_digest;
use crate::collect_snapshot;
use crate::evaluate_prepared_plan_with_ndu;
use crate::prepare_plan;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct VerifiedContextRecordV1 {
    pub record_id: StableId,
    pub revision: Revision,
    pub content_digest: Digest32,
}

/// Host-only evidence after verifying the canonical read and local scope.
/// `encoded_context` excludes planning metadata to avoid self-reference.
pub struct ObservedContextV1<'a> {
    pub owner_id: StableId,
    pub body_generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub read_digest: Digest32,
    pub request_binding_digest: Digest32,
    pub verified_records: &'a [VerifiedContextRecordV1],
    pub encoded_context: &'a [u8],
    pub maximum_context_bytes: u32,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ObservedContextPlanV1 {
    pub read_allowed: bool,
    pub context_digest: Digest32,
    pub record_binding_digest: Digest32,
    pub evaluation: EvaluatedPlanV1,
}

/// Compute a two-candidate read/abstain plan using actual NDU and planner code.
/// Utility is derived from canonical record bindings; resource cost is the
/// encoded delivery size. Zero records, ties, and exceeded budgets abstain.
pub fn plan_observed_context(
    observed: ObservedContextV1<'_>,
) -> Result<ObservedContextPlanV1, NduPlanningError> {
    use NduPlanningError as E;
    if observed.verified_records.len() > 4
        || observed.encoded_context.len() > 24 * 1024
        || observed.maximum_context_bytes > 24 * 1024
    {
        return Err(E::Planner(PlannerError::LimitExceeded("observed_context")));
    }
    if observed.source_snapshot_digest.is_zero()
        || observed.read_digest.is_zero()
        || observed.request_binding_digest.is_zero()
        || observed
            .verified_records
            .iter()
            .any(|record| record.content_digest.is_zero())
    {
        return Err(E::Planner(PlannerError::EmptyDigest(
            "authenticated context observation",
        )));
    }
    let mut identities = BTreeSet::new();
    for record in observed.verified_records {
        if !identities.insert((record.record_id.clone(), record.revision)) {
            return Err(E::Planner(PlannerError::DuplicateCandidate(
                record.record_id.to_string(),
            )));
        }
    }

    let id = |name: &str| StableId::new(name).map_err(|_| E::Planner(PlannerError::Arithmetic));
    let count_axis = id("verified-context-items")?;
    let bytes_axis = id("context-bytes")?;
    let read_id = id("read-context")?;
    let context_digest = Digest32::of_bytes(observed.encoded_context);
    let record_binding_digest = digest_verified_records(observed.verified_records);
    let q32 = |value: u32| FixedQ32::from_raw(i64::from(value) << 32);
    let record_count = u32::try_from(observed.verified_records.len())
        .map_err(|_| E::Planner(PlannerError::Arithmetic))?;
    let budget = q32(observed.maximum_context_bytes);
    let bytes = q32(observed.encoded_context.len() as u32);
    let mut objective = b"hepta.control.deliver-verified-context.v2\0".to_vec();
    objective.extend_from_slice(&observed.maximum_context_bytes.to_be_bytes());
    objective.extend_from_slice(observed.request_binding_digest.as_array());
    objective.extend_from_slice(record_binding_digest.as_array());
    let objective_digest = Digest32::of_bytes(&objective);
    let profile = UtilityProfile {
        profile_id: id("verified-context-delivery-v2")?,
        axis_registry_digest: Digest32::of_bytes(
            b"hepta.control.verified-context-axis-registry.v1",
        ),
        normalization_manifest_digest: Digest32::of_bytes(
            b"hepta.control.verified-context-normalization.v1",
        ),
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
    let mut input = NduPlanningInputV1 {
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
    let mut fence = b"hepta.control.context-read-generation.v2\0".to_vec();
    fence.extend_from_slice(observed.owner_id.as_str().as_bytes());
    fence.extend_from_slice(&observed.body_generation.get().to_be_bytes());
    fence.extend_from_slice(observed.request_binding_digest.as_array());
    let mut support = b"hepta.control.authenticated-context-support.v1\0".to_vec();
    support.extend_from_slice(observed.read_digest.as_array());
    support.extend_from_slice(record_binding_digest.as_array());
    support.extend_from_slice(observed.request_binding_digest.as_array());
    let snapshot = collect_snapshot(
        SnapshotRequestV1 {
            objective_digest,
            body_generation: observed.body_generation,
            configuration_digest,
            revocation_frontier_digest: Digest32::of_bytes(&fence),
            snapshot_policy_digest: Digest32::of_bytes(
                b"hepta.control.immutable-context-observation.v2",
            ),
            collected_at_micros: observed.observed_at_micros,
            maximum_owner_age_micros: 1,
            expires_at_micros: observed.expires_at_micros,
            required_owner_ids: vec![observed.owner_id.clone()],
        },
        vec![OwnerSummaryV1 {
            owner_id: observed.owner_id.clone(),
            revision: Revision::new(1).map_err(|_| E::Planner(PlannerError::Arithmetic))?,
            objective_digest,
            body_generation: observed.body_generation,
            configuration_digest,
            observed_at_micros: observed.observed_at_micros,
            expires_at_micros: observed.expires_at_micros,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: observed.source_snapshot_digest,
            support_digest: Digest32::of_bytes(&support),
        }],
    )
    .map_err(E::Planner)?;
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
                    Digest32::of_bytes(b"hepta.control.context-abstain.v2")
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
    let prepared = prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("context-delivery")?,
            now_micros: observed.observed_at_micros,
            deadline_micros: observed.expires_at_micros,
            evaluation_policy_digest: configuration_digest,
            resource_profile_digest: objective_digest,
            candidates,
            resource_reservations: vec![ResourceReservationV1 {
                axis: bytes_axis.clone(),
                endowment: budget,
                essential_floor: FixedQ32::ZERO,
            }],
        },
    )
    .map_err(E::Planner)?;
    input.contributions.contributions = prepared
        .feasible_candidates()
        .iter()
        .map(|candidate| {
            let is_read = candidate.candidate_id == read_id;
            UtilityContribution {
                candidate_id: candidate.candidate_id.clone(),
                organ_id: observed.owner_id.clone(),
                objective_digest,
                generation: observed.body_generation,
                feasibility: FeasibilityPosture::Feasible,
                utility: vec![AxisValue {
                    axis: count_axis.clone(),
                    value: if is_read {
                        q32(record_count)
                    } else {
                        FixedQ32::ZERO
                    },
                }],
                risk: vec![],
                resource: vec![AxisValue {
                    axis: bytes_axis.clone(),
                    value: if is_read { bytes } else { FixedQ32::ZERO },
                }],
                uncertainty: vec![AxisValue {
                    axis: count_axis.clone(),
                    value: FixedQ32::ZERO,
                }],
                support_digest: Digest32::of_bytes(&support),
            }
        })
        .collect();
    let evaluation =
        evaluate_prepared_plan_with_ndu(&snapshot, &prepared, input, observed.observed_at_micros)?;
    Ok(ObservedContextPlanV1 {
        read_allowed: evaluation.plan.chosen_candidate_id() == Some(&read_id),
        context_digest,
        record_binding_digest,
        evaluation,
    })
}

fn digest_verified_records(records: &[VerifiedContextRecordV1]) -> Digest32 {
    let mut bytes = b"hepta.control.verified-context-records.v1\0".to_vec();
    bytes.extend_from_slice(&(records.len() as u64).to_be_bytes());
    for record in records {
        bytes.extend_from_slice(&(record.record_id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(record.record_id.as_str().as_bytes());
        bytes.extend_from_slice(&record.revision.get().to_be_bytes());
        bytes.extend_from_slice(record.content_digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "planner_context_tests.rs"]
mod tests;
