#![cfg(all(unix, feature = "qualification"))]

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AdoptSpec;
use codex_hepta_supervisor::Adoption;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_supervisor::ManagedProcess;
use codex_hepta_supervisor::ProcessDriver;
use codex_hepta_supervisor::ProcessDriverError;
use codex_hepta_supervisor::ProcessExit;
use codex_hepta_supervisor::ProcessIdentity;
use codex_hepta_supervisor::ProcessObservation;
use codex_hepta_supervisor::ProcessState;
use codex_hepta_supervisor::SpawnSpec;
use codex_hepta_supervisor::SpawnedProcess;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::qualification_mutex::MeasuredMutex;
use serde_json::json;
use tokio::sync::RwLock;

const INSTANCE_COUNT: usize = 256;

#[derive(Clone, Default)]
struct QualificationControl {
    world: Arc<Mutex<QualificationWorld>>,
}

#[derive(Default)]
struct QualificationWorld {
    next_id: u64,
    poll_delay: Duration,
    processes: BTreeMap<u64, QualificationProcessState>,
}

struct QualificationProcessState {
    agent_id: AgentId,
    identity: ProcessIdentity,
    healthy: bool,
    drained: bool,
    exit: Option<ProcessExit>,
}

struct QualificationDriver {
    world: Arc<Mutex<QualificationWorld>>,
}

struct QualificationProcess {
    id: u64,
    world: Arc<Mutex<QualificationWorld>>,
}

impl QualificationControl {
    fn driver(&self) -> QualificationDriver {
        QualificationDriver {
            world: Arc::clone(&self.world),
        }
    }

    #[expect(
        clippy::expect_used,
        reason = "poisoned fixture state must fail qualification rather than supply a successful measurement"
    )]
    fn set_poll_delay(&self, delay: Duration) {
        self.world.lock().expect("qualification world").poll_delay = delay;
    }

    #[expect(
        clippy::expect_used,
        reason = "poisoned fixture state must fail qualification rather than omit a requested fault wave"
    )]
    fn crash_prefix(&self, agents: &[AgentId], count: usize) {
        let mut world = self.world.lock().expect("qualification world");
        for agent_id in agents.iter().take(count) {
            if let Some(state) = world
                .processes
                .values_mut()
                .rev()
                .find(|state| &state.agent_id == agent_id && state.exit.is_none())
            {
                state.exit = Some(ProcessExit {
                    success: false,
                    code: Some(137),
                });
            }
        }
    }
}

impl ProcessDriver for QualificationDriver {
    type Process = QualificationProcess;

    #[expect(
        clippy::expect_used,
        reason = "poisoned process fixture state must fail the qualification run"
    )]
    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let mut world = self.world.lock().expect("qualification world");
        world.next_id = world.next_id.saturating_add(1);
        let id = world.next_id;
        let identity = ProcessIdentity::new(id, format!("qualification-{id}-{}", spec.generation))
            .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        world.processes.insert(
            id,
            QualificationProcessState {
                agent_id: spec.agent_id.clone(),
                identity: identity.clone(),
                healthy: true,
                drained: false,
                exit: None,
            },
        );
        Ok(SpawnedProcess {
            identity,
            process: QualificationProcess {
                id,
                world: Arc::clone(&self.world),
            },
        })
    }

    #[expect(
        clippy::expect_used,
        reason = "poisoned process fixture state must fail the qualification run"
    )]
    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        let world = self.world.lock().expect("qualification world");
        let Some((&id, _)) = world.processes.iter().find(|(_, state)| {
            state.agent_id == spec.agent_id
                && state.identity == spec.identity
                && state.exit.is_none()
        }) else {
            return Ok(Adoption::Missing);
        };
        Ok(Adoption::Adopted(QualificationProcess {
            id,
            world: Arc::clone(&self.world),
        }))
    }
}

