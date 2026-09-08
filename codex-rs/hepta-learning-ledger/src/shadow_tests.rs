use std::fmt::Debug;

use codex_hepta_intuition::ActionCandidate;
use codex_hepta_intuition::DecisionRequest;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::CreditAssignment;
use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::ShadowDecisionError;
use crate::ShadowDecisionRequest;
use crate::append_shadow_decision;
use crate::canonical_candidate_set_digest;
use crate::prepare_shadow_decision;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value.to_string()))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn probability(raw: u64) -> ProbabilityQ32 {
    must(ProbabilityQ32::from_raw(raw))
}

fn candidate(
    candidate_id: &str,
    utility: i64,
    confidence: ProbabilityQ32,
    legal: bool,
    hard_veto: bool,
) -> ActionCandidate {
    ActionCandidate {
        candidate_id: id(candidate_id),
        legal,
        hard_veto,
        utility: FixedQ32::from_raw(utility),
        confidence,
        support_digest: digest(&format!("support.{candidate_id}")),
    }
}

fn decision_request() -> DecisionRequest {
    let mut request = DecisionRequest {
        decision_id: id("decision.shadow.001"),
        objective_digest: digest("objective.shadow.001"),
        candidate_set_digest: Digest32::ZERO,
        minimum_confidence: probability(1_u64 << 31),
        candidates: vec![
            candidate(
                "candidate-b",
                10,
                ProbabilityQ32::ONE,
                true,
                false,
            ),
            candidate(
                "candidate-a",
                20,
                ProbabilityQ32::ONE,
                true,
                false,
            ),
            candidate(
                "candidate-vetoed",
                100,
                ProbabilityQ32::ONE,
                true,
                true,
            ),
        ],
    };
    request.candidate_set_digest = canonical_candidate_set_digest(&request);
    request
}

fn shadow_request() -> ShadowDecisionRequest {
    ShadowDecisionRequest {
        record_id: id("record.shadow.001"),
        episode_id: id("episode.shadow.001"),
        policy_id: id("policy.shadow.001"),
        decision: decision_request(),
    }
}

#[test]
fn bridge_recomputes_intuition_and_appends_complete_candidate_set() {
    let mut ledger = LearningLedger::new();
    let receipt = must(append_shadow_decision(&mut ledger, shadow_request()));

    assert_eq!(receipt.ledger_receipt.disposition, AppendDisposition::Appended);
    assert_eq!(
        receipt.artifact.ledger_decision.selected_candidate_id,
        id("candidate-a")
    );
    assert_eq!(
        receipt.artifact.ledger_decision.selected_propensity,
        ProbabilityQ32::ONE
    );
    assert_eq!(
        receipt.artifact.ledger_decision.candidate_ids,
        vec![
            id("abstain"),
            id("candidate-a"),
            id("candidate-b"),
            id("candidate-vetoed"),
        ]
    );
    assert_eq!(ledger.records().len(), 1);
    assert_ne!(receipt.artifact.artifact_digest, Digest32::ZERO);
    assert!(!receipt.artifact.authority.grants_any());
}

#[test]
fn exact_shadow_replay_is_idempotent() {
    let mut ledger = LearningLedger::new();
    let first = must(append_shadow_decision(&mut ledger, shadow_request()));
    let second = must(append_shadow_decision(&mut ledger, shadow_request()));

    assert_eq!(first.artifact, second.artifact);
    assert_eq!(
        second.ledger_receipt.disposition,
        AppendDisposition::IdempotentReplay
    );
    assert_eq!(ledger.records().len(), 1);
}

#[test]
fn caller_supplied_candidate_set_digest_drift_fails_closed() {
    let mut request = shadow_request();
    request.decision.candidate_set_digest = digest("forged-candidate-set");

    let error = prepare_shadow_decision(request).expect_err("forged digest must reject");
    assert!(matches!(
        error,
        ShadowDecisionError::CandidateSetDigestMismatch { .. }
    ));
}

#[test]
fn reserved_abstain_cannot_be_smuggled_into_policy_candidates() {
    let mut request = shadow_request();
    request.decision.candidates.push(candidate(
        "abstain",
        200,
        ProbabilityQ32::ONE,
        true,
        false,
    ));
    request.decision.candidate_set_digest = canonical_candidate_set_digest(&request.decision);

    let error = prepare_shadow_decision(request).expect_err("reserved abstain must reject");
    assert!(matches!(
        error,
        ShadowDecisionError::ReservedAbstainCandidate
    ));
}

#[test]
fn low_confidence_is_logged_as_explicit_abstain_with_nonzero_propensity() {
    let mut request = shadow_request();
    request.decision.minimum_confidence = ProbabilityQ32::ONE;
    for candidate in &mut request.decision.candidates {
        candidate.confidence = probability(1_u64 << 30);
    }
    request.decision.candidate_set_digest = canonical_candidate_set_digest(&request.decision);

    let artifact = must(prepare_shadow_decision(request));
    assert_eq!(
        artifact.ledger_decision.selected_candidate_id,
        id("abstain")
    );
    assert_eq!(
        artifact.ledger_decision.selected_propensity,
        ProbabilityQ32::ONE
    );
}

#[test]
fn shadow_bridge_does_not_weaken_independent_terminal_outcome_rules() {
    let request = shadow_request();
    let policy_id = request.policy_id.clone();
    let episode_id = request.episode_id.clone();
    let mut ledger = LearningLedger::new();
    must(append_shadow_decision(&mut ledger, request));

    let self_labeled = ledger.append(LedgerEvent::Outcome(OutcomeObservation {
        record_id: id("record.outcome.self"),
        outcome_id: id("outcome.self"),
        episode_id: episode_id.clone(),
        observer_id: policy_id,
        value: FixedQ32::ONE,
        finality: OutcomeFinality::Terminal,
        support_digest: digest("outcome.self.support"),
    }));
    assert_eq!(self_labeled, Err(LedgerError::PolicySelfLabelsOutcome));

    must(ledger.append(LedgerEvent::Outcome(OutcomeObservation {
        record_id: id("record.outcome.independent"),
        outcome_id: id("outcome.independent"),
        episode_id: episode_id.clone(),
        observer_id: id("observer.independent"),
        value: FixedQ32::ONE,
        finality: OutcomeFinality::Terminal,
        support_digest: digest("outcome.independent.support"),
    })));
    must(ledger.append(LedgerEvent::Credit(CreditAssignment {
        record_id: id("record.credit.001"),
        credit_id: id("credit.001"),
        episode_id,
        outcome_id: id("outcome.independent"),
        target_artifact_id: id("artifact.policy.candidate.001"),
        allocator_id: id("allocator.independent"),
        credit: FixedQ32::ONE,
        support_digest: digest("credit.support"),
    })));
    assert_eq!(ledger.active_records().len(), 3);
}
