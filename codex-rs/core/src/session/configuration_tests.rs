use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn reload_user_config_layer_updates_effective_apps_config() {
    let (session, _turn_context) = make_session_and_context().await;
    let codex_home = session.codex_home().await;
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    let config_toml_path = codex_home.join(CONFIG_TOML_FILE);
    std::fs::write(
        &config_toml_path,
        "[apps.calendar]\nenabled = false\ndestructive_enabled = false\n",
    )
    .expect("write user config");

    session.reload_user_config_layer().await;

    let config = session.get_config().await;
    let apps_toml = config
        .config_layer_stack
        .effective_config()
        .as_table()
        .and_then(|table| table.get("apps"))
        .cloned()
        .expect("apps table");
    let apps = codex_config::types::AppsConfigToml::deserialize(apps_toml)
        .expect("deserialize apps config");
    let app = apps
        .apps
        .get("calendar")
        .expect("calendar app config exists");

    assert!(!app.enabled);
    assert_eq!(app.destructive_enabled, Some(false));
}

#[tokio::test]
async fn reload_user_config_layer_keeps_previous_config_for_malformed_shell_policy() {
    let (session, _turn_context) = make_session_and_context().await;
    let codex_home = session.codex_home().await;
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    let config_toml_path = codex_home.join(CONFIG_TOML_FILE);
    std::fs::write(&config_toml_path, "[apps.calendar]\nenabled = false\n")
        .expect("write valid user config");
    session.reload_user_config_layer().await;
    let previous_config = session
        .get_config()
        .await
        .config_layer_stack
        .effective_user_config()
        .expect("previous user config");

    std::fs::write(
        &config_toml_path,
        r#"
[apps.calendar]
enabled = true

[shell_environment_policy]
exclude = ["SECRET_*", 17]
"#,
    )
    .expect("write malformed user config");

    session.reload_user_config_layer().await;

    let current_config = session
        .get_config()
        .await
        .config_layer_stack
        .effective_user_config()
        .expect("current user config");
    assert_eq!(current_config, previous_config);
}

#[tokio::test]
async fn reload_user_config_layer_updates_base_and_selected_profile_layers() {
    let (session, _turn_context) = make_session_and_context().await;
    let codex_home = session.codex_home().await;
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    let base_config_path = codex_home.join(CONFIG_TOML_FILE);
    let profile_config_path = codex_home.join("work.config.toml");
    std::fs::write(
        &base_config_path,
        "model = \"base\"\napproval_policy = \"on-request\"\n",
    )
    .expect("write base user config");
    std::fs::write(&profile_config_path, "model = \"profile-old\"\n")
        .expect("write profile user config");
    let config = ConfigBuilder::without_managed_config_for_tests()
        .codex_home(codex_home.to_path_buf())
        .loader_overrides(LoaderOverrides {
            user_config_path: Some(profile_config_path.abs()),
            user_config_profile: Some("work".parse().expect("profile-v2 name")),
            ..LoaderOverrides::without_managed_config_for_tests()
        })
        .build()
        .await
        .expect("load profile config");
    {
        let mut state = session.state.lock().await;
        state.session_configuration.original_config_do_not_use = Arc::new(config);
    }
    std::fs::write(
        &base_config_path,
        "model = \"base\"\napproval_policy = \"never\"\n",
    )
    .expect("update base user config");
    std::fs::write(&profile_config_path, "model = \"profile-new\"\n")
        .expect("update profile user config");

    session.reload_user_config_layer().await;

    let config = session.get_config().await;
    assert_eq!(
        config
            .config_layer_stack
            .get_user_config_file()
            .map(codex_utils_absolute_path::AbsolutePathBuf::as_path),
        Some(profile_config_path.as_path())
    );
    let effective_user_config = config
        .config_layer_stack
        .effective_user_config()
        .expect("merged user config");
    assert_eq!(
        effective_user_config
            .get("model")
            .and_then(toml::Value::as_str),
        Some("profile-new")
    );
    assert_eq!(
        effective_user_config
            .get("approval_policy")
            .and_then(toml::Value::as_str),
        Some("never")
    );
}

