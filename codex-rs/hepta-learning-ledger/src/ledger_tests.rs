use std::fmt::Debug;

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::LearningLedger;
use crate::AppendDisposition;
use crate::CandidateSetCompleteness;
use crate::CreditAssignment;
use crate::EpisodeDecision;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn must_err<T: Debug, E>(result: Result<T, E>) -> E {
    match result {
        Err(error) => error,
        Ok(value) => panic!("expected error, received value: {value:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn decision() -> EpisodeDecision {
    EpisodeDecision {
        record_id: id("record-decision-1"),
        episode_id: id("episode-1"),
        objective_digest: Digest32::of_bytes(b"objective"),
        policy_id: id("policy-a"),
        candidate_ids: vec![id("candidate-b"), id("abstain"), id("candidate-a")],
        selected_candidate_id: id("candidate-a"),
        selected_propensity: must(ProbabilityQ32::from_raw(1_u64 << 31)),
        completeness: CandidateSetCompleteness::Complete,
        support_digest: Digest32::of_bytes(b"candidate-set"),
    }
}

fn outcome() -> OutcomeObservation {
    OutcomeObservation {
        record_id: id("record-outcome-1"),
        outcome_id: id("outcome-1"),
        episode_id: id("episode-1"),
        observer_id: id("independent-observer"),
        value: FixedQ32::ONE,
        finality: OutcomeFinality::Terminal,
        support_digest: Digest32::of_bytes(b"outcome-support"),
    }
}

fn credit() -> CreditAssignment {
    CreditAssignment {
        record_id: id("record-credit-1"),
        credit_id: id("credit-1"),
        episode_id: id("episode-1"),
        outcome_id: id("outcome-1"),
        target_artifact_id: id("artifact-a"),
        allocator_id: id("credit-evaluator"),
        credit: FixedQ32::ONE,
        support_digest: Digest32::of_bytes(b"credit-support"),
    }
}

#[test]
fn append_is_deterministic_and_idempotent() {
    let event = LedgerEvent::Decision(decision());
    let mut first = LearningLedger::new();
    let first_receipt = must(first.append(event.clone()));
    let replay = must(first.append(event.clone()));
    let mut second = LearningLedger::new();
    let second_receipt = must(second.append(event));

    assert_eq!(first_receipt, second_receipt);
    assert_eq!(replay.disposition, AppendDisposition::IdempotentReplay);
    assert_eq!(first.snapshot(), second.snapshot());
}

#[test]
fn evaluated_policy_cannot_label_its_own_outcome() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::Decision(decision())));
    let mut self_labeled = outcome();
    self_labeled.observer_id = id("policy-a");

    let error = must_err(ledger.append(LedgerEvent::Outcome(self_labeled)));

    assert_eq!(error, LedgerError::PolicySelfLabelsOutcome);
}

#[test]
fn incomplete_or_duplicate_candidate_sets_fail_closed() {
    let mut incomplete = decision();
    incomplete.completeness = CandidateSetCompleteness::Incomplete;
    let mut ledger = LearningLedger::new();
    assert_eq!(
        must_err(ledger.append(LedgerEvent::Decision(incomplete))),
        LedgerError::IncompleteCandidateSet
    );

    let mut duplicate = decision();
    duplicate.candidate_ids.push(id("candidate-a"));
    assert_eq!(
        must_err(ledger.append(LedgerEvent::Decision(duplicate))),
        LedgerError::DuplicateCandidate("candidate-a".to_owned())
    );
}

#[test]
fn credit_cannot_be_double_counted() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::Decision(decision())));
    must(ledger.append(LedgerEvent::Outcome(outcome())));
    must(ledger.append(LedgerEvent::Credit(credit())));
    let mut duplicate = credit();
    duplicate.record_id = id("record-credit-2");
    duplicate.credit_id = id("credit-2");

    assert_eq!(
        must_err(ledger.append(LedgerEvent::Credit(duplicate))),
        LedgerError::CreditAlreadyAssigned
    );
}

#[test]
fn revocation_removes_descendants_and_snapshot_restore_does_not_resurrect() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::Decision(decision())));
    must(ledger.append(LedgerEvent::Outcome(outcome())));
    must(ledger.append(LedgerEvent::Credit(credit())));
    must(ledger.append(LedgerEvent::Revocation(Revocation {
        record_id: id("record-revocation-1"),
        target_record_id: id("record-decision-1"),
        authority_id: id("deletion-authority"),
        reason_digest: Digest32::of_bytes(b"delete"),
    })));

    let active_ids: Vec<_> = ledger
        .active_records()
        .iter()
        .map(|record| record.event.record_id().to_string())
        .collect();
    assert_eq!(active_ids, vec!["record-revocation-1"]);

    let restored = must(LearningLedger::from_snapshot(ledger.snapshot()));
    assert_eq!(restored.active_records().len(), 1);
    assert_eq!(restored.snapshot(), ledger.snapshot());
}

#[test]
fn outcome_and_credit_cannot_attach_to_revoked_ancestors() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::Decision(decision())));
    must(ledger.append(LedgerEvent::Revocation(Revocation {
        record_id: id("record-revocation-1"),
        target_record_id: id("record-decision-1"),
        authority_id: id("deletion-authority"),
        reason_digest: Digest32::of_bytes(b"delete"),
    })));

    assert_eq!(
        must_err(ledger.append(LedgerEvent::Outcome(outcome()))),
        LedgerError::EpisodeRevoked("episode-1".to_owned())
    );
}

#[test]
fn zero_propensity_and_missing_abstain_fail_closed() {
    let mut zero = decision();
    zero.selected_propensity = ProbabilityQ32::ZERO;
    let mut ledger = LearningLedger::new();
    assert_eq!(
        must_err(ledger.append(LedgerEvent::Decision(zero))),
        LedgerError::ZeroSelectedPropensity
    );

    let mut missing = decision();
    missing
        .candidate_ids
        .retain(|candidate| candidate.as_str() != "abstain");
    assert_eq!(
        must_err(ledger.append(LedgerEvent::Decision(missing))),
        LedgerError::MissingAbstainCandidate
    );
}

#[test]
fn tampered_snapshot_chain_is_rejected() {
    let mut ledger = LearningLedger::new();
    must(ledger.append(LedgerEvent::Decision(decision())));
    let mut snapshot = ledger.snapshot();
    snapshot.records[0].chain_digest = Digest32::of_bytes(b"tampered");

    assert_eq!(
        must_err(LearningLedger::from_snapshot(snapshot)),
        LedgerError::SnapshotRecordMismatch(1)
    );
}
