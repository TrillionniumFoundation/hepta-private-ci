use super::*;
use crate::error::{ControlError, ErrorCode};
use pretty_assertions::assert_eq;
use serde_json::json;

fn invalid_error() -> ControlError {
    ControlError::new(ErrorCode::InvalidInput)
}

#[test]
fn canonical_order_matches_javascript_utf16_and_integer_key_vectors() {
    assert_eq!(
        canonical_json(&json!({"2":"two", "10":"ten", "\u{e000}":1, "😀":2})),
        Ok("{\"10\":\"ten\",\"2\":\"two\",\"😀\":2,\"\u{e000}\":1}".to_owned())
    );
    assert_eq!(
        canonical_json(&json!([1.0, -0.0, -9_007_199_254_740_991_i64])),
        Ok("[1,0,-9007199254740991]".to_owned())
    );
}

#[test]
fn digests_match_javascript_domain_separation() {
    assert_eq!(
        digest_canonical("hepta.ui-control.one.v1", &json!({"a":1})),
        Ok("bfe5e678e651a84acdf10b3b23b9365c5f9556c67a6f7a254f06b66fc513e21f".to_owned())
    );
    assert_ne!(
        digest_canonical("hepta.ui-control.one.v1", &json!({"a":1})),
        digest_canonical("hepta.ui-control.two.v1", &json!({"a":1}))
    );
}

#[test]
fn canonical_rejects_unsafe_numbers_keys_text_and_noncanonical_encodings() {
    for value in [
        json!(9_007_199_254_740_992_u64),
        json!(-9_007_199_254_740_992_i64),
        json!(1.5),
        json!({"__proto__":1}),
        json!({"nested":{"constructor":false}}),
        json!({"":1}),
        json!("e\u{301}"),
        json!("a\u{202e}b"),
        json!("a\u{0}b"),
        json!("a\u{200b}b"),
        json!("a\u{feff}b"),
    ] {
        assert_eq!(canonical_json(&value), Err(invalid_error()), "{value:?}");
    }
    for text in [
        "{\"b\":1,\"a\":2}",
        "{\"a\":1,\"a\":2}",
        "[1.0]",
        "[-0]",
        "[1e0]",
        " null",
        "\"\\u0061\"",
        "\"\\ud800\"",
    ] {
        assert_eq!(parse_canonical_json(text), Err(invalid_error()), "{text}");
    }
    assert_eq!(
        parse_canonical_json("{\"a\":2,\"b\":1}"),
        Ok(json!({"a":2,"b":1}))
    );
}

#[test]
fn wire_parser_rejects_duplicate_keys_at_every_depth_without_requiring_key_order() {
    for text in [
        "{\"a\":1,\"a\":2}",
        "{\"x\":[{\"a\":1,\"a\":2}]}",
        "{\"a\":1,\"\\u0061\":2}",
        "{\"prototype\":1}",
        "[] false",
        "\"\\ud800\"",
    ] {
        assert_eq!(
            parse_bounded_json(text, CanonicalLimits::default()),
            Err(invalid_error()),
            "{text}"
        );
    }
    assert_eq!(
        parse_bounded_json(" { \"b\": 1, \"a\": 2 } ", CanonicalLimits::default()),
        Ok(json!({"a":2,"b":1}))
    );
}

#[test]
fn independently_enforces_each_resource_limit() {
    let cases = [
        (
            json!([[0]]),
            CanonicalLimits {
                max_depth: 1,
                ..CanonicalLimits::default()
            },
        ),
        (
            json!({"x":[1,2]}),
            CanonicalLimits {
                max_entries: 2,
                ..CanonicalLimits::default()
            },
        ),
        (
            json!([1, 2]),
            CanonicalLimits {
                max_array_length: 1,
                ..CanonicalLimits::default()
            },
        ),
        (
            json!("é"),
            CanonicalLimits {
                max_string_bytes: 1,
                ..CanonicalLimits::default()
            },
        ),
        (
            json!([1, 2]),
            CanonicalLimits {
                max_encoded_bytes: 4,
                ..CanonicalLimits::default()
            },
        ),
    ];
    for (value, limits) in cases {
        assert_eq!(
            canonical_json_with_limits(&value, limits),
            Err(invalid_error())
        );
        assert_eq!(
            parse_bounded_json(&value.to_string(), limits),
            Err(invalid_error())
        );
    }
    for limits in [
        CanonicalLimits {
            max_depth: 65,
            ..CanonicalLimits::default()
        },
        CanonicalLimits {
            max_encoded_bytes: 0,
            ..CanonicalLimits::default()
        },
        CanonicalLimits {
            max_entries: 1_000_001,
            ..CanonicalLimits::default()
        },
    ] {
        assert_eq!(
            canonical_json_with_limits(&json!(null), limits),
            Err(invalid_error())
        );
    }
    assert_eq!(
        canonical_json_with_limits(
            &json!([]),
            CanonicalLimits {
                max_depth: 0,
                max_entries: 0,
                max_array_length: 0,
                max_string_bytes: 0,
                max_encoded_bytes: 2
            }
        ),
        Ok("[]".to_owned())
    );
}

#[test]
fn identifiers_and_digests_are_bounded_and_nonzero() {
    for text in ["", "with spaces", "日本語", "operator/role", "a\u{202e}"] {
        assert_eq!(assert_stable_identifier(text), Err(invalid_error()));
    }
    assert_eq!(
        assert_stable_identifier("runtime.agentd-1:local"),
        Ok("runtime.agentd-1:local")
    );
    assert_eq!(assert_sha256(&"0".repeat(64)), Err(invalid_error()));
    assert_eq!(assert_sha256(&"A".repeat(64)), Err(invalid_error()));
    assert!(assert_sha256_allow_zero(&"0".repeat(64)).is_ok());
    assert!(constant_time_equal("same", "same"));
    assert!(!constant_time_equal("same", "diff"));
    assert!(!constant_time_equal("same", "longer"));
}
