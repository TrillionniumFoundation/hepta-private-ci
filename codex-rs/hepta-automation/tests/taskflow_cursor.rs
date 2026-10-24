#![allow(
    clippy::expect_used,
    reason = "qualification fixtures should fail loudly"
)]

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowError;
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
use pretty_assertions::assert_eq;

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
        "step-outbox",
        /*version*/ 1,
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
        Sha256Digest::for_bytes(b"step-policy"),
    )
    .expect("definition")
}

fn fence(generation: u64) -> TaskFlowFence {
    TaskFlowFence::new(
        AgentId::parse(AGENT_ID).expect("agent id"),
        "step-owner",
        /*owner_epoch*/ 1,
        generation,
        format!("step-fence-{generation}"),
    )
    .expect("fence")
}

async fn prepared_store(
    fixture: &Fixture,
) -> (AutomationStore, TaskFlowFence, Sha256Digest, Sha256Digest) {
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("open store");
    let owner = fence(/*generation*/ 1);
    let definition = definition();
    store
        .register_taskflow_definition(&definition, &owner, /*registered_at_ms*/ 10)
        .await
        .expect("register");
    store
        .create_taskflow_run(
            "step-run",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-step",
            /*created_at_ms*/ 10,
        )
        .await
        .expect("create");
    store
        .claim_taskflow_run(
            "step-run", &owner, /*now_ms*/ 20, /*lease_duration_ms*/ 1_000,
        )
        .await
        .expect("claim run");
    (
        store,
        owner,
        Sha256Digest::for_bytes(b"step-intent"),
        Sha256Digest::for_bytes(b"step-payload"),
    )
}

#[tokio::test]
async fn cursor_reopens_the_same_observation_and_exact_cas_replay_is_idempotent() {
    let fixture = Fixture::new();
    let (store, owner, _, _) = prepared_store(&fixture).await;
    let first = store
        .commit_taskflow_cursor(
            "step-run",
            "turn:1",
            &owner,
            /*previous*/ None,
            r#"{"phase":"model","request":"original"}"#,
            /*now_ms*/ 21,
        )
        .await
        .expect("initial frame");
    let next = store
        .commit_taskflow_cursor(
            "step-run",
            "turn:1",
            &owner,
            Some(&first),
            r#"{"phase":"tools","observed_usage":14,"continuation":"receipt"}"#,
            /*now_ms*/ 22,
        )
        .await
        .expect("atomic observed successor");
    let replay = store
        .commit_taskflow_cursor(
            "step-run",
            "turn:1",
            &owner,
            Some(&first),
            &next.payload,
            /*now_ms*/ 23,
        )
        .await
        .expect("exact replay");
    assert_eq!(replay, next);
    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen same owner");
    assert_eq!(
        reopened
            .taskflow_cursor("step-run", "turn:1", &owner)
            .await
            .expect("read"),
        Some(next)
    );
    assert!(matches!(
        reopened
            .commit_taskflow_cursor(
                "step-run",
                "turn:1",
                &owner,
                Some(&first),
                "conflicting successor",
                /*now_ms*/ 24
            )
            .await,
        Err(TaskFlowError::Conflict(_))
    ));
}

#[tokio::test]
async fn stale_fence_expired_write_and_foreign_predecessor_leave_cursor_unchanged() {
    let fixture = Fixture::new();
    let (store, owner, _, _) = prepared_store(&fixture).await;
    let first = store
        .commit_taskflow_cursor(
            "step-run", "turn:1", &owner, /*previous*/ None, "original", /*now_ms*/ 21,
        )
        .await
        .expect("initial");
    let foreign = fence(/*generation*/ 2);
    assert!(matches!(
        store.taskflow_cursor("step-run", "turn:1", &foreign).await,
        Err(TaskFlowError::StaleFence)
    ));
    assert!(matches!(
        store
            .commit_taskflow_cursor(
                "step-run",
                "turn:1",
                &foreign,
                Some(&first),
                "changed",
                /*now_ms*/ 22
            )
            .await,
        Err(TaskFlowError::StaleFence)
    ));
    assert!(matches!(
        store
            .commit_taskflow_cursor(
                "step-run",
                "turn:1",
                &owner,
                Some(&first),
                "changed",
                /*now_ms*/ 1020
            )
            .await,
        Err(TaskFlowError::StaleFence)
    ));
    assert!(matches!(
        store
            .commit_taskflow_cursor(
                "step-run",
                "turn:2",
                &owner,
                Some(&first),
                "changed",
                /*now_ms*/ 22
            )
            .await,
        Err(TaskFlowError::Conflict(_))
    ));
    assert_eq!(
        store
            .taskflow_cursor("step-run", "turn:1", &owner)
            .await
            .expect("observation"),
        Some(first)
    );
}

