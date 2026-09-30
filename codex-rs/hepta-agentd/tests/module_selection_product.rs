#![cfg(all(feature = "server", unix))]
//! One real Supervisor lifecycle owner starts the ordinary Agentd binary with
//! its selected profile. No model request, test-only execution spine or grant.
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::automation::AutomationSchedule;
use codex_hepta_agent_components::automation::AutomationTaskDraft;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::control_plane::RuntimeModuleAbiV1;
use codex_hepta_agent_components::control_plane::RuntimeModuleStateClassV1;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ReleaseId;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::RuntimeModuleCatalogV1;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_supervisor::DurableRuntimeModuleSupervisorV1;
use codex_hepta_supervisor::SupervisordAgentStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::run_supervisord;
use std::fs::File;
use std::path::Path;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use tokio::time::sleep;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

fn selected_binary(binary: &Path) -> Result<RuntimeModuleAbiV1> {
    let catalog = RuntimeModuleCatalogV1::canonical()?;
    let definition = catalog
        .module("automation.taskflow")
        .context("Automation catalog")?;
    let module_id = StableId::new(&definition.id)?;
    let manifest = definition.manifest_digest.parse::<Digest32>()?;
    let mut file = File::open(binary)?;
    let artifact = Digest32::of_reader(&mut file, file_size(binary)?)?;
    // Independent test calculation of the documented image/manifest binding.
    // This expected value is not a RuntimeExecutableIdentity observation or grant.
    let origin = if cfg!(target_os = "linux") {
        1_u8
    } else {
        2_u8
    };
    let name = module_id.as_str().as_bytes();
    let implementation = Digest32::of_parts(&[
        b"hepta.runtime-module-executable.v1\0",
        &[origin],
        &(name.len() as u64).to_be_bytes(),
        name,
        artifact.as_array(),
        manifest.as_array(),
    ]);
    Ok(RuntimeModuleAbiV1 {
        module_id,
        owner_id: StableId::new(&definition.owner)?,
        generation: Generation::new(7)?,
        implementation_digest: implementation,
        candidate_artifact_digest: artifact,
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: definition
            .dependencies
            .iter()
            .map(StableId::new)
            .collect::<Result<_, _>>()?,
        authoritative_domains: definition
            .authoritative_domains
            .iter()
            .map(StableId::new)
            .collect::<Result<_, _>>()?,
        input_ports: vec![],
        output_ports: vec![],
        effect_scope: Default::default(),
    })
}

fn file_size(binary: &Path) -> Result<u64> {
    let size = std::fs::metadata(binary)?.len();
    ensure!(
        size > 0 && size <= 2 * 1024 * 1024 * 1024,
        "bounded executable"
    );
    Ok(size)
}

async fn ready(
    client: &SupervisordClient,
    registry: &FleetRegistry,
    agent: &AgentId,
    after: u64,
) -> Result<(AgentdClient, SupervisordAgentStatus)> {
    timeout(Duration::from_secs(30), async {
        loop {
            let status = client.agent(agent.clone()).await?;
            if let Some(generation) = status
                .spawn_generation
                .filter(|generation| *generation > after)
            {
                let record = registry.load_agent(agent)?;
                let product = AgentdClient::new(
                    record.layout.agentd_control_socket().to_path_buf(),
                    agent.clone(),
                    generation,
                )?;
                if product.health().await.is_ok_and(|health| health.ready) {
                    return Ok((product, status));
                }
            }
            sleep(Duration::from_millis(25)).await;
        }
    })
    .await
    .context("normal Agentd readiness deadline")?
}

async fn exercise(
    client: &SupervisordClient,
    registry: &FleetRegistry,
    agent: &AgentId,
    release: ReleaseId,
) -> Result<()> {
    let before = client.agent(agent.clone()).await?;
    client.start(before.control_fence, release).await?;
    let (product, first) = ready(client, registry, agent, 0).await?;
    let now = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    // Keep the task outside this test's lifetime: no model/provider dispatch.
    let draft = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "retained selected module task",
        AutomationSchedule::FixedInterval {
            interval_ms: 86_400_000,
        },
        now + 86_400_000,
        now,
    );
    let created = product.automation_create(draft).await?;
    ensure!(product.automation_list(10).await?.len() == 1);
    let current = client.agent(agent.clone()).await?;
    client.restart(current.control_fence).await?;
    let (reopened, second) = ready(
        client,
        registry,
        agent,
        first.spawn_generation.context("first generation")?,
    )
    .await?;
    ensure!(
        first.process_id != second.process_id,
        "restart must change the real process"
    );
    let tasks = reopened.automation_list(10).await?;
    ensure!(
        tasks.len() == 1 && tasks[0].task_id == created.task_id,
        "selected product must retain one task without duplicate owner effects"
    );
    let selection = client
        .runtime_module_selection("automation.taskflow".to_string())
        .await?;
    ensure!(
        selection.selected.context("selected module")?.generation == 7,
        "process restart cannot reinterpret the selected module generation"
    );
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_agentd_binary_consumes_selected_topology_and_recovers_one_durable_task()
-> Result<()> {
    let temp = tempfile::Builder::new()
        .prefix("hsel-product-")
        .tempdir_in("/tmp")?;
    let root = temp.path().canonicalize()?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").map_err(anyhow::Error::msg)?;
    registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    let binary = codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?;
    let release_id = ReleaseId::parse("selected-profile-fixture".to_string())?;
    let installed = registry.install_release(
        release_id.clone(),
        &binary,
        vec![
            "--runtime-module-profile".to_string(),
            "supervisor-selected".to_string(),
        ],
    )?;
    {
        let mut owner = DurableRuntimeModuleSupervisorV1::open(
            registry.layout().runtime_module_supervisor_state(),
        )?;
        let abi = selected_binary(&installed.program)?;
        for dependency in &abi.dependencies {
            let mut prerequisite = abi.clone();
            prerequisite.module_id = dependency.clone();
            prerequisite.owner_id = dependency.clone();
            prerequisite.dependencies.clear();
            prerequisite.authoritative_domains.clear();
            prerequisite.state_class = RuntimeModuleStateClassV1::Stateless;
            owner.register_bootstrap(prerequisite)?;
        }
        owner.register_bootstrap(abi)?;
    }
    let stop = CancellationToken::new();
    let daemon = tokio::spawn(run_supervisord(fleet, stop.clone()));
    let client = SupervisordClient::new(registry.layout().supervisor_socket().to_path_buf())?;
    let result = async {
        timeout(Duration::from_secs(5), async {
            while client.health().await.is_err() {
                sleep(Duration::from_millis(20)).await;
            }
        })
        .await?;
        exercise(&client, &registry, &agent, release_id).await
    }
    .await;
    // Explicitly settle owned processes even after an assertion/operation error.
    if let Ok(status) = client.agent(agent.clone()).await {
        let _ = client.kill(status.control_fence).await;
        let _ = timeout(Duration::from_secs(5), async {
            while client
                .agent(agent.clone())
                .await
                .is_ok_and(|status| status.active)
            {
                sleep(Duration::from_millis(25)).await;
            }
        })
        .await;
    }
    stop.cancel();
    daemon.await??;
    result
}
