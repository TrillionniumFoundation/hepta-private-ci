//! Final public-boundary checks shared by all planner consumers.
//!
//! Internal deterministic routines remain unchanged. Public NDU projections are
//! bounded before normalization; owner freshness is checked again at both seal
//! and grant-request boundaries rather than trusting collection-time masks.

use crate::FeasiblePlanReceiptV1;
use crate::GlobalStateSnapshotV1;
use crate::GrantRequestSetV1;
use crate::NduPlanEvaluationInputV1;
use crate::NduPlanEvaluationV1;
use crate::PlannerError;
use crate::PreparedPlanInputV1;
use crate::planner;
use crate::planner_guard::validate_current_snapshot;

const MAX_CANDIDATES: usize = 128;

pub fn bind_ndu_plan_evaluation_v1(
    input: NduPlanEvaluationInputV1,
) -> Result<NduPlanEvaluationV1, PlannerError> {
    if input.evaluated_candidate_ids.len() > MAX_CANDIDATES
        || input.rejected_candidate_ids.len() > MAX_CANDIDATES
        || input.pareto_candidate_ids.len() > MAX_CANDIDATES
        || input.evaluated_candidate_ids.len() + input.rejected_candidate_ids.len() > MAX_CANDIDATES
    {
        return Err(PlannerError::LimitExceeded("NDU candidate projection"));
    }
    planner::bind_ndu_plan_evaluation_v1(input)
}

pub fn finalize_plan(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    evaluation: &NduPlanEvaluationV1,
    now_micros: u64,
) -> Result<FeasiblePlanReceiptV1, PlannerError> {
    validate_current_snapshot(snapshot, now_micros)?;
    planner::finalize_plan(snapshot, prepared, evaluation, now_micros)
}

