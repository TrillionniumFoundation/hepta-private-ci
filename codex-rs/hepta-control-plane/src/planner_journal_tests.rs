use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

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
use crate::PreparedPlanInputV1;
use crate::ResourceReservationV1;
use crate::SnapshotRequestV1;
use crate::bind_ndu_plan_evaluation_v1;
use crate::canonical_resource_profile_digest;
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

fn summary() -> OwnerSummaryV1 {
    OwnerSummaryV1 {
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
    }
}

fn snapshot_request() -> SnapshotRequestV1 {
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
    }
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

fn planning_request() -> PlanningRequestV1 {
    let resource_reservations = vec![ResourceReservationV1 {
        axis: id("compute"),
        endowment: q32(10),
        essential_floor: FixedQ32::ZERO,
    }];
    PlanningRequestV1 {
        plan_id: id("plan-run"),
        now_micros: 100,
        deadline_micros: 400,
        evaluation_policy_digest: digest("policy"),
        resource_profile_digest: must(canonical_resource_profile_digest(&resource_reservations)),
        candidates: vec![candidate("abstain"), candidate("work")],
        resource_reservations,
    }
}

fn evaluation(prepared: &PreparedPlanInputV1) -> crate::NduPlanEvaluationV1 {
    must(bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1 {
        objective_digest: prepared.objective_digest(),
        body_generation: prepared.body_generation(),
        evaluation_policy_digest: prepared.evaluation_policy_digest(),
        evaluation_digest: digest("ndu-evaluation"),
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

fn receipt() -> FeasiblePlanReceiptV1 {
    let snapshot = must(collect_snapshot(snapshot_request(), vec![summary()]));
    let prepared = must(prepare_plan(&snapshot, planning_request()));
    let evaluation = evaluation(&prepared);
    must(finalize_plan(&snapshot, &prepared, &evaluation, 110))
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

fn encode_semantic_entries(entries: &[(PlannerJournalKindV1, Digest32, Digest32)]) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"HCPJNL01");
    bytes.extend_from_slice(&(entries.len() as u32).to_be_bytes());
    let mut predecessor = Digest32::ZERO;
    for (index, (kind, identity, payload)) in entries.iter().copied().enumerate() {
        let sequence = (index as u64) + 1;
        let entry_digest = super::digest_entry(sequence, kind, identity, payload, predecessor);
        bytes.extend_from_slice(&sequence.to_be_bytes());
        bytes.push(match kind {
            PlannerJournalKindV1::Snapshot => 0,
            PlannerJournalKindV1::Decision => 1,
            PlannerJournalKindV1::SelectedPlan => 2,
            PlannerJournalKindV1::Revocation => 3,
        });
        bytes.extend_from_slice(identity.as_array());
        bytes.extend_from_slice(payload.as_array());
        bytes.extend_from_slice(predecessor.as_array());
        bytes.extend_from_slice(entry_digest.as_array());
        predecessor = entry_digest;
    }
    bytes
}

#[test]
fn semantic_replay_rejects_hash_valid_invalid_selection_history() {
    let target = digest("decision");
    let without_decision =
        encode_semantic_entries(&[(PlannerJournalKindV1::SelectedPlan, digest("select"), target)]);
    assert_eq!(
        PlannerJournalV1::reopen(&without_decision)
            .expect_err("selection without a prior decision must reject"),
        PlannerJournalError::DecisionNotRecorded
    );

    let after_revocation = encode_semantic_entries(&[
        (PlannerJournalKindV1::Decision, target, target),
        (PlannerJournalKindV1::Revocation, digest("revoke"), target),
        (
            PlannerJournalKindV1::SelectedPlan,
            digest("select-after-revoke"),
            target,
        ),
    ]);
    assert_eq!(
        PlannerJournalV1::reopen(&after_revocation)
            .expect_err("a revoked decision cannot be selected during replay"),
        PlannerJournalError::RevokedPlan
    );
}
