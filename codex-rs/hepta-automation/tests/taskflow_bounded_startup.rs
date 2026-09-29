#![allow(
    clippy::expect_used,
    reason = "bounded startup integration fixtures should fail loudly"
)]

use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaAgentLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const PAGE_SIZE: u32 = 256;
const ZERO_DIGEST: &str = "0000000000000000000000000000000000000000000000000000000000000000";

struct Fixture {
    _temp: tempfile::TempDir,
    layout: HeptaAgentLayout,
}

impl Fixture {
    fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        std::fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let manifest = AgentManifest::new(
            AgentId::parse(AGENT_ID).expect("agent id"),
            WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
            ResourceBudget::local_default(),
        )
        .expect("manifest");
        Self {
            _temp: temp,
            layout: registry.register(manifest).expect("register agent").layout,
        }
    }
}

fn definition(version: u32) -> TaskFlowDefinition {
    TaskFlowDefinition::new(
        "bounded-startup",
        version,
        "work",
        vec![
            TaskFlowNodeSpec::new("work", TaskFlowNodeKind::Activity),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("work", "success"),
            TaskFlowEdgeSpec::new("work", "failure"),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"bounded-startup-policy"),
    )
    .expect("valid definition")
}

fn fence(generation: u64) -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "bounded-startup-owner",
        1,
        generation,
        format!("bounded-startup-fence-{generation}"),
    )
    .expect("valid fence")
}

async fn open_store(fixture: &Fixture) -> AutomationStore {
    AutomationStore::open(&fixture.layout)
        .await
        .expect("open automation store")
}

async fn inspection_pool(fixture: &Fixture, store: &AutomationStore) -> sqlx::SqlitePool {
    let sqlite_home = AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root())
        .expect("absolute sqlite home");
    SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("open inspection pool")
}

async fn assert_reopen_corrupt(fixture: &Fixture) {
    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(AutomationError::Corrupt)
    ));
}

#[tokio::test]
async fn corruption_after_first_definition_page_fails_reopen() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence(1);
    for version in 1..=PAGE_SIZE + 1 {
        store
            .register_taskflow_definition(&definition(version), &owner, u64::from(version))
            .await
            .expect("register definition");
    }

    let pool = inspection_pool(&fixture, &store).await;
    store.close().await;
    sqlx::query("DROP TRIGGER taskflow_definitions_no_update")
        .execute(&pool)
        .await
        .expect("drop immutable definition trigger in adversarial fixture");
    sqlx::query(
        "UPDATE taskflow_definitions SET definition_json = '{}'
         WHERE owner_agent_id = ? AND workflow_id = ? AND version = ?",
    )
    .bind(AGENT_ID)
    .bind("bounded-startup")
    .bind(i64::from(PAGE_SIZE + 1))
    .execute(&pool)
    .await
    .expect("corrupt second definition page");
    pool.close().await;

    assert_reopen_corrupt(&fixture).await;
}

#[tokio::test]
async fn corruption_after_first_run_page_fails_reopen() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence(1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 1)
        .await
        .expect("register definition");
    for index in 1..=PAGE_SIZE + 1 {
        store
            .create_taskflow_run(
                format!("run-{index:04}"),
                &definition.workflow_id,
                definition.version,
                definition.definition_digest(),
                format!("thread-{index:04}"),
                u64::from(index),
            )
            .await
            .expect("create run");
    }

    let pool = inspection_pool(&fixture, &store).await;
    store.close().await;
    sqlx::query(
        "UPDATE taskflow_runs SET state_digest = ?
         WHERE owner_agent_id = ? AND run_id = ?",
    )
    .bind(ZERO_DIGEST)
    .bind(AGENT_ID)
    .bind(format!("run-{:04}", PAGE_SIZE + 1))
    .execute(&pool)
    .await
    .expect("corrupt second run page");
    pool.close().await;

    assert_reopen_corrupt(&fixture).await;
}

#[tokio::test]
async fn corruption_after_first_event_page_fails_reopen() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &fence(1), 1)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "event-page-run",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "event-page-thread",
            1,
        )
        .await
        .expect("create run");
    for generation in 1..=PAGE_SIZE + 4 {
        let now_ms = u64::from(generation) * 10;
        store
            .claim_taskflow_run("event-page-run", &fence(u64::from(generation)), now_ms, 1)
            .await
            .expect("advance lease generation");
    }

    let pool = inspection_pool(&fixture, &store).await;
    store.close().await;
    sqlx::query("DROP TRIGGER taskflow_events_no_update")
        .execute(&pool)
        .await
        .expect("drop immutable event trigger in adversarial fixture");
    sqlx::query(
        "UPDATE taskflow_events SET event_digest = ?
         WHERE owner_agent_id = ? AND run_id = ? AND event_seq = ?",
    )
    .bind(ZERO_DIGEST)
    .bind(AGENT_ID)
    .bind("event-page-run")
    .bind(i64::from(PAGE_SIZE + 1))
    .execute(&pool)
    .await
    .expect("corrupt second event page");
    pool.close().await;

    assert_reopen_corrupt(&fixture).await;
}