#[tokio::test]
async fn reload_user_config_layer_refreshes_hooks() -> anyhow::Result<()> {
    let session = make_session_with_config(|config| {
        config
            .features
            .enable(Feature::CodexHooks)
            .expect("enable Codex hooks");
    })
    .await?;
    let codex_home = session.codex_home().await;
    std::fs::create_dir_all(&codex_home)?;
    let config_toml_path = codex_home.join(CONFIG_TOML_FILE);
    let user_config: codex_config::TomlValue = serde_json::from_value(serde_json::json!({
        "hooks": {
            "SessionStart": [{
                "hooks": [{
                    "type": "command",
                    "command": "python3 /tmp/user.py",
                }],
            }],
        },
    }))?;

    let request = codex_hooks::SessionStartRequest {
        session_id: session.thread_id,
        cwd: session.get_config().await.cwd.clone(),
        transcript_path: None,
        model: "gpt-5.2".to_string(),
        permission_mode: "default".to_string(),
        target: codex_hooks::StartHookTarget::SessionStart {
            source: codex_hooks::SessionStartSource::Startup,
        },
    };
    assert!(session.hooks().preview_session_start(&request).is_empty());

    let config = session.get_config().await;
    let hook_list = codex_hooks::list_hooks(codex_hooks::HooksConfig {
        feature_enabled: true,
        config_layer_stack: Some(
            config
                .config_layer_stack
                .with_user_config(&config_toml_path, user_config.clone())
                .expect("hook user config should be valid"),
        ),
        ..codex_hooks::HooksConfig::default()
    });
    assert_eq!(hook_list.hooks.len(), 1);
    assert_eq!(
        hook_list.hooks[0].trust_status,
        codex_protocol::protocol::HookTrustStatus::Untrusted
    );

    let trusted_user_config: codex_config::TomlValue = serde_json::from_value(serde_json::json!({
        "hooks": {
            "SessionStart": [{
                "hooks": [{
                    "type": "command",
                    "command": "python3 /tmp/user.py",
                }],
            }],
            "state": {
                hook_list.hooks[0].key.clone(): {
                    "trusted_hash": hook_list.hooks[0].current_hash.clone(),
                },
            },
        },
    }))?;
    std::fs::write(&config_toml_path, toml::to_string(&trusted_user_config)?)?;

    session.reload_user_config_layer().await;

    assert_eq!(session.hooks().preview_session_start(&request).len(), 1);
    Ok(())
}

#[tokio::test]
async fn refresh_runtime_config_refreshes_hooks() -> anyhow::Result<()> {
    let (session, _turn_context) = make_session_and_context().await;
    {
        let mut state = session.state.lock().await;
        let mut config = (*state.session_configuration.original_config_do_not_use).clone();
        config
            .features
            .enable(Feature::CodexHooks)
            .expect("enable Codex hooks");
        state.session_configuration.original_config_do_not_use = Arc::new(config);
    }
    let codex_home = session.codex_home().await;
    std::fs::create_dir_all(&codex_home)?;
    let config_toml_path = codex_home.join(CONFIG_TOML_FILE);
    #[derive(serde::Serialize)]
    struct NormalizedHookIdentity {
        event_name: &'static str,
        #[serde(flatten)]
        group: codex_config::MatcherGroup,
    }
    let trusted_hash = {
        let identity = NormalizedHookIdentity {
            event_name: "session_start",
            group: codex_config::MatcherGroup {
                matcher: None,
                hooks: vec![codex_config::HookHandlerConfig::Command {
                    command: "python3 /tmp/user.py".to_string(),
                    command_windows: None,
                    timeout_sec: Some(600),
                    r#async: false,
                    status_message: None,
                    additional_context_limit: None,
                }],
            },
        };
        let identity = codex_config::TomlValue::try_from(identity)?;
        codex_config::version_for_toml(&identity)
    };
    let hook_key = format!("{}:session_start:0:0", config_toml_path.display());
    let trusted_user_config: codex_config::TomlValue = serde_json::from_value(serde_json::json!({
        "hooks": {
            "SessionStart": [{
                "hooks": [{
                    "type": "command",
                    "command": "python3 /tmp/user.py",
                }],
            }],
            "state": {
                hook_key: {
                    "trusted_hash": trusted_hash,
                },
            },
        },
    }))?;
    std::fs::write(&config_toml_path, toml::to_string(&trusted_user_config)?)?;

    let request = codex_hooks::SessionStartRequest {
        session_id: session.thread_id,
        cwd: session.get_config().await.cwd.clone(),
        transcript_path: None,
        model: "gpt-5.2".to_string(),
        permission_mode: "default".to_string(),
        target: codex_hooks::StartHookTarget::SessionStart {
            source: codex_hooks::SessionStartSource::Startup,
        },
    };
    assert!(session.hooks().preview_session_start(&request).is_empty());

    let next_config = load_latest_config_for_session(&session).await;
    session.refresh_runtime_config(next_config).await;

    assert_eq!(session.hooks().preview_session_start(&request).len(), 1);
    Ok(())
}

