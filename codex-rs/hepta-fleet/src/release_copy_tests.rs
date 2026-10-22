use super::*;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

#[test]
fn readonly_source_is_copied_synced_and_preserved_on_duplicate_install()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let source = temporary.path().join("source-program");
    let content = b"reviewed immutable program bytes";
    std::fs::write(&source, content)?;
    set_mode(&source, /*mode*/ 0o555)?;
    let root = HeptaFleetRoot::parse(temporary.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let release_id = ReleaseId::parse("readonly-source")?;
    let installed = registry.install_release_bundle(
        release_id.clone(),
        &source,
        Vec::new(),
        Some(&source),
        Vec::new(),
    )?;
    let matrixd = installed.matrixd.as_ref().ok_or("missing matrixd")?;
    for path in [&source, &installed.program, &matrixd.program] {
        assert_eq!(std::fs::read(path)?, content);
        validate_immutable_regular_file(path, /*executable*/ true)?;
    }
    let reopened = FleetRegistry::open_existing(root)?;
    assert!(matches!(
        reopened.install_release(release_id, &source, Vec::new()),
        Err(FleetRegistryError::Invalid(_))
    ));
    assert_eq!(std::fs::read(&installed.program)?, content);
    // Windows read-only attributes also affect cleanup; restore only fixtures.
    make_tree_removable(
        installed
            .program
            .parent()
            .and_then(Path::parent)
            .ok_or("release root")?,
    );
    set_mode(&source, /*mode*/ 0o700)?;
    Ok(())
}

#[test]
fn unsealed_final_name_never_grants_admission_even_after_reopen()
-> Result<(), Box<dyn std::error::Error>> {
    use crate::AgentManifest;
    use crate::ResourceBudget;
    use crate::WorkspaceBinding;

    let temporary = tempfile::tempdir()?;
    let source = temporary.path().join("source-program");
    std::fs::write(&source, b"sealed program bytes")?;
    let root = HeptaFleetRoot::parse(temporary.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = temporary.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let workspace = workspace.canonicalize()?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let record = registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    let release_id = ReleaseId::parse("sealed-publication")?;
    let installed = registry.install_release(release_id.clone(), &source, Vec::new())?;
    registry.allow_release(&agent, &release_id)?;
    let binding = registry.resolve_release_binding(&agent, &release_id)?;
    let state = registry.load()?;
    let marker = allowance_path(record.layout.releases_root(), &release_id);
    let marker_bytes = std::fs::read(&marker)?;
    let final_root = registry.layout().releases_root().join(release_id.as_str());

    // Model the post-rename/pre-seal residue without granting a repair API.
    // Even a pre-existing allow marker cannot make this name admissible.
    set_mode(&final_root, /*mode*/ 0o755)?;
    validate_immutable_regular_file(&installed.program, /*executable*/ true)?;
    let reopened = FleetRegistry::open_existing(root)?;
    for owner in [&registry, &reopened] {
        assert!(matches!(
            resolve_catalog_release(owner.layout().releases_root(), &release_id),
            Err(FleetRegistryError::Corrupt(_))
        ));
        assert!(matches!(
            owner.resolve_release_binding(&agent, &release_id),
            Err(FleetRegistryError::Corrupt(_))
        ));
        assert!(matches!(
            owner.allow_release(&agent, &release_id),
            Err(FleetRegistryError::Corrupt(_))
        ));
        assert!(matches!(
            owner.install_release(release_id.clone(), &source, Vec::new()),
            Err(FleetRegistryError::Invalid(_))
        ));
        assert_eq!(owner.load()?, state);
        assert_eq!(std::fs::read(&marker)?, marker_bytes);
    }
    // Fixture-only restoration; production errors never auto-seal residue.
    set_mode(&final_root, /*mode*/ 0o555)?;
    sync_directory(&final_root)?;
    sync_directory(reopened.layout().releases_root())?;
    assert_eq!(reopened.resolve_release(&agent, &release_id)?, installed);
    assert_eq!(
        reopened.resolve_release_binding(&agent, &release_id)?,
        binding
    );
    reopened.revoke_release(&agent, &release_id)?;
    assert!(reopened.resolve_release(&agent, &release_id).is_err());
    make_tree_removable(&final_root);
    Ok(())
}
