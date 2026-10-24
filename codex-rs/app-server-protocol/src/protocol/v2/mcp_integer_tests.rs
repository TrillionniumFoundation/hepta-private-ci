use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

#[test]
fn integer_schema_and_reply_preserve_exact_values_across_protocol_conversions() {
    for exact in [9_007_199_254_740_993_i64, -9_007_199_254_740_993_i64] {
        let wire_schema = json!({
            "type": "object",
            "properties": {
                "value": {
                    "type": "integer",
                    "minimum": i64::MIN,
                    "maximum": i64::MAX,
                    "default": exact,
                },
            },
            "required": ["value"],
        });
        let vendor_schema: rmcp::model::ElicitationSchema =
            serde_json::from_value(wire_schema.clone()).expect("valid vendor integer schema");
        let request = McpServerElicitationRequest::try_from(CoreElicitationRequest::Form {
            meta: None,
            message: "Confirm the exact value".to_string(),
            requested_schema: serde_json::to_value(vendor_schema)
                .expect("vendor schema wire value"),
        })
        .expect("exact integer form should convert");

        assert_eq!(
            serde_json::to_value(request).expect("app-server request wire value"),
            json!({
                "mode": "form",
                "_meta": null,
                "message": "Confirm the exact value",
                "requestedSchema": wire_schema,
            })
        );

        let reply: McpServerElicitationRequestResponse = serde_json::from_value(json!({
            "action": "accept",
            "content": {"value": exact},
            "_meta": null,
        }))
        .expect("exact integer reply should deserialize");
        let mut expected = rmcp::model::ElicitResult::new(rmcp::model::ElicitationAction::Accept);
        expected.content = Some(json!({"value": exact}));
        assert_eq!(rmcp::model::ElicitResult::from(reply), expected);
    }
}

#[test]
fn numeric_schema_rejects_non_numeric_bounds_and_defaults() {
    for field in ["minimum", "maximum", "default"] {
        for invalid in [json!("9007199254740993"), json!(true), json!([]), json!({})] {
            let mut wire = json!({"type": "integer"});
            wire[field] = invalid;
            assert!(serde_json::from_value::<McpElicitationNumberSchema>(wire).is_err());
        }
    }
}

#[test]
fn fractional_number_schema_preserves_numeric_values() {
    let wire = json!({
        "type": "number",
        "minimum": 1.25,
        "maximum": 99.75,
        "default": 30.5,
    });
    let schema: McpElicitationPrimitiveSchema =
        serde_json::from_value(wire.clone()).expect("fractional number schema");
    assert_eq!(
        serde_json::to_value(schema).expect("numeric wire value"),
        wire
    );
}