#[tokio::test]
async fn reload_user_config_layer_updates_effective_tool_suggest_config() {
    let (session, _turn_context) = make_session_and_context().await;
    let codex_home = session.codex_home().await;
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    let config_toml_path = codex_home.join(CONFIG_TOML_FILE);
    std::fs::write(
        &config_toml_path,
        r#"[tool_suggest]
disabled_tools = [
  { type = "connector", id = " calendar " },
  { type = "plugin", id = "slack@openai-curated" },
]
"#,
    )
    .expect("write user config");

    session.reload_user_config_layer().await;

    let config = session.get_config().await;
    assert_eq!(
        config.tool_suggest.disabled_tools,
        vec![
            ToolSuggestDisabledTool::connector("calendar"),
            ToolSuggestDisabledTool::plugin("slack@openai-curated"),
        ]
    );
}

#[tokio::test]
async fn refresh_runtime_config_updates_runtime_refreshable_fields_and_keeps_session_static_settings()
 {
    let (session, _turn_context) = make_session_and_context().await;
    let codex_home = session.codex_home().await;
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    std::fs::write(
        codex_home.join(CONFIG_TOML_FILE),
        r#"[apps.calendar]
enabled = false
destructive_enabled = false

[tool_suggest]
disabled_tools = [
  { type = "connector", id = " calendar " },
  { type = "plugin", id = "slack@openai-curated" },
]
"#,
    )
    .expect("write user config");

    let original = session.get_config().await;
    let mut next_config = load_latest_config_for_session(&session).await;
    next_config.model = Some("gpt-5.4".to_string());
    next_config.notify = Some(vec!["echo".to_string()]);

    session.refresh_runtime_config(next_config).await;

    let config = session.get_config().await;
    let apps_toml = config
        .config_layer_stack
        .effective_config()
        .as_table()
        .and_then(|table| table.get("apps"))
        .cloned()
        .expect("apps table");
    let apps = codex_config::types::AppsConfigToml::deserialize(apps_toml)
        .expect("deserialize apps config");
    let app = apps
        .apps
        .get("calendar")
        .expect("calendar app config exists");

    assert!(!app.enabled);
    assert_eq!(app.destructive_enabled, Some(false));
    assert_eq!(config.model, original.model);
    assert_eq!(config.notify, original.notify);
    assert_eq!(
        config.tool_suggest.disabled_tools,
        vec![
            ToolSuggestDisabledTool::connector("calendar"),
            ToolSuggestDisabledTool::plugin("slack@openai-curated"),
        ]
    );
}

#[tokio::test]
async fn refresh_mcp_config_replaces_managed_server_and_plugin_requirements() {
    let (session, _turn_context) = make_session_and_context().await;
    let server = serde_json::from_value::<McpServerConfig>(json!({
        "url": "https://example.com/mcp",
        "enabled": true
    }))
    .expect("valid test MCP server");
    let requirement = serde_json::from_value::<codex_config::McpServerRequirement>(json!({
        "identity": { "url": "https://example.com/mcp" }
    }))
    .expect("valid managed MCP requirement");
    let plugin_requirements = std::collections::BTreeMap::from([(
        "example-plugin".to_string(),
        codex_config::PluginRequirementsToml {
            mcp_servers: Some(std::collections::BTreeMap::from([(
                "beta".to_string(),
                requirement,
            )])),
        },
    )]);

    let mut next_config = session.get_config().await.as_ref().clone();
    next_config.mcp_servers = codex_config::Constrained::normalized(
        HashMap::from([("beta".to_string(), server.clone())]),
        |mut servers: HashMap<String, McpServerConfig>| {
            servers.retain(|name, _| name == "beta");
            servers
        },
    )
    .expect("valid refreshed MCP constraints");
    let mut requirements = next_config.config_layer_stack.requirements().clone();
    requirements.plugins = Some(Sourced::new(
        plugin_requirements.clone(),
        RequirementSource::LegacyManagedConfigTomlFromMdm,
    ));
    let mut requirements_toml = next_config.config_layer_stack.requirements_toml().clone();
    requirements_toml.plugins = Some(plugin_requirements.clone());
    let layers = next_config
        .config_layer_stack
        .all_layers_low_to_high()
        .cloned()
        .collect();
    next_config.config_layer_stack = ConfigLayerStack::new(layers, requirements, requirements_toml)
        .expect("managed MCP and plugin requirements");

    session.refresh_mcp_config(next_config).await;

    let config = session.get_config().await;
    let mut managed_servers = config.mcp_servers.clone();
    managed_servers
        .set(HashMap::from([
            ("alpha".to_string(), server.clone()),
            ("beta".to_string(), server.clone()),
        ]))
        .expect("apply refreshed managed MCP constraints");
    assert_eq!(
        managed_servers.get(),
        &HashMap::from([("beta".to_string(), server.clone())])
    );
    assert_eq!(
        config
            .config_layer_stack
            .requirements()
            .plugins
            .as_ref()
            .map(|requirements| &requirements.value),
        Some(&plugin_requirements)
    );

    let mut plugin_servers = HashMap::from([
        ("alpha".to_string(), server.clone()),
        ("beta".to_string(), server),
    ]);
    config.apply_plugin_mcp_server_requirements("example-plugin", &mut plugin_servers);
    assert!(!plugin_servers["alpha"].enabled);
    assert!(plugin_servers["beta"].enabled);
}

