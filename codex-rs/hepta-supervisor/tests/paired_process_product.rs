#![cfg(unix)]

use std::io::Write;
use std::sync::Mutex;
use std::sync::OnceLock;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use codex_hepta_contracts::AgentId;
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
static PAIR_TRACE_START: OnceLock<Instant> = OnceLock::new();
static PAIR_FIXTURE_SIZE_LOGGED: OnceLock<()> = OnceLock::new();

// Write fixed, infrequent markers through the stderr handle, outside libtest's
// print-macro capture. A timeout can then retain the last entered lifecycle
// boundary. Diagnostic write failure must not replace the test's own outcome.
fn trace_pair_stage(marker: &'static [u8]) {
    let elapsed_ms = PAIR_TRACE_START
        .get_or_init(Instant::now)
        .elapsed()
        .as_millis();
    // The longest fixed label plus a full u128 elapsed value is 103 bytes.
    let mut record = [0_u8; 128];
    let used = {
        let mut output = record.as_mut_slice();
        let _ = output.write_all(marker.strip_suffix(b"\n").unwrap_or(marker));
        let _ = writeln!(output, " elapsed_ms={elapsed_ms}");
        128 - output.len()
    };
    let _ = std::io::stderr().write_all(&record[..used]);
}

fn trace_pair_ready_failure(cause: &'static str, agent_count: usize, fault_count: usize) {
    let elapsed_ms = PAIR_TRACE_START
        .get_or_init(Instant::now)
        .elapsed()
        .as_millis();
    // Fixed causes and full u128/64-bit usize values need at most 149 bytes.
    let mut record = [0_u8; 256];
    let used = {
        let mut output = record.as_mut_slice();
        let _ = writeln!(
            output,
            "paired-ready-error cause={cause} elapsed_ms={elapsed_ms} agents={agent_count} faults={fault_count}"
        );
        256 - output.len()
    };
    let _ = std::io::stderr().write_all(&record[..used]);
}

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
    trace_pair_stage(b"paired-stage two_pairs lock_wait\n");
    let _pair_product_test_guard = PAIR_PRODUCT_TEST_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    trace_pair_stage(b"paired-stage two_pairs lock_acquired\n");
    trace_pair_stage(b"paired-stage two_pairs fixture_create_begin\n");
    let mut fixture = PairFleet::new(2)?;
    trace_pair_stage(b"paired-stage two_pairs fixture_create_complete\n");
    trace_pair_stage(b"paired-stage two_pairs start_all_begin\n");
    fixture.start_all()?;
    trace_pair_stage(b"paired-stage two_pairs start_all_complete\n");
    trace_pair_stage(b"paired-stage two_pairs ready_wait_begin\n");
    fixture.wait_ready(Duration::from_secs(60))?;
    trace_pair_stage(b"paired-stage two_pairs ready_wait_complete\n");
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

    trace_pair_stage(b"paired-stage two_pairs restart_begin\n");
    fixture
        .supervisor
        .as_mut()
        .context("supervisor")?
        .restart(&target, Instant::now())?;
    trace_pair_stage(b"paired-stage two_pairs restart_complete\n");
    trace_pair_stage(b"paired-stage two_pairs replacement_wait_begin\n");
    let target_after = fixture.wait_restarted(
        &target,
        target_before,
        expected_spawn_generation,
        expected_runtime_generation,
        Duration::from_secs(60),
    )?;
    trace_pair_stage(b"paired-stage two_pairs replacement_wait_complete\n");
    assert_ne!(target_after.agent_pid, target_before.agent_pid);
    assert_ne!(target_after.matrix_pid, target_before.matrix_pid);
    assert_eq!(
        target_after.matrix_attached_agent_generation, target_after.spawn_generation,
        "Matrix generation fence must bind to the replacement agentd spawn"
    );
    let peer_after = fixture.pair_runtime_fence(&peer)?;
    assert_eq!(peer_after, peer_before, "peer pair must not restart");
    trace_pair_stage(b"paired-stage two_pairs shutdown_begin\n");
    fixture.shutdown()?;
    trace_pair_stage(b"paired-stage two_pairs shutdown_complete\n");
    trace_pair_stage(b"paired-stage two_pairs body_complete\n");
    Ok(())
}

