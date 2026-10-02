use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use anyhow::Result;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use super::*;
use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentRelease;
use crate::ManagedProcess;
use crate::ProcessDriverError;
use crate::ProcessExit;
use crate::ProcessIdentity;
use crate::ProcessLog;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::ProcessStream;
use crate::SpawnSpec;
use crate::SupervisorConfig;
use crate::daemon::status_from;
use crate::driver::SpawnedProcess;

#[derive(Default)]
struct Signals {
    healthy: AtomicBool,
    log: AtomicBool,
}

struct Driver(Arc<Signals>);
struct Process {
    signals: Arc<Signals>,
    exited: bool,
}

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        Ok(SpawnedProcess {
            identity: ProcessIdentity::new(
                100 + spec.generation,
                format!("{}-{}", spec.agent_id, spec.generation),
            )
            .map_err(|error| ProcessDriverError::new(error.to_string()))?,
            process: Process {
                signals: Arc::clone(&self.0),
                exited: false,
            },
        })
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Ok(Adoption::Missing)
    }
}

impl ManagedProcess for Process {
    fn poll(&mut self, max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        Ok(ProcessObservation {
            state: if self.exited {
                ProcessState::Exited(ProcessExit {
                    success: true,
                    code: Some(0),
                })
            } else {
                ProcessState::Running {
                    healthy: self.signals.healthy.load(Ordering::Relaxed),
                    drained: false,
                }
            },
            logs: if max_logs > 0 && self.signals.log.swap(false, Ordering::Relaxed) {
                vec![ProcessLog {
                    stream: ProcessStream::Stdout,
                    bytes: b"fresh diagnostic".to_vec(),
                }]
            } else {
                Vec::new()
            },
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        Ok(())
    }
    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.exited = true;
        Ok(())
    }
    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.exited = true;
        Ok(())
    }
}

struct Fixture {
    temp: tempfile::TempDir,
    registry: FleetRegistry,
    supervisor: Supervisor<Driver>,
    signals: Arc<Signals>,
    agents: [AgentId; 2],
    epoch: SupervisorEpoch,
    view: ReadView,
}

impl Fixture {
    fn new() -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().canonicalize()?.join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let agents = [
            AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?,
            AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3")?,
        ];
        for (index, agent) in agents.iter().enumerate() {
            let workspace = temp.path().join(format!("workspace-{index}"));
            std::fs::create_dir(&workspace)?;
            registry.register(AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
                ResourceBudget::local_default(),
            )?)?;
        }
        let signals = Arc::new(Signals::default());
        let (supervisor, report) = Supervisor::recover(
            registry.clone(),
            Driver(Arc::clone(&signals)),
            SupervisorConfig::local_default(),
            Instant::now(),
        )?;
        assert_eq!(report, crate::TickReport::default());
        let fixture = Self {
            temp,
            registry,
            supervisor,
            signals,
            agents,
            epoch: SupervisorEpoch::new(),
            view: ReadView::default(),
        };
        fixture.publish()?;
        Ok(fixture)
    }

    fn publish(&self) -> Result<()> {
        self.view
            .publish(&self.registry, &self.supervisor, &self.epoch)?;
        Ok(())
    }

    fn observation(&self) -> Arc<Observation> {
        self.view
            .current
            .read()
            .expect("read view lock")
            .clone()
            .expect("published observation")
    }

    fn start(&mut self) -> Result<()> {
        let source = self.temp.path().join("source");
        std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
        let release_id = ReleaseId::parse("projection-v1")?;
        self.registry
            .install_release(release_id.clone(), &source, Vec::new())?;
        self.registry.allow_release(&self.agents[0], &release_id)?;
        let release = AgentRelease::try_from(
            self.registry
                .resolve_release(&self.agents[0], &release_id)?,
        )?;
        self.supervisor
            .start_release(&self.agents[0], release, Instant::now())?;
        self.signals.healthy.store(true, Ordering::Relaxed);
        assert_eq!(
            self.supervisor.tick(Instant::now()),
            crate::TickReport::default()
        );
        self.publish()
    }
}

#[test]
fn unchanged_capture_reuses_every_agent_but_refreshes_capture_time() -> Result<()> {
    let fixture = Fixture::new()?;
    let previous = fixture.observation();
    fixture.publish()?;
    let current = fixture.observation();
    assert!(current.captured_at >= previous.captured_at);
    assert!(!Arc::ptr_eq(&previous, &current));
    for agent in &fixture.agents {
        assert!(Arc::ptr_eq(&previous.agents[agent], &current.agents[agent]));
    }
    assert_eq!(current.ready, previous.ready);
    Ok(())
}