#[tokio::test]
async fn session_configuration_apply_preserves_profile_file_system_policy_on_cwd_only_update() {
    let mut session_configuration = make_session_configuration_for_tests().await;
    let workspace = tempfile::tempdir().expect("create temp dir");
    let project_root = workspace.path().join("project");
    let original_cwd = project_root.join("subdir");
    let docs_dir = original_cwd.join("docs");
    std::fs::create_dir_all(&docs_dir).expect("create docs dir");
    let project_root = project_root.abs();
    let docs_dir = docs_dir.abs();

    session_configuration.legacy_fallback_cwd = original_cwd.abs();
    let sandbox_policy = SandboxPolicy::WorkspaceWrite {
        writable_roots: Vec::new(),
        network_access: false,
        exclude_tmpdir_env_var: true,
        exclude_slash_tmp: true,
    };
    let file_system_sandbox_policy = FileSystemSandboxPolicy::restricted(vec![
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::project_roots(/*subpath*/ None),
            },
            access: FileSystemAccessMode::Write,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: docs_dir.into(),
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
    ]);
    let network_sandbox_policy = NetworkSandboxPolicy::from(&sandbox_policy);
    session_configuration
        .set_permission_profile_for_tests(
            PermissionProfile::from_runtime_permissions_with_enforcement(
                SandboxEnforcement::from_legacy_sandbox_policy(&sandbox_policy),
                &file_system_sandbox_policy,
                network_sandbox_policy,
            ),
        )
        .expect("set permission profile");
    let expected_file_system_sandbox_policy =
        file_system_sandbox_policy.materialize_project_roots_with_workspace_roots(&[]);

    let updated = session_configuration
        .apply(
            &SessionSettingsUpdate {
                environments: Some(TurnEnvironmentSelections::new(project_root, Vec::new())),
                ..Default::default()
            },
            &[],
        )
        .expect("cwd-only update should succeed");

    assert_eq!(
        updated.file_system_sandbox_policy(&[]),
        expected_file_system_sandbox_policy
    );
}

