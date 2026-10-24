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
    let release_root = registry.layout().releases_root().join(release_id.as_str());
    validate_physical_directory(&release_root, /*immutable*/ true)?;
    validate_physical_directory(&release_root.join("bin"), /*immutable*/ true)?;
    let manifest = release_root.join(RELEASE_MANIFEST_FILE);
    validate_immutable_regular_file(&manifest, /*executable*/ false)?;
    let manifest_bytes = std::fs::read(&manifest)?;
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
    assert_eq!(std::fs::read(&matrixd.program)?, content);
    assert_eq!(std::fs::read(&manifest)?, manifest_bytes);
    validate_physical_directory(&release_root, /*immutable*/ true)?;
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
fn unsealed_release_root_is_not_admitted_or_replaced_after_reopen()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let source = temporary.path().join("source-program");
    std::fs::write(&source, b"reviewed immutable program bytes")?;
    set_mode(&source, /*mode*/ 0o555)?;
    let root = HeptaFleetRoot::parse(temporary.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = temporary.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    registry.register(crate::AgentManifest::new(
        agent_id.clone(),
        crate::WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
        crate::ResourceBudget::local_default(),
    )?)?;
    let release_id = ReleaseId::parse("unsealed-root")?;
    let installed = registry.install_release(release_id.clone(), &source, Vec::new())?;
    registry.allow_release(&agent_id, &release_id)?;
    let release_root = registry.layout().releases_root().join(release_id.as_str());
    let manifest = release_root.join(RELEASE_MANIFEST_FILE);
    let original_manifest = std::fs::read(&manifest)?;
    let original_program = std::fs::read(&installed.program)?;

    // Model a crash after rename but before sealing the final root. Even a
    // digest-bound allowance cannot admit that otherwise complete bundle.
    set_mode(&release_root, /*mode*/ 0o700)?;
    let reopened = FleetRegistry::open_existing(root.clone())?;
    for result in [
        reopened.resolve_release(&agent_id, &release_id).map(|_| ()),
        reopened.allow_release(&agent_id, &release_id),
        reopened
            .resolve_release_binding(&agent_id, &release_id)
            .map(|_| ()),
        reopened.allowed_releases(&agent_id).map(|_| ()),
    ] {
        assert!(matches!(result, Err(FleetRegistryError::Corrupt(_))));
    }
    assert!(matches!(
        reopened.install_release(release_id.clone(), &source, Vec::new()),
        Err(FleetRegistryError::Invalid(_))
    ));
    assert_eq!(std::fs::read(&manifest)?, original_manifest);
    assert_eq!(std::fs::read(&installed.program)?, original_program);
    assert!(is_writable(&std::fs::metadata(&release_root)?));
    assert_eq!(
        reopened
            .load()?
            .agent(&agent_id)
            .ok_or("missing agent")?
            .release_state,
        AgentReleaseState::initial(agent_id.clone())
    );
    // The release-state CAS is metadata persistence, not executable admission.
    // A stored ID must still go through the catalog resolver after recovery.
    let recorded = reopened.compare_and_set_release_state(
        &agent_id,
        /*expected_generation*/ 0,
        Some(release_id.clone()),
        /*previous*/ None,
    )?;
    let reopened = FleetRegistry::open_existing(root)?;
    assert_eq!(
        reopened
            .load()?
            .agent(&agent_id)
            .ok_or("missing agent")?
            .release_state,
        recorded
    );
    assert!(matches!(
        reopened.resolve_release(&agent_id, &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    // The installation API must not silently seal or replace crash residue.
    // Restore permissions only so this test's private fixtures can be removed.
    make_tree_removable(&release_root);
    set_mode(&source, /*mode*/ 0o700)?;
    Ok(())
}
