#![cfg(feature = "taskflow-structural-qualification")]
#![allow(
    clippy::expect_used,
    reason = "TaskFlow qualification fixtures should fail loudly"
)]

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
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

fn definition() -> TaskFlowDefinition {
    TaskFlowDefinition::new(
        "structural-review",
        /*version*/ 1,
        "work",
        vec![
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
            TaskFlowNodeSpec::new("review", TaskFlowNodeKind::Activity),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("work", TaskFlowNodeKind::Activity),
        ],
        vec![
            TaskFlowEdgeSpec::new("review", "failure"),
            TaskFlowEdgeSpec::new("review", "success"),
            TaskFlowEdgeSpec::new("work", "failure"),
            TaskFlowEdgeSpec::new("work", "review"),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"structural-policy"),
    )
    .expect("valid definition")
}

fn fence(generation: u64) -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "structural-owner",
        /*owner_epoch*/ 1,
        generation,
        format!("structural-fence-{generation}"),
    )
    .expect("valid fence")
}

#[test]
fn frontier_is_sorted_and_fail_closed_for_blocked_states() {
    let definition = definition();
    let running = definition
        .structural_frontier("work", TaskFlowRunState::Running)
        .expect("running frontier");
    assert_eq!(
        running.frontier_nodes,
        vec!["failure".to_string(), "review".to_string()]
    );
    assert!(!running.blocked);
    assert!(!running.terminal);

    let waiting = definition
        .structural_frontier("review", TaskFlowRunState::Waiting)
        .expect("waiting frontier");
    assert!(waiting.frontier_nodes.is_empty());
    assert!(waiting.blocked);
    assert!(!waiting.terminal);

    let terminal = definition
        .structural_frontier("success", TaskFlowRunState::Succeeded)
        .expect("terminal frontier");
    assert!(terminal.frontier_nodes.is_empty());
    assert!(terminal.blocked);
    assert!(terminal.terminal);

    assert!(matches!(
        definition.structural_frontier("missing", TaskFlowRunState::Running),
        Err(TaskFlowError::Corrupt(_))
    ));
}

#[tokio::test]
async fn durable_replay_reconstructs_current_node_and_frontier() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let owner = fence(/*generation*/ 1);
    let definition = definition();
    store
        .register_taskflow_definition(&definition, &owner, /*registered_at_ms*/ 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "structural-run",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-structural",
            /*created_at_ms*/ 10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run(
            "structural-run",
            &owner,
            /*now_ms*/ 20,
            /*lease_duration_ms*/ 1_000,
        )
        .await
        .expect("claim run");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "structural-run",
                "structural-start",
                owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                /*now_ms*/ 21,
            )
            .expect("start command"),
        )
        .await
        .expect("start run");
    let waiting = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "structural-run",
                "structural-wait",
                owner.clone(),
                started.revision,
                TaskFlowTransition::Wait {
                    token: "resume-review".to_string(),
                    resume_node: Some("review".to_string()),
                },
                /*now_ms*/ 22,
            )
            .expect("wait command"),
        )
        .await
        .expect("wait run");
    let waiting_projection = store
        .taskflow_run("structural-run")
        .await
        .expect("read waiting run")
        .expect("waiting projection");
    assert_eq!(waiting_projection.current_node, "review");

    let waiting_replay = store
        .replay_taskflow_structural("structural-run")
        .await
        .expect("replay waiting run");
    assert_eq!(waiting_replay.current_node, "review");
    assert_eq!(waiting_replay.state, TaskFlowRunState::Waiting);
    assert!(waiting_replay.frontier.frontier_nodes.is_empty());
    assert_eq!(waiting_replay.event_count, 4);

    let resumed = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "structural-run",
                "structural-resume",
                owner.clone(),
                waiting.revision,
                TaskFlowTransition::Resume {
                    token: "resume-review".to_string(),
                },
                /*now_ms*/ 23,
            )
            .expect("resume command"),
        )
        .await
        .expect("resume run");
    let running_replay = store
        .replay_taskflow_structural("structural-run")
        .await
        .expect("replay resumed run");
    assert_eq!(running_replay.revision, resumed.revision);
    assert_eq!(
        running_replay.frontier.frontier_nodes,
        vec!["failure".to_string(), "success".to_string()]
    );

    let succeeded = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "structural-run",
                "structural-success",
                owner,
                resumed.revision,
                TaskFlowTransition::Succeed {
                    output_digest: Sha256Digest::for_bytes(b"read-only-result"),
                },
                /*now_ms*/ 24,
            )
            .expect("success command"),
        )
        .await
        .expect("complete run");
    let final_replay = store
        .replay_taskflow_structural("structural-run")
        .await
        .expect("replay completed run");
    assert_eq!(final_replay.revision, succeeded.revision);
    assert_eq!(final_replay.state, TaskFlowRunState::Succeeded);
    assert!(final_replay.frontier.terminal);
    assert!(final_replay.frontier.frontier_nodes.is_empty());
    store.close().await;
}

#[tokio::test]
async fn command_writer_rejects_a_non_structural_resume_target_before_append() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let owner = fence(/*generation*/ 1);
    let definition = definition();
    store
        .register_taskflow_definition(&definition, &owner, /*registered_at_ms*/ 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "invalid-structural-run",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-structural",
            /*created_at_ms*/ 10,
        )
        .await
        .expect("create run");
    let claimed = store
        .claim_taskflow_run(
            "invalid-structural-run",
            &owner,
            /*now_ms*/ 20,
            /*lease_duration_ms*/ 1_000,
        )
        .await
        .expect("claim run");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "invalid-structural-run",
                "invalid-start",
                owner.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                /*now_ms*/ 21,
            )
            .expect("start command"),
        )
        .await
        .expect("start run");
    let invalid = TaskFlowCommand::new(
        "invalid-structural-run",
        "invalid-wait",
        owner,
        started.revision,
        TaskFlowTransition::Wait {
            token: "invalid-target".to_string(),
            resume_node: Some("success".to_string()),
        },
        /*now_ms*/ 22,
    )
    .expect("wait command");
    assert!(matches!(
        store.apply_taskflow_command(&invalid).await,
        Err(TaskFlowError::InvalidTransition(message))
            if message.contains("outgoing edge")
    ));
    let replay = store
        .replay_taskflow_structural("invalid-structural-run")
        .await
        .expect("replay unchanged run");
    assert_eq!(replay.state, TaskFlowRunState::Running);
    assert_eq!(replay.current_node, "work");
    store.close().await;
}

#[tokio::test]
async fn structural_replay_rejects_hash_valid_taskflow_event_fence_tamper() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let owner = fence(/*generation*/ 1);
    let definition = definition();
    store
        .register_taskflow_definition(&definition, &owner, /*registered_at_ms*/ 10)
        .await
        .expect("register definition");
    store
        .create_taskflow_run(
            "structural-fence-tamper",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-structural",
            /*created_at_ms*/ 10,
        )
        .await
        .expect("create run");
    store
        .claim_taskflow_run(
            "structural-fence-tamper",
            &owner,
            /*now_ms*/ 20,
            /*lease_duration_ms*/ 1_000,
        )
        .await
        .expect("claim run");

    let sqlite_home = AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root())
        .expect("absolute sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("open inspection pool");
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
    .bind("structural-fence-tamper")
    .execute(&pool)
    .await
    .expect("tamper event fence");
    pool.close().await;

    assert!(matches!(
        store
            .replay_taskflow_structural("structural-fence-tamper")
            .await,
        Err(TaskFlowError::Corrupt(message))
            if message.contains("TaskFlow event tail fence does not match run projection")
    ));
    store.close().await;
}
