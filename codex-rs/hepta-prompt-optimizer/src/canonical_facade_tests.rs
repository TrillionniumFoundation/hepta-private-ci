use super::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id: {error}"))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn strict_candidate_codec_rejects_unknown_fields_and_noncanonical_json() {
    let receipt = PromptCandidateSetReceiptV1 {
        set_id: id("set:codec"),
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        registry_digest: digest("registry"),
        candidate_factor_ids: vec![id("factor:a"), id("factor:b")],
        selection_grammar_digest: digest("grammar"),
        receipt_digest: digest("internal-receipt"),
        authority: AuthorityPosture::DENY_ALL,
    };
    let encoded = encode_candidate_set_v1(&receipt)
        .unwrap_or_else(|error| panic!("encode candidate set: {error}"));
    let decoded = decode_candidate_set_v1(&encoded)
        .unwrap_or_else(|error| panic!("decode candidate set: {error}"));
    assert_eq!(decoded.set_id, receipt.set_id);
    assert_eq!(decoded.candidate_factor_ids, receipt.candidate_factor_ids);

    let mut with_unknown = encoded.clone();
    let closing = with_unknown
        .pop()
        .unwrap_or_else(|| panic!("encoded JSON has closing delimiter"));
    assert_eq!(closing, b'}');
    with_unknown.extend_from_slice(b",\"unknownCritical\":true}");
    assert!(decode_candidate_set_v1(&with_unknown).is_err());

    let mut with_whitespace = Vec::with_capacity(encoded.len() + 1);
    with_whitespace.push(b' ');
    with_whitespace.extend_from_slice(&encoded);
    assert!(decode_candidate_set_v1(&with_whitespace).is_err());
}

#[test]
fn strict_portfolio_codec_round_trips_registered_shape() {
    let receipt = PromptPortfolioReceiptV1 {
        portfolio_id: id("portfolio:codec"),
        candidate_set_digest: digest("candidate-set"),
        factor_ids: vec![id("factor:a"), id("factor:b")],
        interaction_digest: digest("interaction"),
        expected_utility_q32: FixedQ32::from_raw(42),
        total_token_upper_bound: 12,
        valid_until_unix_ms: 5_000,
        receipt_digest: digest("internal-portfolio-receipt"),
        authority: AuthorityPosture::DENY_ALL,
    };
    let encoded = encode_portfolio_receipt_v1(&receipt)
        .unwrap_or_else(|error| panic!("encode portfolio: {error}"));
    let decoded = decode_portfolio_receipt_v1(&encoded)
        .unwrap_or_else(|error| panic!("decode portfolio: {error}"));
    assert_eq!(decoded.portfolio_id, receipt.portfolio_id);
    assert_eq!(decoded.factor_ids, receipt.factor_ids);
    assert_eq!(decoded.expected_utility_q32, receipt.expected_utility_q32);
}

#[test]
fn exercise_policy_digest_binds_policy_semantics() {
    let base = PromptExercisePolicyV1 {
        policy_id: id("policy:exercise"),
        objective_digest: digest("objective"),
        scope_digest: digest("scope"),
        model_tuple_digest: digest("model-tuple"),
        allowed_boundaries: vec![PromptDecisionBoundaryV1::BeforeModelOrToolDispatch],
        minimum_exercise_margin_q32: FixedQ32::from_raw(1),
        valid_from_unix_ms: 1,
        valid_until_unix_ms: 10_000,
    };
    let mut changed = base.clone();
    changed.minimum_exercise_margin_q32 = FixedQ32::from_raw(2);
    assert_ne!(
        base.digest()
            .unwrap_or_else(|error| panic!("base policy: {error}")),
        changed
            .digest()
            .unwrap_or_else(|error| panic!("changed policy: {error}"))
    );
}

#[test]
fn exercise_policy_rejects_noncanonical_boundary_order() {
    let policy = PromptExercisePolicyV1 {
        policy_id: id("policy:exercise"),
        objective_digest: digest("objective"),
        scope_digest: digest("scope"),
        model_tuple_digest: digest("model-tuple"),
        allowed_boundaries: vec![
            PromptDecisionBoundaryV1::BeforeModelOrToolDispatch,
            PromptDecisionBoundaryV1::BeforePlanning,
        ],
        minimum_exercise_margin_q32: FixedQ32::ZERO,
        valid_from_unix_ms: 1,
        valid_until_unix_ms: 10_000,
    };
    assert!(policy.digest().is_err());
}
