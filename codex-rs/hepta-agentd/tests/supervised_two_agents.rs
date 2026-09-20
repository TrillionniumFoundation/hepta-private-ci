#![cfg(unix)]

use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_memory::CognitiveAccess;
use codex_hepta_memory::CognitiveScope;
use codex_hepta_memory::CognitiveStore;
use codex_hepta_memory::LedgerSourceKind;
use codex_hepta_memory::MemoryDraft;
use codex_hepta_memory::MemoryLifecycleState;
use codex_hepta_memory::MemoryRevisionDraft;
use codex_hepta_memory::MemoryRevisionRecord;
use codex_hepta_memory::MemoryVerification;
use codex_hepta_memory::RetrievalRequest;
use codex_hepta_memory::SourceDraft;

mod support;

use support::fleet::FleetHarness;
use support::fleet::connect_app_server;

const AGENT_A: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const AGENT_B: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";

#[tokio::test(flavor = "multi_thread", worker_threads = 4)]
async fn two_supervised_real_agentd_processes_are_fault_isolated() -> Result<()> {
    let mut harness = FleetHarness::new()?;
    let fixture_a = harness.register(AGENT_A, "workspace-a")?;
    let fixture_b = harness.register(AGENT_B, "workspace-b")?;
    let agent_a = fixture_a.agent_id.clone();
    let agent_b = fixture_b.agent_id.clone();
    let workspace_a = fixture_a.workspace.clone();
    let workspace_b = fixture_b.workspace.clone();
    let layout_a = fixture_a.layout.clone();
    let layout_b = fixture_b.layout.clone();
    harness.start(&fixture_a)?;
    harness.start(&fixture_b)?;
    let (client_a, health_a) = harness.wait_ready(&fixture_a, 1).await?;
    let (client_b, health_b) = harness.wait_ready(&fixture_b, 1).await?;
    assert_ne!(health_a.process_id, health_b.process_id);
    assert_eq!(health_a.workspace, workspace_a);
    assert_eq!(health_b.workspace, workspace_b);
    assert_eq!(health_a.home_root, layout_a.home_root());
    assert_eq!(health_b.home_root, layout_b.home_root());
    assert_ne!(health_a.run_root, health_b.run_root);

    let ingress_a = client_a.session_ingress().await?;
    let ingress_b = client_b.session_ingress().await?;
    assert_eq!(ingress_a.socket_path, layout_a.app_server_socket());
    assert_eq!(ingress_b.socket_path, layout_b.app_server_socket());
    assert_ne!(ingress_a.socket_path, ingress_b.socket_path);
    assert_eq!(
        initialized_codex_home(&ingress_a.socket_path).await?,
        layout_a.home_root().to_string_lossy()
    );
    assert_eq!(
        initialized_codex_home(&ingress_b.socket_path).await?,
        layout_b.home_root().to_string_lossy()
    );

    let (store_a, access_a, memory_a) =
        remember_agent_fact(&layout_a, &agent_a, "Agent A remembers a red cedar.").await?;
    let (store_b, access_b, memory_b) =
        remember_agent_fact(&layout_b, &agent_b, "Agent B remembers a blue ocean.").await?;
    assert_eq!(store_a.path().parent(), Some(layout_a.cognitive_root()));
    assert_eq!(store_b.path().parent(), Some(layout_b.cognitive_root()));
    assert_ne!(store_a.path(), store_b.path());
    assert_ne!(memory_a.id.memory_id, memory_b.id.memory_id);
    assert_eq!(
        retrieved_contents(&store_a, &access_a).await?,
        vec![memory_a.content.clone()]
    );
    assert_eq!(
        retrieved_contents(&store_b, &access_b).await?,
        vec![memory_b.content.clone()]
    );

    let b_process_before = health_b.process_id;
    harness.supervisor.kill(&agent_a)?;
    harness.wait_stopped(&agent_a).await?;
    let b_during_a_failure = client_b.health().await?;
    assert!(b_during_a_failure.ready);
    assert_eq!(b_during_a_failure.process_id, b_process_before);
    assert_eq!(
        initialized_codex_home(&ingress_b.socket_path).await?,
        layout_b.home_root().to_string_lossy()
    );
    assert_eq!(
        retrieved_contents(&store_b, &access_b).await?,
        vec![memory_b.content.clone()]
    );

    harness.supervisor.restart(&agent_a, Instant::now())?;
    let restarted_generation = harness
        .registry
        .load()?
        .agent(&agent_a)
        .context("agent A missing after restart")?
        .lifecycle
        .generation;
    assert_eq!(restarted_generation, 5);
    let restarted_a = harness.control_client(&fixture_a, restarted_generation)?;
    let restarted_health_a = harness.wait_until_ready(&agent_a, &restarted_a).await?;
    let still_healthy_b = client_b.health().await?;
    assert_ne!(restarted_health_a.process_id, health_a.process_id);
    assert_eq!(still_healthy_b.process_id, b_process_before);
    assert_eq!(
        initialized_codex_home(layout_a.app_server_socket()).await?,
        layout_a.home_root().to_string_lossy()
    );
    let reopened_a = CognitiveStore::open(&layout_a).await?;
    assert_eq!(reopened_a.owner_agent_id(), &agent_a);
    assert_eq!(
        retrieved_contents(&reopened_a, &access_a).await?,
        vec![memory_a.content]
    );
    assert_eq!(
        retrieved_contents(&store_b, &access_b).await?,
        vec![memory_b.content]
    );

    let events = restarted_a.events(0, 256).await?;
    assert!(!events.events.is_empty());
    let resumed = restarted_a.events(events.next_cursor, 256).await?;
    assert!(!resumed.gap);
    assert!(resumed.events.is_empty());

    assert_eq!(
        harness
            .registry
            .load()?
            .agent(&agent_b)
            .context("agent B missing")?
            .lifecycle
            .lifecycle,
        AgentLifecycle::Running
    );
    Ok(())
}

