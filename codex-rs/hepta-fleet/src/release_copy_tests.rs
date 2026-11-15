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
fn catalog_rejects_published_directory_until_immutable_seal()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let source = temporary.path().join("source-program");
    let content = b"immutable release admission fixture";
    std::fs::write(&source, content)?;
    set_mode(&source, /*mode*/ 0o555)?;
    let root = HeptaFleetRoot::parse(temporary.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root)?;
    let release_id = ReleaseId::parse("publication-seal")?;
    let installed = registry.install_release(release_id.clone(), &source, Vec::new())?;
    let release_root = registry.layout().releases_root().join(release_id.as_str());

    set_mode(&release_root, /*mode*/ 0o755)?;
    assert!(matches!(
        resolve_catalog_release(registry.layout().releases_root(), &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert_eq!(std::fs::read(&installed.program)?, content);
    set_mode(&release_root, /*mode*/ 0o555)?;
    assert_eq!(
        resolve_catalog_release(registry.layout().releases_root(), &release_id)?,
        installed
    );
    make_tree_removable(&release_root);
    set_mode(&source, /*mode*/ 0o700)?;
    Ok(())
}

#[test]
fn competing_installations_keep_the_winning_release_immutable()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let source_a = temporary.path().join("source-a");
    let source_b = temporary.path().join("source-b");
    std::fs::write(&source_a, b"first program")?;
    std::fs::write(&source_b, b"second program")?;
    let root = HeptaFleetRoot::parse(temporary.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root)?;
    let release_id = ReleaseId::parse("competing-installation")?;
    let start = std::sync::Barrier::new(2);
    let results = std::thread::scope(|scope| {
        let first = scope.spawn(|| {
            start.wait();
            registry.install_release(release_id.clone(), &source_a, Vec::new())
        });
        let second = scope.spawn(|| {
            start.wait();
            registry.install_release(release_id.clone(), &source_b, Vec::new())
        });
        [first.join(), second.join()]
    });
    let first = results[0]
        .as_ref()
        .map_err(|_| "first publisher panicked")?;
    let second = results[1]
        .as_ref()
        .map_err(|_| "second publisher panicked")?;
    assert_eq!(usize::from(first.is_ok()) + usize::from(second.is_ok()), 1);
    let expected = if first.is_ok() {
        std::fs::read(&source_a)?
    } else {
        std::fs::read(&source_b)?
    };
    let installed = resolve_catalog_release(registry.layout().releases_root(), &release_id)?;
    assert_eq!(std::fs::read(&installed.program)?, expected);
    assert_eq!(
        directory_names(registry.layout().releases_root())?,
        BTreeSet::from([release_id.as_str().to_string()])
    );
    make_tree_removable(&registry.layout().releases_root().join(release_id.as_str()));
    Ok(())
}
