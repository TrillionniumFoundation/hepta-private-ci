use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::SignedFinalUseGrant;
use serde_json::Value;
use serde_json::json;

use super::super::BrowserFinalUseInvocation;
use super::super::DecodedFrame;
use super::super::canonical_json;
use super::super::hex_lower;
use super::response_result;

fn invocation() -> BrowserFinalUseInvocation {
    let binding = FinalUseBinding {
        subject_id: "principal.1".to_string(),
        destination_id: "browser.profile.1".to_string(),
        request_sha256: [0x11; 32],
        scope_sha256: [0x22; 32],
        payload_sha256: [0x33; 32],
    };
    BrowserFinalUseInvocation {
        signed_grant: SignedFinalUseGrant {
            grant: FinalUseGrant {
                schema_version: 1,
                signer_id: "test".to_string(),
                authority_epoch: 7,
                grant_id: "grant.1".to_string(),
                nonce: [0x44; 32],
                binding: binding.clone(),
                not_before_unix_ms: 1,
                expires_at_unix_ms: 2,
            },
            signature: vec![],
        },
        binding,
    }
}

fn fixture() -> (DecodedFrame, Value) {
    let input = json!({"profileId":"profile.1","principalId":"principal.1",
        "generation":1,"operationId":"operation.1"});
    let frame = DecodedFrame {
        kind: "response".to_string(),
        request_id: "request.1".to_string(),
        payload: json!({
            "ok":true,
            "replay":{
                "schema":"hepta.browser.replay-observation.v1",
                "profileId":"profile.1","principalId":"principal.1",
                "generation":1,"operationId":"operation.1",
                "requestDigest":hex_lower(&[0x11;32]),
                "semanticDigest":hex_lower(&[0x22;32]),
            },
            "result":{
                "kind":"BrowserEffectObservationV1","profileId":"profile.1",
                "operationId":"operation.1","semanticDigest":hex_lower(&[0x22;32]),
                "status":"succeeded","outcomeDigest":hex_lower(&[0x33;32]),
                "terminalObserved":true,"observationReason":"terminal_observed",
                "networkAuthority":false,"filesystemAuthority":false,
                "credentialExportAuthority":false,
            },
        }),
    };
    (frame, input)
}

#[test]
fn canonical_json_matches_node_utf8_and_integer_golden_vectors() {
    let vectors = [
        (
            json!({"2":"two","10":"ten","𐀀":"astral","":"private"}),
            r#"{"10":"ten","2":"two","":"private","𐀀":"astral"}"#,
        ),
        (
            json!({"nested":[-0.0,0,9_007_199_254_740_991_i64,-9_007_199_254_740_991_i64],"floatInteger":1.0}),
            r#"{"floatInteger":1,"nested":[0,0,9007199254740991,-9007199254740991]}"#,
        ),
        (
            json!({"nested":{"2":"two","10":"ten"},"text":"\u{8}\u{c}\n\r\t\"\\😀"}),
            r#"{"nested":{"10":"ten","2":"two"},"text":"\b\f\n\r\t\"\\😀"}"#,
        ),
    ];
    for (value, expected) in vectors {
        assert_eq!(canonical_json(&value).expect("canonical vector"), expected);
    }
    for value in [
        json!({"nested":[0.5]}),
        json!([9_007_199_254_740_992_u64]),
        json!([-9_007_199_254_740_992_i64]),
    ] {
        assert!(canonical_json(&value).is_err());
    }
}

#[test]
fn historical_observations_do_not_need_a_live_or_claimable_grant() {
    let (mut frame, input) = fixture();
    let invocation = invocation();
    // The grant is expired and unsigned; this is observation, not a new claim.
    assert_eq!(
        response_result(&frame, &input, &invocation).expect("replay"),
        frame.payload["result"]
    );
    frame.payload["result"]["status"] = json!("failed");
    assert!(response_result(&frame, &input, &invocation).is_ok());
    let mut float_input = input.clone();
    float_input["generation"] = json!(1.0);
    assert!(response_result(&frame, &float_input, &invocation).is_ok());
    frame.payload["result"]["status"] = json!("indeterminate");
    frame.payload["result"]["terminalObserved"] = json!(false);
    frame.payload["result"]["outcomeDigest"] = Value::Null;
    assert!(response_result(&frame, &input, &invocation).is_ok());
}

#[test]
fn replay_proof_binds_every_caller_identity_and_original_request() {
    for field in [
        "profileId",
        "principalId",
        "operationId",
        "generation",
        "requestDigest",
    ] {
        let (mut frame, input) = fixture();
        frame.payload["replay"][field] = if field == "generation" {
            json!(2)
        } else {
            json!("changed")
        };
        assert!(
            response_result(&frame, &input, &invocation()).is_err(),
            "{field}"
        );
    }
    let (mut frame, input) = fixture();
    frame.payload["replay"]["requestDigest"] = json!(hex_lower(&[0x55; 32]));
    assert!(response_result(&frame, &input, &invocation()).is_err());
}

#[test]
fn replay_result_cannot_change_identity_grant_authority_or_forge_terminality() {
    for field in ["profileId", "operationId", "semanticDigest"] {
        let (mut frame, input) = fixture();
        frame.payload["result"][field] = json!("changed");
        assert!(
            response_result(&frame, &input, &invocation()).is_err(),
            "{field}"
        );
    }
    for field in [
        "networkAuthority",
        "filesystemAuthority",
        "credentialExportAuthority",
    ] {
        let (mut frame, input) = fixture();
        frame.payload["result"][field] = json!(true);
        assert!(
            response_result(&frame, &input, &invocation()).is_err(),
            "{field}"
        );
    }
    for value in [Value::Null, json!(hex_lower(&[0; 32])), json!("wrong")] {
        let (mut frame, input) = fixture();
        frame.payload["result"]["outcomeDigest"] = value;
        assert!(response_result(&frame, &input, &invocation()).is_err());
    }
    let (mut frame, input) = fixture();
    frame.payload["result"]["terminalObserved"] = json!(false);
    assert!(response_result(&frame, &input, &invocation()).is_err());
}

#[test]
fn replay_is_an_explicit_closed_response_shape() {
    let (mut frame, input) = fixture();
    frame
        .payload
        .as_object_mut()
        .expect("payload")
        .remove("replay");
    assert!(response_result(&frame, &input, &invocation()).is_err());
    for layer in ["", "replay", "result"] {
        let (mut frame, input) = fixture();
        let object = if layer.is_empty() {
            &mut frame.payload
        } else {
            &mut frame.payload[layer]
        };
        object["unexpected"] = json!(true);
        assert!(response_result(&frame, &input, &invocation()).is_err());
    }
}
