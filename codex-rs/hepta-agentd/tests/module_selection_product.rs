#![cfg(all(feature = "server", unix))]
//! One real Supervisor lifecycle owner starts the ordinary Agentd binary with
//! its selected profile. No model request, test-only execution spine or grant.
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agent_components::automation::AutomationSchedule;
use codex_hepta_agent_components::automation::AutomationStore;
use codex_hepta_agent_components::automation::AutomationTaskDraft;
use codex_hepta_agent_components::automation::TimerPhase;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::control_plane::RuntimeModuleAbiV1;
use codex_hepta_agent_components::control_plane::RuntimeModuleStateClassV1;
use codex_hepta_agent_components::fleet::AgentLifecycle;
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
            let status = client
                .snapshot(agent.clone())
                .await
                .context("snapshot while awaiting selected Agentd readiness")?;
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
    let before = client.snapshot(agent.clone()).await?;
    client
        .start(before.control_fence, release)
        .await
        .context("start explicitly allowed installed release")?;
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
    let created = product
        .automation_create(draft)
        .await
        .context("create remote product task")?;
    ensure!(product.automation_list(10).await?.len() == 1);
    let current = client.snapshot(agent.clone()).await?;
    client
        .restart(current.control_fence)
        .await
        .context("restart selected installed release")?;
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ProfileCase {
    Selected,
    Absent,
    WrongImage,
    RetainedUnselected,
    CorruptSelected,
    RetiredSelected,
}

async fn run_product_case(case: ProfileCase) -> Result<()> {
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
    // Explicit administrator allowance in this isolated fixture; installation
    // alone must not authorize an Agent to execute an otherwise valid release.
    registry.allow_release(&agent, &release_id)?;
    let layout = registry.load_agent(&agent)?.layout;
    let mut preserved_database = None;
    if matches!(
        case,
        ProfileCase::RetainedUnselected | ProfileCase::RetiredSelected
    ) {
        let store = AutomationStore::open(&layout).await?;
        if case == ProfileCase::RetiredSelected {
            ensure!(store.quiesce_timer().await?.can_handoff());
            ensure!(store.retire_timer().await?.phase == TimerPhase::Retired);
        }
        let path = store.path().to_path_buf();
        store.close().await;
        preserved_database = Some((path.clone(), std::fs::read(path)?));
    } else if case == ProfileCase::CorruptSelected {
        let path = layout.automation_root().join("automation_1.sqlite3");
        let bytes = b"deliberately invalid SQLite product fixture".to_vec();
        std::fs::write(&path, &bytes)?;
        preserved_database = Some((path, bytes));
    }
    if !matches!(case, ProfileCase::Absent | ProfileCase::RetainedUnselected) {
        let mut owner = DurableRuntimeModuleSupervisorV1::open(
            registry.layout().runtime_module_supervisor_state(),
        )?;
        let mut abi = selected_binary(&installed.program)?;
        if case == ProfileCase::WrongImage {
            abi.implementation_digest = Digest32::of_bytes(b"different installed image");
        }
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
        if case == ProfileCase::Selected {
            return exercise(&client, &registry, &agent, release_id).await;
        }
        let before = client.snapshot(agent.clone()).await?;
        client.start(before.control_fence, release_id).await?;
        if matches!(
            case,
            ProfileCase::WrongImage
                | ProfileCase::RetainedUnselected
                | ProfileCase::CorruptSelected
        ) {
            // Pair these rejection cases with the successful identical installed
            // binary above. The separate owner tests assert the exact error class.
            timeout(Duration::from_secs(15), async {
                loop {
                    let status = client.snapshot(agent.clone()).await?;
                    ensure!(
                        !status.healthy,
                        "rejected {case:?} became a healthy product"
                    );
                    if status.lifecycle == AgentLifecycle::Failed && !status.active {
                        return Ok::<_, anyhow::Error>(());
                    }
                    sleep(Duration::from_millis(25)).await;
                }
            })
            .await
            .context("selected product rejection deadline")??;
        } else {
            let (product, first) = ready(&client, &registry, &agent, 0).await?;
            ensure!(
                product.health().await?.ready,
                "unrelated core must remain live"
            );
            ensure!(
                product.automation_list(10).await.is_err(),
                "absent/retired Automation must not advertise an idle owner"
            );
            let current = client.snapshot(agent.clone()).await?;
            client.restart(current.control_fence).await?;
            let (reopened, second) = ready(
                &client,
                &registry,
                &agent,
                first.spawn_generation.context("first process generation")?,
            )
            .await?;
            ensure!(
                first.process_id != second.process_id,
                "real process restart required"
            );
            ensure!(
                reopened.automation_list(10).await.is_err(),
                "restart resurrected optional owner"
            );
        }
        Ok(())
    }
    .await;
    // Explicitly settle owned processes even after an assertion/operation error.
    if let Ok(status) = client.snapshot(agent.clone()).await {
        let _ = client.kill(status.control_fence).await;
        let _ = timeout(Duration::from_secs(5), async {
            while client
                .snapshot(agent.clone())
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
    result?;
    if matches!(case, ProfileCase::Absent | ProfileCase::WrongImage) {
        ensure!(
            std::fs::read_dir(layout.automation_root())?
                .next()
                .is_none(),
            "absent/rejected module opened storage"
        );
    }
    if matches!(
        case,
        ProfileCase::RetainedUnselected | ProfileCase::CorruptSelected
    ) {
        let (path, bytes) = preserved_database.context("preserved owner input")?;
        ensure!(
            std::fs::read(path)? == bytes,
            "rejected startup changed retained owner input"
        );
    }
    if case == ProfileCase::RetiredSelected {
        let owner = AutomationStore::open(&layout).await?;
        let status = owner.timer_status().await?;
        owner.close().await;
        ensure!(
            status.phase == TimerPhase::Retired,
            "restart cleared permanent retirement"
        );
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_agentd_binary_consumes_selected_topology_and_recovers_one_durable_task()
-> Result<()> {
    run_product_case(ProfileCase::Selected).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_agentd_absent_module_preserves_core_and_never_opens_storage_after_restart()
-> Result<()> {
    run_product_case(ProfileCase::Absent).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_agentd_wrong_selected_image_rejects_before_owner_open() -> Result<()> {
    run_product_case(ProfileCase::WrongImage).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_agentd_unselection_cannot_abandon_retained_owner_state() -> Result<()> {
    run_product_case(ProfileCase::RetainedUnselected).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_agentd_selected_corrupt_owner_requires_recovery_not_false_readiness() -> Result<()>
{
    run_product_case(ProfileCase::CorruptSelected).await
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn normal_agentd_retired_timer_is_not_resurrected_by_selected_profile_or_restart()
-> Result<()> {
    run_product_case(ProfileCase::RetiredSelected).await
}