#[tokio::test]
async fn session_configuration_apply_permission_profile_preserves_existing_deny_read_entries() {
    let mut session_configuration = make_session_configuration_for_tests().await;
    let cwd = tempfile::tempdir().expect("create temp dir");
    session_configuration.legacy_fallback_cwd = cwd.path().abs();

    let workspace_policy = SandboxPolicy::new_workspace_write_policy();
    let deny_entry = FileSystemSandboxEntry {
        path: FileSystemPath::GlobPattern {
            pattern: "**/*.env".to_string(),
        },
        access: FileSystemAccessMode::Deny,
        missing_path_behavior: None,
    };
    let mut existing_file_system_policy =
        FileSystemSandboxPolicy::from_legacy_sandbox_policy_for_cwd(
            &workspace_policy,
            session_configuration.cwd().as_path(),
        );
    existing_file_system_policy.glob_scan_max_depth = Some(2);
    existing_file_system_policy.entries.push(deny_entry.clone());
    session_configuration
        .set_permission_profile_for_tests(
            PermissionProfile::from_runtime_permissions_with_enforcement(
                SandboxEnforcement::from_legacy_sandbox_policy(&workspace_policy),
                &existing_file_system_policy,
                NetworkSandboxPolicy::Restricted,
            ),
        )
        .expect("set permission profile");

    let requested_file_system_policy = FileSystemSandboxPolicy::from_legacy_sandbox_policy_for_cwd(
        &workspace_policy,
        session_configuration.cwd().as_path(),
    );
    let permission_profile = codex_protocol::models::PermissionProfile::from_runtime_permissions(
        &requested_file_system_policy,
        NetworkSandboxPolicy::Restricted,
    );
    let updated = session_configuration
        .apply(
            &SessionSettingsUpdate {
                permission_profile: Some(permission_profile),
                ..Default::default()
            },
            &[],
        )
        .expect("permission profile update should succeed");

    let mut expected_file_system_policy =
        requested_file_system_policy.materialize_project_roots_with_workspace_roots(&[]);
    expected_file_system_policy.glob_scan_max_depth = Some(2);
    expected_file_system_policy.entries.push(deny_entry);
    assert_eq!(
        updated.file_system_sandbox_policy(&[]),
        expected_file_system_policy
    );
}

#[tokio::test]
async fn session_configuration_apply_permission_profile_accepts_direct_write_roots() {
    let mut session_configuration = make_session_configuration_for_tests().await;
    let cwd = tempfile::tempdir().expect("create cwd");
    session_configuration.legacy_fallback_cwd = cwd.path().abs();
    let external_write_dir = tempfile::tempdir().expect("create external write root");
    let external_write_path = AbsolutePathBuf::from_absolute_path(
        codex_utils_absolute_path::canonicalize_preserving_symlinks(external_write_dir.path())
            .expect("canonical temp dir"),
    )
    .expect("canonical temp dir should be absolute");
    let file_system_sandbox_policy =
        FileSystemSandboxPolicy::restricted(vec![FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: external_write_path.clone().into(),
            },
            access: FileSystemAccessMode::Write,
            missing_path_behavior: None,
        }]);
    let permission_profile = PermissionProfile::from_runtime_permissions(
        &file_system_sandbox_policy,
        NetworkSandboxPolicy::Restricted,
    );

    let updated = session_configuration
        .apply(
            &SessionSettingsUpdate {
                permission_profile: Some(permission_profile.clone()),
                ..Default::default()
            },
            &[],
        )
        .expect("permission profile update should accept direct runtime permissions");

    assert_eq!(updated.permission_profile(), permission_profile);
    assert_eq!(
        updated.file_system_sandbox_policy(&[]),
        file_system_sandbox_policy
    );
    assert_eq!(
        updated.sandbox_policy(&[]),
        SandboxPolicy::WorkspaceWrite {
            writable_roots: vec![external_write_path],
            network_access: false,
            exclude_tmpdir_env_var: true,
            exclude_slash_tmp: true,
        }
    );
}

