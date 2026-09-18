use super::*;

use crate::test_support::digest;
use crate::test_support::id;

#[test]
fn prompt_factor_v1_round_trips_canonical_json_and_rejects_unknown_fields() {
    let value = PromptFactorV1 {
        factor_id: id("factor:1"),
        semantic_purpose: "Verify evidence before making a claim".to_string(),
        authority_class: "registered_prompt_factor".to_string(),
        eligible_objective_dimensions: vec![id("dimension:evidence"), id("dimension:truth")],
        lifecycle: Lifecycle::Admitted,
        revision: Revision::new(7).expect("revision"),
    };
    let encoded = encode_prompt_factor_v1(&value).expect("encode factor");
    assert_eq!(
        decode_prompt_factor_v1(&encoded).expect("decode factor"),
        value
    );

    let mut unknown = String::from_utf8(encoded.clone()).expect("utf8");
    let index = unknown.len() - 1;
    unknown.insert_str(index, ",\"unknownCritical\":true");
    assert!(matches!(
        decode_prompt_factor_v1(unknown.as_bytes()),
        Err(PromptProtocolError::InvalidJson(_))
    ));

    let mut noncanonical = b" ".to_vec();
    noncanonical.extend_from_slice(&encoded);
    assert_eq!(
        decode_prompt_factor_v1(&noncanonical),
        Err(PromptProtocolError::NonCanonical)
    );
}

#[test]
fn prompt_factor_v1_requires_canonical_dimension_order() {
    let value = PromptFactorV1 {
        factor_id: id("factor:1"),
        semantic_purpose: "purpose".to_string(),
        authority_class: "registered".to_string(),
        eligible_objective_dimensions: vec![id("dimension:z"), id("dimension:a")],
        lifecycle: Lifecycle::Draft,
        revision: Revision::new(1).expect("revision"),
    };
    assert_eq!(
        encode_prompt_factor_v1(&value),
        Err(PromptProtocolError::InvalidField(
            "eligibleObjectiveDimensions"
        ))
    );
}

#[test]
fn prompt_realization_v1_round_trips_and_is_payload_digest_bound() {
    let value = PromptRealizationV1 {
        factor_id: id("factor:1"),
        model_id: id("model:gpt"),
        model_version: "2026-09-17".to_string(),
        tokenizer_digest: digest("tokenizer"),
        system_template_digest: digest("system-template"),
        message_role: PromptRoleV2::DeveloperInstruction,
        payload_digest: digest("payload"),
        token_cost_upper_bound: 32,
        expires_unix_ms: Some(1_000),
    };
    let encoded = encode_prompt_realization_v1(&value).expect("encode realization");
    assert_eq!(
        decode_prompt_realization_v1(&encoded).expect("decode realization"),
        value
    );

    let mut unknown = String::from_utf8(encoded).expect("utf8");
    let index = unknown.len() - 1;
    unknown.insert_str(index, ",\"extra\":1");
    assert!(matches!(
        decode_prompt_realization_v1(unknown.as_bytes()),
        Err(PromptProtocolError::InvalidJson(_))
    ));
}

#[test]
fn prompt_realization_v1_rejects_zero_digest_and_zero_token_cost() {
    let mut value = PromptRealizationV1 {
        factor_id: id("factor:1"),
        model_id: id("model:gpt"),
        model_version: "v1".to_string(),
        tokenizer_digest: digest("tokenizer"),
        system_template_digest: digest("template"),
        message_role: PromptRoleV2::SystemInstruction,
        payload_digest: digest("payload"),
        token_cost_upper_bound: 1,
        expires_unix_ms: None,
    };
    value.payload_digest = Digest32::ZERO;
    assert_eq!(
        encode_prompt_realization_v1(&value),
        Err(PromptProtocolError::InvalidDigest("payloadDigest"))
    );
    value.payload_digest = digest("payload");
    value.token_cost_upper_bound = 0;
    assert_eq!(
        encode_prompt_realization_v1(&value),
        Err(PromptProtocolError::InvalidField("tokenCostUpperBound"))
    );
}
