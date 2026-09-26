use super::*;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn candidate_wire_roundtrip_is_exact_and_rejects_unknown_fields() {
    let value = PromptCandidateSetWireV1 {
        set_id: "candidate-set:test".to_owned(),
        objective_digest: digest("objective").to_string(),
        state_digest: digest("state").to_string(),
        registry_digest: digest("registry").to_string(),
        candidate_factor_ids: vec!["factor:a".to_owned(), "factor:b".to_owned()],
        selection_grammar_digest: digest("grammar").to_string(),
    };
    let encoded = to_canonical_json_v1(&value)
        .unwrap_or_else(|error| panic!("canonical candidate JSON: {error}"));
    let decoded = from_canonical_json_v1::<PromptCandidateSetWireV1>(&encoded)
        .unwrap_or_else(|error| panic!("strict candidate JSON roundtrip: {error}"));
    assert_eq!(decoded, value);

    let mut tampered = encoded;
    let end = tampered
        .pop()
        .unwrap_or_else(|| panic!("canonical object must have a closing byte"));
    assert_eq!(end, b'}');
    tampered.extend_from_slice(b",\"unknownCritical\":true}");
    assert!(matches!(
        from_canonical_json_v1::<PromptCandidateSetWireV1>(&tampered),
        Err(PromptWireError::InvalidJson(_))
    ));
}

#[test]
fn canonical_decoder_rejects_whitespace_and_field_reordering() {
    let value = PromptPortfolioReceiptWireV1 {
        portfolio_id: "portfolio:test".to_owned(),
        candidate_set_digest: digest("candidate-set").to_string(),
        factor_ids: vec!["factor:a".to_owned()],
        interaction_digest: digest("interaction").to_string(),
        expected_utility_q32: 7,
        total_token_upper_bound: 4,
        valid_until_unix_ms: 10_000,
    };
    let encoded = to_canonical_json_v1(&value)
        .unwrap_or_else(|error| panic!("canonical portfolio JSON: {error}"));
    let mut padded = b" ".to_vec();
    padded.extend_from_slice(&encoded);
    assert_eq!(
        from_canonical_json_v1::<PromptPortfolioReceiptWireV1>(&padded),
        Err(PromptWireError::NonCanonicalJson)
    );

    let reordered = format!(
        "{{\"factorIds\":[\"factor:a\"],\"portfolioId\":\"portfolio:test\",\"candidateSetDigest\":\"{}\",\"interactionDigest\":\"{}\",\"expectedUtilityQ32\":7,\"totalTokenUpperBound\":4,\"validUntilUnixMs\":10000}}",
        digest("candidate-set"),
        digest("interaction")
    );
    assert_eq!(
        from_canonical_json_v1::<PromptPortfolioReceiptWireV1>(reordered.as_bytes()),
        Err(PromptWireError::NonCanonicalJson)
    );
}

#[test]
fn pricing_wire_rejects_invalid_bounds() {
    let value = PromptPricingReceiptWireV1 {
        factor_id: "factor:a".to_owned(),
        state_digest: digest("state").to_string(),
        expected_utility_q32: 1,
        downside_q32: 0,
        token_cost: 1,
        latency_cost_micros: 1,
        interference_ppm: 1_000_001,
        confidence_interval: PromptConfidenceIntervalWireV1 {
            lower_q32: 0,
            upper_q32: 2,
            support_count: 1,
            support_audit_digest: digest("support").to_string(),
        },
    };
    assert_eq!(
        to_canonical_json_v1(&value),
        Err(PromptWireError::InvalidBounds("pricingReceipt"))
    );
}

#[test]
fn exercise_wire_uses_closed_enum_values() {
    let value = PromptExerciseDecisionWireV1 {
        factor_or_portfolio_id: "portfolio:test".to_owned(),
        decision_boundary: PromptDecisionBoundaryWireV1::BeforeModelOrToolDispatch,
        exercise_now_value_q32: 5,
        wait_value_q32: 1,
        decision: PromptExerciseActionWireV1::Exercise,
        policy_digest: digest("policy").to_string(),
    };
    let encoded = to_canonical_json_v1(&value)
        .unwrap_or_else(|error| panic!("canonical exercise JSON: {error}"));
    assert!(
        std::str::from_utf8(&encoded)
            .unwrap_or_else(|error| panic!("JSON utf8: {error}"))
            .contains("before_model_or_tool_dispatch")
    );
    assert_eq!(
        from_canonical_json_v1::<PromptExerciseDecisionWireV1>(&encoded)
            .unwrap_or_else(|error| panic!("exercise roundtrip: {error}")),
        value
    );
}
