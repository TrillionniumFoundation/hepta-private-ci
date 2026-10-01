//! Real Fleet records and filesystem changes at the constructor observation
//! boundary. These are not startup latency or target-host execution receipts.

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::*;

struct Fixture {
    temporary: tempfile::TempDir,
    registry: FleetRegistry,
    first: AgentId,
    second: AgentId,
}

impl Fixture {
    fn new() -> Result<Self> {
        let temporary = tempfile::tempdir()?;
        let base = temporary.path().canonicalize()?;
        let root = HeptaFleetRoot::parse(base.join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let first = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let second = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")?;
        for (agent, name) in [(&first, "first-workspace"), (&second, "second-workspace")] {
            let workspace = base.join(name);
            std::fs::create_dir(&workspace)?;
            registry.register(AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(workspace, &root)?,
                ResourceBudget::local_default(),
            )?)?;
        }
        Ok(Self {
            temporary,
            registry,
            first,
            second,
        })
    }

    fn record(&self) -> Result<AgentRecord> {
        Ok(self
            .registry
            .load()?
            .agent(&self.first)
            .expect("first Agent")
            .clone())
    }
}

fn witness_paths(record: &AgentRecord) -> Vec<std::path::PathBuf> {
    let run = record.layout.run_root();
    vec![
        run.join(crate::lease::PROCESS_LEASE_FILE),
        record.layout.matrixd_process_lease().to_path_buf(),
        run.join(crate::control_intent::CONTROL_INTENT_FILE),
        run.join(crate::restart_journal::RESTART_JOURNAL_FILE),
        run.join(crate::restart_lineage::RESTART_LINEAGE_FILE),
        run.join(crate::release_transaction::RELEASE_TRANSACTION_FILE),
        run.join(crate::signed_intent::SIGNED_INTENT_FILE),
        run.join(crate::signed_intent::SIGNED_INTENT_RECOVERY_FILE),
    ]
}

#[test]
fn initial_idle_record_survives_complete_fleet_revalidation() -> Result<()> {
    let fixture = Fixture::new()?;
    let initial = fixture.record()?;
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fixture.first, &initial));
    assert!(observation.record_if_idle(&fixture.first, &initial));
    assert_eq!(
        observation.agents().cloned().collect::<Vec<_>>(),
        vec![fixture.first]
    );
    assert!(observation.changed_agents(&fixture.registry)?.is_empty());
    Ok(())
}

#[test]
fn empty_observation_does_not_read_an_unrelated_corrupt_fleet() -> Result<()> {
    let fixture = Fixture::new()?;
    let unrelated = fixture.registry.layout().agent(&fixture.second);
    std::fs::write(unrelated.agent_config(), b"not = [")?;
    assert!(fixture.registry.load().is_err());
    assert!(
        ConstructorHydrationObservation::default()
            .changed_agents(&fixture.registry)?
            .is_empty()
    );
    Ok(())
}

#[test]
fn empty_release_cas_generation_change_cannot_hide_behind_absent_run_witnesses() -> Result<()> {
    let fixture = Fixture::new()?;
    let initial = fixture.record()?;
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fixture.first, &initial));
    let successor = fixture.registry.compare_and_set_release_state(
        &fixture.first,
        /*expected_generation*/ 0,
        /*current*/ None,
        /*previous*/ None,
    )?;
    assert_eq!(successor.generation, 1);
    assert!(
        witness_paths(&initial)
            .into_iter()
            .all(|path| !path.exists())
    );
    assert_eq!(
        observation.changed_agents(&fixture.registry)?,
        vec![fixture.first.clone()]
    );
    assert!(!observation.record_if_idle(&fixture.first, &fixture.record()?));
    assert_eq!(
        observation.changed_agents(&fixture.registry)?,
        vec![fixture.first]
    );
    Ok(())
}

