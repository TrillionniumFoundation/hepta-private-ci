#![allow(
    clippy::expect_used,
    reason = "qualification fixtures should fail loudly"
)]

use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowStepCommandStatus;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepState;
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
async fn step_outbox_lifecycle_is_durable_fenced_and_idempotent() {
    let fixture = Fixture::new();
    let (store, owner, intent, payload) = prepared_store(&fixture).await;
    let run = store
        .taskflow_run("step-run")
        .await
        .expect("run")
        .expect("exists");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "step-run",
                "start",
                owner.clone(),
                run.revision,
                TaskFlowTransition::Start,
                20,
            )
            .expect("start command"),
        )
        .await
        .expect("start run");
    let prepared = store
        .prepare_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "step-prepare",
            /*now_ms*/ 21,
        )
        .await
        .expect("prepare");
    assert_eq!(prepared.status, TaskFlowStepCommandStatus::Applied);
    assert_eq!(prepared.receipt.state, TaskFlowStepState::Prepared);
    let prepared_replay = store
        .prepare_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "step-prepare",
            /*now_ms*/ 21,
        )
        .await
        .expect("prepare replay");
    assert_eq!(
        prepared_replay.status,
        TaskFlowStepCommandStatus::AlreadyApplied
    );

    let claimed = store
        .claim_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "step-claim",
            /*now_ms*/ 22,
        )
        .await
        .expect("step claim");
    assert_eq!(claimed.receipt.state, TaskFlowStepState::Claimed);
    for (index, transition) in [
        TaskFlowTransition::Succeed {
            output_digest: intent.clone(),
        },
        TaskFlowTransition::Fail {
            reason: "failure".to_string(),
        },
        TaskFlowTransition::Cancel {
            reason: "cancel".to_string(),
        },
        TaskFlowTransition::Wait {
            token: "wait".to_string(),
            resume_node: None,
        },
        TaskFlowTransition::Retry { retry_at_ms: 30 },
    ]
    .into_iter()
    .enumerate()
    {
        let command = TaskFlowCommand::new(
            "step-run",
            format!("blocked-{index}"),
            owner.clone(),
            started.revision,
            transition,
            22,
        )
        .expect("command");
        assert!(matches!(
            store.apply_taskflow_command(&command).await,
            Err(codex_hepta_automation::TaskFlowError::Conflict(_))
        ));
    }
    assert!(matches!(
        store
            .claim_taskflow_run("step-run", &fence(2), 1_021, 100)
            .await,
        Err(codex_hepta_automation::TaskFlowError::Conflict(_))
    ));
    assert!(matches!(
        store
            .prepare_taskflow_step(
                "step-run",
                "work",
                2,
                &owner,
                &intent,
                &payload,
                "unsafe-retry",
                22
            )
            .await,
        Err(codex_hepta_automation::TaskFlowError::Conflict(_))
    ));
    let observed = store
        .record_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "step-record",
            &Sha256Digest::for_bytes(b"unknown-receipt"),
            TaskFlowStepObservation::Indeterminate,
            /*now_ms*/ 23,
        )
        .await
        .expect("record");
    assert_eq!(observed.receipt.state, TaskFlowStepState::Recorded);
    assert_eq!(
        observed.receipt.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    let quarantined = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "step-run",
                "quarantine",
                owner.clone(),
                started.revision,
                TaskFlowTransition::Indeterminate {
                    reason: "unknown".to_string(),
                },
                23,
            )
            .expect("quarantine command"),
        )
        .await
        .expect("quarantine");
    assert!(matches!(
        store
            .prepare_taskflow_step(
                "step-run",
                "work",
                2,
                &owner,
                &intent,
                &payload,
                "quarantined-retry",
                23
            )
            .await,
        Err(codex_hepta_automation::TaskFlowError::Conflict(_))
    ));
    let terminal = TaskFlowCommand::new(
        "step-run",
        "terminal",
        owner.clone(),
        quarantined.revision,
        TaskFlowTransition::Reconcile {
            receipt_digest: Sha256Digest::for_bytes(b"final-receipt"),
            outcome: TaskFlowReconcileOutcome::Succeeded,
        },
        24,
    )
    .expect("terminal command");
    assert!(matches!(
        store.apply_taskflow_command(&terminal).await,
        Err(codex_hepta_automation::TaskFlowError::Conflict(_))
    ));
    let reconciled = store
        .reconcile_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "step-reconcile",
            &Sha256Digest::for_bytes(b"final-receipt"),
            TaskFlowReconcileOutcome::Succeeded,
            /*now_ms*/ 24,
        )
        .await
        .expect("reconcile");
    assert_eq!(reconciled.receipt.state, TaskFlowStepState::Reconciled);
    assert_eq!(
        reconciled.receipt.final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded)
    );
    store
        .apply_taskflow_command(&terminal)
        .await
        .expect("settled step permits terminal run");
    let read = store
        .read_taskflow_step("step-run", "work", /*attempt*/ 1, &owner)
        .await
        .expect("read")
        .expect("step exists");
    assert_eq!(read.event_seq, 4);
    assert_eq!(read.intent_digest, intent);
    assert_eq!(read.payload_digest, payload);

    let stale = fence(/*generation*/ 2);
    assert!(matches!(
        store
            .read_taskflow_step("step-run", "work", /*attempt*/ 1, &stale)
            .await,
        Err(codex_hepta_automation::TaskFlowError::StaleFence)
    ));

    store.close().await;
    let reopened = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen store");
    let reopened_read = reopened
        .read_taskflow_step("step-run", "work", /*attempt*/ 1, &owner)
        .await
        .expect("read after reopen")
        .expect("step after reopen");
    assert_eq!(reopened_read.state, TaskFlowStepState::Reconciled);
    reopened.close().await;
}

