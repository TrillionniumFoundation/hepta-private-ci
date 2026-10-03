use super::*;
use std::os::unix::fs::PermissionsExt;

#[path = "initial_cpu_goal_material_test_fixture_v3.rs"]
mod material_fixture;

#[test]
fn successor_goal_uses_its_complete_current_plan_and_keeps_training_scope_separate()
-> HostResult<()> {
    use codex_hepta_agent_components::fleet::*;
    use codex_hepta_agent_components::paths::HeptaFleetRoot;
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = codex_hepta_contracts::AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let registered = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    let identity = AgentdIdentity {
        agent_id,
        layout: registered.layout.clone(),
        spawn_generation: 7,
        fleet_root: fleet_path,
        workspace,
        resources: registered.manifest.resources,
        home_root: registered.layout.home_root().to_path_buf(),
        run_root: registered.layout.run_root().to_path_buf(),
        control_socket: registered.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: registered.layout.app_server_socket().to_path_buf(),
    };
    let mut current = material_fixture::baseline()?;
    current.scope = NeuronTickInputV1::journal_scope_for_subject(
        &id(identity.agent_id.as_str())?,
        current.scope.objective_digest,
    )?;
    current.store_context.scope = current.scope;
    current.index_context.scope = current.scope;
    current.witness_context.scope = current.scope;
    current.generation_store = identity.home_root.join("generation");
    current.runtime_index = identity.home_root.join("index");
    current.witness = identity.home_root.join("witness");
    let goal_scope = NeuronTickInputV1::journal_scope_for_subject(
        &id(identity.agent_id.as_str())?,
        Digest32::of_bytes(b"actual second Goal objective"),
    )?;
    let mut expected = AgentdNeuronGoalScopeV3 {
        ordinal: 2,
        identity: AgentdNeuronScopeIdentityV3 {
            model_generation: 2,
            subject_scope_digest: goal_scope.scope_digest,
            objective_digest: goal_scope.objective_digest,
            runtime_configuration_digest: current.runtime.semantic_digest()?,
            body_bundle_digest: current.body.semantic_digest()?,
        },
    };
    let next = scope_plan(&current, &identity, &expected)?;
    assert_eq!(next.runtime, current.runtime);
    assert_eq!(next.body, current.body);
    assert_eq!(next.native, current.native);
    assert_eq!(next.scope, goal_scope);
    assert_ne!(next.scope, current.scope);
    for path in [&next.generation_store, &next.runtime_index, &next.witness] {
        assert!(path.starts_with(&identity.home_root));
        assert!(path.to_string_lossy().ends_with(".goal-2"));
        assert!(!path.exists());
    }
    expected.identity.model_generation = 1;
    assert!(scope_plan(&current, &identity, &expected).is_err());
    Ok(())
}

#[test]
fn partial_goal_stores_require_reconciliation_and_preserve_original_bytes() -> HostResult<()> {
    let directory = tempfile::tempdir()?;
    let paths = ["generation", "index", "witness"].map(|name| directory.path().join(name));
    let refs = paths.each_ref().map(PathBuf::as_path);
    assert!(mode(refs, StoreRequirement::Existing).is_err());
    assert!(matches!(
        mode(refs, StoreRequirement::NewOrExisting)?,
        crate::CpuNeuronGenerationOpenModeV1::Create
    ));
    for (index, path) in paths.iter().enumerate() {
        std::fs::write(path, b"original fixture journal bytes")?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        if index < 2 {
            assert!(mode(refs, StoreRequirement::NewOrExisting).is_err());
            assert!(mode(refs, StoreRequirement::Existing).is_err());
        }
    }
    assert!(matches!(
        mode(refs, StoreRequirement::Existing)?,
        crate::CpuNeuronGenerationOpenModeV1::Recover
    ));
    for path in &paths {
        assert_eq!(std::fs::read(path)?, b"original fixture journal bytes");
    }
    // The original native owners, rather than this file-presence check,
    // authenticate the recovered headers when opening the scope.
    Ok(())
}

#[test]
fn goal_recovery_rejects_exposed_linked_or_aliased_files_without_reset() -> HostResult<()> {
    let directory = tempfile::tempdir()?;
    let paths = ["generation", "index", "witness"].map(|name| directory.path().join(name));
    let refs = paths.each_ref().map(PathBuf::as_path);
    for path in &paths {
        std::fs::write(path, b"original private bytes")?;
        std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
    }
    std::fs::set_permissions(&paths[0], std::fs::Permissions::from_mode(0o640))?;
    assert!(mode(refs, StoreRequirement::Existing).is_err());
    std::fs::set_permissions(&paths[0], std::fs::Permissions::from_mode(0o600))?;
    let alias = directory.path().join("aliased-generation");
    std::fs::hard_link(&paths[0], &alias)?;
    assert!(mode(refs, StoreRequirement::Existing).is_err());
    std::fs::remove_file(&alias)?;
    std::fs::rename(&paths[0], &alias)?;
    std::os::unix::fs::symlink(&alias, &paths[0])?;
    assert!(mode(refs, StoreRequirement::Existing).is_err());
    assert_eq!(std::fs::read(&alias)?, b"original private bytes");
    Ok(())
}