#[test]
fn five_real_pairs_adopt_all_ten_children_and_isolate_one_matrix_crash() -> Result<()> {
    trace_pair_stage(b"paired-stage five_pairs lock_wait\n");
    let _pair_product_test_guard = PAIR_PRODUCT_TEST_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    trace_pair_stage(b"paired-stage five_pairs lock_acquired\n");
    trace_pair_stage(b"paired-stage five_pairs fixture_create_begin\n");
    let mut fixture = PairFleet::new(5)?;
    trace_pair_stage(b"paired-stage five_pairs fixture_create_complete\n");
    trace_pair_stage(b"paired-stage five_pairs warm_pair_begin\n");
    fixture.warm_first_pair()?;
    trace_pair_stage(b"paired-stage five_pairs warm_pair_complete\n");
    trace_pair_stage(b"paired-stage five_pairs start_all_begin\n");
    fixture.start_all()?;
    trace_pair_stage(b"paired-stage five_pairs start_all_complete\n");
    trace_pair_stage(b"paired-stage five_pairs ready_wait_begin\n");
    fixture.wait_ready(Duration::from_secs(60))?;
    trace_pair_stage(b"paired-stage five_pairs ready_wait_complete\n");
    let before: Vec<_> = fixture
        .agents
        .iter()
        .map(|agent_id| fixture.pids(agent_id))
        .collect::<Result<_>>()?;

    let old = fixture.supervisor.take().context("supervisor")?;
    trace_pair_stage(b"paired-stage five_pairs supervisor_drop_begin\n");
    drop(old);
    trace_pair_stage(b"paired-stage five_pairs supervisor_drop_complete\n");
    trace_pair_stage(b"paired-stage five_pairs recover_begin\n");
    let recovery_result = Supervisor::recover(
        fixture.registry.clone(),
        UnixProcessDriver::new(64).map_err(anyhow::Error::msg)?,
        test_config(),
        Instant::now(),
    );
    trace_pair_stage(b"paired-stage five_pairs recover_returned\n");
    let (recovered, report) = recovery_result?;
    assert!(report.faults.is_empty(), "recovery faults: {report:?}");
    trace_pair_stage(b"paired-stage five_pairs recover_complete\n");
    fixture.supervisor = Some(recovered);
    trace_pair_stage(b"paired-stage five_pairs adopted_ready_wait_begin\n");
    fixture.wait_ready(Duration::from_secs(60))?;
    trace_pair_stage(b"paired-stage five_pairs adopted_ready_wait_complete\n");
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
    trace_pair_stage(b"paired-stage five_pairs matrix_kill_begin\n");
    send_kill(failed_matrix_pid)?;
    trace_pair_stage(b"paired-stage five_pairs matrix_kill_complete\n");
    let failed_agent = fixture.agents[0].clone();
    trace_pair_stage(b"paired-stage five_pairs replacement_wait_begin\n");
    fixture.wait_matrix_replaced(&failed_agent, failed_matrix_pid, Duration::from_secs(60))?;
    trace_pair_stage(b"paired-stage five_pairs replacement_wait_complete\n");
    for (agent_id, expected) in fixture.agents.iter().skip(1).zip(before.iter().skip(1)) {
        assert_eq!(fixture.pids(agent_id)?, *expected, "peer pair changed");
    }
    trace_pair_stage(b"paired-stage five_pairs shutdown_begin\n");
    fixture.shutdown()?;
    trace_pair_stage(b"paired-stage five_pairs shutdown_complete\n");
    trace_pair_stage(b"paired-stage five_pairs body_complete\n");
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
        // The child fixtures bind the same compact control sockets as the
        // product.  Keep the synthetic fleet under a short root so Darwin's
        // SUN_LEN limit is exercised against production geometry, not the
        // SSD harness's intentionally deep temporary directory.
        let temp = tempfile::Builder::new()
            .prefix("hsup-pairs-")
            .tempdir_in("/tmp")?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        trace_pair_stage(b"paired-stage fixture registry_init_begin\n");
        let registry = FleetRegistry::initialize(root.clone())?;
        trace_pair_stage(b"paired-stage fixture registry_init_complete\n");
        let mut agents = Vec::new();
        for (index, value) in IDS.iter().take(count).enumerate() {
            let workspace = temp.path().join(format!("workspace-{index}"));
            std::fs::create_dir(&workspace)?;
            let agent_id = AgentId::parse(*value)?;
            trace_pair_stage(b"paired-stage fixture register_begin\n");
            registry.register(AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
                ResourceBudget::local_default(),
            )?)?;
            trace_pair_stage(b"paired-stage fixture register_complete\n");
            agents.push(agent_id);
        }
        let release_id = ReleaseId::parse("paired-process-fixture-v1")?;
        // Admit the actual child executable, including its complete bytes.
        // Bazel may expose it through a runfiles symlink; preserve admission's
        // existing real-file requirement by resolving that link first.
        let fixture_binary =
            codex_utils_cargo_bin::cargo_bin("hepta-paired-process-fixture")?.canonicalize()?;
        PAIR_FIXTURE_SIZE_LOGGED.get_or_init(|| {
            let libtest_bytes = std::env::current_exe()
                .and_then(std::fs::metadata)
                .map(|metadata| metadata.len())
                .ok();
            let fixture_bytes = std::fs::metadata(&fixture_binary)
                .map(|metadata| metadata.len())
                .ok();
            let mut record = [0_u8; 160];
            let used = {
                let mut output = record.as_mut_slice();
                let _ = writeln!(
                    output,
                    "paired-fixture-size libtest_bytes={libtest_bytes:?} fixture_bytes={fixture_bytes:?}"
                );
                160 - output.len()
            };
            let _ = std::io::stderr().write_all(&record[..used]);
        });
        let child_args = Vec::new();
        trace_pair_stage(b"paired-stage fixture install_release_begin\n");
        registry.install_release_bundle(
            release_id.clone(),
            &fixture_binary,
            child_args.clone(),
            Some(&fixture_binary),
            child_args,
        )?;
        trace_pair_stage(b"paired-stage fixture install_release_complete\n");
        for agent_id in &agents {
            trace_pair_stage(b"paired-stage fixture allow_release_begin\n");
            registry.allow_release(agent_id, &release_id)?;
            trace_pair_stage(b"paired-stage fixture allow_release_complete\n");
            trace_pair_stage(b"paired-stage fixture write_binding_begin\n");
            write_binding(&registry, agent_id)?;
            trace_pair_stage(b"paired-stage fixture write_binding_complete\n");
        }
        trace_pair_stage(b"paired-stage fixture initial_recover_begin\n");
        let initial_recovery_result = Supervisor::recover(
            registry.clone(),
            UnixProcessDriver::new(64).map_err(anyhow::Error::msg)?,
            test_config(),
            Instant::now(),
        );
        trace_pair_stage(b"paired-stage fixture initial_recover_returned\n");
        let (supervisor, report) = initial_recovery_result?;
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
        let agent_id = self.agents[0].clone();
        let release =
            AgentRelease::try_from(self.registry.resolve_release(&agent_id, &self.release_id)?)?;
        trace_pair_stage(b"paired-stage warm_pair start_begin\n");
        self.supervisor
            .as_mut()
            .context("supervisor")?
            .start_release(&agent_id, release, Instant::now())?;
        trace_pair_stage(b"paired-stage warm_pair start_complete\n");
        trace_pair_stage(b"paired-stage warm_pair ready_wait_begin\n");
        self.wait_agents_ready(std::slice::from_ref(&agent_id), Duration::from_secs(60))?;
        trace_pair_stage(b"paired-stage warm_pair ready_wait_complete\n");
        trace_pair_stage(b"paired-stage warm_pair kill_begin\n");
        self.supervisor
            .as_mut()
            .context("supervisor")?
            .kill(&agent_id)?;
        trace_pair_stage(b"paired-stage warm_pair kill_complete\n");
        trace_pair_stage(b"paired-stage warm_pair inactive_wait_begin\n");
        self.wait_agents_inactive(std::slice::from_ref(&agent_id), Duration::from_secs(10))
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
            if !report.faults.is_empty() {
                trace_pair_ready_failure("tick_fault", agents.len(), report.faults.len());
            }
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
                trace_pair_ready_failure("deadline_reached", agents.len(), report.faults.len());
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