#[tokio::test]
async fn reconciled_step_remains_readable_after_run_projection_refence() {
    let fixture = Fixture::new();
    let (store, owner, intent, payload) = prepared_store(&fixture).await;
    store
        .prepare_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "recovery-prepare",
            /*now_ms*/ 21,
        )
        .await
        .expect("prepare");
    store
        .claim_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "recovery-claim",
            /*now_ms*/ 22,
        )
        .await
        .expect("claim");
    store
        .record_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "recovery-record",
            &Sha256Digest::for_bytes(b"unknown"),
            TaskFlowStepObservation::Indeterminate,
            /*now_ms*/ 23,
        )
        .await
        .expect("record");
    store
        .reconcile_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "recovery-reconcile",
            &Sha256Digest::for_bytes(b"terminal"),
            TaskFlowReconcileOutcome::Succeeded,
            /*now_ms*/ 24,
        )
        .await
        .expect("reconcile");

    // Simulate the recovery crash window: the immutable step is terminal under
    // generation 1, then a newer generation reclaims only the still-Running
    // run projection and crashes before writing its quarantine/terminal events.
    let recovery = fence(/*generation*/ 2);
    store
        .claim_taskflow_run(
            "step-run", &recovery, /*now_ms*/ 2_000, /*lease_duration_ms*/ 1_000,
        )
        .await
        .expect("re-fence run projection");

    let historical = store
        .read_taskflow_step("step-run", "work", /*attempt*/ 1, &owner)
        .await
        .expect("historical terminal step remains readable")
        .expect("step exists");
    assert_eq!(historical.state, TaskFlowStepState::Reconciled);
    assert_eq!(
        historical.final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded)
    );
    assert!(matches!(
        store
            .read_taskflow_step("step-run", "work", /*attempt*/ 1, &recovery)
            .await,
        Err(codex_hepta_automation::TaskFlowError::StaleFence)
    ));
    assert!(matches!(
        store
            .claim_taskflow_step(
                "step-run",
                "work",
                /*attempt*/ 1,
                &owner,
                &intent,
                &payload,
                "recovery-illegal-mutation",
                /*now_ms*/ 2_001,
            )
            .await,
        Err(codex_hepta_automation::TaskFlowError::StaleFence)
    ));
    store.close().await;
}

