use super::ConfigManager;
use codex_core::config::Config;
use codex_extension_api::ExtensionData;
use codex_extension_api::ExtensionRegistryBuilder;
use codex_extension_api::ThreadStartInput;
use codex_features::Feature;
use codex_login::AuthManager;
use codex_login::CodexAuth;
use codex_protocol::protocol::SessionSource;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::collections::HashMap;

#[tokio::test]
async fn required_token_budget_off_removes_resolved_history_notes_after_request_and_reload()
-> anyhow::Result<()> {
    let home = tempfile::tempdir()?;
    let manager = ConfigManager::without_managed_config_for_tests(home.path().to_path_buf());
    let request = HashMap::from([(
        "features".to_string(),
        json!({
            "token_budget": {
                "enabled": true,
                "use_history_notes_extension": true
            }
        }),
    )]);
    let enabled = manager
        .load_for_cwd(
            Some(request.clone()),
            Default::default(),
            Some(home.path().to_path_buf()),
        )
        .await?;
    assert!(enabled.features.enabled(Feature::TokenBudget));
    assert!(
        enabled
            .token_budget
            .as_ref()
            .is_some_and(|budget| budget.use_history_notes_extension)
    );

    // Use the real extension with fixture auth; no backend request is sent.
    let mut builder = ExtensionRegistryBuilder::<Config>::new();
    codex_history_notes_extension::install(
        &mut builder,
        AuthManager::from_auth_for_testing(CodexAuth::create_dummy_chatgpt_auth_for_testing()),
    );
    let registry = builder.build();
    let session = ExtensionData::new("required-feature-session");
    let thread = ExtensionData::new("required-feature-thread");
    for contributor in registry.thread_lifecycle_contributors() {
        contributor
            .on_thread_start(ThreadStartInput {
                config: &enabled,
                session_source: &SessionSource::Cli,
                installation_id: "required-feature-fixture",
                persistent_thread_state_available: true,
                environments: &[],
                mcp_resource_client: None,
                extension_metrics: None,
                session_store: &session,
                thread_store: &thread,
            })
            .await;
    }
    assert!(
        registry
            .tool_contributors()
            .iter()
            .any(|contributor| !contributor.tools(&session, &thread).is_empty())
    );

    manager
        .require_feature_states([(Feature::TokenBudget, false)])
        .expect("host constraint lock");
    let disabled = manager
        .load_for_cwd(
            Some(request),
            Default::default(),
            Some(home.path().to_path_buf()),
        )
        .await?;
    let reloaded = manager.load_latest_config_for_thread(&enabled).await?;
    for config in [&disabled, &reloaded] {
        assert_eq!(
            (
                config.features.enabled(Feature::TokenBudget),
                config.token_budget.is_none(),
            ),
            (false, true),
        );
    }
    for contributor in registry.config_contributors() {
        contributor.on_config_changed(&session, &thread, &enabled, &disabled);
    }
    assert!(
        registry
            .tool_contributors()
            .iter()
            .all(|contributor| contributor.tools(&session, &thread).is_empty())
    );
    Ok(())
}
