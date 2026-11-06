#![cfg(unix)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Write;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use app_test_support::MockResponsesConfig;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::FleetReleaseTrustConfig;
use codex_hepta_fleet::PqReleaseQualification;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::SupervisordAgentStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::SupervisordControlFence;
use codex_hepta_supervisor::SupervisordMutation;
use codex_hepta_supervisor::SupervisordMutationAccepted;
use core_test_support::responses;

#[path = "support/recovery.rs"]
mod recovery;

const CHILD_MODE_ENV: &str = "HEPTA_TEST_SUPERVISORD_CHILD";
const CHILD_FLEET_ROOT_ENV: &str = "HEPTA_TEST_SUPERVISORD_FLEET_ROOT";
const CHILD_RELEASE_TRUST_ENV: &str = "HEPTA_TEST_SUPERVISORD_RELEASE_TRUST";
const READY_TIMEOUT: Duration = Duration::from_secs(120);
const DAEMON_TIMEOUT: Duration = Duration::from_secs(15);
const AGENT_IDS: [&str; 5] = [
    "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
    "019153a4-3088-7e03-a56a-9b1964f75dd3",
    "019153a4-3088-7e03-a56a-9b1964f75dd4",
    "019153a4-3088-7e03-a56a-9b1964f75dd5",
    "019153a4-3088-7e03-a56a-9b1964f75dd6",
];

/// The parent test spawns this integration-test executable as an isolated
/// process so the exact product daemon implementation can itself own and
/// survive independently from the test coordinator.
#[test]
fn supervisord_child_entry() -> Result<()> {
    if std::env::var_os(CHILD_MODE_ENV).is_none() {
        return Ok(());
    }
    let fleet_root = std::env::var_os(CHILD_FLEET_ROOT_ENV)
        .map(PathBuf::from)
        .context("child fleet root is missing")?;
    let runtime = tokio::runtime::Builder::new_multi_thread()
        .worker_threads(2)
        .enable_all()
        .build()?;
    runtime.block_on(codex_hepta_supervisor::run_supervisord(
        HeptaFleetRoot::parse(fleet_root)?,
        FleetReleaseTrustConfig::read(&PathBuf::from(
            std::env::var_os(CHILD_RELEASE_TRUST_ENV)
                .context("child release trust configuration is missing")?,
        ))?,
        tokio_util::sync::CancellationToken::new(),
    ))?;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 8)]
