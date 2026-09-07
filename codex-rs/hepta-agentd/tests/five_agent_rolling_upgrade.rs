#![cfg(unix)]

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_app_server_protocol::ClientRequest;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadStartParams;
use codex_app_server_protocol::ThreadStartResponse;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskState;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_supervisor::AgentRelease;
use codex_hepta_supervisor::SupervisorEventKind;
use codex_uds::UnixStream;
use core_test_support::responses;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

mod support;

use support::fleet::AgentFixture;
use support::fleet::FleetHarness;
use support::fleet::agentd_binary;
use support::fleet::connect_app_server;

const AGENT_IDS: [&str; 5] = [
    "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
    "019153a4-3088-7e03-a56a-9b1964f75dd3",
    "019153a4-3088-7e03-a56a-9b1964f75dd4",
    "019153a4-3088-7e03-a56a-9b1964f75dd5",
    "019153a4-3088-7e03-a56a-9b1964f75dd6",
];
const SIX_AGENT_IDS: [&str; 6] = [
    "019153a4-3088-7e03-a56a-9b1964f75dd7",
    "019153a4-3088-7e03-a56a-9b1964f75dd8",
    "019153a4-3088-7e03-a56a-9b1964f75dd9",
    "019153a4-3088-7e03-a56a-9b1964f75dda",
    "019153a4-3088-7e03-a56a-9b1964f75ddb",
    "019153a4-3088-7e03-a56a-9b1964f75ddc",
];
const RELEASE_WAIT: Duration = Duration::from_secs(90);