#[test]
fn observed_idle_record_still_requires_unrelated_agent_global_validation() -> Result<()> {
    let fixture = Fixture::new()?;
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fixture.first, &fixture.record()?));
    let unrelated = fixture.registry.layout().agent(&fixture.second);
    std::fs::write(unrelated.agent_config(), b"not = [")?;
    assert!(observation.changed_agents(&fixture.registry).is_err());
    assert_eq!(
        observation.agents().cloned().collect::<Vec<_>>(),
        vec![fixture.first]
    );
    Ok(())
}

#[test]
fn every_new_durable_witness_forces_fresh_recovery_without_changing_the_fleet_record() -> Result<()>
{
    let fixture = Fixture::new()?;
    let initial = fixture.record()?;
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fixture.first, &initial));
    for path in witness_paths(&initial) {
        std::fs::write(&path, b"damaged evidence must reach its original codec")?;
        assert_eq!(fixture.record()?, initial);
        assert_eq!(
            observation.changed_agents(&fixture.registry)?,
            vec![fixture.first.clone()]
        );
        assert!(
            !ConstructorHydrationObservation::default().record_if_idle(&fixture.first, &initial)
        );
        std::fs::remove_file(path)?;
    }
    assert!(observation.changed_agents(&fixture.registry)?.is_empty());
    Ok(())
}

#[test]
fn missing_observed_agent_forces_fresh_recovery() -> Result<()> {
    let fixture = Fixture::new()?;
    let initial = fixture.record()?;
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fixture.first, &initial));
    std::fs::rename(
        initial.layout.agent_root(),
        fixture.temporary.path().join("removed-agent"),
    )?;
    assert_eq!(
        observation.changed_agents(&fixture.registry)?,
        vec![fixture.first]
    );
    Ok(())
}

#[test]
fn missing_or_non_directory_run_parent_is_never_an_idle_observation() -> Result<()> {
    let fixture = Fixture::new()?;
    let initial = fixture.record()?;
    let run = initial.layout.run_root();
    let saved = fixture.temporary.path().join("saved-run");
    std::fs::rename(run, &saved)?;
    assert!(!ConstructorHydrationObservation::default().record_if_idle(&fixture.first, &initial));
    std::fs::write(run, b"not a physical directory")?;
    assert!(!ConstructorHydrationObservation::default().record_if_idle(&fixture.first, &initial));
    std::fs::remove_file(run)?;
    std::fs::rename(saved, run)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn symlink_parent_and_special_file_witnesses_are_never_absence() -> Result<()> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;

    let fixture = Fixture::new()?;
    let initial = fixture.record()?;
    let mut observation = ConstructorHydrationObservation::default();
    assert!(observation.record_if_idle(&fixture.first, &initial));
    let witness = initial
        .layout
        .run_root()
        .join(crate::signed_intent::SIGNED_INTENT_RECOVERY_FILE);
    std::os::unix::fs::symlink(fixture.temporary.path().join("absent"), &witness)?;
    assert!(!ConstructorHydrationObservation::default().record_if_idle(&fixture.first, &initial));
    assert_eq!(
        observation.changed_agents(&fixture.registry)?,
        vec![fixture.first.clone()]
    );
    std::fs::remove_file(&witness)?;
    let fifo = CString::new(witness.as_os_str().as_bytes())?;
    // SAFETY: fifo is a live NUL-terminated pathname for this synchronous call.
    assert_eq!(
        unsafe {
            libc::mkfifo(fifo.as_ptr(), /*mode*/ 0o600)
        },
        0
    );
    assert!(!ConstructorHydrationObservation::default().record_if_idle(&fixture.first, &initial));
    assert_eq!(
        observation.changed_agents(&fixture.registry)?,
        vec![fixture.first.clone()]
    );
    std::fs::remove_file(&witness)?;
    let run = initial.layout.run_root();
    let saved = fixture.temporary.path().join("saved-run");
    std::fs::rename(run, &saved)?;
    std::os::unix::fs::symlink(&saved, run)?;
    assert!(!ConstructorHydrationObservation::default().record_if_idle(&fixture.first, &initial));
    assert!(observation.changed_agents(&fixture.registry).is_err());
    std::fs::remove_file(run)?;
    std::fs::rename(saved, run)?;
    Ok(())
}
