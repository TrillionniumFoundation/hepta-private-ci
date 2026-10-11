#![allow(
    clippy::expect_used,
    reason = "TaskFlow integration fixtures should fail loudly"
)]

use codex_hepta_automation::AutomationError;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowCommandStatus;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowTransition;
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
const FOREIGN_AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dd4";

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
        let agent_id = AgentId::parse(AGENT_ID).expect("agent id");
        let manifest = AgentManifest::new(
            agent_id,
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
        "memory-review",
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
        Sha256Digest::for_bytes(b"taskflow-policy"),
    )
    .expect("valid definition")
}

fn fence(owner_id: &str, generation: u64) -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        owner_id,
        1,
        generation,
        format!("fence-{owner_id}-{generation}"),
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

#[test]
fn invalid_graph_and_effect_contract_fail_closed() {
    let cycle = TaskFlowDefinition::new(
        "cycle",
        1,
        "entry",
        vec![
            TaskFlowNodeSpec::new("entry", TaskFlowNodeKind::Activity),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("entry", "entry"),
            TaskFlowEdgeSpec::new("entry", "success"),
            TaskFlowEdgeSpec::new("entry", "failure"),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"policy"),
    );
    assert!(matches!(cycle, Err(TaskFlowError::Invalid(_))));

    let missing_effect_contract = TaskFlowDefinition::new(
        "effect",
        1,
        "effect",
        vec![
            TaskFlowNodeSpec::new("effect", TaskFlowNodeKind::Effect),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("effect", "success"),
            TaskFlowEdgeSpec::new("effect", "failure"),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"policy"),
    );
    assert!(matches!(
        missing_effect_contract,
        Err(TaskFlowError::Invalid(_))
    ));
}

#[tokio::test]
async fn definition_registration_is_idempotent_and_generation_scoped() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let first = definition(1);

    let receipt = store
        .register_taskflow_definition(&first, &owner, 10)
        .await
        .expect("register definition");
    assert!(receipt.inserted);
    let replay = store
        .register_taskflow_definition(&first, &owner, 11)
        .await
        .expect("replay definition");
    assert!(!replay.inserted);
    assert_eq!(replay.registered_generation, 1);

    // A generation may register more than one workflow/version.  Only a
    // strictly older generation is stale.
    let second = definition(2);
    assert!(
        store
            .register_taskflow_definition(&second, &owner, 12)
            .await
            .expect("register second version")
            .inserted
    );

    let altered = TaskFlowDefinition::new(
        "memory-review",
        1,
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
        Sha256Digest::for_bytes(b"different-policy"),
    )
    .expect("altered definition");
    assert!(matches!(
        store
            .register_taskflow_definition(&altered, &owner, 13)
            .await,
        Err(TaskFlowError::Conflict(_))
    ));
}