#[tokio::test(flavor = "multi_thread", worker_threads = 8)]
async fn five_real_agentd_processes_roll_one_agent_without_stopping_peers() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let mut agents = Vec::new();
    for (index, agent_id) in AGENT_IDS.iter().enumerate() {
        agents.push(fleet.register(agent_id, &format!("workspace-{index}"))?);
    }
    assert_distinct_agent_roots(&agents)?;

    let model = responses::start_mock_server().await;
    for agent in &agents {
        MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    }

    let release_root = agents[0]
        .workspace
        .parent()
        .context("workspace has no fixture root")?
        .join("immutable-releases");
    std::fs::create_dir(&release_root)?;
    let agentd_binary = agentd_binary()?;
    let v1 = actual_agentd_wrapper(&release_root, "agentd-v1", &agentd_binary)?;
    let v2 = actual_agentd_wrapper(&release_root, "agentd-v2", &agentd_binary)?;
    let failing = failing_wrapper(&release_root, "agentd-failing")?;
    std::fs::set_permissions(&release_root, std::fs::Permissions::from_mode(0o555))?;
    let _release_root_guard = ImmutableReleaseRoot(release_root.clone());

    for (index, agent) in agents.iter().enumerate() {
        fleet.start_release(
            agent,
            release(
                &format!("initial-{index}"),
                if index == 0 { &v1 } else { &agentd_binary },
            )?,
        )?;
        let (control, health) = fleet.wait_ready(agent, 1).await?;
        ensure!(health.ready, "agent {index} did not become ready");
        ensure!(control.session_ingress().await?.socket_path == agent.layout.app_server_socket());
        ensure!(
            agent
                .layout
                .cognitive_root()
                .join("cognitive_1.sqlite3")
                .is_file(),
            "agent {index} cognitive store was not materialized"
        );
        ensure!(
            agent
                .layout
                .automation_root()
                .join("automation_1.sqlite3")
                .is_file(),
            "agent {index} automation store was not materialized"
        );
    }

    let peer_ids: Vec<_> = agents[1..]
        .iter()
        .map(|agent| agent.agent_id.clone())
        .collect();
    let peer_baseline = peer_snapshots(&fleet, &peer_ids)?;
    let a_initial_pid = process_id(&fleet, &agents[0].agent_id)?;

    signal_process(a_initial_pid, "STOP")?;
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;

    let thread_ids = create_peer_threads(&fleet, &agents[1..]).await?;
    let response_mock = responses::mount_sse_sequence(
        &model,
        (0..4)
            .map(|index| final_sse(&format!("peer-automation-{index}")))
            .collect(),
    )
    .await;
    let now_ms = unix_time_ms()?;
    let mut peer_tasks = Vec::new();
    for ((agent, thread_id), index) in agents[1..].iter().zip(thread_ids.iter()).zip(1_u64..) {
        let control = fleet.control_client(agent, 1)?;
        let task = control
            .automation_create(AutomationTaskDraft::new(
                thread_id,
                format!("peer {index} automation continues while Agent A is stopped"),
                AutomationSchedule::Once,
                now_ms,
                now_ms,
            ))
            .await?;
        peer_tasks.push((control, task.task_id));
    }
    wait_peer_automation_completed(&peer_tasks).await?;
    timeout(Duration::from_secs(20), async {
        while response_mock.requests().len() != 4 {
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .context("peer automation turns were queued but not dispatched")?;
    ensure!(
        response_mock.requests().len() == 4,
        "all four peer automation turns must enter their owning App Servers"
    );
    signal_process(a_initial_pid, "CONT")?;
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;

    fleet.supervisor.kill(&agents[0].agent_id)?;
    wait_inactive(&mut fleet, &agents[0].agent_id).await?;
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;

    fleet
        .supervisor
        .restart(&agents[0].agent_id, Instant::now())?;
    let (_, restarted_health) = wait_release(&mut fleet, &agents[0], "initial-0").await?;
    ensure!(
        restarted_health.process_id != a_initial_pid,
        "Agent A restart reused its old process"
    );
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;

    fleet.supervisor.upgrade(
        &agents[0].agent_id,
        release("agent-a-v2", &v2)?,
        Instant::now(),
    )?;
    let (_, v2_health) = wait_release(&mut fleet, &agents[0], "agent-a-v2").await?;
    ensure!(
        v2_health.process_id != restarted_health.process_id,
        "successful upgrade did not replace Agent A"
    );
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;

    fleet.supervisor.upgrade(
        &agents[0].agent_id,
        release("agent-a-failing", &failing)?,
        Instant::now(),
    )?;
    let (_, auto_rollback_health) = wait_release(&mut fleet, &agents[0], "agent-a-v2").await?;
    ensure!(
        auto_rollback_health.process_id != v2_health.process_id,
        "failed target did not start a fresh rollback process"
    );
    let after_failed = fleet
        .supervisor
        .snapshot(&agents[0].agent_id)
        .context("Agent A snapshot missing after failed upgrade")?;
    ensure!(
        after_failed.events.iter().any(|event| matches!(
            &event.kind,
            SupervisorEventKind::AutomaticRollbackCommitted { failed, restored }
                if failed == "agent-a-failing" && restored == "agent-a-v2"
        )),
        "failed release did not produce a single committed automatic rollback"
    );
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;

    fleet
        .supervisor
        .rollback(&agents[0].agent_id, Instant::now())?;
    let (_, explicit_rollback_health) = wait_release(&mut fleet, &agents[0], "initial-0").await?;
    ensure!(
        explicit_rollback_health.process_id != auto_rollback_health.process_id,
        "explicit rollback did not replace Agent A"
    );
    let final_a = fleet
        .supervisor
        .snapshot(&agents[0].agent_id)
        .context("final Agent A snapshot missing")?;
    ensure!(final_a.previous_release.as_deref() == Some("agent-a-v2"));
    ensure!(!final_a.release_change_pending);
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;
    for (control, task_id) in &peer_tasks {
        let tasks = control.automation_list(32).await?;
        ensure!(
            tasks.iter().any(|task| {
                task.task_id == *task_id && task.state == AutomationTaskState::Completed
            }),
            "peer automation state was lost across Agent A release changes"
        );
    }
    Ok(())
}

/// Qualification-only expansion beyond the five-agent minimum gate.
///
/// This exercises a six-agent roster through registration/start, target stop
/// and restart, target upgrade and explicit rollback. While each target is
/// being changed, the other five agents keep their process identities,
/// generations, readiness, and real automation turns. The slice is bounded;
/// it does not grant fleet-wide release or promotion authority.
#[tokio::test(flavor = "multi_thread", worker_threads = 8)]
async fn six_agent_fleet_lifecycle_keeps_peers_fair_and_isolated() -> Result<()> {
    let mut fleet = FleetHarness::new()?;
    let mut agents = Vec::new();
    for (index, agent_id) in SIX_AGENT_IDS.iter().enumerate() {
        agents.push(fleet.register(agent_id, &format!("six-workspace-{index}"))?);
    }
    assert_distinct_agent_roots_count(&agents, SIX_AGENT_IDS.len())?;

    let model = responses::start_mock_server().await;
    for agent in &agents {
        MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
    }

    let release_root = agents[0]
        .workspace
        .parent()
        .context("workspace has no fixture root")?
        .join("six-immutable-releases");
    std::fs::create_dir(&release_root)?;
    let agentd_binary = agentd_binary()?;
    let v1 = actual_agentd_wrapper(&release_root, "agentd-six-v1", &agentd_binary)?;
    let v2 = actual_agentd_wrapper(&release_root, "agentd-six-v2", &agentd_binary)?;
    std::fs::set_permissions(&release_root, std::fs::Permissions::from_mode(0o555))?;
    let _release_root_guard = ImmutableReleaseRoot(release_root);

    for (index, agent) in agents.iter().enumerate() {
        fleet.start_release(
            agent,
            release(
                &format!("six-initial-{index}"),
                if index == 0 || index == 5 {
                    &v1
                } else {
                    &agentd_binary
                },
            )?,
        )?;
        let (control, health) = fleet
            .wait_ready(agent, 1)
            .await
            .with_context(|| format!("six-agent {index} readiness/control handshake"))?;
        ensure!(health.ready, "six-agent {index} did not become ready");
        let ingress = control
            .session_ingress()
            .await
            .with_context(|| format!("six-agent {index} session ingress"))?;
        ensure!(
            ingress.socket_path == agent.layout.app_server_socket(),
            "six-agent {index} ingress drifted"
        );
    }

    // Stop only Agent 0, then prove the other five continue real turns.
    let peer_ids: Vec<_> = agents[1..]
        .iter()
        .map(|agent| agent.agent_id.clone())
        .collect();
    let peer_baseline = peer_snapshots(&fleet, &peer_ids)?;
    let target_zero_pid = process_id(&fleet, &agents[0].agent_id)?;
    fleet.supervisor.stop(&agents[0].agent_id, Instant::now())?;
    wait_inactive(&mut fleet, &agents[0].agent_id).await?;
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;

    let thread_ids = create_peer_threads(&fleet, &agents[1..])
        .await
        .context("six-agent peer thread creation")?;
    let response_mock = responses::mount_sse_sequence(
        &model,
        (0..5)
            .map(|index| final_sse(&format!("six-peer-automation-{index}")))
            .collect(),
    )
    .await;
    let now_ms = unix_time_ms()?;
    let mut peer_tasks = Vec::new();
    for ((agent, thread_id), index) in agents[1..].iter().zip(thread_ids.iter()).zip(1_u64..) {
        let control = fleet.control_client(agent, 1)?;
        let task = control
            .automation_create(AutomationTaskDraft::new(
                thread_id,
                format!("six-agent peer {index} turn while Agent 0 is stopped"),
                AutomationSchedule::Once,
                now_ms,
                now_ms,
            ))
            .await
            .with_context(|| format!("six-agent peer {index} automation create"))?;
        peer_tasks.push((control, task.task_id));
    }
    wait_peer_automation_completed(&peer_tasks).await?;
    timeout(Duration::from_secs(20), async {
        while response_mock.requests().len() != 5 {
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .context("six-agent peer automation did not reach all peer App Servers")?;
    ensure!(
        response_mock.requests().len() == 5,
        "all five peers must receive a turn while Agent 0 is stopped"
    );

    fleet
        .supervisor
        .restart(&agents[0].agent_id, Instant::now())?;
    let (_, restarted_zero) = wait_release(&mut fleet, &agents[0], "six-initial-0")
        .await
        .context("six-agent Agent 0 restart readiness")?;
    ensure!(
        restarted_zero.process_id != target_zero_pid,
        "Agent 0 restart reused its stopped process"
    );
    assert_peers_healthy_and_unchanged(&fleet, &agents[1..], &peer_baseline).await?;

    // Upgrade and explicitly roll back Agent 5 while every other agent stays live.
    let target_peers = &agents[..5];
    let target_peer_ids: Vec<_> = target_peers
        .iter()
        .map(|agent| agent.agent_id.clone())
        .collect();
    let target_peer_baseline = peer_snapshots(&fleet, &target_peer_ids)?;
    fleet.supervisor.upgrade(
        &agents[5].agent_id,
        release("six-agent-5-v2", &v2)?,
        Instant::now(),
    )?;
    let (_, upgraded) = wait_release(&mut fleet, &agents[5], "six-agent-5-v2")
        .await
        .context("six-agent Agent 5 upgrade readiness")?;
    fleet
        .supervisor
        .rollback(&agents[5].agent_id, Instant::now())?;
    let (_, rolled_back) = wait_release(&mut fleet, &agents[5], "six-initial-5")
        .await
        .context("six-agent Agent 5 rollback readiness")?;
    ensure!(
        rolled_back.process_id != upgraded.process_id,
        "Agent 5 explicit rollback did not replace the upgraded process"
    );
    let final_target = fleet
        .supervisor
        .snapshot(&agents[5].agent_id)
        .context("Agent 5 snapshot missing after explicit rollback")?;
    ensure!(!final_target.release_change_pending);
    assert_peers_healthy_and_unchanged(&fleet, target_peers, &target_peer_baseline).await?;

    for agent in &agents {
        let snapshot = fleet
            .supervisor
            .snapshot(&agent.agent_id)
            .context("six-agent snapshot missing at lifecycle boundary")?;
        ensure!(
            snapshot.active,
            "{} is not active at final boundary",
            agent.agent_id
        );
        ensure!(
            snapshot.healthy,
            "{} is not healthy at final boundary",
            agent.agent_id
        );
    }
    Ok(())
}

fn assert_distinct_agent_roots(agents: &[AgentFixture]) -> Result<()> {
    let homes = agents
        .iter()
        .map(|agent| agent.layout.home_root().to_path_buf())
        .collect::<BTreeSet<_>>();
    let workspaces = agents
        .iter()
        .map(|agent| agent.workspace.clone())
        .collect::<BTreeSet<_>>();
    let controls = agents
        .iter()
        .map(|agent| agent.layout.agentd_control_socket().to_path_buf())
        .collect::<BTreeSet<_>>();
    let cognitive = agents
        .iter()
        .map(|agent| agent.layout.cognitive_root().to_path_buf())
        .collect::<BTreeSet<_>>();
    let automation = agents
        .iter()
        .map(|agent| agent.layout.automation_root().to_path_buf())
        .collect::<BTreeSet<_>>();
    ensure!(
        [
            homes.len(),
            workspaces.len(),
            controls.len(),
            cognitive.len(),
            automation.len()
        ] == [5; 5],
        "five Agent identities do not own five independent path sets"
    );
    Ok(())
}

fn assert_distinct_agent_roots_count(agents: &[AgentFixture], expected: usize) -> Result<()> {
    let homes = agents
        .iter()
        .map(|agent| agent.layout.home_root().to_path_buf())
        .collect::<BTreeSet<_>>();
    let workspaces = agents
        .iter()
        .map(|agent| agent.workspace.clone())
        .collect::<BTreeSet<_>>();
    let controls = agents
        .iter()
        .map(|agent| agent.layout.agentd_control_socket().to_path_buf())
        .collect::<BTreeSet<_>>();
    let cognitive = agents
        .iter()
        .map(|agent| agent.layout.cognitive_root().to_path_buf())
        .collect::<BTreeSet<_>>();
    let automation = agents
        .iter()
        .map(|agent| agent.layout.automation_root().to_path_buf())
        .collect::<BTreeSet<_>>();
    ensure!(
        [
            homes.len(),
            workspaces.len(),
            controls.len(),
            cognitive.len(),
            automation.len()
        ] == [expected; 5],
        "fleet identities do not own {expected} independent path sets"
    );
    Ok(())
}

fn release(identity: &str, program: &Path) -> Result<AgentRelease> {
    Ok(AgentRelease::new(
        identity,
        AgentCommand::new(program, Vec::new())?,
    )?)
}

fn actual_agentd_wrapper(root: &Path, name: &str, agentd: &Path) -> Result<PathBuf> {
    ensure!(
        !agentd.to_string_lossy().contains('\''),
        "fixture binary path cannot contain a shell quote"
    );
    let wrapper = root.join(name);
    std::fs::write(
        &wrapper,
        format!("#!/bin/sh\nexec '{}' \"$@\"\n", agentd.display()),
    )?;
    std::fs::set_permissions(&wrapper, std::fs::Permissions::from_mode(0o555))?;
    Ok(wrapper)
}

struct ImmutableReleaseRoot(PathBuf);

impl Drop for ImmutableReleaseRoot {
    fn drop(&mut self) {
        let _ = std::fs::set_permissions(&self.0, std::fs::Permissions::from_mode(0o755));
    }
}

fn failing_wrapper(root: &Path, name: &str) -> Result<PathBuf> {
    let wrapper = root.join(name);
    std::fs::write(&wrapper, "#!/bin/sh\nexit 42\n")?;
    std::fs::set_permissions(&wrapper, std::fs::Permissions::from_mode(0o555))?;
    Ok(wrapper)
}

fn signal_process(process_id: u32, signal: &str) -> Result<()> {
    let outcome = Command::new("/bin/kill")
        .arg(format!("-{signal}"))
        .arg(process_id.to_string())
        .status()?;
    ensure!(
        outcome.success(),
        "failed to send SIG{signal} to {process_id}"
    );
    Ok(())
}

fn process_id(fleet: &FleetHarness, agent_id: &AgentId) -> Result<u32> {
    let system_id = fleet
        .supervisor
        .snapshot(agent_id)
        .and_then(|snapshot| snapshot.process_system_id)
        .context("active process identity missing")?;
    u32::try_from(system_id).context("process identity does not fit pid_t")
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct PeerSnapshot {
    agent_id: AgentId,
    process_system_id: Option<u64>,
    spawn_generation: Option<u64>,
    runtime_generation: Option<u64>,
}

fn peer_snapshots(fleet: &FleetHarness, agent_ids: &[AgentId]) -> Result<Vec<PeerSnapshot>> {
    agent_ids
        .iter()
        .map(|agent_id| {
            let snapshot = fleet
                .supervisor
                .snapshot(agent_id)
                .context("peer supervisor snapshot missing")?;
            Ok(PeerSnapshot {
                agent_id: agent_id.clone(),
                process_system_id: snapshot.process_system_id,
                spawn_generation: snapshot.spawn_generation,
                runtime_generation: snapshot.runtime_generation,
            })
        })
        .collect()
}

async fn assert_peers_healthy_and_unchanged(
    fleet: &FleetHarness,
    peers: &[AgentFixture],
    baseline: &[PeerSnapshot],
) -> Result<()> {
    ensure!(
        peer_snapshots(
            fleet,
            &baseline
                .iter()
                .map(|item| item.agent_id.clone())
                .collect::<Vec<_>>()
        )? == baseline
    );
    for peer in peers {
        let supervisor_snapshot = fleet.supervisor.snapshot(&peer.agent_id);
        let expected_generation = supervisor_snapshot
            .as_ref()
            .and_then(|snapshot| snapshot.spawn_generation)
            .context("peer supervisor snapshot has no spawn generation")?;
        let control = fleet.control_client(peer, expected_generation)?;
        let health = match control.health().await {
            Ok(health) => health,
            Err(error) => {
                let raw = raw_health_response(peer, expected_generation)
                    .await
                    .unwrap_or_else(|raw_error| format!("<raw health failed: {raw_error}>"));
                bail!(
                    "peer {} health failed (expected_generation={expected_generation}, error={error}); supervisor={supervisor_snapshot:?}; raw={raw}",
                    peer.agent_id
                );
            }
        };
        ensure!(health.ready, "peer {} is not ready", peer.agent_id);
        let ingress = control.session_ingress().await.with_context(|| {
            format!(
                "peer {} session ingress failed (expected_generation={expected_generation}, supervisor={supervisor_snapshot:?}, health={health:?})",
                peer.agent_id
            )
        })?;
        ensure!(
            ingress.socket_path == peer.layout.app_server_socket(),
            "peer {} session ingress drifted",
            peer.agent_id
        );
    }
    Ok(())
}

async fn raw_health_response(agent: &AgentFixture, generation: u64) -> Result<String> {
    let stream = UnixStream::connect(agent.layout.agentd_control_socket()).await?;
    let (reader, mut writer) = tokio::io::split(stream);
    let mut request = serde_json::to_vec(&AgentdRequest::health(9001, generation))?;
    request.push(b'\n');
    writer.write_all(&request).await?;
    writer.shutdown().await?;
    let mut reader = BufReader::new(reader);
    let mut response = String::new();
    reader.read_line(&mut response).await?;
    Ok(response)
}

async fn create_peer_threads(fleet: &FleetHarness, peers: &[AgentFixture]) -> Result<Vec<String>> {
    let mut thread_ids = Vec::new();
    for peer in peers {
        let control = fleet.control_client(peer, 1)?;
        let ingress = control.session_ingress().await?;
        let client = connect_app_server(&ingress.socket_path, "hepta-five-agent-e2e", 64).await?;
        let response: ThreadStartResponse = client
            .request_typed(ClientRequest::ThreadStart {
                request_id: RequestId::Integer(1),
                params: ThreadStartParams {
                    cwd: Some(peer.workspace.to_string_lossy().into_owned()),
                    ephemeral: Some(false),
                    ..ThreadStartParams::default()
                },
            })
            .await?;
        thread_ids.push(response.thread.id);
        client.shutdown().await?;
    }
    Ok(thread_ids)
}

async fn wait_peer_automation_completed(
    tasks: &[(AgentdClient, codex_hepta_automation::AutomationTaskId)],
) -> Result<()> {
    timeout(Duration::from_secs(20), async {
        loop {
            let mut complete = true;
            for (control, task_id) in tasks {
                let tasks = control.automation_list(32).await?;
                complete &= tasks.iter().any(|task| {
                    task.task_id == *task_id && task.state == AutomationTaskState::Completed
                });
            }
            if complete {
                return Ok::<(), anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(50)).await;
        }
    })
    .await
    .context("peer automation did not complete while Agent A was blocked")??;
    Ok(())
}

async fn wait_inactive(fleet: &mut FleetHarness, agent_id: &AgentId) -> Result<()> {
    timeout(RELEASE_WAIT, async {
        loop {
            let report = fleet.supervisor.tick(Instant::now());
            ensure!(
                report.faults.is_empty(),
                "Supervisor fault while stopping {agent_id}: {:?}",
                report.faults
            );
            let inactive = fleet
                .supervisor
                .snapshot(agent_id)
                .is_some_and(|snapshot| !snapshot.active);
            let stopped = fleet
                .registry
                .load()?
                .agent(agent_id)
                .is_some_and(|record| record.lifecycle.lifecycle == AgentLifecycle::Stopped);
            if inactive && stopped {
                return Ok::<(), anyhow::Error>(());
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .context("Agent did not stop within its bounded deadline")??;
    Ok(())
}

async fn wait_release(
    fleet: &mut FleetHarness,
    agent: &AgentFixture,
    release_identity: &str,
) -> Result<(AgentdClient, codex_hepta_agentd::HealthSnapshot)> {
    timeout(RELEASE_WAIT, async {
        loop {
            let report = fleet.supervisor.tick(Instant::now());
            ensure!(
                report.faults.is_empty(),
                "Supervisor fault while waiting for {} release {release_identity}: {:?}",
                agent.agent_id,
                report.faults
            );
            if let Some(snapshot) = fleet.supervisor.snapshot(&agent.agent_id)
                && snapshot.active_release.as_deref() == Some(release_identity)
                && !snapshot.release_change_pending
                && let Some(spawn_generation) = snapshot.spawn_generation
            {
                let control = fleet.control_client(agent, spawn_generation)?;
                if let Ok(health) = control.health().await
                    && health.ready
                {
                    return Ok::<_, anyhow::Error>((control, health));
                }
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .with_context(|| {
        format!(
            "Agent {} did not reach release {release_identity}",
            agent.agent_id
        )
    })?
}

fn unix_time_ms() -> Result<u64> {
    Ok(u64::try_from(
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis(),
    )?)
}

fn final_sse(response_id: &str) -> String {
    responses::sse(vec![
        responses::ev_response_created(response_id),
        responses::ev_assistant_message(&format!("message-{response_id}"), "done"),
        responses::ev_completed(response_id),
    ])
}