#[tokio::test]
async fn competing_writers_cannot_append_two_successors_to_one_revision() {
    let fixture = Fixture::new();
    let (store, owner, _, _) = prepared_store(&fixture).await;
    let first = store
        .commit_taskflow_cursor(
            "step-run", "turn:1", &owner, /*previous*/ None, "original", /*now_ms*/ 21,
        )
        .await
        .expect("initial");
    let (left, right) = tokio::join!(
        store.commit_taskflow_cursor(
            "step-run",
            "turn:1",
            &owner,
            Some(&first),
            "left",
            /*now_ms*/ 22
        ),
        store.commit_taskflow_cursor(
            "step-run",
            "turn:1",
            &owner,
            Some(&first),
            "right",
            /*now_ms*/ 22
        )
    );
    assert_eq!(usize::from(left.is_ok()) + usize::from(right.is_ok()), 1);
    let observed = store
        .taskflow_cursor("step-run", "turn:1", &owner)
        .await
        .expect("read")
        .expect("present");
    assert_eq!(observed.revision, 2);
    assert!(observed.payload == "left" || observed.payload == "right");
}

#[tokio::test]
async fn immutable_history_and_digest_validation_reject_a_modified_snapshot() {
    let fixture = Fixture::new();
    let (store, owner, _, _) = prepared_store(&fixture).await;
    store
        .commit_taskflow_cursor(
            "step-run", "turn:1", &owner, /*previous*/ None, "original", /*now_ms*/ 21,
        )
        .await
        .expect("initial");
    let home =
        AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root()).expect("absolute");
    let pool = SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("test corruption connection");
    assert!(
        sqlx::query("UPDATE taskflow_native_cursors SET encoded = CAST('{}' AS BLOB)")
            .execute(&pool)
            .await
            .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM taskflow_native_cursors")
            .execute(&pool)
            .await
            .is_err()
    );
    // Deliberately bypass only this isolated fixture's immutable trigger to
    // establish that read-time validation is independent of the write guard.
    sqlx::query("DROP TRIGGER taskflow_native_cursors_no_update")
        .execute(&pool)
        .await
        .expect("fixture only");
    sqlx::query("UPDATE taskflow_native_cursors SET encoded = CAST('{}' AS BLOB)")
        .execute(&pool)
        .await
        .expect("fixture corruption");
    assert!(matches!(
        store.taskflow_cursor("step-run", "turn:1", &owner).await,
        Err(TaskFlowError::Corrupt(_))
    ));
}

#[tokio::test]
async fn oversized_snapshot_is_rejected_without_creating_a_cursor() {
    let fixture = Fixture::new();
    let (store, owner, _, _) = prepared_store(&fixture).await;
    let large = "x".repeat(codex_hepta_automation::MAX_TASKFLOW_CURSOR_PAYLOAD_BYTES + 1);
    assert!(matches!(
        store
            .commit_taskflow_cursor(
                "step-run", "turn:1", &owner, /*previous*/ None, &large, /*now_ms*/ 21
            )
            .await,
        Err(TaskFlowError::Invalid(_))
    ));
    assert_eq!(
        store
            .taskflow_cursor("step-run", "turn:1", &owner)
            .await
            .expect("absent"),
        None
    );
}

async fn apply_transition(
    store: &AutomationStore,
    owner: &TaskFlowFence,
    transition: codex_hepta_automation::TaskFlowTransition,
) {
    let run = store
        .taskflow_run("step-run")
        .await
        .expect("run")
        .expect("present");
    let command = codex_hepta_automation::TaskFlowCommand::new(
        "step-run",
        format!("cursor-test:{}", run.revision),
        owner.clone(),
        run.revision,
        transition,
        30 + run.revision,
    )
    .expect("command");
    store
        .apply_taskflow_command(&command)
        .await
        .expect("owner transition");
}

#[tokio::test]
async fn terminal_owner_clear_keeps_read_only_recovery_without_reopening_a_writer() {
    use codex_hepta_automation::TaskFlowTransition;
    for terminal in [
        TaskFlowTransition::Succeed {
            output_digest: Sha256Digest::for_bytes(b"complete"),
        },
        TaskFlowTransition::Fail {
            reason: "failed".into(),
        },
        TaskFlowTransition::Cancel {
            reason: "cancelled".into(),
        },
        TaskFlowTransition::Reconcile {
            receipt_digest: Sha256Digest::for_bytes(b"observed"),
            outcome: codex_hepta_automation::TaskFlowReconcileOutcome::Succeeded,
        },
    ] {
        let fixture = Fixture::new();
        let (store, owner, _, _) = prepared_store(&fixture).await;
        let first = store
            .commit_taskflow_cursor(
                "step-run",
                "turn:1",
                &owner,
                /*previous*/ None,
                "original observation",
                /*now_ms*/ 21,
            )
            .await
            .expect("initial");
        apply_transition(&store, &owner, TaskFlowTransition::Start).await;
        if matches!(&terminal, TaskFlowTransition::Reconcile { .. }) {
            apply_transition(
                &store,
                &owner,
                TaskFlowTransition::Indeterminate {
                    reason: "unknown".into(),
                },
            )
            .await;
        }
        apply_transition(&store, &owner, terminal).await;
        store.close().await;
        let reopened = AutomationStore::open(&fixture.layout)
            .await
            .expect("reopen terminal");
        assert_eq!(
            reopened
                .taskflow_cursor("step-run", "turn:1", &owner)
                .await
                .expect("historical observation"),
            Some(first.clone())
        );
        assert!(matches!(
            reopened
                .taskflow_cursor("step-run", "turn:1", &fence(/*generation*/ 2))
                .await,
            Err(TaskFlowError::StaleFence)
        ));
        assert!(
            reopened
                .commit_taskflow_cursor(
                    "step-run",
                    "turn:1",
                    &owner,
                    Some(&first),
                    "must not reopen",
                    /*now_ms*/ 40
                )
                .await
                .is_err()
        );
    }
}