#[tokio::test]
async fn run_lifecycle_is_fenced_and_command_deduplicated() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    let created = store
        .create_taskflow_run(
            "run-1",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run("run-1", &owner, 20, 1_000)
        .await
        .expect("claim run");
    assert_eq!(claimed.state, TaskFlowRunState::Queued);
    assert_eq!(claimed.revision, created.revision + 1);

    let start = TaskFlowCommand::new(
        "run-1",
        "command-start",
        owner.clone(),
        claimed.revision,
        TaskFlowTransition::Start,
        21,
    )
    .expect("start command");
    let started = store
        .apply_taskflow_command(&start)
        .await
        .expect("start run");
    assert_eq!(started.state, TaskFlowRunState::Running);
    let replay = store
        .apply_taskflow_command(&start)
        .await
        .expect("replay start");
    assert_eq!(replay.status, TaskFlowCommandStatus::AlreadyApplied);
    assert_eq!(replay.revision, started.revision);

    let reused = TaskFlowCommand::new(
        "run-1",
        "command-start",
        owner.clone(),
        started.revision,
        TaskFlowTransition::Fail {
            reason: "different bytes".to_string(),
        },
        22,
    )
    .expect("reused command");
    assert!(matches!(
        store.apply_taskflow_command(&reused).await,
        Err(TaskFlowError::Conflict(_))
    ));

    let stale = TaskFlowCommand::new(
        "run-1",
        "command-stale",
        fence("foreign-owner", 1),
        started.revision,
        TaskFlowTransition::Fail {
            reason: "must not apply".to_string(),
        },
        22,
    )
    .expect("stale command");
    assert!(matches!(
        store.apply_taskflow_command(&stale).await,
        Err(TaskFlowError::StaleFence)
    ));

    let wait = TaskFlowCommand::new(
        "run-1",
        "command-wait",
        owner.clone(),
        started.revision,
        TaskFlowTransition::Wait {
            token: "wait-1".to_string(),
            resume_node: Some("success".to_string()),
        },
        23,
    )
    .expect("wait command");
    let waiting = store.apply_taskflow_command(&wait).await.expect("wait run");
    assert_eq!(waiting.state, TaskFlowRunState::Waiting);
    let resume = TaskFlowCommand::new(
        "run-1",
        "command-resume",
        owner.clone(),
        waiting.revision,
        TaskFlowTransition::Resume {
            token: "wait-1".to_string(),
        },
        24,
    )
    .expect("resume command");
    let running = store
        .apply_taskflow_command(&resume)
        .await
        .expect("resume run");
    assert_eq!(running.state, TaskFlowRunState::Running);
    let cancel = TaskFlowCommand::new(
        "run-1",
        "command-cancel",
        owner,
        running.revision,
        TaskFlowTransition::Cancel {
            reason: "operator requested".to_string(),
        },
        25,
    )
    .expect("cancel command");
    let cancelled = store
        .apply_taskflow_command(&cancel)
        .await
        .expect("cancel run");
    assert_eq!(cancelled.state, TaskFlowRunState::Cancelled);
    assert!(matches!(
        store
            .taskflow_run("run-1")
            .await
            .expect("read run")
            .expect("run exists")
            .state,
        TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
    ));
}

#[tokio::test]
async fn indeterminate_requires_explicit_receipt_reconcile() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "run-indeterminate",
            &definition.workflow_id,
            1,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run("run-indeterminate", &owner, 20, 10)
        .await
        .expect("claim run");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "run-indeterminate",
                "start",
                owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                21,
            )
            .expect("start command"),
        )
        .await
        .expect("start run");
    let indeterminate = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "run-indeterminate",
                "unknown-outcome",
                owner.clone(),
                started.revision,
                TaskFlowTransition::Indeterminate {
                    reason: "crash-after-send".to_string(),
                },
                22,
            )
            .expect("indeterminate command"),
        )
        .await
        .expect("mark indeterminate");
    assert_eq!(indeterminate.state, TaskFlowRunState::Indeterminate);
    assert!(matches!(
        store
            .claim_taskflow_run("run-indeterminate", &fence("owner-a", 2), 23, 10)
            .await,
        Err(TaskFlowError::Conflict(_))
    ));

    // Reconcile is allowed after the lease deadline, but only with the exact
    // retained owner tuple and an explicit receipt digest.
    let reconciled = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "run-indeterminate",
                "reconcile",
                owner,
                indeterminate.revision,
                TaskFlowTransition::Reconcile {
                    receipt_digest: Sha256Digest::for_bytes(b"provider-status-receipt"),
                    outcome: TaskFlowReconcileOutcome::Succeeded,
                },
                100,
            )
            .expect("reconcile command"),
        )
        .await
        .expect("reconcile run");
    assert_eq!(reconciled.state, TaskFlowRunState::Succeeded);
}