#[tokio::test]
async fn step_outbox_rejects_wrong_order_and_append_only_tamper() {
    let fixture = Fixture::new();
    let (store, owner, intent, payload) = prepared_store(&fixture).await;
    let receipt = Sha256Digest::for_bytes(b"receipt");
    assert!(matches!(
        store
            .record_taskflow_step(
                "step-run",
                "work",
                /*attempt*/ 1,
                &owner,
                &intent,
                &payload,
                "record-before-claim",
                &receipt,
                TaskFlowStepObservation::Succeeded,
                /*now_ms*/ 21,
            )
            .await,
        Err(codex_hepta_automation::TaskFlowError::Conflict(_))
            | Err(codex_hepta_automation::TaskFlowError::InvalidTransition(_))
    ));
    store
        .prepare_taskflow_step(
            "step-run", "work", /*attempt*/ 1, &owner, &intent, &payload, "prepare",
            /*now_ms*/ 22,
        )
        .await
        .expect("prepare");
    let sqlite_home =
        AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root()).expect("sqlite home");
    let pool = SqliteConfig::from_sqlite_home(sqlite_home)
        .open_durable_evidence_pool(store.path())
        .await
        .expect("inspection pool");
    assert!(
        sqlx::query(
            "UPDATE taskflow_step_outbox SET event_kind = 'claimed' WHERE owner_agent_id = ?"
        )
        .bind(AGENT_ID)
        .execute(&pool)
        .await
        .is_err()
    );
    assert!(
        sqlx::query("DELETE FROM taskflow_step_outbox WHERE owner_agent_id = ?")
            .bind(AGENT_ID)
            .execute(&pool)
            .await
            .is_err()
    );
    pool.close().await;
    store.close().await;
}

#[tokio::test]
async fn step_outbox_failed_commands_leave_no_partial_event_and_expiry_is_fenced() {
    let fixture = Fixture::new();
    let (store, owner, intent, payload) = prepared_store(&fixture).await;
    let prepared = store
        .prepare_taskflow_step(
            "step-run",
            "work",
            /*attempt*/ 1,
            &owner,
            &intent,
            &payload,
            "atomic-prepare",
            /*now_ms*/ 21,
        )
        .await
        .expect("prepare");
    assert_eq!(prepared.receipt.event_seq, 1);

    // A mismatched payload is rejected before the append.  The original
    // prepared event remains the complete durable state.
    let wrong_payload = Sha256Digest::for_bytes(b"wrong-payload");
    assert!(matches!(
        store
            .claim_taskflow_step(
                "step-run",
                "work",
                /*attempt*/ 1,
                &owner,
                &intent,
                &wrong_payload,
                "atomic-claim-wrong",
                /*now_ms*/ 22,
            )
            .await,
        Err(codex_hepta_automation::TaskFlowError::Conflict(_))
    ));
    let unchanged = store
        .read_taskflow_step("step-run", "work", /*attempt*/ 1, &owner)
        .await
        .expect("read unchanged")
        .expect("prepared event remains");
    assert_eq!(unchanged.state, TaskFlowStepState::Prepared);
    assert_eq!(unchanged.event_seq, 1);

    // The exact owner tuple is required even when the lease has expired; a
    // newer generation cannot claim or append to the old intent.
    let expired_owner = fence(/*generation*/ 2);
    assert!(matches!(
        store
            .claim_taskflow_step(
                "step-run",
                "work",
                /*attempt*/ 1,
                &expired_owner,
                &intent,
                &payload,
                "atomic-claim-stale",
                /*now_ms*/ 1_000,
            )
            .await,
        Err(codex_hepta_automation::TaskFlowError::StaleFence)
    ));
    let still_unchanged = store
        .read_taskflow_step("step-run", "work", /*attempt*/ 1, &owner)
        .await
        .expect("read after stale claim")
        .expect("prepared event remains");
    assert_eq!(still_unchanged.event_seq, 1);
    store.close().await;
}