async fn remember_agent_fact(
    layout: &codex_hepta_paths::HeptaAgentLayout,
    agent_id: &AgentId,
    content: &str,
) -> Result<(CognitiveStore, CognitiveAccess, MemoryRevisionRecord)> {
    let store = CognitiveStore::open(layout).await?;
    if store.owner_agent_id() != agent_id {
        bail!("cognitive store owner does not match its typed agent layout");
    }
    let access = CognitiveAccess::agent_private(agent_id.clone());
    let scope = CognitiveScope::AgentPrivate;
    let citation = store
        .append_source(
            &access,
            &SourceDraft {
                scope: scope.clone(),
                kind: LedgerSourceKind::ExplicitMemoryDirective,
                event_key: "same-cognitive-source".to_string(),
                content: content.as_bytes().to_vec(),
                observed_at_unix_seconds: 100,
            },
        )
        .await?;
    let memory = store
        .remember_memory(
            &access,
            &MemoryDraft {
                stable_key: "same-stable-memory".to_string(),
                revision: MemoryRevisionDraft {
                    scope,
                    content: content.to_string(),
                    verification: MemoryVerification::Verified,
                    lifecycle: MemoryLifecycleState::Active,
                    valid_from_unix_seconds: 100,
                    valid_to_unix_seconds: None,
                    citations: vec![citation],
                },
            },
        )
        .await?;
    Ok((store, access, memory))
}

async fn retrieved_contents(
    store: &CognitiveStore,
    access: &CognitiveAccess,
) -> Result<Vec<String>> {
    Ok(store
        .retrieve_memory_candidates(access, &RetrievalRequest::new("remembers", 200))
        .await?
        .candidates
        .into_iter()
        .map(|candidate| candidate.memory.content)
        .collect())
}

impl FleetHarness {
    async fn wait_stopped(&mut self, agent_id: &AgentId) -> Result<()> {
        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            let report = self.supervisor.tick(Instant::now());
            ensure!(
                report.faults.is_empty(),
                "supervisor faults while stopping {agent_id}: {:?}",
                report.faults
            );
            let inactive = self
                .supervisor
                .snapshot(agent_id)
                .is_some_and(|snapshot| !snapshot.active);
            let stopped = self
                .registry
                .load()?
                .agent(agent_id)
                .is_some_and(|record| record.lifecycle.lifecycle == AgentLifecycle::Stopped);
            if inactive && stopped {
                return Ok(());
            }
            if Instant::now() >= deadline {
                bail!("timed out waiting for agent {agent_id} to stop");
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
    }
}

async fn initialized_codex_home(socket_path: &Path) -> Result<String> {
    let client = connect_app_server(socket_path, "hepta-agentd-e2e", 8).await?;
    let home = client
        .codex_home()
        .ok_or_else(|| anyhow::anyhow!("initialize response omitted Codex home"))?
        .to_string();
    client.shutdown().await?;
    Ok(home)
}
