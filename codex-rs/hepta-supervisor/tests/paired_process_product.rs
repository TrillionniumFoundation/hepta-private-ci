#![cfg(unix)]

use std::path::PathBuf;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_agent_protocol::AgentdMethod;
use codex_hepta_agent_protocol::AgentdPayload;
use codex_hepta_agent_protocol::AgentdRequest;
use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_agent_protocol::HealthSnapshot;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentLifecycleState;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AgentRelease;
use codex_hepta_supervisor::AgentSupervisorSnapshot;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use codex_hepta_supervisor::UnixProcessDriver;

#[path = "../src/paired_process_fixture.rs"]
mod pair_fixture;
use pair_fixture::agent_fixture_payload;

const IDS: [&str; 5] = [
    "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
    "019153a4-3088-7e03-a56a-9b1964f75dd3",
    "019153a4-3088-7e03-a56a-9b1964f75dd4",
    "019153a4-3088-7e03-a56a-9b1964f75dd5",
    "019153a4-3088-7e03-a56a-9b1964f75dd6",
];

// Both product tests spawn real agentd+matrixd pairs. Running them in parallel
// can make one test's bounded shutdown compete with the other's ten-child
// adoption workload, which turns a lifecycle assertion into host-load timing.
// Keep the product scenarios isolated while leaving their child processes and
// all supervisor behavior unchanged.
static PAIR_PRODUCT_TEST_LOCK: Mutex<()> = Mutex::new(());

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PairRuntimeFence {
    agent_pid: u64,
    matrix_pid: u64,
    spawn_generation: u64,
    runtime_generation: u64,
    matrix_attached_agent_generation: u64,
}

impl PairRuntimeFence {
    fn from_ready_snapshot(snapshot: &AgentSupervisorSnapshot) -> Option<Self> {
        if !snapshot.active
            || !snapshot.healthy
            || !snapshot.matrix.active
            || !snapshot.matrix.healthy
        {
            return None;
        }
        let fence = Self {
            agent_pid: snapshot.process_system_id?,
            matrix_pid: snapshot.matrix.process_system_id?,
            spawn_generation: snapshot.spawn_generation?,
            runtime_generation: snapshot.runtime_generation?,
            matrix_attached_agent_generation: snapshot.matrix.attached_agent_generation?,
        };
        (fence.matrix_attached_agent_generation == fence.spawn_generation).then_some(fence)
    }
}

#[test]
fn two_real_pairs_restart_one_without_peer_pid_churn() -> Result<()> {
    let _pair_product_test_guard = PAIR_PRODUCT_TEST_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let mut fixture = PairFleet::new(2)?;
    fixture.start_all()?;
    fixture.wait_ready(Duration::from_secs(60))?;
    let target = fixture.agents[0].clone();
    let peer = fixture.agents[1].clone();
    let target_before = fixture.pair_runtime_fence(&target)?;
    let peer_before = fixture.pair_runtime_fence(&peer)?;
    let expected_spawn_generation = target_before
        .runtime_generation
        .checked_add(3)
        .context("expected restart spawn generation")?;
    let expected_runtime_generation = expected_spawn_generation
        .checked_add(1)
        .context("expected restart runtime generation")?;

    fixture
        .supervisor
        .as_mut()
        .context("supervisor")?
        .restart(&target, Instant::now())?;
    let target_after = fixture.wait_restarted(
        &target,
        target_before,
        expected_spawn_generation,
        expected_runtime_generation,
        Duration::from_secs(60),
    )?;
    assert_ne!(target_after.agent_pid, target_before.agent_pid);
    assert_ne!(target_after.matrix_pid, target_before.matrix_pid);
    assert_eq!(
        target_after.matrix_attached_agent_generation, target_after.spawn_generation,
        "Matrix generation fence must bind to the replacement agentd spawn"
    );
    let peer_after = fixture.pair_runtime_fence(&peer)?;
    assert_eq!(peer_after, peer_before, "peer pair must not restart");
    fixture.shutdown()?;
    Ok(())
}