#[tokio::test]
async fn invalid_transition_does_not_advance_projection_or_event_tail() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    let run = store
        .create_taskflow_run(
            "run-invalid",
            "memory-review",
            1,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run("run-invalid", &owner, 20, 100)
        .await
        .expect("claim run");
    let before = store
        .taskflow_run("run-invalid")
        .await
        .expect("read before")
        .expect("run before");
    assert_eq!(before.revision, run.revision + 1);
    let invalid = TaskFlowCommand::new(
        "run-invalid",
        "bad-wait",
        owner,
        claimed.revision,
        TaskFlowTransition::Wait {
            token: String::new(),
            resume_node: None,
        },
        21,
    )
    .expect("command envelope");
    assert!(matches!(
        store.apply_taskflow_command(&invalid).await,
        Err(TaskFlowError::InvalidTransition(_))
    ));
    let after = store
        .taskflow_run("run-invalid")
        .await
        .expect("read after")
        .expect("run after");
    assert_eq!(after, before);
}

#[tokio::test]
async fn command_writer_enforces_graph_resume_target_and_advances_current_node() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "run-graph-writer",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run("run-graph-writer", &owner, 20, 1_000)
        .await
        .expect("claim run");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "run-graph-writer",
                "graph-start",
                owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                21,
            )
            .expect("start command"),
        )
        .await
        .expect("start run");

    let invalid = TaskFlowCommand::new(
        "run-graph-writer",
        "graph-invalid-wait",
        owner.clone(),
        started.revision,
        TaskFlowTransition::Wait {
            token: "invalid-target".to_string(),
            resume_node: Some("detached".to_string()),
        },
        22,
    )
    .expect("invalid target command envelope");
    assert!(matches!(
        store.apply_taskflow_command(&invalid).await,
        Err(TaskFlowError::InvalidTransition(message))
            if message.contains("outgoing edge")
    ));
    let unchanged = store
        .taskflow_run("run-graph-writer")
        .await
        .expect("read unchanged run")
        .expect("run exists");
    assert_eq!(unchanged.revision, started.revision);
    assert_eq!(unchanged.current_node, "work");
    assert_eq!(unchanged.state, TaskFlowRunState::Running);

    let waiting = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "run-graph-writer",
                "graph-valid-wait",
                owner,
                started.revision,
                TaskFlowTransition::Wait {
                    token: "valid-target".to_string(),
                    resume_node: Some("success".to_string()),
                },
                23,
            )
            .expect("valid wait command"),
        )
        .await
        .expect("wait run");
    assert_eq!(waiting.state, TaskFlowRunState::Waiting);
    let waiting_run = store
        .taskflow_run("run-graph-writer")
        .await
        .expect("read advanced run")
        .expect("run exists");
    assert_eq!(waiting_run.current_node, "success");
    assert_eq!(
        store
            .taskflow_run("run-graph-writer")
            .await
            .expect("read advanced run")
            .expect("run exists")
            .current_node,
        "success"
    );
}

#[tokio::test]
async fn taskflow_mutations_reject_corrupt_event_chain_before_replay_or_append() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    let created = store
        .create_taskflow_run(
            "run-corrupt-events",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run("run-corrupt-events", &owner, 20, 1_000)
        .await
        .expect("claim run");
    assert_eq!(claimed.revision, created.revision + 1);

    // Bypass the immutable test trigger to model a damaged local database
    // discovered after the opener's initial verification.  Mutating paths
    // must validate the append-only event chain while holding their write
    // transaction, before returning a replay or appending another event.
    let database_path = store.path().to_path_buf();
    let sqlite_home = AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root())
        .expect("absolute sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await
        .expect("open inspection pool");
    sqlx::query("DROP TRIGGER taskflow_events_no_update")
        .execute(&pool)
        .await
        .expect("drop event immutability trigger");
    sqlx::query(
        "UPDATE taskflow_events
         SET payload_json = 'tampered'
         WHERE owner_agent_id = ? AND run_id = ? AND event_seq = 1",
    )
    .bind(AGENT_ID)
    .bind("run-corrupt-events")
    .execute(&pool)
    .await
    .expect("tamper event payload");
    pool.close().await;

    let replay_create = store
        .create_taskflow_run(
            "run-corrupt-events",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-1",
            11,
        )
        .await;
    assert!(matches!(
        replay_create,
        Err(TaskFlowError::Corrupt(message))
            if message.contains("TaskFlow event digest mismatch")
    ));

    let replay_claim = store
        .claim_taskflow_run("run-corrupt-events", &owner, 21, 1_000)
        .await;
    assert!(matches!(
        replay_claim,
        Err(TaskFlowError::Corrupt(message))
            if message.contains("TaskFlow event digest mismatch")
    ));

    let command = TaskFlowCommand::new(
        "run-corrupt-events",
        "start-corrupt-events",
        owner,
        claimed.revision,
        TaskFlowTransition::Start,
        22,
    )
    .expect("start command");
    let append_attempt = store.apply_taskflow_command(&command).await;
    assert!(matches!(
        append_attempt,
        Err(TaskFlowError::Corrupt(message))
            if message.contains("TaskFlow event digest mismatch")
    ));

    let sqlite_home = AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root())
        .expect("absolute sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(&database_path)
        .await
        .expect("reopen inspection pool");
    let event_count: i64 = sqlx::query_scalar(
        "SELECT COUNT(*) FROM taskflow_events
         WHERE owner_agent_id = ? AND run_id = ?",
    )
    .bind(AGENT_ID)
    .bind("run-corrupt-events")
    .fetch_one(&pool)
    .await
    .expect("event count");
    assert_eq!(event_count, 2, "corrupt history must not be extended");
    pool.close().await;
}

