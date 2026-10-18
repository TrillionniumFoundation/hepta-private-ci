//! Actual owner journals and the same Supervisor recovery entry point.
use super::*;
use pretty_assertions::assert_eq;

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    control: FakeControl,
    owner: Supervisor<FakeDriver>,
    configuration: SupervisorConfig,
    now: Instant,
}

impl Fixture {
    fn running() -> Result<Self, SupervisorError> {
        Self::running_with_config(config())
    }

    fn running_with_config(configuration: SupervisorConfig) -> Result<Self, SupervisorError> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse(AGENT_ID)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let source = temp.path().join("release");
        std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
        let release_id = ReleaseId::parse("restart-loss-release")?;
        registry.install_release(release_id.clone(), &source, Vec::new())?;
        registry.allow_release(&agent, &release_id)?;
        let release = AgentRelease::try_from(registry.resolve_release(&agent, &release_id)?)?;
        let control = FakeControl::default();
        let now = Instant::now();
        let (mut owner, report) = Supervisor::recover(
            registry.clone(),
            control.driver(),
            configuration.clone(),
            now,
        )?;
        assert_eq!(report, TickReport::default());
        owner.start_release(&agent, release, now)?;
        control.healthy(&agent);
        assert_eq!(owner.tick(now), TickReport::default());
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            control,
            owner,
            configuration,
            now,
        })
    }

    fn unready_replacement(&mut self) -> Result<(), SupervisorError> {
        self.control.crash(&self.agent);
        assert_eq!(self.owner.tick(self.now), TickReport::default());
        self.now += Duration::from_millis(250);
        assert_eq!(self.owner.tick(self.now), TickReport::default());
        assert_eq!(self.control.spawn_count(&self.agent), 2);
        Ok(())
    }
}

#[test]
fn missing_unhealthy_replacement_consumes_the_next_original_budget_attempt()
-> Result<(), SupervisorError> {
    for removed_by_previous_owner in [false, true] {
        let mut fixture = Fixture::running()?;
        fixture.unready_replacement()?;
        fixture.control.crash(&fixture.agent);
        let record = fixture.registry.load_agent(&fixture.agent)?;
        let owner_root = record.layout.owner_run_root();
        let before: serde_json::Value = serde_json::from_slice(&std::fs::read(
            owner_root.join("supervisor-restart-lineage.json"),
        )?)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        if removed_by_previous_owner {
            // The previous owner already proved Missing and removed its lease,
            // but crashed before resolving the exact replacement lineage.
            std::fs::remove_file(owner_root.join("supervisor-process.json"))?;
        }
        drop(fixture.owner);
        let (mut owner, report) = Supervisor::recover(
            fixture.registry.clone(),
            fixture.control.driver(),
            fixture.configuration.clone(),
            fixture.now,
        )?;
        assert_eq!(report, TickReport::default());
        let snapshot = owner.snapshot(&fixture.agent).expect("snapshot");
        assert!(
            snapshot.events.iter().any(|event| matches!(
                event.kind,
                SupervisorEventKind::AutomaticRestartQueued { attempt: 2 }
            )),
            "a proved missing replacement must remain runnable: {snapshot:?}"
        );
        let after: serde_json::Value = serde_json::from_slice(&std::fs::read(
            owner_root.join("supervisor-restart-lineage.json"),
        )?)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        assert_eq!(after["predecessor"], before["replacement"]);
        assert_eq!(
            after["window_started_unix_ms"],
            before["window_started_unix_ms"]
        );
        assert_eq!(after["attempt"], serde_json::json!(2));
        assert_eq!(fixture.control.spawn_count(&fixture.agent), 2);
        fixture.now += Duration::from_millis(500);
        assert_eq!(owner.tick(fixture.now), TickReport::default());
        assert_eq!(fixture.control.spawn_count(&fixture.agent), 3);
        fixture.control.healthy(&fixture.agent);
        assert_eq!(owner.tick(fixture.now), TickReport::default());
        assert!(owner.snapshot(&fixture.agent).expect("snapshot").healthy);
    }
    Ok(())
}

#[test]
fn running_process_absence_after_owner_recovery_uses_the_existing_restart_policy()
-> Result<(), SupervisorError> {
    let fixture = Fixture::running()?;
    fixture.control.crash(&fixture.agent);
    drop(fixture.owner);
    let (mut owner, report) = Supervisor::recover(
        fixture.registry,
        fixture.control.driver(),
        fixture.configuration.clone(),
        fixture.now,
    )?;
    assert_eq!(report, TickReport::default());
    let snapshot = owner.snapshot(&fixture.agent).expect("snapshot");
    assert!(snapshot.events.iter().any(|event| matches!(
        event.kind,
        SupervisorEventKind::AutomaticRestartQueued { attempt: 1 }
    )));
    assert_eq!(fixture.control.spawn_count(&fixture.agent), 1);
    assert_eq!(
        owner.tick(fixture.now + Duration::from_millis(250)),
        TickReport::default()
    );
    assert_eq!(fixture.control.spawn_count(&fixture.agent), 2);
    Ok(())
}

