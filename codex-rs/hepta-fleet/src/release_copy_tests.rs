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
fn writable_publication_root_cannot_be_resolved_before_it_is_sealed()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let source = temporary.path().join("source-program");
    let content = b"immutable release content";
    std::fs::write(&source, content)?;
    let root = HeptaFleetRoot::parse(temporary.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root)?;
    let release_id = ReleaseId::parse("publication-fence")?;
    let installed = registry.install_release(release_id.clone(), &source, Vec::new())?;
    let catalog_root = registry.layout().releases_root();
    let release_root = catalog_root.join(release_id.as_str());

    // Reconstruct the state between rename and sealing, including a complete
    // manifest and immutable executable. A complete payload alone cannot admit
    // a release whose root still permits mutation.
    set_mode(&release_root, /*mode*/ 0o755)?;
    validate_immutable_regular_file(&installed.program, /*executable*/ true)?;
    assert!(matches!(
        resolve_catalog_release(catalog_root, &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert!(matches!(
        registry.install_release(release_id.clone(), &source, Vec::new()),
        Err(FleetRegistryError::Invalid(_))
    ));
    assert_eq!(std::fs::read(&installed.program)?, content);

    set_mode(&release_root, /*mode*/ 0o555)?;
    assert_eq!(
        resolve_catalog_release(catalog_root, &release_id)?,
        installed
    );
    make_tree_removable(&release_root);
    Ok(())
}
