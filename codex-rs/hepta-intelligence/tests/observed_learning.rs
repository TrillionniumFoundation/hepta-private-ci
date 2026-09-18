use std::fs::OpenOptions;

use codex_hepta_intelligence::ObservedLearningErrorV1;
use codex_hepta_intelligence::record_observed_credit_v1;
use codex_hepta_intelligence::record_observed_outcome_v1;
use codex_hepta_learning_ledger::AppendDisposition;
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

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn ledger_at(path: &std::path::Path) -> DurableLedger {
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .expect("ledger file");
    DurableLedger::create(file, digest("observed-learning-ledger"), 8).expect("ledger")
}

fn append_decision(ledger: &mut DurableLedger) -> Digest32 {
    ledger
        .append(
            Digest32::ZERO,
            LedgerEvent::Decision(EpisodeDecision {
                record_id: id("decision.record"),
                episode_id: id("episode.one"),
                objective_digest: digest("objective"),
                policy_id: id("policy.one"),
                candidate_ids: vec![id("action.one")],
                selected_candidate_id: id("action.one"),
                selected_propensity: ProbabilityQ32::ONE,
                completeness: CandidateSetCompleteness::Complete,
                support_digest: digest("decision-support"),
            }),
        )
        .expect("decision append")
        .chain_digest
}

fn outcome(finality: OutcomeFinality, observer: &str) -> OutcomeObservation {
    OutcomeObservation {
        record_id: id("outcome.record"),
        outcome_id: id("outcome.one"),
        episode_id: id("episode.one"),
        observer_id: id(observer),
        value: FixedQ32::ONE,
        finality,
        support_digest: digest("outcome-support"),
    }
}

fn credit() -> CreditAssignment {
    CreditAssignment {
        record_id: id("credit.record"),
        credit_id: id("credit.one"),
        episode_id: id("episode.one"),
        outcome_id: id("outcome.one"),
        target_artifact_id: id("artifact.one"),
        allocator_id: id("allocator.one"),
        credit: FixedQ32::ONE,
        support_digest: digest("credit-support"),
    }
}

#[test]
fn terminal_external_outcome_and_credit_append_durably_in_order() {
    let temp = tempfile::tempdir().expect("tempdir");
    let mut ledger = ledger_at(&temp.path().join("ledger"));
    let decision_head = append_decision(&mut ledger);

    let outcome_receipt = record_observed_outcome_v1(
        &mut ledger,
        decision_head,
        outcome(OutcomeFinality::Terminal, "observer.one"),
    )
    .expect("outcome append");
    assert_eq!(outcome_receipt.disposition, AppendDisposition::Appended);

    let credit_receipt =
        record_observed_credit_v1(&mut ledger, outcome_receipt.chain_digest, credit())
            .expect("credit append");
    assert_eq!(credit_receipt.disposition, AppendDisposition::Appended);
    assert_eq!(ledger.records().expect("records").len(), 3);
    assert_eq!(
        ledger
            .records()
            .expect("records")
            .last()
            .expect("credit record")
            .chain_digest,
        credit_receipt.chain_digest
    );
}

#[test]
fn policy_cannot_self_label_an_outcome_through_the_facade() {
    let temp = tempfile::tempdir().expect("tempdir");
    let mut ledger = ledger_at(&temp.path().join("ledger"));
    let decision_head = append_decision(&mut ledger);

    let result = record_observed_outcome_v1(
        &mut ledger,
        decision_head,
        outcome(OutcomeFinality::Terminal, "policy.one"),
    );
    assert!(matches!(result, Err(ObservedLearningErrorV1::Ledger(_))));
    assert_eq!(ledger.records().expect("records").len(), 1);
}

#[test]
fn credit_waits_for_a_terminal_observed_outcome() {
    let temp = tempfile::tempdir().expect("tempdir");
    let mut ledger = ledger_at(&temp.path().join("ledger"));
    let decision_head = append_decision(&mut ledger);
    let outcome_receipt = record_observed_outcome_v1(
        &mut ledger,
        decision_head,
        outcome(OutcomeFinality::Intermediate, "observer.one"),
    )
    .expect("intermediate outcome append");

    let result = record_observed_credit_v1(&mut ledger, outcome_receipt.chain_digest, credit());
    assert!(matches!(result, Err(ObservedLearningErrorV1::Ledger(_))));
    assert_eq!(ledger.records().expect("records").len(), 2);
}
