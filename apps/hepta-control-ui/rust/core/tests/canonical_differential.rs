use hepta_control_core::canonical::{
    CanonicalLimits, canonical_json, digest_canonical, parse_canonical_json,
};
use hepta_control_core::error::ControlError;
use serde::Serialize;
use serde_json::{Value, json};

fn outcome<T: Serialize>(result: Result<T, ControlError>) -> Value {
    match result {
        Ok(value) => json!({ "ok": value }),
        Err(error) => json!({ "error": error.code.as_str(), "retryable": error.retryable }),
    }
}

#[test]
fn canonical_json_matches_actual_javascript_vectors() {
    let fixture: Value =
        serde_json::from_str(include_str!("fixtures/javascript-reference.json")).unwrap();
    for case in fixture["canonical"].as_array().unwrap() {
        let mut limits = CanonicalLimits::default();
        for (key, value) in case["limits"].as_object().unwrap() {
            let value = value.as_u64().unwrap() as usize;
            match key.as_str() {
                "maxDepth" => limits.max_depth = value,
                "maxEntries" => limits.max_entries = value,
                "maxArrayLength" => limits.max_array_length = value,
                "maxStringBytes" => limits.max_string_bytes = value,
                "maxEncodedBytes" => limits.max_encoded_bytes = value,
                _ => panic!("unexpected fixture limit"),
            }
        }
        let input = case["input"].as_str().unwrap();
        if let Some(expected) = case.get("result") {
            let decoded = serde_json::from_str(input).map_err(|_| ControlError::invalid());
            let result = decoded.and_then(|value| canonical_json(&value, &limits));
            assert_eq!(outcome(result), *expected, "canonical: {}", case["name"]);
        }
        assert_eq!(
            outcome(parse_canonical_json(input, &limits)),
            case["parse"],
            "parse: {}",
            case["name"]
        );
    }
    for case in fixture["domains"].as_array().unwrap() {
        assert_eq!(
            digest_canonical(
                case["domain"].as_str().unwrap(),
                &case["value"],
                &CanonicalLimits::default()
            )
            .unwrap(),
            case["digest"]
        );
    }
}

#[test]
fn bounded_decoder_rejects_duplicate_escaped_keys_and_deep_oversized_inputs() {
    for input in [
        r#"{"a":1,"\u0061":2}"#,
        r#"{"x":{"a":1,"a":2}}"#,
        "[9007199254740992]",
        "1e400",
    ] {
        assert!(
            parse_canonical_json(input, &CanonicalLimits::default()).is_err(),
            "{input}"
        );
    }
    let depth = format!("{}0{}", "[".repeat(65), "]".repeat(65));
    assert!(
        parse_canonical_json(
            &depth,
            &CanonicalLimits {
                max_depth: 64,
                ..CanonicalLimits::default()
            }
        )
        .is_err()
    );
    let at_depth = format!("{}0{}", "[".repeat(64), "]".repeat(64));
    assert!(
        parse_canonical_json(
            &at_depth,
            &CanonicalLimits {
                max_depth: 64,
                ..CanonicalLimits::default()
            }
        )
        .is_ok()
    );
    assert!(
        parse_canonical_json(
            "[]",
            &CanonicalLimits {
                max_encoded_bytes: 1,
                ..CanonicalLimits::default()
            }
        )
        .is_err()
    );
    assert!(canonical_json(&json!({ "a".repeat(257): 1 }), &CanonicalLimits::default()).is_err());
}
