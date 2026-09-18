use std::fs::OpenOptions;

use codex_hepta_learning_ledger::AppendDisposition;
use codex_hepta_learning_ledger::CandidateSetCompleteness;
use codex_hepta_learning_ledger::CreditAssignment;
use codex_hepta_learning_ledger::DurableLedger;
use codex_hepta_learning_ledger::EpisodeDecision;
use codex_hepta_learning_ledger::OutcomeFinality;
use codex_hepta_learning_ledger::OutcomeObservation;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn decision() -> EpisodeDecision {
    EpisodeDecision {
        record_id: id("decision:v3"),
        episode_id: id("episode:v3"),
        objective_digest: digest("objective"),
        policy_id: id("policy:v3"),
        candidate_ids: vec![id("action"), id("abstain")],
        selected_candidate_id: id("action"),
        selected_propensity: ProbabilityQ32::ONE,
        completeness: CandidateSetCompleteness::Complete,
        support_digest: digest("decision-support"),
    }
}

fn outcome() -> OutcomeObservation {
    OutcomeObservation {
        record_id: id("outcome-record:v3"),
        outcome_id: id("outcome:v3"),
        episode_id: id("episode:v3"),
        observer_id: id("independent-observer"),
        value: FixedQ32::ONE,
        finality: OutcomeFinality::Terminal,
        support_digest: digest("outcome-support"),
    }
}

fn credit() -> CreditAssignment {
    CreditAssignment {
        record_id: id("credit-record:v3"),
        credit_id: id("credit:v3"),
        episode_id: id("episode:v3"),
        outcome_id: id("outcome:v3"),
        target_artifact_id: id("artifact:v3"),
        allocator_id: id("independent-allocator"),
        credit: FixedQ32::ONE,
        support_digest: digest("credit-support"),
    }
}

fn ledger() -> (tempfile::TempDir, DurableLedger) {
    let temp = tempfile::tempdir().expect("tempdir");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("ledger"))
        .expect("ledger file");
    let ledger = DurableLedger::create(file, digest("scope"), 8).expect("ledger");
    (temp, ledger)
}

#[test]
fn terminal_outcome_and_credit_close_the_existing_decision_chain() {
    let (_temp, mut ledger) = ledger();
    let decision = append_decision_v3(
        &mut ledger,
        DecisionAppendRequestV3 {
            expected_ledger_head: Digest32::ZERO,
            decision: decision(),
        },
    )
    .expect("decision");

    let closure = append_outcome_and_credit_v3(
        &mut ledger,
        OutcomeCreditClosureRequestV3 {
            expected_ledger_head: decision.chain_digest,
            outcome: outcome(),
            credit: credit(),
        },
    )
    .expect("closure");

    assert!(!closure.closure_digest.is_zero());
    assert_eq!(ledger.records().expect("records").len(), 3);
    assert_eq!(closure.outcome.disposition, AppendDisposition::Appended);
    assert_eq!(closure.credit.disposition, AppendDisposition::Appended);
}

#[test]
fn exact_retry_replays_outcome_and_credit_without_new_records() {
    let (_temp, mut ledger) = ledger();
    let decision = append_decision_v3(
        &mut ledger,
        DecisionAppendRequestV3 {
            expected_ledger_head: Digest32::ZERO,
            decision: decision(),
        },
    )
    .expect("decision");
    let request = OutcomeCreditClosureRequestV3 {
        expected_ledger_head: decision.chain_digest,
        outcome: outcome(),
        credit: credit(),
    };
    let first = append_outcome_and_credit_v3(&mut ledger, request.clone()).expect("first");
    let second = append_outcome_and_credit_v3(&mut ledger, request).expect("retry");

    assert_eq!(ledger.records().expect("records").len(), 3);
    assert_eq!(
        second.outcome.disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(
        second.credit.disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(second.closure_digest, first.closure_digest);
}

#[test]
fn mismatched_or_intermediate_observation_never_appends_partial_closure() {
    let (_temp, mut ledger) = ledger();
    let decision = append_decision_v3(
        &mut ledger,
        DecisionAppendRequestV3 {
            expected_ledger_head: Digest32::ZERO,
            decision: decision(),
        },
    )
    .expect("decision");

    let mut wrong_credit = credit();
    wrong_credit.outcome_id = id("different-outcome");
    assert!(matches!(
        append_outcome_and_credit_v3(
            &mut ledger,
            OutcomeCreditClosureRequestV3 {
                expected_ledger_head: decision.chain_digest,
                outcome: outcome(),
                credit: wrong_credit,
            },
        ),
        Err(LearningClosureErrorV3::Binding("outcome-credit linkage"))
    ));
    assert_eq!(ledger.records().expect("records").len(), 1);

    let mut intermediate = outcome();
    intermediate.finality = OutcomeFinality::Intermediate;
    assert!(matches!(
        append_outcome_and_credit_v3(
            &mut ledger,
            OutcomeCreditClosureRequestV3 {
                expected_ledger_head: decision.chain_digest,
                outcome: intermediate,
                credit: credit(),
            },
        ),
        Err(LearningClosureErrorV3::Binding("non-terminal outcome"))
    ));
    assert_eq!(ledger.records().expect("records").len(), 1);
}
