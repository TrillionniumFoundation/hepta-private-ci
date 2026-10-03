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
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::SupervisordAgentStatus;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::run_supervisord;
use std::fs::File;
use std::os::unix::ffi::OsStrExt;
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
            let status = snapshot_after_busy(client, agent)
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
    start_allowed_release(client, agent, release).await?;
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
    restart_same_process(client, agent)
        .await
        .context("restart selected module product")?;
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
    // Preserve the client's original two-second read budget. The Restart has
    // already committed; contention permits another read, never another effect.
    let selection = timeout(Duration::from_secs(2), async {
        loop {
            let before = snapshot_after_busy(client, agent).await?;
            ensure!(
                same_restart_intent(&second, &before),
                "selected process changed before module read"
            );
            match client
                .runtime_module_selection("automation.taskflow".to_string())
                .await
            {
                Ok(selection) => {
                    let after = snapshot_after_busy(client, agent).await?;
                    ensure!(
                        same_restart_intent(&second, &after),
                        "selected process changed during module read"
                    );
                    return Ok::<_, anyhow::Error>(selection);
                }
                Err(SupervisorError::NotAdmittedBusy) => sleep(Duration::from_millis(25)).await,
                Err(error) => return Err(error.into()),
            }
        }
    })
    .await
    .context("selected module read original deadline")?
    .context("read selected module after committed Restart")?;
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

// The enclosing original deadline covers every read, busy response and wait.
// Reads never submit a lifecycle mutation; other error classes fail immediately.
async fn snapshot_after_busy(
    client: &SupervisordClient,
    agent: &AgentId,
) -> Result<SupervisordAgentStatus> {
    loop {
        match client.snapshot(agent.clone()).await {
            Ok(status) => return Ok(status),
            Err(SupervisorError::NotAdmittedBusy) => sleep(Duration::from_millis(25)).await,
            Err(error) => return Err(error.into()),
        }
    }
}

async fn start_allowed_release(
    client: &SupervisordClient,
    agent: &AgentId,
    release: ReleaseId,
) -> Result<()> {
    // Only an explicit no-admission response can retry. All snapshots, reads,
    // sleeps and RPCs share one two-second deadline, preserving the first intent.
    timeout(Duration::from_secs(2), async {
        let intent = snapshot_after_busy(client, agent)
            .await
            .context("snapshot before original mutation intent")?;
        let mut before = intent.clone();
        loop {
            ensure!(
                before.control_fence == intent.control_fence
                    && before.process_id == intent.process_id,
                "unadmitted Start intent changed"
            );
            match client.start(before.control_fence, release.clone()).await {
                Ok(_) => return Ok::<_, anyhow::Error>(()),
                Err(SupervisorError::NotAdmittedBusy | SupervisorError::StaleControlFence) => {
                    sleep(Duration::from_millis(25)).await;
                    before = snapshot_after_busy(client, agent)
                        .await
                        .context("read unadmitted Start intent")?;
                }
                Err(error) => return Err(error.into()),
            }
        }
    })
    .await
    .context("start explicitly allowed installed release control deadline")?
}

fn same_restart_intent(
    original: &SupervisordAgentStatus,
    current: &SupervisordAgentStatus,
) -> bool {
    // A healthy observation of the same Starting process advances exactly one
    // lifecycle generation. A replacement, release change, owner epoch, Matrix
    // change or unaccounted state-digest change must never be silently rebound.
    if original.control_fence == current.control_fence {
        return original.process_id == current.process_id;
    }
    original.agent_id == current.agent_id
        && original.control_fence.supervisor_epoch == current.control_fence.supervisor_epoch
        && original.active
        && current.active
        && original.process_id.is_some()
        && original.process_id == current.process_id
        && original.spawn_generation.is_some()
        && original.spawn_generation == current.spawn_generation
        && original.current_release == current.current_release
        && original.previous_release == current.previous_release
        && !original.release_change_pending
        && !current.release_change_pending
        && original.matrix == current.matrix
        && original.lifecycle == AgentLifecycle::Starting
        && current.lifecycle == AgentLifecycle::Running
        && current.healthy
        && original.lifecycle_generation.checked_add(1) == Some(current.lifecycle_generation)
        && original
            .runtime_generation
            .and_then(|generation| generation.checked_add(1))
            == current.runtime_generation
}

async fn restart_same_process(client: &SupervisordClient, agent: &AgentId) -> Result<()> {
    timeout(Duration::from_secs(2), async {
        let intent = snapshot_after_busy(client, agent)
            .await
            .context("snapshot before original mutation intent")?;
        let mut current = intent.clone();
        loop {
            ensure!(
                same_restart_intent(&intent, &current),
                "Restart intent changed"
            );
            match client.restart(current.control_fence.clone()).await {
                Ok(_) => return Ok::<_, anyhow::Error>(()),
                Err(SupervisorError::StaleControlFence | SupervisorError::NotAdmittedBusy) => {
                    sleep(Duration::from_millis(25)).await;
                    current = snapshot_after_busy(client, agent)
                        .await
                        .context("read unadmitted Restart intent")?;
                }
                Err(error) => return Err(error.into()),
            }
        }
    })
    .await
    .context("restart selected installed process control deadline")?
}