pub fn request_execution_grants(
    snapshot: &GlobalStateSnapshotV1,
    prepared: &PreparedPlanInputV1,
    receipt: &FeasiblePlanReceiptV1,
    now_micros: u64,
) -> Result<GrantRequestSetV1, PlannerError> {
    validate_current_snapshot(snapshot, now_micros)?;
    planner::request_execution_grants(snapshot, prepared, receipt, now_micros)
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::Digest32;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::Revision;
    use codex_hepta_types::StableId;

    use super::*;
    use crate::OwnerReadinessV1;
    use crate::OwnerSummaryV1;
    use crate::PlanCandidateV1;
    use crate::PlannerAxisValueV1;
    use crate::PlanningEvaluationDispositionV1;
    use crate::PlanningRequestV1;
    use crate::ResourceReservationV1;
    use crate::SnapshotRequestV1;
    use crate::collect_snapshot;
    use crate::prepare_plan;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn evaluation_input() -> NduPlanEvaluationInputV1 {
        NduPlanEvaluationInputV1 {
            objective_digest: digest("objective"),
            body_generation: Generation::new(1).expect("generation"),
            evaluation_policy_digest: digest("policy"),
            evaluation_digest: digest("evaluation"),
            evaluated_candidate_ids: vec![id("abstain"), id("work")],
            rejected_candidate_ids: Vec::new(),
            pareto_candidate_ids: vec![id("work")],
            advisory_candidate_id: Some(id("work")),
            uncertainty_digest: digest("uncertainty"),
            disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
        }
    }

    fn inputs() -> (GlobalStateSnapshotV1, PreparedPlanInputV1, NduPlanEvaluationV1) {
        let generation = Generation::new(1).expect("generation");
        let snapshot = collect_snapshot(
            SnapshotRequestV1 {
                objective_digest: digest("objective"),
                body_generation: generation,
                configuration_digest: digest("configuration"),
                revocation_frontier_digest: digest("revocations"),
                snapshot_policy_digest: digest("snapshot-policy"),
                collected_at_micros: 1_000,
                maximum_owner_age_micros: 100,
                expires_at_micros: 5_000,
                required_owner_ids: vec![id("owner")],
            },
            vec![OwnerSummaryV1 {
                owner_id: id("owner"),
                revision: Revision::new(1).expect("revision"),
                objective_digest: digest("objective"),
                body_generation: generation,
                configuration_digest: digest("configuration"),
                observed_at_micros: 950,
                expires_at_micros: 5_000,
                readiness: OwnerReadinessV1::Ready,
                source_frontier_digest: digest("frontier"),
                support_digest: digest("support"),
            }],
        )
        .expect("snapshot");
        let candidates = ["abstain", "work"]
            .into_iter()
            .map(|name| PlanCandidateV1 {
                candidate_id: id(name),
                operation_id: id(name),
                plan_digest: digest(name),
                required_owner_ids: vec![id("owner")],
                final_payload_digests: if name == "work" {
                    vec![digest("payload")]
                } else {
                    Vec::new()
                },
                resource_costs: vec![PlannerAxisValueV1 {
                    axis: id("compute"),
                    value: FixedQ32::ZERO,
                }],
            })
            .collect();
        let prepared = prepare_plan(
            &snapshot,
            PlanningRequestV1 {
                plan_id: id("plan"),
                now_micros: 1_000,
                deadline_micros: 4_000,
                evaluation_policy_digest: digest("policy"),
                resource_profile_digest: digest("resources"),
                candidates,
                resource_reservations: vec![ResourceReservationV1 {
                    axis: id("compute"),
                    endowment: FixedQ32::from_raw(1 << 32),
                    essential_floor: FixedQ32::ZERO,
                }],
            },
        )
        .expect("prepared plan");
        let evaluation = bind_ndu_plan_evaluation_v1(evaluation_input()).expect("evaluation");
        (snapshot, prepared, evaluation)
    }

    #[test]
    fn oversized_ndu_projection_rejects_before_duplicate_normalization() {
        for which in 0..3 {
            let mut input = evaluation_input();
            match which {
                0 => input.evaluated_candidate_ids = vec![id("work"); 129],
                1 => input.rejected_candidate_ids = vec![id("work"); 129],
                _ => input.pareto_candidate_ids = vec![id("work"); 129],
            }
            assert_eq!(
                bind_ndu_plan_evaluation_v1(input),
                Err(PlannerError::LimitExceeded("NDU candidate projection"))
            );
        }
    }

    #[test]
    fn evaluated_and_rejected_union_has_one_shared_capacity_bound() {
        let mut input = evaluation_input();
        input.evaluated_candidate_ids = vec![id("work"); 64];
        input.rejected_candidate_ids = vec![id("rejected"); 65];
        assert_eq!(
            bind_ndu_plan_evaluation_v1(input),
            Err(PlannerError::LimitExceeded("NDU candidate projection"))
        );
    }

    #[test]
    fn owner_age_expires_at_finalization_and_grant_request_before_snapshot_expiry() {
        let (snapshot, prepared, evaluation) = inputs();
        let receipt = finalize_plan(&snapshot, &prepared, &evaluation, 1_000).expect("receipt");
        assert!(finalize_plan(&snapshot, &prepared, &evaluation, 1_050).is_ok());
        assert!(request_execution_grants(&snapshot, &prepared, &receipt, 1_050).is_ok());
        assert_eq!(
            finalize_plan(&snapshot, &prepared, &evaluation, 1_051),
            Err(PlannerError::SnapshotExpired)
        );
        assert_eq!(
            request_execution_grants(&snapshot, &prepared, &receipt, 1_051),
            Err(PlannerError::SnapshotExpired)
        );
    }

    #[test]
    fn clock_rollback_cannot_restore_a_plan_at_either_final_boundary() {
        let (snapshot, prepared, evaluation) = inputs();
        let receipt = finalize_plan(&snapshot, &prepared, &evaluation, 1_000).expect("receipt");
        assert_eq!(
            finalize_plan(&snapshot, &prepared, &evaluation, 999),
            Err(PlannerError::InvalidTime("snapshot clock rollback"))
        );
        assert_eq!(
            request_execution_grants(&snapshot, &prepared, &receipt, 999),
            Err(PlannerError::InvalidTime("snapshot clock rollback"))
        );
    }
}