#[tokio::test]
async fn active_profile_update_rebuilds_network_proxy_config() -> std::io::Result<()> {
    let codex_home = tempfile::tempdir().expect("create codex home");
    let cwd = tempfile::tempdir().expect("create cwd");
    let permissions = PermissionsToml {
        entries: std::collections::BTreeMap::from([
            (
                "locked-down".to_string(),
                PermissionProfileToml {
                    description: None,
                    extends: None,
                    workspace_roots: None,
                    filesystem: Some(FilesystemPermissionsToml {
                        glob_scan_max_depth: None,
                        entries: std::collections::BTreeMap::from([(
                            ":minimal".to_string(),
                            FilesystemPermissionToml::Access(FileSystemAccessMode::Read),
                        )]),
                    }),
                    network: None,
                },
            ),
            (
                "web-enabled".to_string(),
                PermissionProfileToml {
                    description: None,
                    extends: None,
                    workspace_roots: None,
                    filesystem: Some(FilesystemPermissionsToml {
                        glob_scan_max_depth: None,
                        entries: std::collections::BTreeMap::from([(
                            ":minimal".to_string(),
                            FilesystemPermissionToml::Access(FileSystemAccessMode::Read),
                        )]),
                    }),
                    network: Some(NetworkToml {
                        enabled: Some(true),
                        proxy_url: Some("http://127.0.0.1:43128".to_string()),
                        enable_socks5: Some(false),
                        ..Default::default()
                    }),
                },
            ),
        ]),
    };
    let base_config = ConfigToml {
        features: Some(toml::from_str("network_proxy = true").expect("valid features")),
        default_permissions: Some("locked-down".to_string()),
        permissions: Some(permissions),
        ..Default::default()
    };
    std::fs::write(
        codex_home.path().join(codex_config::CONFIG_TOML_FILE),
        toml::to_string(&base_config).expect("serialize config"),
    )?;
    let locked_config = Arc::new(
        ConfigBuilder::default()
            .codex_home(codex_home.path().to_path_buf())
            .harness_overrides(ConfigOverrides {
                cwd: Some(cwd.path().to_path_buf()),
                ..Default::default()
            })
            .build()
            .await?,
    );
    assert_ne!(
        locked_config
            .permissions
            .network
            .as_ref()
            .map(crate::config::NetworkProxySpec::proxy_host_and_port)
            .as_deref(),
        Some("127.0.0.1:43128")
    );
    let selected_config = ConfigBuilder::default()
        .codex_home(codex_home.path().to_path_buf())
        .harness_overrides(ConfigOverrides {
            cwd: Some(cwd.path().to_path_buf()),
            default_permissions: Some("web-enabled".to_string()),
            ..Default::default()
        })
        .build()
        .await?;

    let mut session_configuration = make_session_configuration_for_tests().await;
    session_configuration.permission_profile_state =
        locked_config.permissions.permission_profile_state().clone();
    session_configuration.original_config_do_not_use = Arc::clone(&locked_config);

    let updated = session_configuration
        .apply(
            &SessionSettingsUpdate {
                permission_profile: Some(selected_config.permissions.permission_profile().clone()),
                active_permission_profile: selected_config.permissions.active_permission_profile(),
                ..Default::default()
            },
            &[],
        )
        .expect("active profile update should apply");

    let network = updated
        .original_config_do_not_use
        .permissions
        .network
        .as_ref()
        .expect("selected profile proxy should become the session proxy config");
    assert_eq!(network.proxy_host_and_port(), "127.0.0.1:43128");
    assert!(!network.socks_enabled());
    Ok(())
}

#[cfg_attr(windows, ignore)]
#[tokio::test]
async fn new_default_turn_uses_config_aware_skills_for_role_overrides() {
    let (session, _turn_context) = make_session_and_context().await;
    let parent_config = session.get_config().await;
    let codex_home = parent_config.codex_home.clone();
    let skill_dir = codex_home.join("skills").join("demo");
    std::fs::create_dir_all(&skill_dir).expect("create skill dir");
    let skill_path = skill_dir.join("SKILL.md");
    std::fs::write(
        &skill_path,
        "---\nname: demo-skill\ndescription: demo description\n---\n\n# Body\n",
    )
    .expect("write skill");

    let skill_fs = session
        .services
        .turn_environments
        .environment_manager()
        .default_environment()
        .map(|environment| environment.get_filesystem())
        .unwrap_or_else(|| std::sync::Arc::clone(&codex_exec_server::LOCAL_FS));
    let parent_snapshot = session
        .services
        .skills_service
        .for_request()
        .snapshot_for_cwd(
            &crate::skills_load_input_from_config(&parent_config, Vec::new()),
            /*force_reload*/ true,
            Some(Arc::clone(&skill_fs)),
        )
        .await;
    let parent_outcome = parent_snapshot.outcome();
    let parent_skill = parent_outcome
        .skills
        .iter()
        .find(|skill| skill.name == "demo-skill")
        .expect("demo skill should be discovered");
    assert_eq!(parent_outcome.is_skill_enabled(parent_skill), true);

    let role_path = codex_home.join("skills-role.toml");
    std::fs::write(
        &role_path,
        format!(
            r#"developer_instructions = "Stay focused"

[[skills.config]]
path = "{}"
enabled = false
"#,
            skill_path.display()
        ),
    )
    .expect("write role config");

    let mut child_config = (*parent_config).clone();
    child_config.agent_roles.insert(
        "custom".to_string(),
        crate::config::AgentRoleConfig {
            description: None,
            config_file: Some(role_path.to_path_buf()),
            nickname_candidates: None,
        },
    );
    crate::agent::role::apply_role_to_config(&mut child_config, Some("custom"))
        .await
        .expect("custom role should apply");

    {
        let mut state = session.state.lock().await;
        state.session_configuration.original_config_do_not_use = Arc::new(child_config);
    }

    let child_turn = session
        .new_default_turn_with_sub_id("role-skill-turn".to_string())
        .await;
    let skills_snapshot = child_turn.skills_snapshot();
    let child_skill = skills_snapshot
        .outcome()
        .skills
        .iter()
        .find(|skill| skill.name == "demo-skill")
        .expect("demo skill should be discovered");
    assert_eq!(
        skills_snapshot.outcome().is_skill_enabled(child_skill),
        false
    );
}

