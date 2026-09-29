#![cfg(unix)]

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
use codex_hepta_supervisor::MeasuredMutex;
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
use codex_hepta_supervisor::TickReport;
use serde_json::json;

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
            world: self.world.clone(),
        }
    }

    fn set_poll_delay(&self, delay: Duration) {
        self.world.lock().expect("qualification world").poll_delay = delay;
    }

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

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let mut world = self.world.lock().expect("qualification world");
        world.next_id = world.next_id.saturating_add(1);
        let id = world.next_id;
        let identity = ProcessIdentity::new(
            id,
            format!("qualification-{id}-{}", spec.generation),
        )
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
                world: self.world.clone(),
            },
        })
    }

    fn adopt(
        &mut self,
        spec: &AdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
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
            world: self.world.clone(),
        }))
    }
}

impl ManagedProcess for QualificationProcess {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let delay = self.world.lock().expect("qualification world").poll_delay;
        if !delay.is_zero() {
            std::thread::sleep(delay);
        }
        let world = self.world.lock().expect("qualification world");
        let state = world.processes.get(&self.id).expect("qualification process");
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
async fn qualifies_256_instances_fault_waves_and_global_lock_hol() -> Result<(), SupervisorError> {
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
    let start = Instant::now();
    let (mut supervisor, recovered) =
        Supervisor::recover(registry, control.driver(), config, start)?;
    assert_eq!(recovered, TickReport::default());

    let program: PathBuf = std::env::temp_dir()
        .join("hepta-supervisor-tests")
        .join("qualification-agentd");
    for agent_id in &agents {
        supervisor.start(
            agent_id,
            AgentCommand::new(program.clone(), Vec::new())?,
            start,
        )?;
    }
    assert_eq!(supervisor.tick(start), TickReport::default());

    let supervisor = Arc::new(MeasuredMutex::with_thresholds(
        "runtime.supervisor.qualification",
        supervisor,
        Duration::from_millis(1),
        Duration::from_millis(5),
    ));

    let healthy = run_tick_with_readers(&supervisor, &agents, start).await;

    control.set_poll_delay(Duration::from_micros(100));
    let slow_driver = run_tick_with_readers(
        &supervisor,
        &agents,
        start + Duration::from_secs(1),
    )
    .await;
    control.set_poll_delay(Duration::ZERO);

    let slow_fs_started = Instant::now();
    let slow_fs_lock = supervisor.clone();
    let slow_fs_dir = temp.path().join("slow-fs");
    let slow_fs = tokio::spawn(async move {
        std::fs::create_dir_all(&slow_fs_dir).expect("slow fs directory");
        let _guard = slow_fs_lock.lock().await;
        let path = slow_fs_dir.join("probe");
        let file = std::fs::File::create(path).expect("slow fs probe");
        file.sync_all().expect("sync slow fs probe");
        std::thread::sleep(Duration::from_millis(20));
    });
    tokio::time::sleep(Duration::from_millis(1)).await;
    let slow_fs_waiters = spawn_readers(&supervisor, &agents[..64]).await;
    slow_fs.await.expect("slow fs holder");
    let slow_fs_elapsed = slow_fs_started.elapsed();

    let concurrent_drain = run_concurrent_drain_status_mutation(
        &supervisor,
        &agents,
        start + Duration::from_secs(2),
    )
    .await?;

    let mut fault_wave_metrics = Vec::new();
    for (label, count) in [
        ("10_percent", INSTANCE_COUNT / 10),
        ("50_percent", INSTANCE_COUNT / 2),
        ("100_percent", INSTANCE_COUNT),
    ] {
        control.crash_prefix(&agents, count);
        let sample = run_tick_with_readers(
            &supervisor,
            &agents,
            start + Duration::from_secs(3 + fault_wave_metrics.len() as u64),
        )
        .await;
        fault_wave_metrics.push((label, sample));
    }

    let telemetry = supervisor.telemetry();
    let report = json!({
        "instances": INSTANCE_COUNT,
        "healthy": healthy,
        "slow_driver": slow_driver,
        "slow_filesystem": {
            "holder_elapsed_ns": duration_ns(slow_fs_elapsed),
            "reader_latency": summarize(&slow_fs_waiters),
        },
        "concurrent_drain_status_mutation": concurrent_drain,
        "fault_waves": fault_wave_metrics
            .into_iter()
            .map(|(label, metrics)| json!({"wave": label, "metrics": metrics}))
            .collect::<Vec<_>>(),
        "lock": telemetry,
    });
    println!(
        "runtime_supervisor_256_instance_qualification={}",
        serde_json::to_string(&report)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
    );

    assert!(telemetry.acquisitions > 0);
    assert!(telemetry.contended_acquisitions > 0);
    assert!(telemetry.max_hold_ns >= 5_000_000);
    assert!(telemetry.max_wait_ns >= 1_000_000);
    assert!(telemetry.slow_holds > 0);
    assert!(telemetry.slow_waits > 0);
    Ok(())
}

fn register_agents(
    registry: &FleetRegistry,
    root: &HeptaFleetRoot,
    temp: &std::path::Path,
) -> Result<Vec<AgentId>, SupervisorError> {
    let mut agents = Vec::with_capacity(INSTANCE_COUNT);
    for index in 0..INSTANCE_COUNT {
        let agent_id = AgentId::parse(format!(
            "018f4f72-{index:04x}-7cc1-8f55-{index:012x}"
        ))
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

async fn run_concurrent_drain_status_mutation(
    supervisor: &Arc<MeasuredMutex<Supervisor<QualificationDriver>>>,
    agents: &[AgentId],
    now: Instant,
) -> Result<serde_json::Value, SupervisorError> {
    let before = supervisor.telemetry();
    let mutation_supervisor = supervisor.clone();
    let mutation_agents = agents[..8].to_vec();
    let mutation = tokio::spawn(async move {
        let started = Instant::now();
        let mut guard = mutation_supervisor.lock().await;
        for agent_id in &mutation_agents {
            guard.drain(agent_id, now)?;
        }
        Ok::<Duration, SupervisorError>(started.elapsed())
    });
    tokio::task::yield_now().await;

    let tick_supervisor = supervisor.clone();
    let tick = tokio::spawn(async move {
        let started = Instant::now();
        let report = tick_supervisor.lock().await.tick(now);
        (started.elapsed(), report.faults.len())
    });
    let reader_latencies = spawn_readers(supervisor, &agents[..64]).await;
    let mutation_elapsed = mutation.await.expect("drain mutation task")?;
    let (tick_elapsed, fault_count) = tick.await.expect("concurrent tick task");
    Ok(json!({
        "drain_mutation_elapsed_ns": duration_ns(mutation_elapsed),
        "tick_elapsed_ns": duration_ns(tick_elapsed),
        "fault_count": fault_count,
        "reader_latency": summarize(&reader_latencies),
        "lock_delta": supervisor.telemetry().delta(before),
    }))
}

async fn run_tick_with_readers(
    supervisor: &Arc<MeasuredMutex<Supervisor<QualificationDriver>>>,
    agents: &[AgentId],
    now: Instant,
) -> serde_json::Value {
    let before = supervisor.telemetry();
    let tick_supervisor = supervisor.clone();
    let tick_started = Instant::now();
    let tick = tokio::spawn(async move {
        let report = tick_supervisor.lock().await.tick(now);
        (tick_started.elapsed(), report.faults.len())
    });
    tokio::task::yield_now().await;
    let reader_latencies = spawn_readers(supervisor, &agents[..64]).await;
    let (tick_elapsed, fault_count) = tick.await.expect("tick task");
    let delta = supervisor.telemetry().delta(before);
    json!({
        "tick_elapsed_ns": duration_ns(tick_elapsed),
        "fault_count": fault_count,
        "reader_latency": summarize(&reader_latencies),
        "lock_delta": delta,
    })
}

async fn spawn_readers(
    supervisor: &Arc<MeasuredMutex<Supervisor<QualificationDriver>>>,
    agents: &[AgentId],
) -> Vec<Duration> {
    let mut tasks = Vec::with_capacity(agents.len());
    for agent_id in agents {
        let supervisor = supervisor.clone();
        let agent_id = agent_id.clone();
        tasks.push(tokio::spawn(async move {
            let started = Instant::now();
            let snapshot = supervisor.lock().await.snapshot(&agent_id);
            assert!(snapshot.is_some());
            started.elapsed()
        }));
    }
    let mut latencies = Vec::with_capacity(tasks.len());
    for task in tasks {
        latencies.push(task.await.expect("reader task"));
    }
    latencies
}

fn summarize(samples: &[Duration]) -> serde_json::Value {
    let mut values = samples.iter().copied().map(duration_ns).collect::<Vec<_>>();
    values.sort_unstable();
    json!({
        "count": values.len(),
        "p50_ns": percentile(&values, 50),
        "p95_ns": percentile(&values, 95),
        "p99_ns": percentile(&values, 99),
        "max_ns": values.last().copied().unwrap_or(0),
    })
}

fn percentile(values: &[u64], percentile: usize) -> u64 {
    if values.is_empty() {
        return 0;
    }
    let index = ((values.len() - 1) * percentile).div_ceil(100);
    values[index.min(values.len() - 1)]
}

fn duration_ns(duration: Duration) -> u64 {
    u64::try_from(duration.as_nanos()).unwrap_or(u64::MAX)
}