#[tokio::test]
async fn byte_preflight_rejects_nul_text_and_oversized_digest_before_loading_rows() {
    for column in [
        "encoded",
        "evidence_digest",
        "previous_digest",
        "revision",
        "encoded_blob",
    ] {
        let fixture = Fixture::new();
        let (store, owner, _, _) = prepared_store(&fixture).await;
        store
            .commit_taskflow_cursor(
                "step-run", "turn:1", &owner, /*previous*/ None, "original",
                /*now_ms*/ 21,
            )
            .await
            .expect("initial");
        let home = AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root())
            .expect("absolute");
        let pool = SqliteConfig::from_sqlite_home(home)
            .open_durable_evidence_pool(store.path())
            .await
            .expect("fixture connection");
        // SQLite TEXT length stops at NUL. Deliberately bypass the fixture's
        // write guards and verify independent byte/type preflight on reads.
        let mut connection = pool.acquire().await.expect("one corruption connection");
        sqlx::query("DROP TRIGGER taskflow_native_cursors_no_update")
            .execute(&mut *connection)
            .await
            .expect("fixture only");
        sqlx::query("PRAGMA ignore_check_constraints=ON")
            .execute(&mut *connection)
            .await
            .expect("fixture only");
        let poison = format!("{}\0{}", "0".repeat(64), "x".repeat(1024 * 1024));
        if column == "encoded_blob" {
            sqlx::query("UPDATE taskflow_native_cursors SET encoded = ?")
                .bind(vec![b'x'; 5 * 1024 * 1024])
                .execute(&mut *connection)
                .await
                .expect("oversized row");
        } else {
            let sql = match column {
                "encoded" => "UPDATE taskflow_native_cursors SET encoded = ?",
                "evidence_digest" => "UPDATE taskflow_native_cursors SET evidence_digest = ?",
                "previous_digest" => "UPDATE taskflow_native_cursors SET previous_digest = ?",
                "revision" => "UPDATE taskflow_native_cursors SET revision = ?",
                _ => unreachable!("closed fixture cases"),
            };
            sqlx::query(sql)
                .bind(poison)
                .execute(&mut *connection)
                .await
                .expect("insert malformed TEXT");
        }
        drop(connection);
        assert_eq!(
            store
                .taskflow_cursor("step-run", "turn:1", &owner)
                .await
                .expect_err("preflight rejects"),
            TaskFlowError::Corrupt("cursor history budget".into())
        );
    }
}

#[tokio::test]
async fn rehashed_snapshot_cannot_invent_a_writer_generation_absent_from_run_history() {
    let fixture = Fixture::new();
    let (store, owner, _, _) = prepared_store(&fixture).await;
    store
        .commit_taskflow_cursor(
            "step-run", "turn:1", &owner, /*previous*/ None, "original", /*now_ms*/ 21,
        )
        .await
        .expect("initial");
    let home =
        AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root()).expect("absolute");
    let pool = SqliteConfig::from_sqlite_home(home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("fixture connection");
    let encoded: Vec<u8> = sqlx::query_scalar("SELECT encoded FROM taskflow_native_cursors")
        .fetch_one(&pool)
        .await
        .expect("original evidence");
    let mut entry: serde_json::Value = serde_json::from_slice(&encoded).expect("entry");
    entry["generation"] = serde_json::json!(2);
    entry["fencing_token"] = serde_json::json!("step-fence-2");
    let modified = serde_json::to_vec(&entry).expect("rehashed forgery");
    let digest = Sha256Digest::for_bytes(&modified);
    sqlx::query("DROP TRIGGER taskflow_native_cursors_no_update")
        .execute(&pool)
        .await
        .expect("fixture only");
    sqlx::query("UPDATE taskflow_native_cursors SET encoded = ?, evidence_digest = ?")
        .bind(modified)
        .bind(digest.as_str())
        .execute(&pool)
        .await
        .expect("fixture mutation");
    assert_eq!(
        store
            .taskflow_cursor("step-run", "turn:1", &owner)
            .await
            .expect_err("writer rejected"),
        TaskFlowError::Corrupt("cursor writer has no verified run provenance".into())
    );
}