#[test]
fn external_fleet_cas_and_removal_change_only_the_affected_projection() -> Result<()> {
    let fixture = Fixture::new()?;
    let previous = fixture.observation();
    fixture.registry.compare_and_transition(
        &fixture.agents[0],
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    fixture.publish()?;
    let current = fixture.observation();
    assert!(!Arc::ptr_eq(
        &previous.agents[&fixture.agents[0]],
        &current.agents[&fixture.agents[0]]
    ));
    assert!(Arc::ptr_eq(
        &previous.agents[&fixture.agents[1]],
        &current.agents[&fixture.agents[1]]
    ));
    let record = fixture
        .registry
        .load()?
        .agents
        .remove(&fixture.agents[0])
        .expect("registered Agent");
    assert_eq!(
        current.agents[&fixture.agents[0]].as_ref(),
        &status_from(
            &fixture.epoch,
            &record,
            fixture.supervisor.metadata_snapshot(&fixture.agents[0])
        )?
    );
    let removed = fixture
        .registry
        .load()?
        .agents
        .remove(&fixture.agents[1])
        .expect("registered Agent");
    std::fs::remove_dir_all(removed.layout.agent_root())?;
    fixture.publish()?;
    let pruned = fixture.observation();
    assert_eq!(pruned.agents.len(), 1);
    assert_eq!(pruned.inputs.len(), 1);
    assert!(Arc::ptr_eq(
        &current.agents[&fixture.agents[0]],
        &pruned.agents[&fixture.agents[0]]
    ));
    assert!(
        matches!(fixture.view.respond(&SupervisordMethod::Snapshot { agent_id: fixture.agents[1].clone() }, Instant::now(), /*observed_faults*/ 0), Some(SupervisordPayload::Error { ref code, .. }) if code == "unknown_agent")
    );
    Ok(())
}

#[test]
fn health_without_revision_change_is_dirty_but_diagnostic_rings_are_not() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.start()?;
    let agent = &fixture.agents[0];
    let previous = fixture.observation();
    let before = fixture
        .supervisor
        .metadata_snapshot(agent)
        .expect("runtime");
    fixture.signals.log.store(true, Ordering::Relaxed);
    assert_eq!(
        fixture.supervisor.tick(Instant::now()),
        crate::TickReport::default()
    );
    let full = fixture.supervisor.snapshot(agent).expect("runtime");
    assert!(!full.logs.is_empty() && !full.events.is_empty());
    let mut metadata = full.clone();
    metadata.logs.clear();
    metadata.events.clear();
    assert_eq!(Some(metadata), fixture.supervisor.metadata_snapshot(agent));
    fixture.publish()?;
    let logged = fixture.observation();
    assert!(Arc::ptr_eq(&previous.agents[agent], &logged.agents[agent]));
    assert_eq!(fixture.supervisor.snapshot(agent), Some(full));
    fixture.signals.healthy.store(false, Ordering::Relaxed);
    assert_eq!(
        fixture.supervisor.tick(Instant::now()),
        crate::TickReport::default()
    );
    let after = fixture
        .supervisor
        .metadata_snapshot(agent)
        .expect("runtime");
    assert_eq!(after.control_revision, before.control_revision);
    assert!(!after.healthy);
    fixture.publish()?;
    let unhealthy = fixture.observation();
    assert!(!Arc::ptr_eq(
        &logged.agents[agent],
        &unhealthy.agents[agent]
    ));
    assert!(Arc::ptr_eq(
        &logged.agents[&fixture.agents[1]],
        &unhealthy.agents[&fixture.agents[1]]
    ));
    assert!(!unhealthy.agents[agent].healthy);
    Ok(())
}

#[test]
fn matrix_and_hidden_cas_metadata_changes_cannot_reuse_an_old_status() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.start()?;
    let agent = &fixture.agents[0];
    let previous = fixture.observation();
    let record = fixture
        .registry
        .load()?
        .agents
        .remove(agent)
        .expect("registered Agent");
    let runtime = fixture
        .supervisor
        .metadata_snapshot(agent)
        .expect("runtime");
    let changes: [fn(&mut crate::AgentSupervisorSnapshot); 12] = [
        |value| value.matrix.healthy = true,
        |value| value.matrix.degraded = true,
        |value| value.matrix.last_error = Some("new diagnostic".to_string()),
        |value| value.matrix.restart_attempt += 1,
        |value| value.matrix.binding_revision = Some(1),
        |value| value.matrix.attached_agent_generation = Some(1),
        |value| value.runtime_fenced = true,
        |value| value.runtime_incarnation = Some("different owner".to_string()),
        |value| value.restart_pending = true,
        |value| value.restart_attempt += 1,
        |value| value.release_state_generation += 1,
        |value| value.has_last_command = false,
    ];
    for change in changes {
        let mut changed = runtime.clone();
        change(&mut changed);
        assert_ne!(changed, runtime);
        assert_eq!(changed.control_revision, runtime.control_revision);
        let expected = status_from(&fixture.epoch, &record, Some(changed.clone()))?;
        let (_, status) = ProjectionInput::capture(
            &fixture.epoch,
            record.clone(),
            Some(changed),
            Some((&previous.inputs[agent], &previous.agents[agent])),
        )?;
        assert!(!Arc::ptr_eq(&previous.agents[agent], &status));
        assert_eq!(status.as_ref(), &expected);
        assert_ne!(
            status.control_fence.state_digest,
            previous.agents[agent].control_fence.state_digest
        );
    }
    let mut changed_record = record;
    changed_record.release_state.current = Some(ReleaseId::parse("external-release-selection")?);
    let (_, status) = ProjectionInput::capture(
        &fixture.epoch,
        changed_record.clone(),
        Some(runtime.clone()),
        Some((&previous.inputs[agent], &previous.agents[agent])),
    )?;
    assert!(!Arc::ptr_eq(&previous.agents[agent], &status));
    assert_eq!(
        status.as_ref(),
        &status_from(&fixture.epoch, &changed_record, Some(runtime))?
    );
    assert_ne!(
        status.control_fence.state_digest,
        previous.agents[agent].control_fence.state_digest
    );
    Ok(())
}

