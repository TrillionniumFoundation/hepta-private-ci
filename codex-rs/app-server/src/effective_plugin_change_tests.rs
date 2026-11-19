use super::*;
use codex_plugin::PluginId;
use pretty_assertions::assert_eq;

#[test]
fn only_workspace_listed_materializations_are_eligible() {
    let materialization =
        |name: &str,
         scope: RemotePluginScope,
         discoverability: Option<RemotePluginShareDiscoverability>| {
            RemotePluginMaterialization {
                plugin_id: PluginId::new(name.to_string(), "test".to_string())
                    .expect("valid plugin id"),
                scope,
                discoverability,
                authenticated_account_id: Some("account-123".to_string()),
            }
        };

    let mut materializations = vec![
        materialization(
            "eligible",
            RemotePluginScope::Workspace,
            Some(RemotePluginShareDiscoverability::Listed),
        ),
        materialization(
            "unlisted",
            RemotePluginScope::Workspace,
            Some(RemotePluginShareDiscoverability::Unlisted),
        ),
        materialization(
            "private",
            RemotePluginScope::Workspace,
            Some(RemotePluginShareDiscoverability::Private),
        ),
        materialization("workspace-missing", RemotePluginScope::Workspace, None),
        materialization("global", RemotePluginScope::Global, None),
        materialization("user", RemotePluginScope::User, None),
    ];
    let mut wrong_account = materialization(
        "wrong-account",
        RemotePluginScope::Workspace,
        Some(RemotePluginShareDiscoverability::Listed),
    );
    wrong_account.authenticated_account_id = Some("account-456".to_string());
    materializations.push(wrong_account);

    let plugin_ids = workspace_listed_plugin_ids(materializations, "account-123");

    assert_eq!(plugin_ids, BTreeSet::from(["eligible@test".to_string()]));
}

#[test]
fn hook_trusted_hash_edit_targets_only_escaped_leaf() {
    assert_eq!(
        hook_trusted_hash_edit(r#"plugin."quoted"\path"#, "sha256:current"),
        ConfigEdit {
            key_path: r#"hooks.state."plugin.\"quoted\"\\path".trusted_hash"#.to_string(),
            value: serde_json::json!("sha256:current"),
            merge_strategy: MergeStrategy::Replace,
        }
    );
}

#[tokio::test]
async fn retained_plugin_callback_does_not_keep_closed_runtime_owner_alive() {
    for queue_completion in [false, true] {
        let home = tempfile::TempDir::new().expect("temporary home");
        let config = core_test_support::load_default_config_for_test(&home).await;
        let manager = Arc::new(
            codex_core::test_support::thread_manager_with_models_provider_and_home(
                codex_login::CodexAuth::from_api_key("public-test-only"),
                config.model_provider.clone(),
                home.path().to_path_buf(),
                Arc::new(codex_exec_server::EnvironmentManager::default_for_tests()),
            ),
        );
        let owner = Arc::downgrade(&manager);
        let auth = manager.auth_manager();
        let analytics =
            crate::analytics_utils::analytics_events_client_from_config(Arc::clone(&auth), &config);
        let (sender, _receiver) = tokio::sync::mpsc::channel(8);
        let outgoing = Arc::new(crate::outgoing_message::OutgoingMessageSender::new(
            sender,
            analytics.clone(),
        ));
        let configs = ConfigManager::new(
            home.path().to_path_buf(),
            Vec::new(),
            codex_config::LoaderOverrides::without_managed_config_for_tests(),
            /*strict_config*/ false,
            codex_config::CloudConfigBundleLoader::default(),
            codex_arg0::Arg0DispatchPaths::default(),
            Arc::new(codex_config::NoopThreadConfigLoader),
        );
        // A background marketplace sync can retain this completion callback long
        // after its original App Server has closed. It must not own that runtime.
        let callback = effective_plugins_changed_callback(
            auth,
            Arc::clone(&manager),
            configs,
            outgoing,
            analytics,
            RequestSerializationQueues::default(),
        );
        if queue_completion {
            callback(EffectivePluginsChange {
                materialized_remote_plugins: vec![RemotePluginMaterialization {
                    plugin_id: PluginId::new("qualified".into(), "fixture".into())
                        .expect("plugin ID"),
                    scope: RemotePluginScope::Workspace,
                    discoverability: Some(RemotePluginShareDiscoverability::Listed),
                    authenticated_account_id: Some("test-account".into()),
                }],
            });
        }
        // No spawned task can run before the next yield in this current-thread
        // test. Queued refresh/config work must also defer upgrading the owner.
        drop(manager);
        assert!(
            owner.upgrade().is_none(),
            "plugin completion retained the closed runtime owner"
        );
        callback(EffectivePluginsChange::default());
        tokio::task::yield_now().await;
        assert!(
            owner.upgrade().is_none(),
            "late completion resurrected its original owner"
        );
    }
}
