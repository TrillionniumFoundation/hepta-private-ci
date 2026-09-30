use super::*;
use crate::WorkspaceBinding;
use pretty_assertions::assert_eq;

#[test]
fn predecessor_owner_evidence_moves_without_touching_workload_data()
-> Result<(), FleetRegistryError> {
    let directory = tempfile::tempdir()?;
    let root = HeptaFleetRoot::parse(directory.path().join("fleet")).unwrap();
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
    let record = registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace, &root)?,
        crate::ResourceBudget::local_default(),
    )?)?;
    let layout = record.layout;
    let lifecycle = super::super::lifecycle_path(layout.owner_run_root(), 0);
    let before = std::fs::read(&lifecycle)?;
    std::fs::rename(
        lifecycle,
        super::super::lifecycle_path(layout.run_root(), 0),
    )?;
    std::fs::write(layout.run_root().join("writer.lock"), b"workload lock")?;
    std::fs::write(
        layout.run_root().join("supervisor-process.json"),
        b"retained owner evidence",
    )?;
    let emergency = layout.run_root().join("supervisor-emergency-control");
    std::fs::create_dir(&emergency)?;
    std::fs::write(emergency.join("receipt"), b"ambiguous effect remains")?;
    registry.migrate_owner_journals()?;
    registry.migrate_owner_journals()?;
    assert_eq!(
        registry.load_agent(&agent)?.lifecycle,
        crate::AgentLifecycleState::initial(agent)
    );
    assert_eq!(
        std::fs::read(super::super::lifecycle_path(layout.owner_run_root(), 0))?,
        before
    );
    assert_eq!(
        std::fs::read(layout.owner_run_root().join("supervisor-process.json"))?,
        b"retained owner evidence"
    );
    assert_eq!(
        std::fs::read(
            layout
                .owner_run_root()
                .join("supervisor-emergency-control/receipt")
        )?,
        b"ambiguous effect remains"
    );
    assert_eq!(
        std::fs::read(layout.run_root().join("writer.lock"))?,
        b"workload lock"
    );
    assert!(!layout.run_root().join("supervisor-process.json").exists());
    Ok(())
}