#[tokio::test]
async fn terminal_step_cannot_contradict_provider_evidence_before_projection() {
    for reconcile in [false, true] {
        let fixture = Fixture::new();
        let (store, owner, intent, payload) = prepared_store(&fixture).await;
        let run = store
            .taskflow_run("step-run")
            .await
            .expect("run")
            .expect("exists");
        store
            .apply_taskflow_command(
                &TaskFlowCommand::new(
                    "step-run",
                    "start",
                    owner.clone(),
                    run.revision,
                    TaskFlowTransition::Start,
                    20,
                )
                .expect("start command"),
            )
            .await
            .expect("start");
        store
            .prepare_taskflow_step(
                "step-run", "work", 1, &owner, &intent, &payload, "prepare", 21,
            )
            .await
            .expect("prepare");
        store
            .claim_taskflow_step(
                "step-run", "work", 1, &owner, &intent, &payload, "claim", 22,
            )
            .await
            .expect("claim");
        if reconcile {
            store
                .record_taskflow_step(
                    "step-run",
                    "work",
                    1,
                    &owner,
                    &intent,
                    &payload,
                    "unknown",
                    &Sha256Digest::for_bytes(b"unknown"),
                    TaskFlowStepObservation::Indeterminate,
                    23,
                )
                .await
                .expect("unknown projection");
        }
        let before = store
            .read_taskflow_step("step-run", "work", 1, &owner)
            .await
            .expect("read before")
            .expect("step");
        let sqlite_home = AbsolutePathBuf::from_absolute_path(fixture.layout.automation_root())
            .expect("sqlite home");
        let pool = SqliteConfig::from_sqlite_home(sqlite_home)
            .open_durable_evidence_pool(store.path())
            .await
            .expect("evidence pool");
        let terminal = Sha256Digest::for_bytes(b"provider-terminal");
        // Reproduce the crash after immutable provider evidence commits and
        // before the owning recovery path updates the step projection.
        sqlx::query(
            "INSERT INTO taskflow_effect_dispatch_attempts (
            owner_agent_id, run_id, step_id, attempt, intent_digest, payload_digest,
            binding_digest, destination_id, authority_epoch, grant_id,
            grant_nonce_digest, record_command_id, started_at_ms
        ) VALUES (?, 'step-run', 'work', 1, ?, ?, ?, 'provider:test', 1,
            'test-grant', ?, 'provider-record', 22)",
        )
        .bind(AGENT_ID)
        .bind(intent.as_str())
        .bind(payload.as_str())
        .bind(terminal.as_str())
        .bind(terminal.as_str())
        .execute(&pool)
        .await
        .expect("provider attempt");
        sqlx::query(
            "INSERT INTO taskflow_effect_dispatch_observations (
            owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, observed_at_ms
        ) VALUES (?, 'step-run', 'work', 1, ?, ?, 23)",
        )
        .bind(AGENT_ID)
        .bind(if reconcile {
            "indeterminate"
        } else {
            "succeeded"
        })
        .bind(if reconcile {
            intent.as_str()
        } else {
            terminal.as_str()
        })
        .execute(&pool)
        .await
        .expect("provider observation");
        if reconcile {
            sqlx::query("INSERT INTO taskflow_effect_dispatch_reconciliations (
                owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, observed_at_ms
            ) VALUES (?, 'step-run', 'work', 1, 'succeeded', ?, 24)")
                .bind(AGENT_ID).bind(terminal.as_str())
                .execute(&pool).await.expect("provider terminal reconciliation");
        }
        for (index, (receipt, succeeded)) in [
            (terminal.clone(), false),
            (Sha256Digest::for_bytes(b"different-receipt"), true),
        ]
        .into_iter()
        .enumerate()
        {
            let result = if reconcile {
                store
                    .reconcile_taskflow_step(
                        "step-run",
                        "work",
                        1,
                        &owner,
                        &intent,
                        &payload,
                        &format!("conflicting-{index}"),
                        &receipt,
                        if succeeded {
                            TaskFlowReconcileOutcome::Succeeded
                        } else {
                            TaskFlowReconcileOutcome::Failed
                        },
                        25,
                    )
                    .await
            } else {
                store
                    .record_taskflow_step(
                        "step-run",
                        "work",
                        1,
                        &owner,
                        &intent,
                        &payload,
                        &format!("conflicting-{index}"),
                        &receipt,
                        if succeeded {
                            TaskFlowStepObservation::Succeeded
                        } else {
                            TaskFlowStepObservation::Failed
                        },
                        25,
                    )
                    .await
            };
            assert!(matches!(
                result,
                Err(codex_hepta_automation::TaskFlowError::Conflict(_))
            ));
            assert_eq!(
                store
                    .read_taskflow_step("step-run", "work", 1, &owner)
                    .await
                    .expect("read unchanged")
                    .expect("step"),
                before
            );
        }
        let matched = if reconcile {
            store
                .reconcile_taskflow_step(
                    "step-run",
                    "work",
                    1,
                    &owner,
                    &intent,
                    &payload,
                    "matching",
                    &terminal,
                    TaskFlowReconcileOutcome::Succeeded,
                    26,
                )
                .await
        } else {
            store
                .record_taskflow_step(
                    "step-run",
                    "work",
                    1,
                    &owner,
                    &intent,
                    &payload,
                    "matching",
                    &terminal,
                    TaskFlowStepObservation::Succeeded,
                    26,
                )
                .await
        }
        .expect("matching provider terminal remains recoverable");
        assert_eq!(matched.receipt.receipt_digest, Some(terminal));
        pool.close().await;
        store.close().await;
    }
}