impl ManagedProcess for QualificationProcess {
    #[expect(
        clippy::expect_used,
        reason = "poisoned state or a missing fixture process invalidates the qualification observation"
    )]
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let delay = self.world.lock().expect("qualification world").poll_delay;
        if !delay.is_zero() {
            std::thread::sleep(delay);
        }
        let world = self.world.lock().expect("qualification world");
        let state = world
            .processes
            .get(&self.id)
            .expect("qualification process");
        Ok(ProcessObservation {
            state: state.exit.map_or(
                ProcessState::Running {
                    healthy: state.healthy,
                    drained: state.drained,
                },
                ProcessState::Exited,
            ),
            logs: Vec::new(),
        })
    }

    #[expect(
        clippy::expect_used,
        reason = "fixture control requires the exact existing process and unpoisoned state"
    )]
    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.world
            .lock()
            .expect("qualification world")
            .processes
            .get_mut(&self.id)
            .expect("qualification process")
            .drained = true;
        Ok(())
    }

    #[expect(
        clippy::expect_used,
        reason = "fixture control requires the exact existing process and unpoisoned state"
    )]
    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.world
            .lock()
            .expect("qualification world")
            .processes
            .get_mut(&self.id)
            .expect("qualification process")
            .exit = Some(ProcessExit {
            success: true,
            code: Some(0),
        });
        Ok(())
    }

    #[expect(
        clippy::expect_used,
        reason = "fixture control requires the exact existing process and unpoisoned state"
    )]
    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.world
            .lock()
            .expect("qualification world")
            .processes
            .get_mut(&self.id)
            .expect("qualification process")
            .exit = Some(ProcessExit {
            success: false,
            code: Some(137),
        });
        Ok(())
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn qualifies_256_instances_fault_waves_and_owner_lock_hol() -> Result<(), SupervisorError> {
    let temp = tempfile::tempdir()?;
    let root = HeptaFleetRoot::parse(temp.path().join("fleet"))
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let agents = register_agents(&registry, &root, temp.path())?;
    let control = QualificationControl::default();
    let config = SupervisorConfig {
        health_timeout: Duration::from_secs(5),
        drain_timeout: Duration::from_secs(5),
        stop_grace: Duration::from_secs(1),
        event_capacity: 256,
        log_capacity: 16,
        max_log_bytes: 1_024,
        driver_poll_batch: INSTANCE_COUNT,
        restart_max_attempts: 3,
        restart_window: Duration::from_secs(300),
        restart_backoff_base: Duration::from_millis(1),
    };
    let started = Instant::now();
    let (mut supervisor, _) = Supervisor::recover(registry, control.driver(), config, started)?;
    let program: PathBuf = std::env::temp_dir()
        .join("hepta-supervisor-tests")
        .join("qualification-agentd");
    for agent_id in &agents {
        supervisor.start(
            agent_id,
            AgentCommand::new(program.clone(), Vec::new())?,
            started,
        )?;
    }
    let _ = supervisor.tick(started);

    let owner = Arc::new(MeasuredMutex::new(supervisor));
    let read_view = Arc::new(RwLock::new(agents.clone()));
    let healthy = run_tick_with_status(&owner, &read_view, started + Duration::from_secs(1)).await;

    control.set_poll_delay(Duration::from_micros(100));
    let slow_driver =
        run_tick_with_status(&owner, &read_view, started + Duration::from_secs(2)).await;
    control.set_poll_delay(Duration::ZERO);

    let slow_fs_before = owner.snapshot();
    let slow_fs_owner = Arc::clone(&owner);
    let slow_fs_root = temp.path().join("slow-fs");
    let slow_fs = tokio::spawn(async move {
        std::fs::create_dir_all(&slow_fs_root).expect("slow fs root");
        let _guard = slow_fs_owner.lock().await;
        let path = slow_fs_root.join("probe");
        let file = std::fs::File::create(path).expect("slow fs probe");
        file.sync_all().expect("slow fs sync");
        std::thread::sleep(Duration::from_millis(30));
    });
    tokio::time::sleep(Duration::from_millis(1)).await;
    let status_during_slow_fs = spawn_status_reads(&read_view, 64).await;
    let mutation_wait = spawn_owner_snapshots(&owner, &agents[..64]).await;
    slow_fs.await.expect("slow fs holder");
    let slow_fs_metrics = json!({
        "status_read_latency": summarize(&status_during_slow_fs),
        "owner_wait_latency": summarize(&mutation_wait),
        "lock_delta": lock_json(owner.snapshot().delta(slow_fs_before)),
    });

    let concurrent = run_concurrent_drain_status_mutation(
        &owner,
        &read_view,
        &agents,
        started + Duration::from_secs(3),
    )
    .await;

    let mut fault_waves = Vec::new();
    for (label, count) in [
        ("10_percent", INSTANCE_COUNT / 10),
        ("50_percent", INSTANCE_COUNT / 2),
        ("100_percent", INSTANCE_COUNT),
    ] {
        control.crash_prefix(&agents, count);
        let metrics = run_tick_with_status(
            &owner,
            &read_view,
            started + Duration::from_secs(4 + fault_waves.len() as u64),
        )
        .await;
        fault_waves.push(json!({"wave": label, "metrics": metrics}));
    }

    let telemetry = owner.snapshot();
    let receipt = json!({
        "schema": "hepta.runtime-supervisor.hol-qualification.v1",
        "instances": INSTANCE_COUNT,
        "healthy": healthy,
        "slow_driver": slow_driver,
        "slow_filesystem": slow_fs_metrics,
        "concurrent_drain_status_mutation": concurrent,
        "fault_waves": fault_waves,
        "lock": lock_json(telemetry),
    });
    println!(
        "runtime_supervisor_256_instance_qualification={}",
        serde_json::to_string(&receipt)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
    );
    assert!(telemetry.acquisitions > 0);
    assert!(telemetry.contended_acquisitions > 0);
    assert!(telemetry.hold_max_us >= 25_000);
    assert!(telemetry.wait_max_us >= 1_000);
    Ok(())
}

