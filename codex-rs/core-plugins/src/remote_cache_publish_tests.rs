use super::*;
use crate::test_support::test_http_client_factory;
use pretty_assertions::assert_eq;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;
use wiremock::matchers::path;
use wiremock::matchers::query_param;

async fn catalog_server() -> (MockServer, RemotePluginServiceConfig) {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/backend-api/ps/plugins/list"))
        .and(query_param("scope", "GLOBAL"))
        .respond_with(
            ResponseTemplate::new(/*s*/ 200).set_body_json(serde_json::json!({
                "plugins": [{
                    "id": "catalog-fixture-id",
                    "name": "catalog-fixture",
                    "scope": "GLOBAL",
                    "installation_policy": "AVAILABLE",
                    "authentication_policy": "ON_USE",
                    "release": {
                        "display_name": "Catalog fixture",
                        "description": "Cache publication fixture",
                        "interface": {},
                    },
                }],
                "pagination": {"next_page_token": null},
            })),
        )
        .expect(/*r*/ 1)
        .mount(&server)
        .await;
    let config = RemotePluginServiceConfig::new(
        format!("{}/backend-api", server.uri()),
        test_http_client_factory(),
    );
    (server, config)
}

#[tokio::test]
async fn catalog_refresh_propagates_publication_failure() {
    let codex_home = tempfile::tempdir().expect("create codex home");
    let blocked_parent = codex_home.path().join("cache");
    std::fs::write(&blocked_parent, "retained parent bytes").expect("block cache directory");
    let (server, config) = catalog_server().await;
    let auth = CodexAuth::create_dummy_chatgpt_auth_for_testing();

    let error =
        fetch_and_cache_global_remote_plugin_catalog(codex_home.path(), &config, Some(&auth))
            .await
            .expect_err("network success must not disguise failed cache publication");

    let display = error.to_string();
    assert!(matches!(
        error,
        RemotePluginCatalogError::CachePublish { .. }
    ));
    assert!(display.contains("kind="));
    assert!(display.contains("os_code="));
    assert!(!display.contains(&codex_home.path().to_string_lossy().to_string()));
    assert!(!display.contains(&server.uri()));
    assert_eq!(
        std::fs::read_to_string(blocked_parent).unwrap(),
        "retained parent bytes"
    );
    assert!(!has_fresh_cached_remote_plugin_catalog(
        codex_home.path(),
        &config,
        Some(&auth),
        RemotePluginScope::Global,
    ));
    server.verify().await;
}

#[tokio::test]
async fn foreground_catalog_retains_fetched_plugins_when_publication_fails() {
    let codex_home = tempfile::tempdir().expect("create codex home");
    let blocked_parent = codex_home.path().join("cache");
    std::fs::write(&blocked_parent, "retained parent bytes").expect("block cache directory");
    let (server, config) = catalog_server().await;
    let auth = CodexAuth::create_dummy_chatgpt_auth_for_testing();

    let outcome = fetch_directory_plugins_for_scope_with_cache(
        Some(codex_home.path()),
        &config,
        &auth,
        RemotePluginScope::Global,
        RemotePluginCatalogCacheMode::PreferCache,
    )
    .await
    .expect("foreground catalog remains available without a writable disk cache");

    assert_eq!(outcome.plugins.len(), 1);
    assert_eq!(outcome.plugins[0].id, "catalog-fixture-id");
    assert!(!outcome.cache_refresh_needed);
    assert_eq!(
        std::fs::read_to_string(blocked_parent).unwrap(),
        "retained parent bytes"
    );
    server.verify().await;
}
