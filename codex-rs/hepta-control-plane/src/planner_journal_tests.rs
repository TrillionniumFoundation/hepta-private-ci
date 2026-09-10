use std::fmt::Debug;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::PlannerJournalError;
use super::PlannerJournalKindV1;
use super::PlannerJournalV1;
use crate::FeasiblePlanReceiptV1;
use crate::PlanningEvaluationDispositionV1;
use crate::SearchDisclosureV1;

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

fn receipt() -> FeasiblePlanReceiptV1 {
    FeasiblePlanReceiptV1 {
        plan_id: id("plan-run"),
        objective_digest: digest("objective"),
        body_generation: must(Generation::new(1)),
        configuration_digest: digest("configuration"),
        revocation_frontier_digest: digest("revocations"),
        snapshot_digest: digest("snapshot"),
        source_candidate_set_digest: digest("source-candidates"),
        candidate_set_digest: digest("candidates"),
        resource_rejected_candidate_ids: Vec::new(),
        evaluation_policy_digest: digest("policy"),
        ndu_evaluation_digest: digest("ndu"),
        ndu_binding_digest: digest("ndu-binding"),
        evaluation_disposition: PlanningEvaluationDispositionV1::UniqueParetoRecommendation,
        chosen_candidate_id: Some(id("work")),
        chosen_plan_digest: Some(digest("plan")),
        uncertainty_digest: digest("uncertainty"),
        expires_at_micros: 100,
        search_disclosure: SearchDisclosureV1::UniqueParetoOnBoundedSet,
        receipt_digest: digest("receipt"),
        authority: AuthorityPosture::DENY_ALL,
    }
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
        Some(receipt.receipt_digest)
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
    must(journal.revoke(digest("revoke-1"), receipt.receipt_digest));
    assert_eq!(journal.selected_plan_digest(), None);
    assert_eq!(
        journal
            .select_plan(digest("select-2"), &receipt)
            .expect_err("revoked plan must not be reselected"),
        PlannerJournalError::RevokedPlan
    );
}
