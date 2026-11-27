use pretty_assertions::assert_eq;
use serde_json::json;
use toml_edit::DocumentMut;

use super::*;

fn server(origins: Vec<&str>) -> McpServerConfig {
    serde_json::from_value(json!({
        "url": "http://localhost:8181/mcp",
        "oauth": {
            "client_id": "retained-owner",
            "callback_port": 43111,
            "authorization_origins": origins
        }
    }))
    .unwrap()
}

fn from_inline(value: &InlineTable) -> McpServerConfig {
    let value: toml::Value = toml::from_str(&format!("server = {value}")).unwrap();
    value["server"].clone().try_into().unwrap()
}

#[test]
fn mcp_server_table_and_inline_edit_preserve_exact_owner_oauth_grants() {
    let configured = server(vec![
        "http://localhost:8383",
        "https://authorization.example",
    ]);
    // Render nested tables through the document writer used by config edits.
    let table = DocumentMut::from(serialize_mcp_server_table(&configured));
    let restored: McpServerConfig = toml::from_str(&table.to_string()).unwrap();
    assert_eq!(restored, configured);
    assert_eq!(
        from_inline(&serialize_mcp_server_inline(&configured)),
        configured
    );
}

#[test]
fn replacement_with_empty_grants_revokes_old_inline_and_table_authority() {
    let original = server(vec!["http://localhost:8383"]);
    let revoked = server(Vec::new());
    let mut inline = serialize_mcp_server_inline(&original);
    merge_inline_table(&mut inline, serialize_mcp_server_inline(&revoked));
    let after = from_inline(&inline);
    assert_eq!(after, revoked);
    assert!(after.oauth_authorization_origins().is_empty());
    assert!(!inline.to_string().contains("authorization_origins"));
    let table = DocumentMut::from(serialize_mcp_server_table(&revoked));
    assert!(!table.to_string().contains("authorization_origins"));
    let restored: McpServerConfig = toml::from_str(&table.to_string()).unwrap();
    assert_eq!(restored, revoked);
    assert_eq!(restored.oauth_client_id(), Some("retained-owner"));
    assert_eq!(
        restored.oauth_callback_port(/*global_callback_port*/ None),
        Some(43111)
    );
}
