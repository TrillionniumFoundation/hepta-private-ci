use std::fmt::Debug;

use super::*;
use crate::AppendDisposition;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected test error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value.to_string()))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn support(delivered: bool) -> PromptCausalSupportV1 {
    PromptCausalSupportV1 {
        candidate_completeness_digest: digest("candidate-completeness"),
        prompt_candidate_receipt_digest: digest("prompt-candidates"),
        prompt_pricing_set_digest: digest("pricing"),
        prompt_portfolio_receipt_digest: digest("portfolio"),
        prompt_exercise_receipt_digest: digest("exercise"),
        context_compilation_receipt_digest: digest("context"),
        delivery_observation_receipt_digest: digest("delivery"),
        delivered,
    }
}

fn actions() -> Vec<StableId> {
    vec![id("abstain"), id("portfolio:chosen")]
}

fn request(decision: LearningDecisionV1, delivered: bool) -> PromptLearningDecisionRequestV1 {
    PromptLearningDecisionRequestV1 {
        record_id: id("record:prompt-decision"),
        objective_digest: digest("objective"),
        policy_id: id("prompt.optimizer"),
        action_ids: actions(),
        decision,
        support: support(delivered),
    }
}

#[test]
fn deterministic_delivery_is_durable_but_not_counterfactual_evidence() {
    let action_set_digest = must(canonical_prompt_action_set_digest(&actions()));
    let decision = must(LearningDecisionV1::new_deterministic(
        id("learning-decision"),
        id("episode"),
        action_set_digest,
        digest("policy"),
        id("portfolio:chosen"),
    ));
    let artifact = must(prepare_prompt_learning_decision_v1(request(
        decision.clone(),
        true,
    )));
    assert_eq!(artifact.learning_decision, decision);
    assert_eq!(artifact.ledger_decision.selected_propensity, ProbabilityQ32::ONE);
    assert!(!artifact.causal_evaluation_eligible);
    assert!(!artifact.authority.grants_any());

    let mut ledger = LearningLedger::new();
    let appended = must(append_prompt_learning_decision_v1(
        &mut ledger,
        request(decision.clone(), true),
    ));
    assert_eq!(appended.ledger_receipt.disposition, AppendDisposition::Appended);
    let replay = must(append_prompt_learning_decision_v1(
        &mut ledger,
        request(decision, true),
    ));
    assert_eq!(
        replay.ledger_receipt.disposition,
        AppendDisposition::IdempotentReplay
    );
}

#[test]
fn randomized_delivered_assignment_is_marked_evaluable() {
    let action_set_digest = must(canonical_prompt_action_set_digest(&actions()));
    let decision = must(LearningDecisionV1::new_randomized(
        id("learning-decision-randomized"),
        id("episode-randomized"),
        action_set_digest,
        digest("policy-randomized"),
        id("portfolio:chosen"),
        250_000,
        digest("random-seed"),
    ));
    let artifact = must(prepare_prompt_learning_decision_v1(PromptLearningDecisionRequestV1 {
        record_id: id("record:prompt-randomized"),
        objective_digest: digest("objective"),
        policy_id: id("prompt.optimizer"),
        action_ids: actions(),
        decision,
        support: support(true),
    }));
    assert!(artifact.causal_evaluation_eligible);
    assert!(artifact.ledger_decision.selected_propensity.raw() > 0);
    assert!(artifact.ledger_decision.selected_propensity < ProbabilityQ32::ONE);
}

#[test]
fn undelivered_randomized_assignment_is_not_marked_evaluable() {
    let action_set_digest = must(canonical_prompt_action_set_digest(&actions()));
    let decision = must(LearningDecisionV1::new_randomized(
        id("learning-decision-undelivered"),
        id("episode-undelivered"),
        action_set_digest,
        digest("policy-undelivered"),
        id("portfolio:chosen"),
        500_000,
        digest("random-seed-undelivered"),
    ));
    let artifact = must(prepare_prompt_learning_decision_v1(PromptLearningDecisionRequestV1 {
        record_id: id("record:prompt-undelivered"),
        objective_digest: digest("objective"),
        policy_id: id("prompt.optimizer"),
        action_ids: actions(),
        decision,
        support: support(false),
    }));
    assert!(!artifact.causal_evaluation_eligible);
}

#[test]
fn prompt_action_set_requires_explicit_abstain_and_exact_digest() {
    assert_eq!(
        canonical_prompt_action_set_digest(&[id("portfolio:chosen")]),
        Err(LearningDecisionV1Error::MissingAbstain)
    );

    let decision = must(LearningDecisionV1::new_deterministic(
        id("learning-decision-bad-digest"),
        id("episode-bad-digest"),
        digest("wrong-action-set"),
        digest("policy"),
        id("portfolio:chosen"),
    ));
    assert_eq!(
        prepare_prompt_learning_decision_v1(request(decision, true)),
        Err(LearningDecisionV1Error::CandidateSetDigestMismatch)
    );
}

#[test]
fn randomized_decision_requires_a_seed_and_deterministic_one_rejects_it() {
    let action_set_digest = must(canonical_prompt_action_set_digest(&actions()));
    let randomized = LearningDecisionV1 {
        decision_id: id("bad-randomized"),
        episode_id: id("episode-bad-randomized"),
        candidate_set_digest: action_set_digest,
        policy_digest: digest("policy"),
        chosen_id: id("portfolio:chosen"),
        propensity_ppm: 500_000,
        random_seed_digest: None,
        receipt_digest: digest("placeholder"),
        authority: AuthorityPosture::DENY_ALL,
    };
    assert_eq!(randomized.validate(), Err(LearningDecisionV1Error::RandomSeedRequired));

    let deterministic = LearningDecisionV1::new_randomized(
        id("bad-deterministic"),
        id("episode-bad-deterministic"),
        action_set_digest,
        digest("policy"),
        id("portfolio:chosen"),
        1_000_000,
        digest("unexpected-seed"),
    );
    assert_eq!(
        deterministic,
        Err(LearningDecisionV1Error::RandomSeedUnexpected)
    );
}