async fn five_real_agents_survive_daemon_restart_and_isolate_one_agent_release_changes()
-> Result<()> {
    let observed_start = Instant::now();
    let _ = writeln!(std::io::stderr(), "FIVE_AGENT_PROGRESS setup elapsed_ms=0");
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet"))?;
    let (mut publisher, registry) =
        PqReleaseQualification::initialize(&root.join("publication"), fleet_root.clone())
            .map_err(anyhow::Error::from_boxed)?;
    let agents = register_agents(&registry, &fleet_root, &root)?;
    assert_distinct_roots(&agents)?;

    let model = responses::start_mock_server().await;
    for agent in &agents {
        MockResponsesConfig::new(&model.uri()).write(agent.layout.home_root())?;
        recovery::stage_initial(&root, agent.layout.home_root(), &agent.agent_id)?;
    }

    let sources = root.join("release-sources");
    std::fs::create_dir(&sources)?;
    let agentd = codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?;
    let source_v1 = agentd_wrapper(&sources, "agentd-v1", &agentd)?;
    let source_v2 = agentd_wrapper(&sources, "agentd-v2", &agentd)?;
    let release_v1 = ReleaseId::parse("agentd-v1")?;
    let release_v2 = ReleaseId::parse("agentd-v2")?;
    publisher
        .install_release(&registry, release_v1.clone(), &source_v1, Vec::new())
        .map_err(anyhow::Error::from_boxed)?;
    publisher
        .install_release(&registry, release_v2.clone(), &source_v2, Vec::new())
        .map_err(anyhow::Error::from_boxed)?;
    for agent in &agents {
        registry.allow_release(&agent.agent_id, &release_v1)?;
    }
    registry.allow_release(&agents[0].agent_id, &release_v2)?;

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS publication_ready elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let log_path = root.join("supervisord-child.log");
    let mut process_guard = AgentProcessGuard::default();
    let mut daemon = DaemonChild::spawn(&fleet_root, &log_path, publisher.config_path())?;
    let client = wait_for_daemon(&registry, &mut daemon, &log_path).await?;
    let first_supervisor_epoch = client.health().await?.supervisor_epoch;
    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS daemon_ready elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );

    for agent in &agents[..2] {
        let _ = writeln!(
            std::io::stderr(),
            "FIVE_AGENT_PROGRESS initial_start agent={} elapsed_ms={}",
            agent.agent_id,
            observed_start.elapsed().as_millis()
        );
        let before = client.snapshot(agent.agent_id.clone()).await?;
        let accepted = client
            .start(before.control_fence.clone(), release_v1.clone())
            .await?;
        assert_mutation_accepted(SupervisordMutation::Start, &before.control_fence, &accepted)?;
        wait_for_release(&client, agent, &release_v1, None, &mut process_guard).await?;
    }
    let dual = client.roster(16).await?;
    ensure!(
        dual.iter().filter(|status| status.healthy).count() == 2,
        "the initial two independent agents did not become healthy: {dual:?}"
    );

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS negative_release_admission elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let peer_b_before_rejected_upgrade = client.snapshot(agents[1].agent_id.clone()).await?;
    ensure!(
        client
            .upgrade(
                peer_b_before_rejected_upgrade.control_fence.clone(),
                release_v2.clone(),
            )
            .await
            .is_err(),
        "Agent B used a release allowed only for Agent A"
    );
    assert_exact_status(
        &peer_b_before_rejected_upgrade,
        &client.snapshot(agents[1].agent_id.clone()).await?,
        "Agent B changed after a rejected release",
    )?;
    ensure!(
        client
            .upgrade(
                peer_b_before_rejected_upgrade.control_fence.clone(),
                ReleaseId::parse("missing-release")?,
            )
            .await
            .is_err(),
        "an uninstalled release entered the mutation path"
    );
    assert_exact_status(
        &peer_b_before_rejected_upgrade,
        &client.snapshot(agents[1].agent_id.clone()).await?,
        "Agent B changed after an uninstalled release rejection",
    )?;

    for agent in &agents[2..] {
        let _ = writeln!(
            std::io::stderr(),
            "FIVE_AGENT_PROGRESS remaining_start agent={} elapsed_ms={}",
            agent.agent_id,
            observed_start.elapsed().as_millis()
        );
        let before = client.snapshot(agent.agent_id.clone()).await?;
        let accepted = client
            .start(before.control_fence.clone(), release_v1.clone())
            .await?;
        assert_mutation_accepted(SupervisordMutation::Start, &before.control_fence, &accepted)?;
        wait_for_release(&client, agent, &release_v1, None, &mut process_guard).await?;
    }
    let five = client.roster(16).await?;
    ensure!(
        five.len() == 5 && five.iter().all(|status| status.healthy),
        "the five-Agent fleet did not become independently healthy: {five:?}"
    );
    for status in &five {
        assert_status_fence_coherent(status)?;
        assert_exact_status(
            status,
            &client.snapshot(status.agent_id.clone()).await?,
            "roster and point snapshot observed different authority state",
        )?;
    }

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS drain_restart elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let before_drain = client.snapshot(agents[4].agent_id.clone()).await?;
    let accepted = client.drain(before_drain.control_fence.clone()).await?;
    assert_mutation_accepted(
        SupervisordMutation::Drain,
        &before_drain.control_fence,
        &accepted,
    )?;
    wait_for_stopped(&client, &agents[4], &mut process_guard).await?;
    let stopped = client.snapshot(agents[4].agent_id.clone()).await?;
    let accepted = client.restart(stopped.control_fence.clone()).await?;
    assert_mutation_accepted(
        SupervisordMutation::Restart,
        &stopped.control_fence,
        &accepted,
    )?;
    wait_for_release(&client, &agents[4], &release_v1, None, &mut process_guard).await?;

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS stop_restart elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let before_stop = client.snapshot(agents[3].agent_id.clone()).await?;
    let accepted = client.stop(before_stop.control_fence.clone()).await?;
    assert_mutation_accepted(
        SupervisordMutation::Stop,
        &before_stop.control_fence,
        &accepted,
    )?;
    wait_for_stopped(&client, &agents[3], &mut process_guard).await?;
    let stopped = client.snapshot(agents[3].agent_id.clone()).await?;
    let accepted = client.restart(stopped.control_fence.clone()).await?;
    assert_mutation_accepted(
        SupervisordMutation::Restart,
        &stopped.control_fence,
        &accepted,
    )?;
    wait_for_release(&client, &agents[3], &release_v1, None, &mut process_guard).await?;

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS kill_restart elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let mut peer_status_baseline = peer_baseline(&client, &agents[1..]).await?;
    let initial_a = client.snapshot(agents[0].agent_id.clone()).await?;
    let initial_a_pid = require_pid(&initial_a)?;

    let accepted = client.kill(initial_a.control_fence.clone()).await?;
    assert_mutation_accepted(
        SupervisordMutation::Kill,
        &initial_a.control_fence,
        &accepted,
    )?;
    wait_for_stopped(&client, &agents[0], &mut process_guard).await?;
    assert_peers_unchanged(&client, &agents[1..], &peer_status_baseline).await?;

    let stopped_a = client.snapshot(agents[0].agent_id.clone()).await?;
    ensure!(
        client.drain(stopped_a.control_fence.clone()).await.is_err(),
        "a stopped Agent entered an invalid drain transition"
    );
    assert_exact_status(
        &stopped_a,
        &client.snapshot(agents[0].agent_id.clone()).await?,
        "invalid drain changed Agent A control state",
    )?;
    let accepted = client.restart(stopped_a.control_fence.clone()).await?;
    assert_mutation_accepted(
        SupervisordMutation::Restart,
        &stopped_a.control_fence,
        &accepted,
    )?;
    let mut restarted_a =
        wait_for_release(&client, &agents[0], &release_v1, None, &mut process_guard).await?;
    ensure!(
        require_pid(&restarted_a)? != initial_a_pid,
        "Agent A restart reused its killed process"
    );
    assert_peers_unchanged(&client, &agents[1..], &peer_status_baseline).await?;

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS concurrent_restart elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let concurrent_fence = restarted_a.control_fence.clone();
    let (left, right) = tokio::join!(
        client.restart(concurrent_fence.clone()),
        client.restart(concurrent_fence.clone())
    );
    ensure!(
        usize::from(left.is_ok()) + usize::from(right.is_ok()) == 1,
        "two clients using one fence did not produce exactly one winner: left={left:?} right={right:?}"
    );
    let (concurrent_accepted, concurrent_rejected) = match (left, right) {
        (Ok(accepted), Err(rejected)) | (Err(rejected), Ok(accepted)) => (accepted, rejected),
        _ => bail!("same-fence winner cardinality changed after validation"),
    };
    ensure!(
        concurrent_rejected
            .to_string()
            .contains("(stale_control_fence)"),
        "the losing same-fence client did not receive stale_control_fence: {concurrent_rejected}"
    );
    assert_mutation_accepted(
        SupervisordMutation::Restart,
        &concurrent_fence,
        &concurrent_accepted,
    )?;
    restarted_a =
        wait_for_release(&client, &agents[0], &release_v1, None, &mut process_guard).await?;
    assert_peers_unchanged(&client, &agents[1..], &peer_status_baseline).await?;

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS upgrade elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let accepted = client
        .upgrade(restarted_a.control_fence.clone(), release_v2.clone())
        .await?;
    assert_mutation_accepted(
        SupervisordMutation::Upgrade,
        &restarted_a.control_fence,
        &accepted,
    )?;
    let upgraded_a = wait_for_release(
        &client,
        &agents[0],
        &release_v2,
        Some(&release_v1),
        &mut process_guard,
    )
    .await?;
    ensure!(
        require_pid(&upgraded_a)? != require_pid(&restarted_a)?,
        "Agent A upgrade did not replace its process"
    );
    assert_peers_unchanged(&client, &agents[1..], &peer_status_baseline).await?;

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS daemon_restart elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let before_daemon_restart = snapshot_all(&client, &agents).await?;
    assert_agentd_endpoints(&agents, &before_daemon_restart).await?;
    daemon.kill()?;
    assert_agentd_endpoints(&agents, &before_daemon_restart).await?;

    let mut restarted_daemon = DaemonChild::spawn(&fleet_root, &log_path, publisher.config_path())?;
    let restarted_client = wait_for_daemon(&registry, &mut restarted_daemon, &log_path).await?;
    let restarted_supervisor_epoch = restarted_client.health().await?.supervisor_epoch;
    ensure!(
        restarted_supervisor_epoch != first_supervisor_epoch,
        "supervisord reused its daemon epoch after process restart"
    );
    for (agent, before) in agents.iter().zip(&before_daemon_restart) {
        let expected_release = before
            .current_release
            .as_ref()
            .context("healthy agent has no current release")?;
        let adopted = wait_for_release(
            &restarted_client,
            agent,
            expected_release,
            before.previous_release.as_ref(),
            &mut process_guard,
        )
        .await?;
        assert_runtime_status(before, &adopted, "daemon restart replaced an agent")?;
        ensure!(
            adopted.control_fence.supervisor_epoch == restarted_supervisor_epoch,
            "adopted Agent did not receive the restarted daemon epoch"
        );
    }
    assert_agentd_endpoints(&agents, &before_daemon_restart).await?;
    peer_status_baseline = peer_baseline(&restarted_client, &agents[1..]).await?;

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS rollback elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    let before_rollback = restarted_client
        .snapshot(agents[0].agent_id.clone())
        .await?;
    let accepted = restarted_client
        .rollback(before_rollback.control_fence.clone())
        .await?;
    assert_mutation_accepted(
        SupervisordMutation::Rollback,
        &before_rollback.control_fence,
        &accepted,
    )?;
    let rolled_back_a = wait_for_release(
        &restarted_client,
        &agents[0],
        &release_v1,
        Some(&release_v2),
        &mut process_guard,
    )
    .await?;
    ensure!(
        require_pid(&rolled_back_a)? != require_pid(&upgraded_a)?,
        "Agent A rollback did not replace its process"
    );
    assert_peers_unchanged(&restarted_client, &agents[1..], &peer_status_baseline).await?;

    let _ = writeln!(
        std::io::stderr(),
        "FIVE_AGENT_PROGRESS final_stop elapsed_ms={}",
        observed_start.elapsed().as_millis()
    );
    for agent in &agents {
        let before = restarted_client.snapshot(agent.agent_id.clone()).await?;
        let accepted = restarted_client.kill(before.control_fence.clone()).await?;
        assert_mutation_accepted(SupervisordMutation::Kill, &before.control_fence, &accepted)?;
    }
    for agent in &agents {
        wait_for_stopped(&restarted_client, agent, &mut process_guard).await?;
    }
    restarted_daemon.kill()?;
    Ok(())
}

