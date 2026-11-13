use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use super::*;
use crate::NduPlanEvaluationInputV1;
use crate::OwnerReadinessV1;
use crate::OwnerSummaryV1;
use crate::PlanCandidateV1;
use crate::PlannerAxisValueV1;
use crate::PlanningEvaluationDispositionV1;
use crate::PlanningRequestV1;
use crate::PreparedPlanInputV1;
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

fn snapshot_and_receipt() -> (GlobalStateSnapshotV1, FeasiblePlanReceiptV1) {
    let snapshot = must(collect_snapshot(
        SnapshotRequestV1 {
            objective_digest: digest("objective"),
            body_generation: must(Generation::new(1)),
            configuration_digest: digest("configuration"),
            revocation_frontier_digest: digest("revocations"),
            snapshot_policy_digest: digest("snapshot-policy"),
            collected_at_micros: 100,
            maximum_owner_age_micros: 50,
            expires_at_micros: 500,
            required_owner_ids: vec![id("planner")],
        },
        vec![OwnerSummaryV1 {
            owner_id: id("planner"),
            revision: must(Revision::new(1)),
            objective_digest: digest("objective"),
            body_generation: must(Generation::new(1)),
            configuration_digest: digest("configuration"),
            observed_at_micros: 90,
            expires_at_micros: 500,
            readiness: OwnerReadinessV1::Ready,
            source_frontier_digest: digest("frontier"),
            support_digest: digest("support"),
        }],
    ));
    let prepared = must(prepare_plan(
        &snapshot,
        PlanningRequestV1 {
            plan_id: id("plan-run"),
            now_micros: 100,
            deadline_micros: 400,
            evaluation_policy_digest: digest("policy"),
            resource_profile_digest: digest("resource-profile"),
            candidates: vec![candidate("abstain"), candidate("work")],
            resource_reservations: vec![ResourceReservationV1 {
                axis: id("compute"),
                endowment: q32(10),
                essential_floor: FixedQ32::ZERO,
            }],
        },
    ));
    let evaluation = evaluation(&prepared);
    let receipt = must(finalize_plan(&snapshot, &prepared, &evaluation, 110));
    (snapshot, receipt)
}

fn candidate(name: &str) -> PlanCandidateV1 {
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
            value: if name == "abstain" {
                FixedQ32::ZERO
            } else {
                q32(1)
            },
        }],
    }
}

fn evaluation(prepared: &PreparedPlanInputV1) -> crate::NduPlanEvaluationV1 {
    must(bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest(),
        body_generation: prepared.body_generation(),
        evaluation_policy_digest: prepared.evaluation_policy_digest(),
        evaluation_digest: digest("evaluation"),
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
    }))
}

#[test]
fn durable_owner_round_trips_file_store_and_anchor() {
    let directory = must(TempDir::new());
    let journal_path = directory.path().join("planner.journal");
    let anchor_path = directory.path().join("planner.anchor");
    let (snapshot, receipt) = snapshot_and_receipt();

    let mut durable = must(DurablePlannerJournalV1::open(
        FilePlannerJournalStoreV1::new(&journal_path),
        FilePlannerJournalAnchorV1::new(&anchor_path),
    ));
    must(durable.record_snapshot(&snapshot));
    must(durable.record_decision(&receipt));
    must(durable.select_plan(digest("selection"), &receipt));
    let expected_head = durable.head();
    drop(durable);

    let reopened = must(DurablePlannerJournalV1::open(
        FilePlannerJournalStoreV1::new(&journal_path),
        FilePlannerJournalAnchorV1::new(&anchor_path),
    ));
    assert_eq!(reopened.head(), expected_head);
    assert_eq!(
        reopened.journal().selected_plan_digest(),
        Some(receipt.receipt_digest())
    );
}

#[test]
fn recovery_advances_an_anchor_only_along_the_exact_durable_chain() {
    let (snapshot, _) = snapshot_and_receipt();
    let mut journal = PlannerJournalV1::new();
    must(journal.record_snapshot(&snapshot));
    let mut store = InMemoryPlannerJournalStoreV1::default();
    must(store.compare_and_commit(PlannerJournalHeadV1::empty(), &journal));
    let durable = must(DurablePlannerJournalV1::open(
        store,
        InMemoryPlannerJournalAnchorV1::default(),
    ));
    assert_eq!(durable.head(), journal.head());
    let (_, _, mut anchor) = durable.into_parts();
    assert_eq!(must(anchor.load_head()), journal.head());
}

#[test]
fn recovery_rejects_a_journal_behind_the_anchor() {
    let anchor_head = PlannerJournalHeadV1 {
        sequence: 1,
        entry_digest: digest("committed-head"),
    };
    let error = DurablePlannerJournalV1::open(
        InMemoryPlannerJournalStoreV1::default(),
        InMemoryPlannerJournalAnchorV1::from_head(anchor_head),
    )
    .expect_err("journal rollback must fail closed");
    assert_eq!(
        error,
        DurablePlannerJournalError::Store(PlannerJournalStoreError::RollbackDetected {
            anchor: anchor_head,
            journal: PlannerJournalHeadV1::empty(),
        })
    );
}

#[test]
fn compare_and_commit_rejects_stale_writers() {
    let (snapshot, receipt) = snapshot_and_receipt();
    let mut first = PlannerJournalV1::new();
    must(first.record_snapshot(&snapshot));
    let mut second = first.clone();
    must(second.record_decision(&receipt));
    let mut store = InMemoryPlannerJournalStoreV1::default();
    must(store.compare_and_commit(PlannerJournalHeadV1::empty(), &first));
    assert_eq!(
        store
            .compare_and_commit(PlannerJournalHeadV1::empty(), &second)
            .expect_err("stale expected head must fail"),
        PlannerJournalStoreError::Conflict {
            expected: PlannerJournalHeadV1::empty(),
            actual: first.head(),
        }
    );
}