#[test]
fn five_real_pairs_adopt_all_ten_children_and_isolate_one_matrix_crash() -> Result<()> {
    let _pair_product_test_guard = PAIR_PRODUCT_TEST_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let mut fixture = PairFleet::new(5)?;
    let started = Instant::now();
    eprintln!("paired-stage five_pair_fixture_created");
    fixture.warm_first_pair()?;
    eprintln!(
        "paired-stage warm_pair_complete elapsed={:?}",
        started.elapsed()
    );
    fixture.start_all()?;
    fixture.wait_ready(Duration::from_secs(60))?;
    eprintln!(
        "paired-stage ten_children_ready elapsed={:?}",
        started.elapsed()
    );
    let before: Vec<_> = fixture
        .agents
        .iter()
        .map(|agent_id| fixture.pids(agent_id))
        .collect::<Result<_>>()?;

    let old = fixture.supervisor.take().context("supervisor")?;
    drop(old);
    let (recovered, report) = Supervisor::recover(
        fixture.registry.clone(),
        UnixProcessDriver::new(64).map_err(anyhow::Error::msg)?,
        test_config(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty(), "recovery faults: {report:?}");
    eprintln!(
        "paired-stage ten_children_adopted elapsed={:?}",
        started.elapsed()
    );
    fixture.supervisor = Some(recovered);
    fixture.wait_ready(Duration::from_secs(60))?;
    eprintln!(
        "paired-stage adopted_health_ready elapsed={:?}",
        started.elapsed()
    );
    let adopted: Vec<_> = fixture
        .agents
        .iter()
        .map(|agent_id| fixture.pids(agent_id))
        .collect::<Result<_>>()?;
    assert_eq!(
        adopted, before,
        "all five exact process pairs must be adopted"
    );

    let failed_matrix_pid = adopted[0].1;
    send_kill(failed_matrix_pid)?;
    let failed_agent = fixture.agents[0].clone();
    fixture.wait_matrix_replaced(&failed_agent, failed_matrix_pid, Duration::from_secs(60))?;
    eprintln!(
        "paired-stage isolated_matrix_replaced elapsed={:?}",
        started.elapsed()
    );
    for (agent_id, expected) in fixture.agents.iter().skip(1).zip(before.iter().skip(1)) {
        assert_eq!(fixture.pids(agent_id)?, *expected, "peer pair changed");
    }
    fixture.shutdown()?;
    Ok(())
}

struct PairFleet {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agents: Vec<AgentId>,
    release_id: ReleaseId,
    supervisor: Option<Supervisor<UnixProcessDriver>>,
}

impl PairFleet {
    fn new(count: usize) -> Result<Self> {
        let started = Instant::now();
        // The child fixtures bind the same compact control sockets as the
        // product.  Keep the synthetic fleet under a short root so Darwin's
        // SUN_LEN limit is exercised against production geometry, not the
        // SSD harness's intentionally deep temporary directory.
        let temp = tempfile::Builder::new()
            .prefix("hsup-pairs-")
            .tempdir_in("/tmp")?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let mut agents = Vec::new();
        for (index, value) in IDS.iter().take(count).enumerate() {
            let workspace = temp.path().join(format!("workspace-{index}"));
            std::fs::create_dir(&workspace)?;
            let agent_id = AgentId::parse(*value)?;
            registry.register(AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
                ResourceBudget::local_default(),
            )?)?;
            agents.push(agent_id);
        }
        let release_id = ReleaseId::parse("paired-process-fixture-v1")?;
        let fixture_binary =
            codex_utils_cargo_bin::cargo_bin("hepta-supervisor-pair-test-fixture")?;
        let child_args = Vec::new();
        eprintln!(
            "paired-stage before_full_release_install elapsed={:?}",
            started.elapsed()
        );
        registry.install_release_bundle(
            release_id.clone(),
            &fixture_binary,
            child_args.clone(),
            Some(&fixture_binary),
            child_args,
        )?;
        eprintln!(
            "paired-stage after_full_release_install elapsed={:?}",
            started.elapsed()
        );
        for agent_id in &agents {
            eprintln!(
                "paired-stage before_full_release_allow agent={agent_id} elapsed={:?}",
                started.elapsed()
            );
            registry.allow_release(agent_id, &release_id)?;
            eprintln!(
                "paired-stage after_full_release_allow agent={agent_id} elapsed={:?}",
                started.elapsed()
            );
            write_binding(&registry, agent_id)?;
        }
        let (supervisor, report) = Supervisor::recover(
            registry.clone(),
            UnixProcessDriver::new(64).map_err(anyhow::Error::msg)?,
            test_config(),
            Instant::now(),
        )?;
        assert!(report.faults.is_empty());
        Ok(Self {
            _temp: temp,
            registry,
            agents,
            release_id,
            supervisor: Some(supervisor),
        })
    }

    fn start_all(&mut self) -> Result<()> {
        for agent_id in &self.agents {
            let release =
                AgentRelease::try_from(self.registry.resolve_release(agent_id, &self.release_id)?)?;
            self.supervisor
                .as_mut()
                .context("supervisor")?
                .start_release(agent_id, release, Instant::now())?;
        }
        Ok(())
    }

    fn warm_first_pair(&mut self) -> Result<()> {
        let started = Instant::now();
        let agent_id = self.agents[0].clone();
        eprintln!(
            "paired-stage before_warm_full_release_resolve elapsed={:?}",
            started.elapsed()
        );
        let release =
            AgentRelease::try_from(self.registry.resolve_release(&agent_id, &self.release_id)?)?;
        eprintln!(
            "paired-stage after_warm_full_release_resolve elapsed={:?}",
            started.elapsed()
        );
        self.supervisor
            .as_mut()
            .context("supervisor")?
            .start_release(&agent_id, release, Instant::now())?;
        eprintln!(
            "paired-stage warm_first_started elapsed={:?}",
            started.elapsed()
        );
        self.wait_agents_ready(std::slice::from_ref(&agent_id), Duration::from_secs(60))?;
        eprintln!(
            "paired-stage warm_first_ready elapsed={:?}",
            started.elapsed()
        );
        self.supervisor
            .as_mut()
            .context("supervisor")?
            .kill(&agent_id)?;
        eprintln!(
            "paired-stage warm_first_killed elapsed={:?}",
            started.elapsed()
        );
        self.wait_agents_inactive(std::slice::from_ref(&agent_id), Duration::from_secs(10))?;
        eprintln!(
            "paired-stage warm_first_inactive elapsed={:?}",
            started.elapsed()
        );
        Ok(())
    }

    fn wait_ready(&mut self, timeout: Duration) -> Result<()> {
        let agents = self.agents.clone();
        self.wait_agents_ready(&agents, timeout)
    }

    fn wait_agents_ready(&mut self, agents: &[AgentId], timeout: Duration) -> Result<()> {
        let deadline = Instant::now() + timeout;
        loop {
            let supervisor = self.supervisor.as_mut().context("supervisor")?;
            let report = supervisor.tick(Instant::now());
            anyhow::ensure!(report.faults.is_empty(), "tick faults: {:?}", report.faults);
            if agents.iter().all(|agent_id| {
                supervisor.snapshot(agent_id).is_some_and(|snapshot| {
                    snapshot.active
                        && snapshot.healthy
                        && snapshot.matrix.active
                        && snapshot.matrix.healthy
                })
            }) {
                return Ok(());
            }
            if Instant::now() >= deadline {
                let snapshots: Vec<_> = agents
                    .iter()
                    .map(|agent_id| (agent_id.clone(), supervisor.snapshot(agent_id)))
                    .collect();
                anyhow::bail!("pair fleet did not become ready: {snapshots:?}");
            }
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    fn wait_agents_inactive(&mut self, agents: &[AgentId], timeout: Duration) -> Result<()> {
        let deadline = Instant::now() + timeout;
        loop {
            let supervisor = self.supervisor.as_mut().context("supervisor")?;
            let report = supervisor.tick(Instant::now());
            anyhow::ensure!(report.faults.is_empty(), "tick faults: {:?}", report.faults);
            if agents.iter().all(|agent_id| {
                supervisor
                    .snapshot(agent_id)
                    .is_some_and(|snapshot| !snapshot.active && !snapshot.matrix.active)
            }) {
                return Ok(());
            }
            anyhow::ensure!(Instant::now() < deadline, "pair fleet did not stop");
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    fn wait_matrix_replaced(
        &mut self,
        agent_id: &AgentId,
        old_pid: u64,
        timeout: Duration,
    ) -> Result<()> {
        let deadline = Instant::now() + timeout;
        loop {
            let supervisor = self.supervisor.as_mut().context("supervisor")?;
            let report = supervisor.tick(Instant::now());
            anyhow::ensure!(report.faults.is_empty(), "tick faults: {:?}", report.faults);
            if supervisor.snapshot(agent_id).is_some_and(|snapshot| {
                snapshot.healthy
                    && snapshot.matrix.healthy
                    && snapshot
                        .matrix
                        .process_system_id
                        .is_some_and(|pid| pid != old_pid)
            }) {
                return Ok(());
            }
            anyhow::ensure!(
                Instant::now() < deadline,
                "Matrix companion was not replaced"
            );
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    fn wait_restarted(
        &mut self,
        agent_id: &AgentId,
        previous: PairRuntimeFence,
        expected_spawn_generation: u64,
        expected_runtime_generation: u64,
        timeout: Duration,
    ) -> Result<PairRuntimeFence> {
        let deadline = Instant::now() + timeout;
        loop {
            let supervisor = self.supervisor.as_mut().context("supervisor")?;
            let report = supervisor.tick(Instant::now());
            anyhow::ensure!(report.faults.is_empty(), "tick faults: {:?}", report.faults);
            if let Some(restarted) = supervisor
                .snapshot(agent_id)
                .as_ref()
                .and_then(PairRuntimeFence::from_ready_snapshot)
                .filter(|fence| {
                    fence.agent_pid != previous.agent_pid
                        && fence.matrix_pid != previous.matrix_pid
                        && fence.spawn_generation == expected_spawn_generation
                        && fence.runtime_generation == expected_runtime_generation
                })
            {
                return Ok(restarted);
            }
            if Instant::now() >= deadline {
                anyhow::bail!(
                    "pair did not complete the expected restart fence: {:?}",
                    supervisor.snapshot(agent_id)
                );
            }
            std::thread::sleep(Duration::from_millis(20));
        }
    }

    fn pair_runtime_fence(&self, agent_id: &AgentId) -> Result<PairRuntimeFence> {
        let snapshot = self
            .supervisor
            .as_ref()
            .context("supervisor")?
            .snapshot(agent_id)
            .context("agent snapshot")?;
        PairRuntimeFence::from_ready_snapshot(&snapshot)
            .context("pair is not ready or its Matrix generation fence is stale")
    }

    fn pids(&self, agent_id: &AgentId) -> Result<(u64, u64)> {
        let snapshot = self
            .supervisor
            .as_ref()
            .context("supervisor")?
            .snapshot(agent_id)
            .context("agent snapshot")?;
        Ok((
            snapshot.process_system_id.context("agentd pid")?,
            snapshot.matrix.process_system_id.context("matrixd pid")?,
        ))
    }

    fn shutdown(&mut self) -> Result<()> {
        let supervisor = self.supervisor.as_mut().context("supervisor")?;
        for agent_id in &self.agents {
            supervisor.kill(agent_id)?;
        }
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            let active = self.agents.iter().any(|agent_id| {
                supervisor
                    .snapshot(agent_id)
                    .is_some_and(|snapshot| snapshot.active || snapshot.matrix.active)
            });
            if !active {
                return Ok(());
            }
            let report = supervisor.tick(Instant::now());
            anyhow::ensure!(
                report.faults.is_empty(),
                "shutdown tick faults: {:?}",
                report.faults
            );
            if Instant::now() >= deadline {
                let snapshots: Vec<_> = self
                    .agents
                    .iter()
                    .map(|agent_id| (agent_id.clone(), supervisor.snapshot(agent_id)))
                    .collect();
                anyhow::bail!("fixture children did not exit: {snapshots:?}");
            }
            std::thread::sleep(Duration::from_millis(10));
        }
    }
}

fn test_config() -> SupervisorConfig {
    SupervisorConfig {
        health_timeout: Duration::from_secs(60),
        drain_timeout: Duration::from_secs(2),
        stop_grace: Duration::from_secs(1),
        event_capacity: 128,
        log_capacity: 128,
        max_log_bytes: 4_096,
        driver_poll_batch: 64,
        restart_max_attempts: 3,
        restart_window: Duration::from_secs(60),
        restart_backoff_base: Duration::from_millis(10),
    }
}

fn write_binding(registry: &FleetRegistry, agent_id: &AgentId) -> Result<()> {
    let record = registry
        .load()?
        .agent(agent_id)
        .cloned()
        .context("agent record")?;
    let binding = serde_json::json!({
        "schema_version": 1,
        "agent_id": agent_id,
        "revision": 1,
        "homeserver": "https://matrix.example.test",
        "expected_mxid": format!("@{}:example.test", &agent_id.as_str()[..8]),
        "expected_device_id": "HEPTA1",
        "allowed_rooms": ["!room:example.test"],
        "allowed_senders": ["@operator:example.test"],
        "require_explicit_mention": true
    });
    std::fs::write(
        record.layout.matrix_public_binding(),
        serde_json::to_vec(&binding)?,
    )?;
    Ok(())
}

fn send_kill(pid: u64) -> Result<()> {
    let pid = i32::try_from(pid).context("pid fits pid_t")?;
    // SAFETY: test-owned PID was read from the exact adopted Matrix process snapshot.
    let result = unsafe { libc::kill(pid, libc::SIGKILL) };
    if result == -1 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(())
}

#[test]
#[ignore = "spawned only as a controlled process fixture"]
fn paired_child_process() {
    let result = pair_fixture::run();
    if let Err(error) = result {
        panic!("paired child failed: {error:#}");
    }
}

#[test]
fn paired_empty_child_drain_refuses_foreign_frames_and_work_before_acknowledging() -> Result<()> {
    let agent_id = AgentId::parse(IDS[0])?;
    let lifecycle = AgentLifecycleState {
        schema_version: 1,
        agent_id: agent_id.clone(),
        generation: 9,
        lifecycle: AgentLifecycle::Draining,
    };
    let health = HealthSnapshot {
        promotion_ready: true,
        ready: false,
        fenced: false,
        lifecycle: AgentLifecycle::Draining,
        process_id: std::process::id(),
        workspace: PathBuf::from("/tmp/fixture-workspace"),
        home_root: PathBuf::from("/tmp/fixture-home"),
        run_root: PathBuf::from("/tmp/fixture-run"),
    };
    for case in 0..7 {
        let mut request = AgentdRequest::drain(1, 7);
        let mut state = lifecycle.clone();
        match case {
            0 => request.schema_version += 1,
            1 => request.request_id = 0,
            2 => request.spawn_generation += 1,
            3 => state.agent_id = AgentId::parse(IDS[1])?,
            4 => state.generation -= 1,
            5 => state.lifecycle = AgentLifecycle::Running,
            6 => request.method = AgentdMethod::SessionIngress,
            _ => unreachable!(),
        }
        let mut closed = false;
        assert!(
            agent_fixture_payload(&request, &agent_id, 7, &state, health.clone(), &mut closed)
                .is_err()
        );
        assert!(!closed, "a refused control frame cannot change admission");
    }
    let mut closed = false;
    let payload = agent_fixture_payload(
        &AgentdRequest::drain(1, 7),
        &agent_id,
        7,
        &lifecycle,
        health,
        &mut closed,
    )?;
    assert!(closed);
    assert!(matches!(
        payload,
        AgentdPayload::Drain(DrainSnapshot {
            admission_closed: true,
            running_turns: 0,
            drained: true,
            lifecycle: AgentLifecycle::Draining,
            fenced: false
        })
    ));
    Ok(())
}
