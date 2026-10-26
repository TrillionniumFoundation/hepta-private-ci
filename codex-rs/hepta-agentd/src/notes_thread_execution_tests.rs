use super::*;

#[test]
fn finite_profile_rejects_enabled_builtins_agents_and_external_mcp() {
    let valid = parse(ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG.as_bytes()).unwrap();
    validate_config(&valid).unwrap();
    for pointer in [
        "/features/shell_tool",
        "/features/unified_exec",
        "/features/view_image",
        "/features/multi_agent",
        "/features/multi_agent_v2",
        "/agents/enabled",
        "/features/apps",
        "/features/plugins",
        "/features/browser_use",
        "/features/computer_use",
        "/features/image_generation",
        "/features/js_repl",
        "/tools/update_plan/enabled",
        "/tools/experimental_request_user_input/enabled",
        "/orchestrator/mcp/enabled",
        "/orchestrator/skills/enabled",
    ] {
        let mut changed = valid.clone();
        *changed.pointer_mut(pointer).unwrap() = Value::Bool(true);
        assert!(validate_config(&changed).is_err(), "accepted {pointer}");
    }
    for (key, value) in [
        ("approval_policy", "on-request"),
        ("sandbox_mode", "workspace-write"),
        ("web_search", "live"),
    ] {
        let mut changed = valid.clone();
        changed[key] = Value::String(value.into());
        assert!(validate_config(&changed).is_err(), "accepted {key}");
    }
    let mut changed = valid;
    changed["mcp_servers"] = serde_json::json!({"external": {"command": "external-server"}});
    assert!(validate_config(&changed).is_err());
}

#[test]
fn persistent_profile_requires_no_environment_and_records_actual_file_bytes() {
    let directory = tempfile::tempdir().unwrap();
    let home = directory.path().canonicalize().unwrap();
    let config = format!(
        "model = \"fixture-model\"\nmodel_provider = \"fixture-provider\"\n{ORIGINAL_NOTES_THREAD_EXECUTION_CONFIG}"
    );
    std::fs::write(home.join("config.toml"), &config).unwrap();
    assert!(
        inspect(&home).is_err(),
        "missing environment file inherited local defaults"
    );
    std::fs::write(
        home.join("environments.toml"),
        ORIGINAL_NOTES_THREAD_ENVIRONMENTS_CONFIG,
    )
    .unwrap();
    let original = inspect(&home).unwrap();
    std::fs::write(home.join("config.toml"), format!("{config}\n")).unwrap();
    let changed = inspect(&home).unwrap();
    assert_ne!(original.config_sha256, changed.config_sha256);
    assert_eq!(original.environments_sha256, changed.environments_sha256);
    for environments in [
        "default = \"local\"\ninclude_local = true\n",
        "default = \"none\"\ninclude_local = true\n",
        "default = \"none\"\ninclude_local = false\n[[environments]]\nid = \"remote\"\nurl = \"ws://localhost:1\"\n",
    ] {
        std::fs::write(home.join("environments.toml"), environments).unwrap();
        assert!(inspect(&home).is_err());
    }
}
