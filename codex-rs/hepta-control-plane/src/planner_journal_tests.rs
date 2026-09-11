use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::PlannerJournalError;
use super::PlannerJournalKindV1;
use super::PlannerJournalV1;
use crate::FeasiblePlanReceiptV1;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PlanningRequestV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::collect_snapshot;
use crate::finalize_plan;
use crate::prepare_plan;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn q32(value: i64) -> FixedQ32 {
    FixedQ32::from_raw(value << 32)
}

fn candidate(name: &str, resource: i64) -> PlanCandidateV1 {
    PlanCandidateV1 {
        candidate_id: id(name),
        operation_id: id(&format!("operation-{name}")),
        plan_digest: digest(&format!("plan:{name}")),
        required_owner_ids: vec![id("planner")],
        final_payload_digests: (name != "abstain")
            .then(|| digest(&format!("payload:{name}")))
            .into_iter()
            .collect(),
        resource_costs: vec![PlannerAxisValueV1 {
            axis: id("compute"),
            value: q32(resource),
        }],
    }
}

fn receipt() -> FeasiblePlanReceiptV1 {
    let snapshot = must(collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: must(Generation::new(1)),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 1_000,
            maximum_owner_age_micros: 100,
            expires_at_micros: 2_000,
            required_owner_ids: vec![id("planner")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("planner"),
            revision: must(Revision::new(1)),
            objective_digest: digest("objective"),
            body_generation: must(Generation::new(1)),
            configuration_digest: digest("configuration"),
            observed_at_micros: 950,
            expires_at_micros: 1_800,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }],
    ));
    let prepared = must(prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("plan-run"),
            now_micros: 1_000,
            deadline_micros: 1_700,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("resource-profile"),
            candidates: vec![candidate("abstain", 0), candidate("work", 1)],
            resource_reservations: vec![ResourceReservationV1 {
                axis: id("compute"),
                endowment: q32(10),
                essential_floor: FixedQ32::ZERO,
            }],
        },
    ));
    let evaluation = must(bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest(),
        body_generation: prepared.body_generation(),
        evaluation_policy_digest: prepared.evaluation_policy_digest(),
        evaluation_digest: digest("ndu"),
        evaluated_candidate_ids: prepared
            .feasible_candidates()
            .iter()
            .map(|candidate| candidate.candidate_id.clone())
            .collect(),
        rejected_candidate_ids: Vec::new(),
        pareto_candidate_ids: vec![id("work")],
        advisory_candidate_id: Some(id("work")),
        uncertainty_digest: digest("uncertainty"),
        disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
    }));
    must(finalize_plan(&snapshot, &prepared, &evaluation, 1_100))
}

#[test]
fn hash_chain_round_trips_and_preserves_selected_pointer() {
    let mut journal = PlannerJournalV1::new();
    let receipt = receipt();
    must(journal.append(
        PlannerJournalKindV1::Snapshot,
        digest("snapshot-identity"),
        digest("snapshot"),
    ));
    must(journal.record_decision(&receipt));
    must(journal.select_plan(digest("selection-operation"), &receipt));
    let bytes = journal.export_bytes();
    let reopened = must(PlannerJournalV1::reopen(&bytes));

    assert_eq!(reopened.entries(), journal.entries());
    assert_eq!(
        reopened.selected_plan_digest(),
        Some(receipt.receipt_digest())
    );
}

#[test]
fn identical_identity_is_idempotent_but_payload_drift_conflicts() {
    let mut journal = PlannerJournalV1::new();
    let identity = digest("identity");
    let payload = digest("payload");
    let first = must(journal.append(PlannerJournalKindV1::Decision, identity, payload));
    let replay = must(journal.append(PlannerJournalKindV1::Decision, identity, payload));
    assert_eq!(first, replay);
    assert_eq!(journal.entries().len(), 1);

    assert_eq!(
        journal
            .append(
                PlannerJournalKindV1::Decision,
                identity,
                digest("different-payload"),
            )
            .expect_err("payload drift must conflict"),
        PlannerJournalError::IdentityConflict
    );
}

#[test]
fn truncation_and_tampering_fail_closed() {
    let mut journal = PlannerJournalV1::new();
    must(journal.append(
        PlannerJournalKindV1::Snapshot,
        digest("identity"),
        digest("payload"),
    ));
    let bytes = journal.export_bytes();
    assert_eq!(
        PlannerJournalV1::reopen(&bytes[..bytes.len() - 1])
            .expect_err("truncated journal must reject"),
        PlannerJournalError::Truncated
    );

    let mut tampered = bytes;
    let last = tampered.len() - 1;
    tampered[last] ^= 1;
    assert_eq!(
        PlannerJournalV1::reopen(&tampered).expect_err("tamper must reject"),
        PlannerJournalError::CorruptEntryDigest
    );
}

#[test]
fn revocation_clears_selection_and_prevents_reselection() {
    let mut journal = PlannerJournalV1::new();
    let receipt = receipt();
    must(journal.record_decision(&receipt));
    must(journal.select_plan(digest("select-1"), &receipt));
    must(journal.revoke(digest("revoke-1"), receipt.receipt_digest()));
    assert_eq!(journal.selected_plan_digest(), None);
    assert_eq!(
        journal
            .select_plan(digest("select-2"), &receipt)
            .expect_err("revoked plan must not be reselected"),
        PlannerJournalError::RevokedPlan
    );
}