#[test]
fn unready_replacements_that_exit_in_one_owner_are_charged_until_budget_exhaustion()
-> Result<(), SupervisorError> {
    let mut fixture = Fixture::running()?;
    fixture.unready_replacement()?;
    for attempt in 2..=3 {
        fixture.control.crash(&fixture.agent);
        assert_eq!(fixture.owner.tick(fixture.now), TickReport::default());
        let snapshot = fixture.owner.snapshot(&fixture.agent).expect("snapshot");
        assert!(snapshot.events.iter().any(|event| matches!(
            event.kind, SupervisorEventKind::AutomaticRestartQueued { attempt: charged } if charged == attempt
        )));
        fixture.now += Duration::from_secs(1);
        assert_eq!(fixture.owner.tick(fixture.now), TickReport::default());
        assert_eq!(
            fixture.control.spawn_count(&fixture.agent),
            attempt as usize + 1
        );
    }
    fixture.control.crash(&fixture.agent);
    assert_eq!(fixture.owner.tick(fixture.now), TickReport::default());
    assert!(
        fixture
            .owner
            .snapshot(&fixture.agent)
            .expect("snapshot")
            .events
            .iter()
            .any(|event| matches!(
                event.kind,
                SupervisorEventKind::AutomaticRestartBudgetExhausted { attempts: 3 }
            ))
    );
    fixture.now += Duration::from_secs(10);
    assert_eq!(fixture.owner.tick(fixture.now), TickReport::default());
    assert_eq!(fixture.control.spawn_count(&fixture.agent), 4);
    Ok(())
}

#[test]
fn missing_lease_never_reopens_a_live_or_rejected_restart_identity() -> Result<(), SupervisorError>
{
    for foreign in [false, true] {
        let mut fixture = Fixture::running()?;
        fixture.unready_replacement()?;
        if foreign {
            fixture.control.update_latest(&fixture.agent, |state| {
                state.identity =
                    ProcessIdentity::new(state.identity.system_id(), "foreign-native-incarnation")
                        .expect("identity");
            });
        }
        let record = fixture.registry.load_agent(&fixture.agent)?;
        std::fs::remove_file(
            record
                .layout
                .owner_run_root()
                .join("supervisor-process.json"),
        )?;
        drop(fixture.owner);
        let (mut owner, _report) = Supervisor::recover(
            fixture.registry,
            fixture.control.driver(),
            fixture.configuration.clone(),
            fixture.now,
        )?;
        let snapshot = owner.snapshot(&fixture.agent).expect("snapshot");
        assert_eq!(snapshot.active, !foreign);
        assert!(!snapshot.healthy);
        assert_eq!(
            owner.tick(fixture.now + Duration::from_secs(10)),
            TickReport::default()
        );
        assert_eq!(fixture.control.spawn_count(&fixture.agent), 2);
        let lineage: serde_json::Value = serde_json::from_slice(&std::fs::read(
            record
                .layout
                .owner_run_root()
                .join("supervisor-restart-lineage.json"),
        )?)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        assert_eq!(lineage["phase"], serde_json::json!("replacement_started"));
    }
    Ok(())
}

#[test]
fn expired_unready_replacement_retains_its_original_charge_after_owner_recovery()
-> Result<(), SupervisorError> {
    let mut configuration = config();
    configuration.restart_window = Duration::from_millis(1);
    configuration.restart_backoff_base = Duration::from_millis(1);
    let mut fixture = Fixture::running_with_config(configuration)?;
    fixture.unready_replacement()?;
    fixture.control.crash(&fixture.agent);
    let record = fixture.registry.load_agent(&fixture.agent)?;
    let path = record
        .layout
        .owner_run_root()
        .join("supervisor-restart-lineage.json");
    let before: serde_json::Value = serde_json::from_slice(&std::fs::read(&path)?)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    std::thread::sleep(Duration::from_millis(2));
    drop(fixture.owner);
    let (mut owner, report) = Supervisor::recover(
        fixture.registry,
        fixture.control.driver(),
        fixture.configuration,
        fixture.now,
    )?;
    assert_eq!(report, TickReport::default());
    let after: serde_json::Value = serde_json::from_slice(&std::fs::read(&path)?)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    assert_eq!(
        after["window_started_unix_ms"],
        before["window_started_unix_ms"]
    );
    assert_eq!(after["attempt"], serde_json::json!(2));
    assert_eq!(after["predecessor"], before["replacement"]);
    assert_eq!(
        owner.tick(fixture.now + Duration::from_millis(1)),
        TickReport::default()
    );
    assert_eq!(fixture.control.spawn_count(&fixture.agent), 2);
    assert_eq!(
        owner.tick(fixture.now + Duration::from_millis(2)),
        TickReport::default()
    );
    assert_eq!(fixture.control.spawn_count(&fixture.agent), 3);
    Ok(())
}
