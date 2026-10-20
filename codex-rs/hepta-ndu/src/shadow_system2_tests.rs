use std::fmt::Debug;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::*;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn policy() -> NduShadowPolicyV1 {
    NduShadowPolicyV1 {
        policy_id: "shadow:fixture".to_owned(),
        max_depth: 4,
        step_cost_micros: 10,
        uncertainty_trigger_q32: 20,
        risk_trigger_q32: 20,
        abstain_uncertainty_q32: 80,
        abstain_risk_q32: 80,
        uncertainty_decay_q32: 15,
        risk_decay_q32: 10,
        value_gain_q32: 7,
    }
}

fn request(policy: &NduShadowPolicyV1) -> NduShadowRequestV1 {
    NduShadowRequestV1 {
        subject_id: "group:fixture".to_owned(),
        run_id: "run:fixture".to_owned(),
        generation: 1,
        input_digest: digest("input"),
        stem_digest: digest("stem"),
        encoder_digest: digest("encoder"),
        group_adapter_digest: digest("adapter"),
        critic_digest: digest("critic"),
        trajectory_digest: digest("trajectory"),
        policy_digest: canonical_ndu_shadow_policy_digest_v1(policy),
        current_depth: 0,
        remaining_budget_micros: 100,
        value_q32: 50,
        risk_q32: 30,
        uncertainty_q32: 40,
    }
}

#[test]
fn high_uncertainty_spends_one_bounded_step() {
    let policy = policy();
    let result = must(suggest_ndu_shadow_v1(&policy, &request(&policy)));
    assert_eq!(result.action, NduShadowActionV1::Deepen);
    assert!(result.should_deepen);
    assert!(!result.abstain);
    assert_eq!(result.recommended_depth, 1);
    assert_eq!(result.remaining_budget_micros, 90);
    assert_eq!(result.projected_value_q32, 57);
    assert_eq!(result.projected_risk_q32, 20);
    assert_eq!(result.projected_uncertainty_q32, 25);
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
    assert!(!result.receipt_digest.is_zero());
}

#[test]
fn exhausted_budget_abstains_when_threshold_remains_unsafe() {
    let policy = policy();
    let mut input = request(&policy);
    input.remaining_budget_micros = 0;
    input.uncertainty_q32 = 100;
    let result = must(suggest_ndu_shadow_v1(&policy, &input));
    assert_eq!(result.action, NduShadowActionV1::Abstain);
    assert!(!result.should_deepen);
    assert!(result.abstain);
    assert_eq!(result.recommended_depth, 0);
    assert_eq!(result.remaining_budget_micros, 0);
}

#[test]
fn safe_request_holds_without_spending_budget() {
    let policy = policy();
    let mut input = request(&policy);
    input.risk_q32 = 2;
    input.uncertainty_q32 = 3;
    let result = must(suggest_ndu_shadow_v1(&policy, &input));
    assert_eq!(result.action, NduShadowActionV1::Hold);
    assert!(!result.should_deepen);
    assert!(!result.abstain);
    assert_eq!(result.remaining_budget_micros, 100);
    assert_eq!(result.projected_value_q32, input.value_q32);
}

#[test]
fn receipt_digest_is_replayable_and_policy_bound() {
    let policy = policy();
    let input = request(&policy);
    let first = must(suggest_ndu_shadow_v1(&policy, &input));
    let second = must(suggest_ndu_shadow_v1(&policy, &input));
    assert_eq!(first, second);
    assert_eq!(
        first.receipt_digest,
        canonical_ndu_shadow_receipt_digest_v1(&first)
    );

    let mut changed = input;
    changed.trajectory_digest = digest("trajectory:changed");
    let third = must(suggest_ndu_shadow_v1(&policy, &changed));
    assert_ne!(first.request_digest, third.request_digest);
    assert_ne!(first.receipt_digest, third.receipt_digest);
}

#[test]
fn malformed_provenance_fails_closed() {
    let policy = policy();
    let mut input = request(&policy);
    input.policy_digest = Digest32::ZERO;
    assert_eq!(
        suggest_ndu_shadow_v1(&policy, &input),
        Err(NduShadowError::ZeroDigest("policy_digest"))
    );

    let mut input = request(&policy);
    input.uncertainty_q32 = -1;
    assert_eq!(
        suggest_ndu_shadow_v1(&policy, &input),
        Err(NduShadowError::NegativeObservation("uncertainty_q32"))
    );
}

#[test]
fn exhausted_depth_abstains_without_budget_mutation() {
    let policy = policy();
    let mut input = request(&policy);
    input.current_depth = policy.max_depth;
    input.risk_q32 = 100;
    let result = must(suggest_ndu_shadow_v1(&policy, &input));
    assert_eq!(result.action, NduShadowActionV1::Abstain);
    assert_eq!(result.recommended_depth, policy.max_depth);
    assert_eq!(
        result.remaining_budget_micros,
        input.remaining_budget_micros
    );
}

#[test]
fn depth_projection_never_emits_negative_risk_or_uncertainty() {
    let policy = policy();
    let mut risk_only = request(&policy);
    risk_only.risk_q32 = 20;
    risk_only.uncertainty_q32 = 1;
    let projected = must(suggest_ndu_shadow_v1(&policy, &risk_only));
    assert_eq!(projected.action, NduShadowActionV1::Deepen);
    assert_eq!(projected.projected_uncertainty_q32, 0);
    assert_eq!(projected.projected_risk_q32, 10);

    let mut uncertainty_only = request(&policy);
    uncertainty_only.risk_q32 = 1;
    uncertainty_only.uncertainty_q32 = 20;
    let projected = must(suggest_ndu_shadow_v1(&policy, &uncertainty_only));
    assert_eq!(projected.action, NduShadowActionV1::Deepen);
    assert_eq!(projected.projected_risk_q32, 0);
    assert_eq!(projected.projected_uncertainty_q32, 5);
}
