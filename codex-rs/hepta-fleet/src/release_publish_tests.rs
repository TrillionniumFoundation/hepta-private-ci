use super::*;
use crate::AgentManifest;
use crate::ResourceBudget;
use crate::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

#[test]
fn interrupted_directory_seal_cannot_admit_or_overwrite_the_release()
-> Result<(), Box<dyn std::error::Error>> {
    let temporary = tempfile::tempdir()?;
    let root = HeptaFleetRoot::parse(temporary.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = temporary.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let record = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    let source = temporary.path().join("source-program");
    let content = b"reviewed immutable program bytes";
    std::fs::write(&source, content)?;
    set_mode(&source, /*mode*/ 0o555)?;
    let release_id = ReleaseId::parse("interrupted-seal")?;
    let installed = registry.install_release_bundle(
        release_id.clone(),
        &source,
        Vec::new(),
        Some(&source),
        Vec::new(),
    )?;
    registry.allow_release(&agent_id, &release_id)?;
    assert_eq!(registry.resolve_release(&agent_id, &release_id)?, installed);
    let allowance = allowance_path(record.layout.releases_root(), &release_id);
    let accepted_allowance = std::fs::read(&allowance)?;
    let final_root = registry.layout().releases_root().join(release_id.as_str());

    // Replay the real directory publication boundary, then model process loss
    // before the final root chmod. Payloads and the bin directory stay sealed.
    set_mode(&final_root, /*mode*/ 0o700)?;
    let staging = registry
        .layout()
        .releases_root()
        .join(".staging-interrupted");
    std::fs::rename(&final_root, &staging)?;
    sync_directory(&staging)?;
    std::fs::rename(&staging, &final_root)?;
    sync_directory(registry.layout().releases_root())?;
    validate_physical_directory(&final_root.join("bin"), /*immutable*/ true)?;
    for program in [
        &installed.program,
        &installed.matrixd.as_ref().ok_or("missing matrixd")?.program,
    ] {
        validate_immutable_regular_file(program, /*executable*/ true)?;
        assert_eq!(std::fs::read(program)?, content);
    }
    assert!(matches!(
        resolve_catalog_release(registry.layout().releases_root(), &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert!(matches!(
        registry.allow_release(&agent_id, &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert_eq!(std::fs::read(&allowance)?, accepted_allowance);
    assert!(matches!(
        registry.resolve_release(&agent_id, &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    let reopened = FleetRegistry::open_existing(root)?;
    assert!(matches!(
        reopened.allow_release(&agent_id, &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert!(matches!(
        reopened.resolve_release(&agent_id, &release_id),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert!(matches!(
        reopened.install_release(release_id, &source, Vec::new()),
        Err(FleetRegistryError::Invalid(_))
    ));
    assert!(is_writable(&std::fs::metadata(&final_root)?));
    assert_eq!(std::fs::read(&allowance)?, accepted_allowance);
    assert_eq!(std::fs::read(&installed.program)?, content);
    make_tree_removable(&final_root);
    set_mode(&source, /*mode*/ 0o700)?;
    Ok(())
}
