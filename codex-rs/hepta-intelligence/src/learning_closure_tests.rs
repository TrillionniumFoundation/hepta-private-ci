use std::fs::OpenOptions;

use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::CreditAssignment;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::OutcomeFinality;
use codex_hepta_learning_ledger::OutcomeObservation;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn ledger(path: &std::path::Path) -> DurableLedger {
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .expect("create ledger");
    DurableLedger::create(file, digest("learning-closure-binding"), 8).expect("ledger")
}

fn decision() -> EpisodeDecision {
    EpisodeDecision {
        record_id: id("decision-record"),
        episode_id: id("episode-1"),
        objective_digest: digest("objective"),
        policy_id: id("policy-1"),
        candidate_ids: vec![id("action-1"), id("abstain")],
        selected_candidate_id: id("action-1"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: digest("candidate-set"),
    }
}

fn closure_request(head: Digest32) -> OutcomeCreditClosureRequestV1 {
    OutcomeCreditClosureRequestV1 {
        expected_decision_head: head,
        outcome: OutcomeObservation {
            record_id: id("outcome-record"),
            outcome_id: id("outcome-1"),
            episode_id: id("episode-1"),
            observer_id: id("independent-observer"),
            value: FixedQ32::ONE,
            finality: OutcomeFinality::Terminal,
            support_digest: digest("outcome-support"),
        },
        credit: CreditAssignment {
            record_id: id("credit-record"),
            credit_id: id("credit-1"),
            episode_id: id("episode-1"),
            outcome_id: id("outcome-1"),
            target_artifact_id: id("artifact-1"),
            allocator_id: id("independent-credit-allocator"),
            credit: FixedQ32::ONE,
            support_digest: digest("credit-support"),
        },
    }
}

#[test]
fn terminal_outcome_and_credit_append_to_the_existing_durable_lineage() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("ledger");
    let mut ledger = ledger(&path);
    let decision = ledger
        .append(Digest32::ZERO, LedgerEvent::Decision(decision()))
        .expect("decision");

    let receipt = append_outcome_and_credit_v1(&mut ledger, closure_request(decision.chain_digest))
        .expect("outcome credit closure");

    assert_eq!(ledger.records().expect("records").len(), 3);
    assert_eq!(
        ledger.records().expect("records")[1].chain_digest,
        receipt.outcome.chain_digest
    );
    assert_eq!(
        ledger.records().expect("records")[2].chain_digest,
        receipt.credit.chain_digest
    );
    assert!(!receipt.closure_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn mismatched_credit_is_rejected_before_any_outcome_append() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("ledger");
    let mut ledger = ledger(&path);
    let decision = ledger
        .append(Digest32::ZERO, LedgerEvent::Decision(decision()))
        .expect("decision");
    let mut request = closure_request(decision.chain_digest);
    request.credit.outcome_id = id("different-outcome");

    assert!(matches!(
        append_outcome_and_credit_v1(&mut ledger, request),
        Err(OutcomeCreditClosureErrorV1::Binding("outcome mismatch"))
    ));
    assert_eq!(ledger.records().expect("records").len(), 1);
}

#[test]
fn intermediate_outcome_cannot_receive_credit() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("ledger");
    let mut ledger = ledger(&path);
    let decision = ledger
        .append(Digest32::ZERO, LedgerEvent::Decision(decision()))
        .expect("decision");
    let mut request = closure_request(decision.chain_digest);
    request.outcome.finality = OutcomeFinality::Intermediate;

    assert!(matches!(
        append_outcome_and_credit_v1(&mut ledger, request),
        Err(OutcomeCreditClosureErrorV1::Binding(
            "outcome is not terminal"
        ))
    ));
    assert_eq!(ledger.records().expect("records").len(), 1);
}