#[tokio::test]
async fn session_configuration_apply_preserves_absolute_cwd_write_root_on_cwd_update() {
    let mut session_configuration = make_session_configuration_for_tests().await;
    let workspace = tempfile::tempdir().expect("create temp dir");
    let original_cwd = workspace.path().join("repo-a");
    let next_cwd = workspace.path().join("repo-b");
    std::fs::create_dir_all(&original_cwd).expect("create original cwd");
    std::fs::create_dir_all(&next_cwd).expect("create next cwd");
    let original_cwd = original_cwd.abs();
    let next_cwd = next_cwd.abs();

    session_configuration.legacy_fallback_cwd = original_cwd.clone();
    let file_system_sandbox_policy = FileSystemSandboxPolicy::restricted(vec![
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::Root,
            },
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: original_cwd.clone().into(),
            },
            access: FileSystemAccessMode::Write,
            missing_path_behavior: None,
        },
    ]);
    session_configuration
        .set_permission_profile_for_tests(
            PermissionProfile::from_runtime_permissions_with_enforcement(
                SandboxEnforcement::Managed,
                &file_system_sandbox_policy,
                NetworkSandboxPolicy::Restricted,
            ),
        )
        .expect("set permission profile");

    let updated = session_configuration
        .apply(
            &SessionSettingsUpdate {
                environments: Some(TurnEnvironmentSelections::new(next_cwd.clone(), Vec::new())),
                ..Default::default()
            },
            &[],
        )
        .expect("cwd-only update should succeed");

    assert_eq!(
        updated.file_system_sandbox_policy(&[]),
        file_system_sandbox_policy
    );
    assert!(
        updated
            .file_system_sandbox_policy(&[])
            .can_write_path_with_cwd(original_cwd.as_path(), updated.cwd().as_path()),
        "absolute grant to the old cwd must remain writable"
    );
    assert!(
        !updated
            .file_system_sandbox_policy(&[])
            .can_write_path_with_cwd(next_cwd.as_path(), updated.cwd().as_path()),
        "cwd-only update must not reinterpret an absolute old-cwd grant as :workspace_roots"
    );
}

#[tokio::test]
async fn session_update_settings_does_not_rewrite_sticky_environment_cwds() {
    let (session, turn_context) = make_session_and_context().await;
    #[allow(deprecated)]
    let updated_cwd = turn_context.cwd.join("project");
    let current_environments = session.services.turn_environments.selections();
    let expected_environments = current_environments.clone();
    std::fs::create_dir_all(updated_cwd.as_path()).expect("create project dir");

    session
        .update_settings(SessionSettingsUpdate {
            environments: Some(TurnEnvironmentSelections::new(
                updated_cwd.clone(),
                current_environments,
            )),
            ..Default::default()
        })
        .await
        .expect("cwd update should succeed");

    let session_cwd = {
        let state = session.state.lock().await;
        state.session_configuration.cwd().clone()
    };
    let stored_environments = session.services.turn_environments.selections();
    let config = session.get_config().await;
    let next_turn = session.new_default_turn().await;

    assert_eq!(session_cwd, updated_cwd);
    assert_eq!(stored_environments, expected_environments);
    #[allow(deprecated)]
    let turn_cwd = turn_context.cwd.clone();
    #[allow(deprecated)]
    let next_turn_cwd = next_turn.cwd.clone();
    assert_eq!(config.cwd, turn_cwd);
    assert_eq!(next_turn_cwd, turn_cwd);
    assert_eq!(next_turn.config.cwd, turn_cwd);
}