#[test]
fn epoch_and_invalidation_discard_all_reuse_preimages() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let previous = fixture.observation();
    fixture.epoch = SupervisorEpoch::new();
    fixture.publish()?;
    let successor = fixture.observation();
    for agent in &fixture.agents {
        assert!(!Arc::ptr_eq(
            &previous.agents[agent],
            &successor.agents[agent]
        ));
        assert_eq!(
            successor.agents[agent].control_fence.supervisor_epoch,
            fixture.epoch
        );
    }
    fixture.view.invalidate();
    assert_eq!(
        fixture.view.respond(
            &SupervisordMethod::Health,
            Instant::now(),
            /*observed_faults*/ 0
        ),
        Some(unavailable())
    );
    fixture.publish()?;
    let refreshed = fixture.observation();
    for agent in &fixture.agents {
        assert!(!Arc::ptr_eq(
            &successor.agents[agent],
            &refreshed.agents[agent]
        ));
    }
    Ok(())
}

#[test]
fn lease_readiness_is_recaptured_even_when_every_status_is_reused() -> Result<()> {
    let fixture = Fixture::new()?;
    let previous = fixture.observation();
    assert!(previous.ready);
    let record = fixture
        .registry
        .load()?
        .agents
        .remove(&fixture.agents[0])
        .expect("registered Agent");
    let lease = crate::lease::ProcessLease {
        schema_version: crate::lease::PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: fixture.agents[0].clone(),
        spawn_generation: 1,
        release_id: ReleaseId::parse("external-owner")?,
        identity: ProcessIdentity::new(/*system_id*/ 42, "external-owner")?,
    };
    crate::lease::write_lease(record.layout.run_root(), &lease)?;
    fixture.publish()?;
    let unresolved = fixture.observation();
    assert!(!unresolved.ready);
    for agent in &fixture.agents {
        assert!(Arc::ptr_eq(
            &previous.agents[agent],
            &unresolved.agents[agent]
        ));
    }
    crate::lease::remove_lease(record.layout.run_root(), &lease)?;
    fixture.publish()?;
    assert!(fixture.observation().ready);
    Ok(())
}

#[test]
fn poisoned_view_never_reuses_or_serves_prior_contents() -> Result<()> {
    let fixture = Fixture::new()?;
    let poisoned = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        let _current = fixture.view.current.write().expect("initial write lock");
        panic!("injected read view publication panic");
    }));
    assert!(poisoned.is_err());
    assert!(fixture.publish().is_err());
    fixture.view.invalidate();
    for method in [
        SupervisordMethod::Health,
        SupervisordMethod::Roster { limit: 2 },
        SupervisordMethod::Snapshot {
            agent_id: fixture.agents[0].clone(),
        },
    ] {
        assert_eq!(
            fixture
                .view
                .respond(&method, Instant::now(), /*observed_faults*/ 0),
            Some(unavailable())
        );
    }
    Ok(())
}

#[test]
fn failed_ownership_capture_invalidates_then_rebuilds_every_agent() -> Result<()> {
    let fixture = Fixture::new()?;
    let previous = fixture.observation();
    let record = fixture
        .registry
        .load()?
        .agents
        .remove(&fixture.agents[0])
        .expect("registered Agent");
    let path = record.layout.run_root().join("supervisor-process.json");
    std::fs::write(&path, b"{broken lease")?;
    assert!(fixture.publish().is_err());
    // The lifecycle refresh caller invalidates on every capture error. There
    // is no successful status-cache fallback for a failed readiness check.
    fixture.view.invalidate();
    assert_eq!(
        fixture.view.respond(
            &SupervisordMethod::Health,
            Instant::now(),
            /*observed_faults*/ 0
        ),
        Some(unavailable())
    );
    std::fs::remove_file(path)?;
    fixture.publish()?;
    let recovered = fixture.observation();
    assert!(recovered.ready);
    for agent in &fixture.agents {
        assert!(!Arc::ptr_eq(
            &previous.agents[agent],
            &recovered.agents[agent]
        ));
    }
    Ok(())
}
