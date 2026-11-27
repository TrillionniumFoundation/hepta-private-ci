use pretty_assertions::assert_eq;
use serde_json::json;

use super::McpServerConfig;

fn server() -> serde_json::Value {
    json!({"url": "http://localhost:8181/mcp"})
}

#[test]
fn owner_oauth_config_defaults_to_no_extra_origins() {
    let config: McpServerConfig = serde_json::from_value(server()).unwrap();
    assert!(config.oauth_authorization_origins().is_empty());
    let mut value = server();
    value["oauth"] = json!({"client_id": "owner-client"});
    let config: McpServerConfig = serde_json::from_value(value).unwrap();
    assert!(config.oauth_authorization_origins().is_empty());
    assert!(
        serde_json::to_value(config).unwrap()["oauth"]
            .get("authorization_origins")
            .is_none()
    );
}

#[test]
fn explicit_owner_oauth_config_round_trips_exact_grants() {
    let mut value = server();
    value["oauth"] = json!({
        "client_id": "owner-client",
        "callback_port": 43111,
        "authorization_origins": ["http://localhost:8383", "https://authorization.example"]
    });
    let config: McpServerConfig = serde_json::from_value(value).unwrap();
    assert_eq!(
        config.oauth_authorization_origins().as_slice(),
        &[
            "http://localhost:8383".to_string(),
            "https://authorization.example".to_string()
        ]
    );
    assert_eq!(config.oauth_client_id(), Some("owner-client"));
    assert_eq!(
        config.oauth_callback_port(/*global_callback_port*/ None),
        Some(43111)
    );
    let encoded = serde_json::to_value(&config).unwrap();
    let recovered: McpServerConfig = serde_json::from_value(encoded).unwrap();
    assert_eq!(recovered, config);
}

#[test]
fn owner_oauth_config_rejects_duplicate_noncanonical_and_wrong_type_grants() {
    for invalid in [
        json!(null),
        json!({"origin": "http://localhost:8383"}),
        json!(["http://localhost:8383", "http://localhost:8383"]),
        json!(["http://localhost:8383/path"]),
        json!(["http://localhost:8383/"]),
        json!(["http://user:password@localhost:8383"]),
        json!(["http://169.254.169.254"]),
    ] {
        let mut value = server();
        value["oauth"] = json!({"authorization_origins": invalid});
        assert!(serde_json::from_value::<McpServerConfig>(value).is_err());
    }
}
