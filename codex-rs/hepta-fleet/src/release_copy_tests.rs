use super::*;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use crate::AgentManifest;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

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
fn unsealed_catalog_root_cannot_gain_an_agent_allowance() -> Result<(), Box<dyn std::error::Error>>
{
    let temporary = tempfile::tempdir()?;
    let parent = temporary.path().canonicalize()?;
    let root = HeptaFleetRoot::parse(parent.join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = parent.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("00000000-0000-4000-8000-00000000c071")?;
    let record = registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    let source = parent.join("source-program");
    std::fs::write(&source, b"reviewed program bytes")?;
    let release_id = ReleaseId::parse("unsealed-publication")?;
    registry.install_release(release_id.clone(), &source, Vec::new())?;
    let release_root = registry.layout().releases_root().join(release_id.as_str());
    let allowance_before = directory_names(record.layout.releases_root())?;

    // Model interruption after the rename and before the final root is sealed.
    // Its bytes and manifest are complete, but it is not an admissible release.
    set_mode(&release_root, /*mode*/ 0o700)?;
    assert!(matches!(
        resolve_catalog_release(registry.layout().releases_root(), &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert!(matches!(
        registry.allow_release(&agent, &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert_eq!(
        directory_names(record.layout.releases_root())?,
        allowance_before
    );
    assert_eq!(registry.allowed_releases(&agent)?, Vec::<ReleaseId>::new());
    assert!(matches!(
        registry.resolve_release(&agent, &release_id),
        Err(FleetRegistryError::ReleaseNotAllowed { .. })
    ));
    make_tree_removable(&release_root);
    Ok(())
}