#[tokio::test]
async fn permission_profile_updates_apply_to_next_turn_environment() {
    for apply_on_turn_start in [false, true] {
        let (session, active_turn) = make_session_and_context().await;
        let active_environment_config = active_turn
            .environments
            .primary()
            .expect("active turn environment")
            .config()
            .clone();
        let profile_root = active_turn.config.cwd.join("profile-root");
        let active_profile = ActivePermissionProfile::read_only();
        let updates = SessionSettingsUpdate {
            permission_profile: Some(PermissionProfile::read_only()),
            active_permission_profile: Some(active_profile.clone()),
            profile_workspace_roots: Some(vec![profile_root.clone()]),
            ..Default::default()
        };

        let next_turn = if apply_on_turn_start {
            session
                .new_turn_with_sub_id("permission-profile-update".to_string(), updates)
                .await
                .expect("turn permission profile update should succeed")
        } else {
            session
                .update_settings(updates)
                .await
                .expect("permission profile update should succeed");
            session.new_default_turn().await
        };
        let next_environment = next_turn
            .environments
            .primary()
            .expect("next turn environment");
        let mut expected_environment_config = active_environment_config.clone();
        expected_environment_config.permission_profile =
            PermissionProfileSnapshot::active_with_profile_workspace_roots(
                PermissionProfile::read_only(),
                active_profile,
                vec![profile_root],
            );

        assert_eq!(next_environment.config(), &expected_environment_config);
        assert_eq!(
            active_turn
                .environments
                .primary()
                .expect("active turn environment")
                .config(),
            &active_environment_config
        );
    }
}

#[tokio::test]
async fn relative_cwd_update_without_environments_resolves_under_session_cwd() {
    let (session, _turn_context) = make_session_and_context().await;
    let original_cwd = session
        .state
        .lock()
        .await
        .session_configuration
        .cwd()
        .clone();
    let updated_cwd = original_cwd.join("project");
    std::fs::create_dir_all(updated_cwd.as_path()).expect("create project dir");

    session
        .update_settings(SessionSettingsUpdate {
            environments: Some(TurnEnvironmentSelections::new(
                updated_cwd.clone(),
                Vec::new(),
            )),
            ..Default::default()
        })
        .await
        .expect("cwd update should succeed");

    let state = session.state.lock().await;
    assert_eq!(state.session_configuration.cwd(), &updated_cwd);
    assert!(session.services.turn_environments.selections().is_empty());
}

#[tokio::test]
async fn environment_settings_preserve_explicit_primary_cwd() {
    let (session, _turn_context) = make_session_and_context().await;
    let (original_cwd, environment_cwd, environments) = {
        let state = session.state.lock().await;
        let original_cwd = state.session_configuration.cwd().clone();
        let environment_cwd = original_cwd.join("environment");
        let environments = vec![local(environment_cwd.clone())];
        (original_cwd, environment_cwd, environments)
    };
    let updated_cwd = original_cwd.join("project");
    std::fs::create_dir_all(updated_cwd.as_path()).expect("create project dir");

    session
        .update_settings(SessionSettingsUpdate {
            environments: Some(TurnEnvironmentSelections::new(
                updated_cwd.clone(),
                environments,
            )),
            ..Default::default()
        })
        .await
        .expect("cwd update should succeed");

    let state = session.state.lock().await;
    assert_eq!(state.session_configuration.cwd(), &updated_cwd);
    assert_eq!(
        session.services.turn_environments.selections()[0].cwd,
        PathUri::from_abs_path(&environment_cwd)
    );
}

#[tokio::test]
async fn absolute_cwd_update_with_turn_environment_is_allowed() {
    let (session, _turn_context, _rx) = make_session_and_context_with_rx().await;
    let absolute_cwd = {
        let state = session.state.lock().await;
        state.session_configuration.cwd().join("absolute-turn")
    };
    std::fs::create_dir_all(absolute_cwd.as_path()).expect("create absolute turn dir");

    let turn_context = session
        .new_turn_with_sub_id(
            "sub-1".to_string(),
            SessionSettingsUpdate {
                environments: Some(TurnEnvironmentSelections::new(
                    absolute_cwd.clone(),
                    vec![local(absolute_cwd.clone())],
                )),
                ..Default::default()
            },
        )
        .await
        .expect("absolute cwd with explicit environments should succeed");

    #[allow(deprecated)]
    let turn_cwd = turn_context.cwd.clone();
    assert_eq!(turn_cwd, absolute_cwd);
    assert_eq!(turn_context.config.cwd, absolute_cwd);
    assert_eq!(turn_context.environments.turn_environments().count(), 1);
}