async fn run_product_case(case: ProfileCase) -> Result<()> {
    let agent =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").map_err(anyhow::Error::msg)?;
    let temp = tempfile::Builder::new().prefix("hsel-").tempdir()?;
    let temporary_fleet = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
    let temp = if temporary_fleet
        .layout()
        .agent(&agent)
        .agentd_control_socket()
        .as_os_str()
        .as_bytes()
        .len()
        <= 103
    {
        temp
    } else {
        // Fall back only when the platform Unix socket path limit requires it.
        drop(temp);
        tempfile::Builder::new()
            .prefix("hsel-")
            .tempdir_in("/tmp")?
    };
    let root = temp.path().canonicalize()?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
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
        start_allowed_release(&client, &agent, release_id).await?;
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
                    let status = snapshot_after_busy(&client, &agent)
                        .await
                        .context("snapshot while awaiting original rejection")?;
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
            restart_same_process(&client, &agent)
                .await
                .context("restart absent or retired module product")?;
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
    if result.is_err() {
        // Read the original owner record before containment and temporary
        // directory cleanup; an ambiguous mutation must never be replayed.
        match codex_hepta_supervisor::read_mutation_status(layout.owner_run_root()) {
            Ok(Some(status)) => eprintln!(
                "failed product case {case:?}: original mutation request={} operation={:?} phase={:?} record={:?} detail={:?}",
                status.request_id,
                status.operation,
                status.phase,
                status.record_sha256,
                status.detail,
            ),
            Ok(None) => eprintln!("failed product case {case:?}: no admitted mutation record"),
            Err(error) => eprintln!("failed product case {case:?}: journal read failed: {error}"),
        }
    }
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

#[test]
fn stale_restart_can_follow_only_same_process_readiness() -> Result<()> {
    let original: SupervisordAgentStatus = serde_json::from_value(serde_json::json!({
        "agent_id": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
        "lifecycle": "starting", "lifecycle_generation": 7,
        "active": true, "healthy": false, "process_id": 1234,
        "spawn_generation": 7, "runtime_generation": 7,
        "current_release": "original-release", "previous_release": null,
        "release_change_pending": false,
        "control_fence": {
            "agent_id": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12",
            "supervisor_epoch": "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12",
            "lifecycle": "starting", "lifecycle_generation": 7,
            "spawn_generation": 7, "runtime_generation": 7,
            "current_release": "original-release", "previous_release": null,
            "release_change_pending": false, "state_digest": "a".repeat(64)
        },
        "matrix": {
            "configured": false, "active": false, "healthy": false, "degraded": false,
            "process_id": null, "attached_agent_generation": null, "binding_revision": null,
            "restart_attempt": 0, "last_error": null
        }
    }))?;
    let mut ready = original.clone();
    ready.lifecycle = AgentLifecycle::Running;
    ready.lifecycle_generation = 8;
    ready.runtime_generation = Some(8);
    ready.healthy = true;
    ready.control_fence.lifecycle = ready.lifecycle;
    ready.control_fence.lifecycle_generation = ready.lifecycle_generation;
    ready.control_fence.runtime_generation = ready.runtime_generation;
    ready.control_fence.state_digest =
        codex_hepta_supervisor::ControlStateDigest::parse("b".repeat(64))
            .map_err(anyhow::Error::msg)?;
    ensure!(same_restart_intent(&original, &ready));
    let mut changed = original.clone();
    changed.control_fence.state_digest = ready.control_fence.state_digest.clone();
    ensure!(
        !same_restart_intent(&original, &changed),
        "unexplained state changed"
    );
    changed = ready.clone();
    changed.process_id = Some(1235);
    ensure!(!same_restart_intent(&original, &changed), "another process");
    changed = ready.clone();
    changed.spawn_generation = Some(8);
    changed.control_fence.spawn_generation = changed.spawn_generation;
    ensure!(!same_restart_intent(&original, &changed), "another spawn");
    changed = ready.clone();
    changed.control_fence.supervisor_epoch = codex_hepta_supervisor::SupervisorEpoch::new();
    ensure!(!same_restart_intent(&original, &changed), "another owner");
    changed = ready.clone();
    changed.current_release = Some(ReleaseId::parse("another-release")?);
    changed.control_fence.current_release = changed.current_release.clone();
    ensure!(!same_restart_intent(&original, &changed), "another release");
    changed = ready.clone();
    changed.lifecycle_generation = 9;
    changed.runtime_generation = Some(9);
    changed.control_fence.lifecycle_generation = 9;
    changed.control_fence.runtime_generation = Some(9);
    ensure!(
        !same_restart_intent(&original, &changed),
        "another lifecycle transition"
    );
    changed = ready;
    changed.matrix.binding_revision = Some(1);
    ensure!(
        !same_restart_intent(&original, &changed),
        "another Matrix binding"
    );
    Ok(())
}
