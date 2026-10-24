//! Ordinary-UID regression of the original Registry control-file boundary.
use super::*;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;

fn registered() -> Result<(TestFleet, codex_hepta_paths::HeptaAgentLayout), FleetRegistryError> {
    let fleet = TestFleet::new()?;
    let manifest = fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace)?;
    let layout = fleet.registry.register(manifest)?.layout;
    Ok((fleet, layout))
}

#[test]
fn original_control_owner_remains_the_same_across_regular_registry_transitions()
-> Result<(), FleetRegistryError> {
    let (fleet, layout) = registered()?;
    let agent = AgentId::parse(FIRST_AGENT_ID)
        .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
    let original_uid = fs::metadata(layout.agent_root())?.uid();
    for (generation, requested) in [
        (0, AgentLifecycle::Starting),
        (1, AgentLifecycle::Running),
        (2, AgentLifecycle::Draining),
        (3, AgentLifecycle::Stopped),
    ] {
        let next = fleet
            .registry
            .compare_and_transition(&agent, generation, requested)?;
        let metadata = fs::metadata(lifecycle_path(layout.run_root(), next.generation))?;
        assert_eq!(metadata.uid(), original_uid);
        assert_eq!(metadata.mode() & 0o022, 0);
        assert_eq!(fleet.registry.load_agent(&agent)?.lifecycle, next);
    }
    let reopened = FleetRegistry::open_existing(fleet.root.clone())?;
    assert_eq!(reopened.load_agent(&agent)?.lifecycle.generation, 4);
    Ok(())
}

#[test]
fn control_reader_rejects_shared_write_symlink_and_fifo_inodes() -> Result<(), FleetRegistryError> {
    let (fleet, layout) = registered()?;
    let agent = AgentId::parse(FIRST_AGENT_ID)
        .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
    let initial = lifecycle_path(layout.run_root(), 0);
    let mode = fs::metadata(&initial)?.mode() & 0o777;
    fs::set_permissions(&initial, fs::Permissions::from_mode(mode | 0o020))?;
    assert!(fleet.registry.load_agent(&agent).is_err());
    fs::set_permissions(&initial, fs::Permissions::from_mode(mode))?;
    let manifest = layout.agent_config();
    let retained = layout.agent_root().join("retained-original-manifest");
    fs::rename(manifest, &retained)?;
    std::os::unix::fs::symlink(&retained, manifest)?;
    assert!(fleet.registry.load_agent(&agent).is_err());
    fs::remove_file(manifest)?;
    rustix::fs::mkfifo(manifest, rustix::fs::Mode::from_bits_truncate(0o600))
        .map_err(std::io::Error::from)?;
    // Opening occurs before fstat now: O_NONBLOCK is necessary to reject a
    // FIFO rather than waiting forever for a writer to an untrusted pathname.
    assert!(fleet.registry.load_agent(&agent).is_err());
    fs::remove_file(manifest)?;
    fs::rename(retained, manifest)?;
    assert_eq!(fleet.registry.load_agent(&agent)?.lifecycle.generation, 0);
    Ok(())
}

#[test]
fn checked_control_descriptor_retains_its_original_inode_across_path_replacement()
-> Result<(), FleetRegistryError> {
    let (_fleet, layout) = registered()?;
    let owner = crate::control_file::ControlOwner::at(layout.agent_root())?;
    let expected = fs::read_to_string(layout.agent_config())?;
    let mut held = owner.open(layout.agent_config())?;
    let inode = held.metadata()?.ino();
    fs::rename(
        layout.agent_config(),
        layout.agent_root().join("retained-original"),
    )?;
    fs::write(layout.agent_config(), b"replacement bytes")?;
    assert_ne!(fs::metadata(layout.agent_config())?.ino(), inode);
    let mut observed = String::new();
    held.read_to_string(&mut observed)?;
    assert_eq!(observed, expected);
    assert_eq!(held.metadata()?.ino(), inode);
    Ok(())
}