fn register_agents(
    registry: &FleetRegistry,
    root: &HeptaFleetRoot,
    temp: &std::path::Path,
) -> Result<Vec<AgentId>, SupervisorError> {
    let mut agents = Vec::with_capacity(INSTANCE_COUNT);
    for index in 0..INSTANCE_COUNT {
        let agent_id = AgentId::parse(format!("018f4f72-{index:04x}-7cc1-8f55-{index:012x}"))
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let workspace = temp.join(format!("workspace-{index:03}"));
        std::fs::create_dir(&workspace)?;
        registry.register(AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, root)?,
            ResourceBudget::local_default(),
        )?)?;
        agents.push(agent_id);
    }
    Ok(agents)
}

#[expect(
    clippy::expect_used,
    reason = "a failed tick task must fail qualification rather than emit a latency receipt"
)]
async fn run_tick_with_status(
    owner: &Arc<MeasuredMutex<Supervisor<QualificationDriver>>>,
    read_view: &Arc<RwLock<Vec<AgentId>>>,
    now: Instant,
) -> serde_json::Value {
    let before = owner.snapshot();
    let tick_owner = Arc::clone(owner);
    let tick = tokio::spawn(async move {
        let started = Instant::now();
        let report = tick_owner.lock().await.tick(now);
        (started.elapsed(), report.faults.len())
    });
    tokio::task::yield_now().await;
    let status_latencies = spawn_status_reads(read_view, 64).await;
    let selected_agents = {
        let view = read_view.read().await;
        view[..64].to_vec()
    };
    let owner_latencies = spawn_owner_snapshots(owner, &selected_agents).await;
    let (tick_elapsed, faults) = tick.await.expect("tick task");
    json!({
        "tick_elapsed_us": micros(tick_elapsed),
        "fault_count": faults,
        "status_read_latency": summarize(&status_latencies),
        "owner_wait_latency": summarize(&owner_latencies),
        "lock_delta": lock_json(owner.snapshot().delta(before)),
    })
}