#[tokio::test]
async fn taskflow_read_rejects_tampered_event_history() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "run-read-tamper",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    store
        .claim_taskflow_run("run-read-tamper", &owner, 20, 1_000)
        .await
        .expect("claim run");

    // Model a damaged local database after the opener has completed.  The
    // ordinary read path must fail closed just like mutation and reopen paths.
    // It now loads the projection and verifies its immutable history from one
    // transaction-scoped snapshot.
    let pool = inspection_pool(&fixture, &store).await;
    sqlx::query("DROP TRIGGER taskflow_events_no_update")
        .execute(&pool)
        .await
        .expect("drop event immutability trigger");
    sqlx::query(
        "UPDATE taskflow_events
         SET payload_json = 'tampered'
         WHERE owner_agent_id = ? AND run_id = ? AND event_seq = 1",
    )
    .bind(AGENT_ID)
    .bind("run-read-tamper")
    .execute(&pool)
    .await
    .expect("tamper event payload");
    pool.close().await;

    assert!(matches!(
        store.taskflow_run("run-read-tamper").await,
        Err(TaskFlowError::Corrupt(message))
            if message.contains("TaskFlow event digest mismatch")
    ));
}

#[tokio::test]
async fn automation_opener_rejects_foreign_taskflow_rows() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    let pool = inspection_pool(&fixture, &store).await;
    let definition_json = serde_json::to_string(&definition).expect("definition JSON");
    sqlx::query(
        "INSERT INTO taskflow_definitions (
             owner_agent_id, workflow_id, version, definition_digest,
             definition_json, registered_generation, registered_at_ms
         ) VALUES (?, ?, ?, ?, ?, ?, ?)",
    )
    .bind(FOREIGN_AGENT_ID)
    .bind(&definition.workflow_id)
    .bind(i64::from(definition.version))
    .bind(definition.definition_digest().as_str())
    .bind(definition_json)
    .bind(1_i64)
    .bind(10_i64)
    .execute(&pool)
    .await
    .expect("insert foreign TaskFlow definition");
    pool.close().await;
    store.close().await;

    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(AutomationError::AccessDenied)
    ));
}

