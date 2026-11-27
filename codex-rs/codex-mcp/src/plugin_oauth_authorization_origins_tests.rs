use pretty_assertions::assert_eq;

use super::parse_executor_plugin_mcp_config;
use super::parse_plugin_mcp_config;
use codex_utils_path_uri::PathUri;

#[test]
fn plugin_manifests_cannot_grant_additional_oauth_origins_on_host_or_executor() {
    let root = std::env::current_dir()
        .unwrap()
        .join("plugin-origin-control");
    let uri = PathUri::from_host_native_path(&root).unwrap();
    let contents = r#"{"demo":{"url":"http://localhost:8181/mcp","oauth":{"authorization_origins":["http://localhost:8383"]}}}"#;
    let host = parse_plugin_mcp_config(&root, contents).unwrap();
    let executor =
        parse_executor_plugin_mcp_config(&uri, contents, "remote-origin-control").unwrap();
    for result in [host, executor] {
        assert!(result.servers.is_empty());
        assert_eq!(result.errors.len(), 1);
        assert_eq!(result.errors[0].name, "demo");
        assert_eq!(
            result.errors[0].message,
            "OAuth authorization origins require explicit owner configuration; plugin manifests cannot grant them"
        );
    }
}

#[test]
fn plugin_oauth_client_settings_without_origin_grants_remain_usable() {
    let root = std::env::current_dir()
        .unwrap()
        .join("plugin-origin-control");
    let contents = r#"{"demo":{"url":"http://localhost:8181/mcp","oauth":{"clientId":"plugin-client","callbackPort":43111,"authorization_origins":[]}}}"#;
    let result = parse_plugin_mcp_config(&root, contents).unwrap();
    assert!(result.errors.is_empty());
    let server = &result.servers["demo"];
    assert_eq!(server.oauth_client_id(), Some("plugin-client"));
    assert_eq!(
        server.oauth_callback_port(/*global_callback_port*/ None),
        Some(43111)
    );
    assert!(server.oauth_authorization_origins().is_empty());
}