#[expect(
    clippy::expect_used,
    reason = "failed mutation or tick tasks must invalidate their qualification measurements"
)]
async fn run_concurrent_drain_status_mutation(
    owner: &Arc<MeasuredMutex<Supervisor<QualificationDriver>>>,
    read_view: &Arc<RwLock<Vec<AgentId>>>,
    agents: &[AgentId],
    now: Instant,
) -> serde_json::Value {
    let before = owner.snapshot();
    let mutation_owner = Arc::clone(owner);
    let mutation_agents = agents[..8].to_vec();
    let mutation = tokio::spawn(async move {
        let started = Instant::now();
        let mut guard = mutation_owner.lock().await;
        let mut accepted = 0_u64;
        for agent_id in &mutation_agents {
            if guard.drain(agent_id, now).is_ok() {
                accepted = accepted.saturating_add(1);
            }
        }
        (started.elapsed(), accepted)
    });
    tokio::task::yield_now().await;
    let tick_owner = Arc::clone(owner);
    let tick = tokio::spawn(async move {
        let started = Instant::now();
        let report = tick_owner.lock().await.tick(now);
        (started.elapsed(), report.faults.len())
    });
    let status_latencies = spawn_status_reads(read_view, 64).await;
    let (mutation_elapsed, accepted) = mutation.await.expect("mutation task");
    let (tick_elapsed, faults) = tick.await.expect("tick task");
    json!({
        "mutation_elapsed_us": micros(mutation_elapsed),
        "accepted_drains": accepted,
        "tick_elapsed_us": micros(tick_elapsed),
        "fault_count": faults,
        "status_read_latency": summarize(&status_latencies),
        "lock_delta": lock_json(owner.snapshot().delta(before)),
    })
}

#[expect(
    clippy::expect_used,
    reason = "failed read tasks must invalidate their qualification measurements"
)]
async fn spawn_status_reads(read_view: &Arc<RwLock<Vec<AgentId>>>, count: usize) -> Vec<Duration> {
    let mut tasks = Vec::with_capacity(count);
    for index in 0..count {
        let read_view = Arc::clone(read_view);
        tasks.push(tokio::spawn(async move {
            let started = Instant::now();
            let guard = read_view.read().await;
            assert!(guard.get(index % guard.len()).is_some());
            started.elapsed()
        }));
    }
    let mut latencies = Vec::with_capacity(tasks.len());
    for task in tasks {
        latencies.push(task.await.expect("status task"));
    }
    latencies
}

#[expect(
    clippy::expect_used,
    reason = "failed owner snapshot tasks must invalidate their qualification measurements"
)]
async fn spawn_owner_snapshots(
    owner: &Arc<MeasuredMutex<Supervisor<QualificationDriver>>>,
    agents: &[AgentId],
) -> Vec<Duration> {
    let mut tasks = Vec::with_capacity(agents.len());
    for agent_id in agents {
        let owner = Arc::clone(owner);
        let agent_id = agent_id.clone();
        tasks.push(tokio::spawn(async move {
            let started = Instant::now();
            assert!(owner.lock().await.snapshot(&agent_id).is_some());
            started.elapsed()
        }));
    }
    let mut latencies = Vec::with_capacity(tasks.len());
    for task in tasks {
        latencies.push(task.await.expect("owner snapshot task"));
    }
    latencies
}

fn summarize(samples: &[Duration]) -> serde_json::Value {
    let mut values = samples.iter().copied().map(micros).collect::<Vec<_>>();
    values.sort_unstable();
    json!({
        "count": values.len(),
        "p50_us": percentile(&values, 50),
        "p95_us": percentile(&values, 95),
        "p99_us": percentile(&values, 99),
        "max_us": values.last().copied().unwrap_or(0),
    })
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let index = ((values.len() - 1) * percentile).div_ceil(100);
    values[index.min(values.len() - 1)]
}

fn micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

fn lock_json(
    lock: codex_hepta_supervisor::qualification_mutex::LockTelemetrySnapshot,
) -> serde_json::Value {
    json!({
        "acquisitions": lock.acquisitions,
        "contended_acquisitions": lock.contended_acquisitions,
        "wait_us": lock.wait_us,
        "wait_max_us": lock.wait_max_us,
        "slow_waits": lock.slow_waits,
        "hold_us": lock.hold_us,
        "hold_max_us": lock.hold_max_us,
        "slow_holds": lock.slow_holds,
    })
}