#[tokio::test]
async fn automation_opener_rejects_uncomputed_persisted_definition_digest() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");

    // The constructor uses an all-zero sentinel before it computes the
    // canonical digest.  Model a damaged database in which both durable
    // copies were changed to that sentinel.  A field-to-column equality check
    // alone would accept this row during reopen; persisted definitions must
    // always be re-derived from their canonical bytes.
    let mut tampered = serde_json::to_value(&definition).expect("definition value");
    tampered["definition_digest"] = serde_json::Value::String("0".repeat(64));
    let tampered_json = serde_json::to_string(&tampered).expect("tampered definition JSON");
    let pool = inspection_pool(&fixture, &store).await;
    sqlx::query("DROP TRIGGER taskflow_definitions_no_update")
        .execute(&pool)
        .await
        .expect("drop definition immutability trigger");
    sqlx::query(
        "UPDATE taskflow_definitions
         SET definition_json = ?, definition_digest = ?
         WHERE owner_agent_id = ? AND workflow_id = ? AND version = ?",
    )
    .bind(tampered_json)
    .bind("0".repeat(64))
    .bind(AGENT_ID)
    .bind(&definition.workflow_id)
    .bind(i64::from(definition.version))
    .execute(&pool)
    .await
    .expect("tamper persisted definition digest");
    pool.close().await;
    store.close().await;

    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(AutomationError::Corrupt)
    ));
}

#[tokio::test]
async fn automation_opener_rejects_tampered_taskflow_event_history() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "run-opener-tamper",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    store
        .claim_taskflow_run("run-opener-tamper", &owner, 20, 1_000)
        .await
        .expect("claim run");
    let pool = inspection_pool(&fixture, &store).await;
    sqlx::query("DROP TRIGGER taskflow_events_no_update")
        .execute(&pool)
        .await
        .expect("drop event immutability trigger");
    sqlx::query(
        "UPDATE taskflow_events
         SET payload_json = 'tampered'
         WHERE owner_agent_id = ? AND run_id = ? AND event_seq = 1",
    )
    .bind(AGENT_ID)
    .bind("run-opener-tamper")
    .execute(&pool)
    .await
    .expect("tamper event payload");
    pool.close().await;
    store.close().await;

    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(AutomationError::Corrupt)
    ));
}

#[tokio::test]
async fn automation_opener_rejects_taskflow_event_generation_drift() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "run-generation-drift",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    store
        .claim_taskflow_run("run-generation-drift", &owner, 20, 1_000)
        .await
        .expect("claim run");
    let pool = inspection_pool(&fixture, &store).await;
    sqlx::query("DROP TRIGGER taskflow_events_no_update")
        .execute(&pool)
        .await
        .expect("drop event immutability trigger");
    sqlx::query(
        "UPDATE taskflow_events SET generation = 2
         WHERE owner_agent_id = ? AND run_id = ? AND event_seq = 2",
    )
    .bind(AGENT_ID)
    .bind("run-generation-drift")
    .execute(&pool)
    .await
    .expect("tamper event generation");
    pool.close().await;
    store.close().await;

    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(AutomationError::Corrupt)
    ));
}

#[tokio::test]
async fn automation_opener_rejects_hash_valid_taskflow_event_fence_tamper() {
    let fixture = Fixture::new();
    let store = open_store(&fixture).await;
    let owner = fence("owner-a", 1);
    let definition = definition(1);
    store
        .register_taskflow_definition(&definition, &owner, 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "run-fence-tamper",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-1",
            10,
        )
        .await
        .expect("create run");
    store
        .claim_taskflow_run("run-fence-tamper", &owner, 20, 1_000)
        .await
        .expect("claim run");

    // The legacy event digest intentionally covers the command/state payload,
    // not the duplicated owner/token columns.  Bypass the immutable trigger
    // to model a direct database edit and ensure the opener still binds those
    // columns to the lease history and active projection.
    let pool = inspection_pool(&fixture, &store).await;
    sqlx::query("DROP TRIGGER taskflow_events_no_update")
        .execute(&pool)
        .await
        .expect("drop event immutability trigger");
    sqlx::query(
        "UPDATE taskflow_events
         SET owner_id = 'forged-owner', fencing_token = 'forged-token'
         WHERE owner_agent_id = ? AND run_id = ? AND event_seq = 2",
    )
    .bind(AGENT_ID)
    .bind("run-fence-tamper")
    .execute(&pool)
    .await
    .expect("tamper event fence");
    pool.close().await;
    store.close().await;

    assert!(matches!(
        AutomationStore::open(&fixture.layout).await,
        Err(AutomationError::Corrupt)
    ));
}
