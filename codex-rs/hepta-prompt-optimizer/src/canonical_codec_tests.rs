use super::*;
use codex_hepta_types::Digest32;

fn digest(label: &str) -> String {
    Digest32::of_bytes(label.as_bytes()).to_string()
}

fn candidate_wire() -> PromptCandidateSetWireV1 {
    PromptCandidateSetWireV1 {
        set_id: "set:codec".to_owned(),
        objective_digest: digest("objective"),
        state_digest: digest("state"),
        registry_digest: digest("registry"),
        candidate_factor_ids: vec!["factor:a".to_owned(), "factor:b".to_owned()],
        selection_grammar_digest: digest("grammar"),
    }
}

#[test]
fn candidate_json_v1_is_canonical_and_round_trips() {
    let value = candidate_wire();
    let encoded = encode_candidate_set_wire_json_v1(&value).expect("encode candidate set");
    let text = std::str::from_utf8(&encoded).expect("utf8");
    assert!(text.starts_with("{\"setId\":"));
    assert!(text.contains("\"candidateFactorIds\":[\"factor:a\",\"factor:b\"]"));
    assert_eq!(
        decode_candidate_set_receipt_json_v1(&encoded).expect("decode candidate set"),
        value
    );
    assert_eq!(
        candidate_set_wire_digest_v1(&value).expect("wire digest"),
        Digest32::of_bytes(&encoded)
    );
}

#[test]
fn unknown_and_missing_critical_fields_are_rejected() {
    let value = candidate_wire();
    let encoded = encode_candidate_set_wire_json_v1(&value).expect("encode");
    let mut json: serde_json::Value = serde_json::from_slice(&encoded).expect("json");
    json.as_object_mut()
        .expect("object")
        .insert("unexpected".to_owned(), serde_json::Value::Bool(true));
    let unknown = serde_json::to_vec(&json).expect("unknown json");
    assert_eq!(
        decode_candidate_set_receipt_json_v1(&unknown),
        Err(PromptCodecErrorV1::Json)
    );
    json.as_object_mut()
        .expect("object")
        .remove("objectiveDigest");
    json.as_object_mut()
        .expect("object")
        .remove("unexpected");
    let missing = serde_json::to_vec(&json).expect("missing json");
    assert_eq!(
        decode_candidate_set_receipt_json_v1(&missing),
        Err(PromptCodecErrorV1::Json)
    );
}

#[test]
fn candidate_order_and_bounds_are_closed() {
    let mut value = candidate_wire();
    value.candidate_factor_ids.reverse();
    assert_eq!(
        encode_candidate_set_wire_json_v1(&value),
        Err(PromptCodecErrorV1::InvalidOrder("candidateFactorIds"))
    );
    let mut too_many = candidate_wire();
    too_many.candidate_factor_ids = (0..129)
        .map(|index| format!("factor:{index:03}"))
        .collect();
    assert_eq!(
        encode_candidate_set_wire_json_v1(&too_many),
        Err(PromptCodecErrorV1::InvalidBound("candidateFactorIds"))
    );
}

#[test]
fn pricing_portfolio_and_exercise_codecs_reject_semantic_drift() {
    let pricing = PromptPricingWireV1 {
        factor_id: "factor:a".to_owned(),
        state_digest: digest("state"),
        expected_utility_q32: 10,
        downside_q32: 1,
        token_cost: 4,
        latency_cost_micros: 15,
        interference_ppm: 2,
        confidence_interval: PromptConfidenceIntervalWireV1 {
            lower_q32: 5,
            upper_q32: 20,
            support_count: 3,
            support_audit_digest: digest("support"),
        },
    };
    let encoded = encode_pricing_wire_json_v1(&pricing).expect("pricing encode");
    assert_eq!(
        decode_pricing_receipt_json_v1(&encoded).expect("pricing decode"),
        pricing
    );
    let mut invalid_pricing = pricing.clone();
    invalid_pricing.interference_ppm = 1_000_001;
    assert_eq!(
        encode_pricing_wire_json_v1(&invalid_pricing),
        Err(PromptCodecErrorV1::InvalidBound("pricing"))
    );

    let portfolio = PromptPortfolioWireV1 {
        portfolio_id: "portfolio:a".to_owned(),
        candidate_set_digest: digest("candidate-set"),
        factor_ids: vec!["factor:a".to_owned()],
        interaction_digest: digest("interaction"),
        expected_utility_q32: 10,
        total_token_upper_bound: 4,
        valid_until_unix_ms: 1_000,
    };
    let portfolio_bytes = encode_portfolio_wire_json_v1(&portfolio).expect("portfolio encode");
    assert_eq!(
        decode_portfolio_receipt_json_v1(&portfolio_bytes).expect("portfolio decode"),
        portfolio
    );

    let exercise = PromptExerciseWireV1 {
        factor_or_portfolio_id: "portfolio:a".to_owned(),
        decision_boundary: PromptDecisionBoundaryWireV1::BeforeModelOrToolDispatch,
        exercise_now_value_q32: 10,
        wait_value_q32: 1,
        decision: PromptExerciseActionWireV1::Exercise,
        policy_digest: digest("policy"),
    };
    let exercise_bytes = encode_exercise_wire_json_v1(&exercise).expect("exercise encode");
    assert_eq!(
        decode_exercise_decision_json_v1(&exercise_bytes).expect("exercise decode"),
        exercise
    );

    let invalid_enum = exercise_bytes
        .windows(b"exercise".len())
        .position(|window| window == b"exercise")
        .map(|offset| {
            let mut bytes = exercise_bytes.clone();
            bytes.splice(offset..offset + b"exercise".len(), b"invalid".iter().copied());
            bytes
        })
        .expect("exercise enum occurrence");
    assert_eq!(
        decode_exercise_decision_json_v1(&invalid_enum),
        Err(PromptCodecErrorV1::Json)
    );
}

#[test]
fn oversized_payload_is_rejected_before_parse() {
    let bytes = vec![b' '; 262_145];
    assert_eq!(
        decode_candidate_set_receipt_json_v1(&bytes),
        Err(PromptCodecErrorV1::EncodedSize)
    );
}
