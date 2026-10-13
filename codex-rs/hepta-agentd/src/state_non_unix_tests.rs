//! Unsupported-platform qualification must prove fail-closed behavior.
//! No permission-agnostic substitute for a Windows ACL owner is allowed.

#[test]
fn prompt_registry_rejects_non_unix_serving_without_private_owner() -> Result<(), Box<dyn std::error::Error>> {
    use codex_hepta_prompt_registry::DurablePromptRegistry;
    use codex_hepta_prompt_registry::DurableRegistryError;

    let directory = tempfile::tempdir()?;
    let path = directory.path().join("prompt-registry");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, /*maximum_records*/ 16),
        Err(DurableRegistryError::UnsafeStateDirectory)
    ));
    Ok(())
}

#[test]
fn agentd_startup_rejects_unsupported_prompt_registry_before_readiness(
) -> Result<(), Box<dyn std::error::Error>> {
    use super::*;
    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;

    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let manifest = AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?;
    let record = registry.register(manifest)?;
    let identity = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root: fleet_path,
        workspace,
        resources: record.manifest.resources,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    assert!(matches!(
        AgentdState::new(identity, registry, /*event_capacity*/ 16),
        Err(AgentdError::Protocol(message))
            if message.contains("RegistryOpen") && message.contains("UnsafeStateDirectory")
    ));
    Ok(())
}