#[derive(Clone)]
struct AgentFixture {
    agent_id: AgentId,
    layout: HeptaAgentLayout,
}

fn register_agents(
    registry: &FleetRegistry,
    fleet_root: &HeptaFleetRoot,
    root: &Path,
) -> Result<Vec<AgentFixture>> {
    AGENT_IDS
        .iter()
        .enumerate()
        .map(|(index, raw_agent_id)| {
            let workspace = root.join(format!("workspace-{index}"));
            std::fs::create_dir(&workspace)?;
            let workspace = workspace.canonicalize()?;
            let agent_id = AgentId::parse(*raw_agent_id).map_err(anyhow::Error::msg)?;
            let record = registry.register(AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(workspace, fleet_root)?,
                ResourceBudget::local_default(),
            )?)?;
            Ok(AgentFixture {
                agent_id,
                layout: record.layout,
            })
        })
        .collect()
}

fn assert_distinct_roots(agents: &[AgentFixture]) -> Result<()> {
    let homes = agents
        .iter()
        .map(|agent| agent.layout.home_root().to_path_buf())
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
            controls.len(),
            cognitive.len(),
            automation.len()
        ] == [5; 4],
        "five Agent identities do not own independent path sets"
    );
    Ok(())
}

fn agentd_wrapper(root: &Path, name: &str, agentd: &Path) -> Result<PathBuf> {
    let recovery_root = root
        .parent()
        .context("fixture release parent missing")?
        .join("recovery");
    ensure!(
        !agentd.to_string_lossy().contains('\'') && !recovery_root.to_string_lossy().contains('\''),
        "fixture binary/recovery path cannot contain a shell quote"
    );
    let wrapper = root.join(name);
    std::fs::write(
        &wrapper,
        format!(
            "#!/bin/sh\n# immutable test release: {name}\nexec '{}' --evidence-recovery-frontier-file '{}/'\"$HEPTA_AGENT_ID\"'/frontier.json' --evidence-recovery-frontier-trust-file '{}/'\"$HEPTA_AGENT_ID\"'/trust.json' \"$@\"\n",
            agentd.display(),
            recovery_root.display(),
            recovery_root.display()
        ),
    )?;
    std::fs::set_permissions(&wrapper, std::fs::Permissions::from_mode(0o555))?;
    Ok(wrapper)
}

