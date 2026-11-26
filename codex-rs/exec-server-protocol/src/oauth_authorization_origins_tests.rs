use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde_json::json;

use super::HttpRequestParams;
use super::HttpRequestRestrictedParams;

fn wire_request() -> serde_json::Value {
    json!({
        "request": {
            "method": "GET",
            "url": "http://localhost:8383/metadata",
            "requestId": "owner-origin-control",
            "streamResponse": true
        },
        "configuredResourceOrigin": "http://localhost:8181"
    })
}

#[test]
fn restricted_rpc_omits_empty_grants_and_round_trips_explicit_origins() {
    let old = wire_request();
    let parsed: HttpRequestRestrictedParams = serde_json::from_value(old).unwrap();
    assert!(parsed.authorization_origins.is_empty());
    let empty_wire = serde_json::to_value(&parsed).unwrap();
    assert!(empty_wire.get("authorizationOrigins").is_none());

    let mut granted = empty_wire.clone();
    granted["authorizationOrigins"] = json!(["http://localhost:8383"]);
    let parsed: HttpRequestRestrictedParams = serde_json::from_value(granted.clone()).unwrap();
    assert_eq!(parsed.configured_resource_origin, "http://localhost:8181");
    assert_eq!(serde_json::to_value(parsed).unwrap(), granted);
}

#[test]
fn restricted_rpc_rejects_unknown_fields_and_unvalidated_origin_lists() {
    for invalid in [
        json!(null),
        json!("http://localhost:8383"),
        json!(["http://localhost:8383/"]),
        json!(["http://localhost:8383", "http://localhost:8383"]),
        json!({"origin": "http://localhost:8383"}),
    ] {
        let mut wire = wire_request();
        wire["authorizationOrigins"] = invalid;
        assert!(serde_json::from_value::<HttpRequestRestrictedParams>(wire).is_err());
    }
    let mut wire = wire_request();
    wire["allowAllLocalhost"] = json!(true);
    assert!(serde_json::from_value::<HttpRequestRestrictedParams>(wire).is_err());
}

#[test]
fn nonempty_grants_fail_closed_at_the_previous_strict_rpc_shape() {
    #[derive(Deserialize)]
    #[serde(rename_all = "camelCase", deny_unknown_fields)]
    struct PreviousRestrictedParams {
        request: HttpRequestParams,
        configured_resource_origin: String,
    }

    let old: PreviousRestrictedParams = serde_json::from_value(wire_request()).unwrap();
    assert_eq!(old.configured_resource_origin, "http://localhost:8181");
    assert_eq!(old.request.request_id, "owner-origin-control");
    let mut newer = wire_request();
    newer["authorizationOrigins"] = json!(["http://localhost:8383"]);
    assert!(serde_json::from_value::<PreviousRestrictedParams>(newer).is_err());
}
