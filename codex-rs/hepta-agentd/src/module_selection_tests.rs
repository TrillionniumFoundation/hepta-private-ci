//! Real Supervisor socket, durable topology owner and the normal Automation factory.
//! Test bootstrap is explicit; no model, external effect or independent acceptance.
use super::*;
use crate::AgentdConfig;
use crate::AgentdState;
use crate::RuntimeTasks;
use crate::automation::AutomationService;
use codex_hepta_agent_components::contracts::AgentId;
use codex_hepta_agent_components::control_plane::RuntimeModuleAbiV1;
use codex_hepta_agent_components::control_plane::RuntimeModuleStateClassV1;
use codex_hepta_agent_components::fleet::AgentLifecycle;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_supervisor::DurableRuntimeModuleSupervisorV1;
use codex_hepta_supervisor::SupervisordClient;
use codex_hepta_supervisor::run_supervisord;
use std::sync::Arc;
use tokio_util::sync::CancellationToken;

fn compiled_abi() -> RuntimeModuleAbiV1 {
    let catalog = RuntimeModuleCatalogV1::canonical().expect("catalog");
    let definition = catalog.module("automation.taskflow").expect("automation");
    let module = StableId::new(&definition.id).expect("module");
    let image = RuntimeExecutableIdentity::observe_current().expect("loaded executable");
    let implementation = image.implementation_digest(
        &module,
        definition.manifest_digest.parse().expect("manifest"),
    );
    RuntimeModuleAbiV1 {
        module_id: module,
        owner_id: StableId::new(&definition.owner).expect("owner"),
        generation: Generation::new(7).expect("selected generation"),
        implementation_digest: implementation,
        candidate_artifact_digest: Digest32::of_bytes(b"independently supplied fixture candidate"),
        predecessor_generation: None,
        rollback_predecessor_digest: Digest32::ZERO,
        state_class: RuntimeModuleStateClassV1::Stateful,
        dependencies: definition
            .dependencies
            .iter()
            .map(|id| StableId::new(id).expect("dependency"))
            .collect(),
        authoritative_domains: definition
            .authoritative_domains
            .iter()
            .map(|id| StableId::new(id).expect("domain"))
            .collect(),
        input_ports: vec![],
        output_ports: vec![],
        effect_scope: Default::default(),
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    _config: AgentdConfig,
    state: Arc<AgentdState>,
    stop: CancellationToken,
    daemon: tokio::task::JoinHandle<Result<(), codex_hepta_supervisor::SupervisorError>>,
}

async fn fixture(selected: Option<RuntimeModuleAbiV1>) -> Fixture {
    let temp = tempfile::Builder::new()
        .prefix("hsel-")
        .tempdir_in("/tmp")
        .expect("short root");
    let root = temp.path().canonicalize().expect("root");
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("initialize");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    let record = registry
        .register(
            AgentManifest::new(
                agent_id.clone(),
                WorkspaceBinding::new(&workspace, &fleet).expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register");
    {
        let mut owner = DurableRuntimeModuleSupervisorV1::open(
            registry.layout().runtime_module_supervisor_state(),
        )
        .expect("topology owner");
        if let Some(abi) = selected {
            // The dependency records are structural fixtures, not running models
            // or tool owners. Only Automation is instantiated by this test.
            for dependency in &abi.dependencies {
                let mut prerequisite = abi.clone();
                prerequisite.module_id = dependency.clone();
                prerequisite.owner_id = dependency.clone();
                prerequisite.dependencies.clear();
                prerequisite.authoritative_domains.clear();
                prerequisite.state_class = RuntimeModuleStateClassV1::Stateless;
                owner
                    .register_bootstrap(prerequisite)
                    .expect("dependency fixture");
            }
            owner
                .register_bootstrap(abi)
                .expect("reviewed bootstrap fixture");
        }
    }
    let stop = CancellationToken::new();
    let daemon = tokio::spawn(run_supervisord(fleet.clone(), stop.clone()));
    let client = SupervisordClient::new(registry.layout().supervisor_socket().to_path_buf())
        .expect("client");
    timeout(Duration::from_secs(5), async {
        loop {
            if client.health().await.is_ok() {
                break;
            }
            assert!(!daemon.is_finished(), "Supervisor exited before readiness");
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("Supervisor readiness");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("starting");
    let config = AgentdConfig::load(
        root.join("fleet"),
        agent_id,
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .expect("normal Agentd configuration and writer lock");
    let state =
        Arc::new(AgentdState::new(config.identity().clone(), registry, 128).expect("normal state"));
    Fixture {
        _temp: temp,
        _config: config,
        state,
        stop,
        daemon,
    }
}

async fn finish(fixture: Fixture) {
    fixture.stop.cancel();
    fixture
        .daemon
        .await
        .expect("Supervisor joined")
        .expect("Supervisor stopped");
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn supervisor_selection_starts_real_owner_at_selected_generation_and_drains_it() {
    let fixture = fixture(Some(compiled_abi())).await;
    let state = Arc::clone(&fixture.state);
    let service = AutomationService::open(
        Arc::clone(&state),
        RuntimeModuleProfileV1::SupervisorSelected,
    )
    .await
    .expect("real selection and owner open");
    assert!(
        !state
            .automation_is_available()
            .expect("not published before revalidation")
    );
    let stop = CancellationToken::new();
    let mut tasks =
        RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).expect("same task host");
    tasks
        .spawn_required("unrelated", std::future::pending())
        .expect("sibling");
    service
        .spawn(&mut tasks, stop.clone())
        .await
        .expect("real constructor");
    assert!(state.automation_is_available().expect("published"));
    assert_eq!(tasks.active_count(), 2);
    assert!(
        tasks
            .retire_optional_generation(
                "automation.taskflow",
                Generation::new(1).expect("host generation")
            )
            .await
            .is_err(),
        "host generation is not the selected module generation"
    );
    tasks
        .retire_optional_generation(
            "automation.taskflow",
            Generation::new(7).expect("module generation"),
        )
        .await
        .expect("real scheduler drains its durable owner");
    assert!(!state.automation_is_available().expect("unpublished"));
    assert_eq!(tasks.active_count(), 1);
    assert!(
        !stop.is_cancelled(),
        "optional retirement must not kill siblings"
    );
    tasks.shutdown().await;
    finish(fixture).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn unselected_module_never_opens_storage_or_advertises_idle_service() {
    let fixture = fixture(None).await;
    let directory = fixture
        .state
        .identity()
        .layout
        .automation_root()
        .to_path_buf();
    let before = std::fs::read_dir(&directory)
        .expect("prepared directory")
        .count();
    let service = AutomationService::open(
        Arc::clone(&fixture.state),
        RuntimeModuleProfileV1::SupervisorSelected,
    )
    .await
    .expect("explicit absence");
    let stop = CancellationToken::new();
    let mut tasks = RuntimeTasks::new(stop.clone(), Duration::from_secs(2)).expect("host");
    service
        .spawn(&mut tasks, stop)
        .await
        .expect("no optional service");
    assert_eq!(tasks.active_count(), 0);
    assert!(
        !fixture
            .state
            .automation_is_available()
            .expect("no attachment")
    );
    assert_eq!(
        std::fs::read_dir(&directory)
            .expect("unchanged directory")
            .count(),
        before
    );
    tasks.shutdown().await;
    finish(fixture).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn selected_image_or_undeclared_effect_mismatch_is_rejected_before_storage() {
    for mismatch in ["image", "effect"] {
        let mut abi = compiled_abi();
        match mismatch {
            "image" => abi.implementation_digest = Digest32::of_bytes(b"different executable"),
            "effect" => {
                abi.effect_scope
                    .insert(StableId::new("undeclared.effect").expect("effect"));
            }
            _ => unreachable!(),
        }
        let fixture = fixture(Some(abi)).await;
        let directory = fixture
            .state
            .identity()
            .layout
            .automation_root()
            .to_path_buf();
        let before = std::fs::read_dir(&directory)
            .expect("prepared directory")
            .count();
        let result = AutomationService::open(
            Arc::clone(&fixture.state),
            RuntimeModuleProfileV1::SupervisorSelected,
        )
        .await;
        assert!(
            matches!(result, Err(AgentdError::GenerationFenced(_))),
            "{mismatch}"
        );
        assert!(
            !fixture
                .state
                .automation_is_available()
                .expect("no attachment")
        );
        assert_eq!(
            std::fs::read_dir(&directory)
                .expect("unchanged directory")
                .count(),
            before
        );
        finish(fixture).await;
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn absent_route_cannot_silently_abandon_existing_owner_state() {
    let fixture = fixture(None).await;
    let owner = codex_hepta_agent_components::automation::AutomationStore::open(
        &fixture.state.identity().layout,
    )
    .await
    .expect("existing durable owner");
    let before = owner.timer_status().await.expect("current owner state");
    let result = AutomationService::open(
        Arc::clone(&fixture.state),
        RuntimeModuleProfileV1::SupervisorSelected,
    )
    .await;
    assert!(matches!(result, Err(AgentdError::GenerationFenced(_))));
    assert_eq!(owner.timer_status().await.expect("owner unchanged"), before);
    assert!(
        !fixture
            .state
            .automation_is_available()
            .expect("not published")
    );
    owner.close().await;
    finish(fixture).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn selected_unavailable_owner_cannot_masquerade_as_an_absent_optional_module() {
    for corrupt_file in [false, true] {
        let fixture = fixture(Some(compiled_abi())).await;
        let database = fixture
            .state
            .identity()
            .layout
            .automation_root()
            .join("automation_1.sqlite3");
        if corrupt_file {
            std::fs::write(&database, b"not a SQLite database").expect("corrupt owner fixture");
        } else {
            std::fs::create_dir(&database).expect("unavailable database fixture");
        }
        let result = AutomationService::open(
            Arc::clone(&fixture.state),
            RuntimeModuleProfileV1::SupervisorSelected,
        )
        .await;
        let rejected = matches!(&result, Err(AgentdError::Protocol(message))
            if message.contains("selected Automation owner") && message.contains("recovery"));
        let unpublished = !fixture
            .state
            .automation_is_available()
            .expect("attachment state");
        drop(result);
        finish(fixture).await;
        assert!(
            rejected,
            "selected unavailable/corrupt owner must reject startup, corrupt_file={corrupt_file}"
        );
        assert!(unpublished, "failed selected owner must not be published");
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn compiled_optional_owner_retains_its_existing_degraded_startup_policy() {
    let fixture = fixture(None).await;
    let database = fixture
        .state
        .identity()
        .layout
        .automation_root()
        .join("automation_1.sqlite3");
    std::fs::create_dir(&database).expect("unavailable database fixture");
    let result =
        AutomationService::open(Arc::clone(&fixture.state), RuntimeModuleProfileV1::Compiled).await;
    let degraded = result.is_ok();
    let unpublished = !fixture
        .state
        .automation_is_available()
        .expect("attachment state");
    drop(result);
    finish(fixture).await;
    assert!(
        degraded,
        "do not silently strengthen the legacy optional profile"
    );
    assert!(unpublished, "degraded does not mean attached");
}