async fn wait_for_daemon(
    registry: &FleetRegistry,
    daemon: &mut DaemonChild,
    log_path: &Path,
) -> Result<SupervisordClient> {
    let deadline = Instant::now() + DAEMON_TIMEOUT;
    let client = SupervisordClient::new(registry.layout().supervisor_socket().to_path_buf())?;
    loop {
        if client.health().await.is_ok() {
            return Ok(client);
        }
        if let Some(status) = daemon.try_wait()? {
            let log = std::fs::read_to_string(log_path).unwrap_or_default();
            bail!("supervisord exited during startup with {status}; log={log}");
        }
        if Instant::now() >= deadline {
            let log = std::fs::read_to_string(log_path).unwrap_or_default();
            bail!("supervisord did not become ready; log={log}");
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

async fn wait_for_release(
    client: &SupervisordClient,
    agent: &AgentFixture,
    current: &ReleaseId,
    previous: Option<&ReleaseId>,
    process_guard: &mut AgentProcessGuard,
) -> Result<SupervisordAgentStatus> {
    let deadline = Instant::now() + READY_TIMEOUT;
    let mut last = None;
    loop {
        if let Ok(status) = client.snapshot(agent.agent_id.clone()).await {
            process_guard.observe(&status)?;
            if status.lifecycle == AgentLifecycle::Running
                && status.active
                && status.healthy
                && status.current_release.as_ref() == Some(current)
                && status.previous_release.as_ref() == previous
                && !status.release_change_pending
            {
                let agentd = AgentdClient::new(
                    agent.layout.agentd_control_socket().to_path_buf(),
                    agent.agent_id.clone(),
                    status
                        .spawn_generation
                        .context("healthy agent has no spawn generation")?,
                )?;
                let health = agentd.health().await?;
                ensure!(
                    health.ready && u64::from(health.process_id) == require_pid(&status)?,
                    "supervisord status did not match the real agentd endpoint"
                );
                return Ok(status);
            }
            last = Some(status);
        }
        if Instant::now() >= deadline {
            bail!(
                "timed out waiting for agent {} release {current}; last={last:?}",
                agent.agent_id
            );
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

async fn wait_for_stopped(
    client: &SupervisordClient,
    agent: &AgentFixture,
    process_guard: &mut AgentProcessGuard,
) -> Result<()> {
    let deadline = Instant::now() + READY_TIMEOUT;
    let mut last = None;
    loop {
        if let Ok(status) = client.snapshot(agent.agent_id.clone()).await {
            process_guard.observe(&status)?;
            if status.lifecycle == AgentLifecycle::Stopped
                && !status.active
                && status.process_id.is_none()
            {
                return Ok(());
            }
            last = Some(status);
        }
        if Instant::now() >= deadline {
            bail!(
                "timed out waiting for agent {} to stop; last={last:?}",
                agent.agent_id
            );
        }
        tokio::time::sleep(Duration::from_millis(25)).await;
    }
}

async fn peer_baseline(
    client: &SupervisordClient,
    peers: &[AgentFixture],
) -> Result<Vec<SupervisordAgentStatus>> {
    let mut baseline = Vec::new();
    for peer in peers {
        let status = client.snapshot(peer.agent_id.clone()).await?;
        ensure!(status.healthy, "peer {} is not healthy", peer.agent_id);
        baseline.push(status);
    }
    Ok(baseline)
}

async fn assert_peers_unchanged(
    client: &SupervisordClient,
    peers: &[AgentFixture],
    baseline: &[SupervisordAgentStatus],
) -> Result<()> {
    ensure!(
        peers.len() == baseline.len(),
        "peer baseline length drifted"
    );
    for (peer, expected) in peers.iter().zip(baseline) {
        let actual = client.snapshot(peer.agent_id.clone()).await?;
        assert_exact_status(expected, &actual, "an isolated peer changed")?;
        assert_agentd_endpoint(peer, expected).await?;
    }
    Ok(())
}

async fn snapshot_all(
    client: &SupervisordClient,
    agents: &[AgentFixture],
) -> Result<Vec<SupervisordAgentStatus>> {
    let mut statuses = Vec::new();
    for agent in agents {
        statuses.push(client.snapshot(agent.agent_id.clone()).await?);
    }
    Ok(statuses)
}

async fn assert_agentd_endpoints(
    agents: &[AgentFixture],
    statuses: &[SupervisordAgentStatus],
) -> Result<()> {
    ensure!(
        agents.len() == statuses.len(),
        "agent status length drifted"
    );
    for (agent, status) in agents.iter().zip(statuses) {
        assert_agentd_endpoint(agent, status).await?;
    }
    Ok(())
}

async fn assert_agentd_endpoint(
    agent: &AgentFixture,
    status: &SupervisordAgentStatus,
) -> Result<()> {
    let client = AgentdClient::new(
        agent.layout.agentd_control_socket().to_path_buf(),
        agent.agent_id.clone(),
        status
            .spawn_generation
            .context("running agent has no spawn generation")?,
    )?;
    let health = client.health().await?;
    ensure!(
        health.ready,
        "agent {} endpoint is not ready",
        agent.agent_id
    );
    ensure!(
        u64::from(health.process_id) == require_pid(status)?,
        "agent {} endpoint PID changed",
        agent.agent_id
    );
    Ok(())
}

fn assert_exact_status(
    expected: &SupervisordAgentStatus,
    actual: &SupervisordAgentStatus,
    message: &str,
) -> Result<()> {
    ensure!(
        actual == expected,
        "{message}: expected={expected:?} actual={actual:?}"
    );
    Ok(())
}

fn assert_runtime_status(
    expected: &SupervisordAgentStatus,
    actual: &SupervisordAgentStatus,
    message: &str,
) -> Result<()> {
    let mut actual = actual.clone();
    actual.control_fence = expected.control_fence.clone();
    assert_exact_status(expected, &actual, message)
}

fn assert_mutation_accepted(
    operation: SupervisordMutation,
    request_fence: &SupervisordControlFence,
    accepted: &SupervisordMutationAccepted,
) -> Result<()> {
    ensure!(
        accepted.operation == operation,
        "mutation response operation changed: expected={operation:?} actual={:?}",
        accepted.operation
    );
    ensure!(
        accepted.accepted_state_digest == request_fence.state_digest,
        "mutation response did not bind the accepted pre-state digest"
    );
    ensure!(
        accepted.agent.control_fence.state_digest != request_fence.state_digest,
        "accepted mutation did not issue a distinct post-state fence"
    );
    Ok(())
}

fn assert_status_fence_coherent(status: &SupervisordAgentStatus) -> Result<()> {
    let fence = &status.control_fence;
    ensure!(
        fence.agent_id == status.agent_id
            && fence.lifecycle == status.lifecycle
            && fence.lifecycle_generation == status.lifecycle_generation
            && fence.spawn_generation == status.spawn_generation
            && fence.runtime_generation == status.runtime_generation
            && fence.current_release == status.current_release
            && fence.previous_release == status.previous_release
            && fence.release_change_pending == status.release_change_pending,
        "status and its authority fence were assembled from different snapshots: {status:?}"
    );
    Ok(())
}

fn require_pid(status: &SupervisordAgentStatus) -> Result<u64> {
    status
        .process_id
        .context("active agent has no process identity")
}

struct DaemonChild(Child, Option<File>);

impl DaemonChild {
    fn spawn(fleet_root: &HeptaFleetRoot, log_path: &Path, release_trust: &Path) -> Result<Self> {
        let log = OpenOptions::new()
            .create(true)
            .append(true)
            .open(log_path)?;
        // Hold an independent read cursor for the same inode the child writes.
        // A diagnostic-open failure must not change the original spawn result.
        let diagnostic_log = rustix::fs::open(
            log_path,
            rustix::fs::OFlags::RDONLY
                | rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::NONBLOCK
                | rustix::fs::OFlags::CLOEXEC,
            rustix::fs::Mode::empty(),
        )
        .ok()
        .map(File::from)
        .filter(|reader| match (log.metadata(), reader.metadata()) {
            (Ok(writer), Ok(reader)) => {
                writer.is_file()
                    && reader.is_file()
                    && writer.dev() == reader.dev()
                    && writer.ino() == reader.ino()
            }
            _ => false,
        });
        let child = Command::new(std::env::current_exe()?)
            .arg("--exact")
            .arg("supervisord_child_entry")
            .arg("--nocapture")
            .arg("--test-threads=1")
            .env(CHILD_MODE_ENV, "1")
            .env(CHILD_FLEET_ROOT_ENV, fleet_root.as_path())
            .env(CHILD_RELEASE_TRUST_ENV, release_trust)
            .stdin(Stdio::null())
            .stdout(Stdio::from(log.try_clone()?))
            .stderr(Stdio::from(log))
            .spawn()?;
        Ok(Self(child, diagnostic_log))
    }

    fn try_wait(&mut self) -> Result<Option<std::process::ExitStatus>> {
        Ok(self.0.try_wait()?)
    }

    fn kill(&mut self) -> Result<()> {
        if self.0.try_wait()?.is_none() {
            self.0.kill()?;
        }
        self.0.wait()?;
        Ok(())
    }
}

impl Drop for DaemonChild {
    fn drop(&mut self) {
        if self.0.try_wait().ok().flatten().is_none() {
            let _ = self.0.kill();
            let _ = self.0.wait();
            // Preserve the actual daemon's bounded tail when test cleanup
            // finds it still running after an error or panic.
            use std::io::Read;
            use std::io::Seek;
            use std::io::SeekFrom;
            if let Some(file) = self.1.as_mut()
                && let Ok(metadata) = file.metadata()
                && metadata.is_file()
                && file
                    .seek(SeekFrom::Start(metadata.len().saturating_sub(65_536)))
                    .is_ok()
            {
                let mut bytes = Vec::new();
                if file.take(65_536).read_to_end(&mut bytes).is_ok() {
                    let mut stderr = std::io::stderr().lock();
                    let _ = stderr.write_all(b"FIVE_AGENT_DAEMON_LOG_TAIL ");
                    let _ = stderr.write_all(&bytes);
                    let _ = stderr.write_all(b"\n");
                }
            }
        }
    }
}

#[derive(Default)]
struct AgentProcessGuard {
    process_ids: BTreeMap<AgentId, u32>,
}

impl AgentProcessGuard {
    fn observe(&mut self, status: &SupervisordAgentStatus) -> Result<()> {
        if let Some(process_id) = status.process_id {
            self.process_ids.insert(
                status.agent_id.clone(),
                u32::try_from(process_id).context("agent PID does not fit pid_t")?,
            );
        } else {
            self.process_ids.remove(&status.agent_id);
        }
        Ok(())
    }
}

impl Drop for AgentProcessGuard {
    fn drop(&mut self) {
        for process_id in self.process_ids.values() {
            let _ = Command::new("/bin/kill")
                .arg("-KILL")
                .arg(process_id.to_string())
                .stdout(Stdio::null())
                .stderr(Stdio::null())
                .status();
        }
    }
}
