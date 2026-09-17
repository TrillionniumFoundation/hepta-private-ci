use std::collections::VecDeque;
use std::ffi::OsString;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessExit;
use crate::ProcessIdentity;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::Supervisor;
use crate::SupervisorConfig;
use crate::SupervisorEventKind;

struct ScriptedProcess {
    states: VecDeque<ProcessState>,
}

impl ManagedProcess for ScriptedProcess {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let state = self.states.pop_front().unwrap_or(ProcessState::Exited(ProcessExit {
            success: false,
            code: Some(91),
        }));
        Ok(ProcessObservation {
            state,
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        Ok(())
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        Ok(())
    }
}

struct RestartDriver {
    spawn_count: Arc<AtomicUsize>,
}

impl ProcessDriver for RestartDriver {
    type Process = ScriptedProcess;

    fn spawn(
        &mut self,
        _spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let attempt = self.spawn_count.fetch_add(1, Ordering::SeqCst);
        if attempt > 0 {
            return Err(ProcessDriverError::new(format!(
                "injected automatic spawn failure {attempt}"
            )));
        }
        Ok(SpawnedProcess {
            process: ScriptedProcess {
                states: VecDeque::from([
                    ProcessState::Running {
                        healthy: true,
                        drained: false,
                    },
                    ProcessState::Exited(ProcessExit {
                        success: false,
                        code: Some(17),
                    }),
                ]),
            },
            identity: ProcessIdentity::new(4242, "restart-qualification-child")?,
        })
    }

    fn adopt(
        &mut self,
        _spec: &AdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Ok(Adoption::Missing)
    }

    fn spawn_matrixd(
        &mut self,
        _spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        Err(ProcessDriverError::new(
            "Matrix is outside primary restart qualification",
        ))
    }

    fn adopt_matrixd(
        &mut self,
        _spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Ok(Adoption::Missing)
    }
}

#[test]
fn primary_agent_crash_uses_three_attempt_exponential_budget_then_stops() {
    let temp = tempfile::tempdir().expect("temporary fleet");
    let fleet_root = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
    let workspace = temp.path().join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("fixed AgentId");
    registry
        .register(
            AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(
                    workspace.canonicalize().expect("canonical workspace"),
                    &fleet_root,
                )
                .expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register agent");

    let spawn_count = Arc::new(AtomicUsize::new(0));
    let driver = RestartDriver {
        spawn_count: Arc::clone(&spawn_count),
    };
    let config = SupervisorConfig {
        health_timeout: Duration::from_secs(1),
        drain_timeout: Duration::from_secs(1),
        stop_grace: Duration::from_secs(1),
        event_capacity: 64,
        log_capacity: 64,
        max_log_bytes: 1024,
        driver_poll_batch: 16,
    };
    let now = Instant::now();
    let (mut supervisor, recovery) =
        Supervisor::recover(registry, driver, config, now).expect("recover supervisor");
    assert!(recovery.faults.is_empty());

    supervisor
        .start(
            &agent_id,
            AgentCommand::new(
                "/qualification/agentd",
                Vec::<OsString>::new(),
            )
            .expect("command"),
            now,
        )
        .expect("initial start");

    // First poll establishes readiness; second poll is the unexpected crash
    // that opens automatic recovery attempt #1.
    assert!(supervisor.tick(now + Duration::from_millis(1)).faults.is_empty());
    assert!(supervisor.tick(now + Duration::from_millis(2)).faults.is_empty());

    let snapshot = supervisor.snapshot(&agent_id).expect("snapshot after crash");
    assert!(snapshot.events.iter().any(|event| matches!(
        event.kind,
        SupervisorEventKind::AutomaticRestartScheduled {
            attempt: 1,
            delay_ms: 250
        }
    )));

    // Each due automatic start is injected to fail. A failure consumes the
    // attempt already scheduled and queues the next backoff until attempt #3.
    let _ = supervisor.tick(now + Duration::from_millis(252));
    let _ = supervisor.tick(now + Duration::from_millis(752));
    let _ = supervisor.tick(now + Duration::from_millis(1_752));

    assert_eq!(
        spawn_count.load(Ordering::SeqCst),
        4,
        "one initial start plus exactly three automatic start attempts"
    );
    let exhausted = supervisor.snapshot(&agent_id).expect("exhausted snapshot");
    assert!(exhausted.events.iter().any(|event| matches!(
        event.kind,
        SupervisorEventKind::RestartBudgetExhausted { attempts: 3 }
    )));

    // Advancing well within the same five-minute recovery window must not
    // attempt a fourth automatic spawn.
    let _ = supervisor.tick(now + Duration::from_secs(30));
    assert_eq!(spawn_count.load(Ordering::SeqCst), 4);
}
