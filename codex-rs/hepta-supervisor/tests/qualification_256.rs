#![cfg(all(feature = "qualification", unix))]

use std::path::Path;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::SupervisorLockMetricsSnapshot;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::run_supervisord_qualification;
use tokio::task::JoinSet;
use tokio_util::sync::CancellationToken;

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn two_hundred_fifty_six_agent_control_plane_records_lock_latency() -> anyhow::Result<()> {
    let temp = tempfile::tempdir()?;
    let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let mut agents = Vec::new();
    for index in 0..256_u16 {
        let agent_id = AgentId::parse(qualification_agent_id(index))?;
        let workspace = temp.path().join(format!("workspace-{index:03}"));
        std::fs::create_dir_all(&workspace)?;
        registry.register(AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        agents.push(agent_id);
    }

    let socket = registry.layout().supervisor_socket().to_path_buf();
    let metrics = temp.path().join("supervisor-lock-metrics.json");
    let cancellation = CancellationToken::new();
    let daemon_cancellation = cancellation.clone();
    let daemon_root = root.clone();
    let metrics_for_daemon = metrics.clone();
    let daemon = tokio::spawn(async move {
        run_supervisord_qualification(
            daemon_root,
            daemon_cancellation,
            None,
            metrics_for_daemon,
        )
        .await
    });
    wait_for_path(&socket).await?;

    let client = SupervisordClient::new(socket.clone())?;
    assert_eq!(client.health().await?.registered_agents, 256);
    assert_eq!(client.roster(256).await?.len(), 256);

    for chunk in agents.chunks(32) {
        let mut reads = JoinSet::new();
        for agent_id in chunk {
            let socket = socket.clone();
            let agent_id = agent_id.clone();
            reads.spawn(async move {
                SupervisordClient::new(socket)?
                    .snapshot(agent_id)
                    .await
                    .map(|_| ())
            });
        }
        while let Some(result) = reads.join_next().await {
            result??;
        }
    }

    for chunk in agents[..64].chunks(16) {
        let mut mutations = JoinSet::new();
        for agent_id in chunk {
            let socket = socket.clone();
            let agent_id = agent_id.clone();
            mutations.spawn(async move {
                let client = SupervisordClient::new(socket)?;
                let fence = client.snapshot(agent_id).await?.control_fence;
                let _expected_rejection = client.restart(fence).await;
                Ok::<(), codex_hepta_supervisor::SupervisorError>(())
            });
        }
        while let Some(result) = mutations.join_next().await {
            result??;
        }
    }

    tokio::time::sleep(Duration::from_millis(100)).await;
    cancellation.cancel();
    daemon.await??;
    let snapshot: SupervisorLockMetricsSnapshot =
        serde_json::from_slice(&std::fs::read(metrics)?)?;
    assert!(snapshot.tick.hold.count > 0);
    assert!(snapshot.read.hold.count >= 258);
    assert!(snapshot.mutation.hold.count >= 64);
    assert!(snapshot.read.wait.max_nanos > 0);
    Ok(())
}

fn qualification_agent_id(index: u16) -> String {
    format!("018f4f72-{index:04x}-7{index:03x}-8{index:03x}-{index:012x}")
}

async fn wait_for_path(path: &Path) -> anyhow::Result<()> {
    for _ in 0..400 {
        if path.exists() {
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
    anyhow::bail!("supervisord socket did not appear at {}", path.display())
}
