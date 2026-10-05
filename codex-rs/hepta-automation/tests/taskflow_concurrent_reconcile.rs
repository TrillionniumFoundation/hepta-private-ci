#![allow(clippy::expect_used, reason = "regression fixtures fail loudly")]

use std::sync::Arc;

use codex_hepta_automation::AutomationSchedule;
use codex_hepta_automation::AutomationStore;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowCommandStatus;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowFence;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
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
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tokio::sync::Barrier;

#[derive(Clone, Copy)]
enum RecoveryProjection {
    Step,
    Run,
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn one_shot_step_reconcile_survives_same_store_timer_writer() {
    reconcile_with_timer_writer(RecoveryProjection::Step).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn one_shot_run_reconcile_survives_same_store_timer_writer() {
    reconcile_with_timer_writer(RecoveryProjection::Run).await;
}

async fn reconcile_with_timer_writer(projection: RecoveryProjection) {
    let temp = tempfile::tempdir().expect("temporary fleet");
    let root = temp.path().canonicalize().expect("canonical root");
    let fleet_root = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    let manifest = AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace, &fleet_root).expect("workspace binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let layout = registry.register(manifest).expect("register").layout;
    let store = AutomationStore::open(&layout)
        .await
        .expect("recovery store");
    let writer = AutomationStore::open(&layout).await.expect("timer store");
    assert_eq!(writer.path(), store.path());
    let fence = TaskFlowFence::new(
        agent,
        "recovery-owner",
        /*owner_epoch*/ 1,
        /*generation*/ 1,
        "recovery-fence",
    )
    .expect("fence");
    let definition = TaskFlowDefinition::new(
        "concurrent-recovery",
        /*version*/ 1,
        "effect",
        vec![
            TaskFlowNodeSpec::effect("effect", "matrix.send", "matrix-send-v1"),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("effect", "success"),
            TaskFlowEdgeSpec::new("effect", "failure"),
        ],
        vec!["matrix.send".to_owned()],
        Sha256Digest::for_bytes(b"recovery-policy"),
    )
    .expect("definition");
    store
        .register_taskflow_definition(&definition, &fence, /*registered_at_ms*/ 10)
        .await
        .expect("definition registered");
    store
        .create_taskflow_run(
            "run",
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread",
            /*created_at_ms*/ 10,
        )
        .await
        .expect("run created");
    let claimed = store
        .claim_taskflow_run(
            "run", &fence, /*now_ms*/ 20, /*lease_duration_ms*/ 1000,
        )
        .await
        .expect("run claimed");
    let started = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "run",
                "start",
                fence.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                /*now_ms*/ 20,
            )
            .expect("start command"),
        )
        .await
        .expect("running effect");
    let intent = Sha256Digest::for_bytes(b"intent");
    let payload = Sha256Digest::for_bytes(b"payload");
    store
        .prepare_taskflow_step(
            "run", "effect", /*attempt*/ 1, &fence, &intent, &payload, "prepare",
            /*now_ms*/ 21,
        )
        .await
        .expect("step prepared");
    store
        .claim_taskflow_step(
            "run", "effect", /*attempt*/ 1, &fence, &intent, &payload, "claim",
            /*now_ms*/ 22,
        )
        .await
        .expect("step claimed");
    store
        .record_taskflow_step(
            "run",
            "effect",
            /*attempt*/ 1,
            &fence,
            &intent,
            &payload,
            "unknown",
            &Sha256Digest::for_bytes(b"unknown receipt"),
            TaskFlowStepObservation::Indeterminate,
            /*now_ms*/ 23,
        )
        .await
        .expect("indeterminate step");

    let unknown = store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                "run",
                "unknown-run",
                fence.clone(),
                started.revision,
                TaskFlowTransition::Indeterminate {
                    reason: "provider-contact-uncertain".to_owned(),
                },
                /*now_ms*/ 23,
            )
            .expect("unknown command"),
        )
        .await
        .expect("indeterminate run");
    assert_eq!(unknown.state, TaskFlowRunState::Indeterminate);
    if matches!(projection, RecoveryProjection::Run) {
        // Full effect recovery settles the step before reconciling its run.
        store
            .reconcile_taskflow_step(
                "run",
                "effect",
                /*attempt*/ 1,
                &fence,
                &intent,
                &payload,
                "reconcile",
                &Sha256Digest::for_bytes(b"provider terminal receipt"),
                TaskFlowReconcileOutcome::Succeeded,
                /*now_ms*/ 24,
            )
            .await
            .expect("settle step first");
    }

    let start = Arc::new(Barrier::new(/*n*/ 2));
    let writer_start = Arc::clone(&start);
    // Exercise the actual timer owner and its fence on the SAME database,
    // rather than an artificial raw-SQL busy/snapshot example.
    let writing = tokio::spawn(async move {
        writer_start.wait().await;
        for _ in 0..64 {
            writer
                .create_task(&AutomationTaskDraft::new(
                    "019153a4-3088-7e03-a56a-9b1964f75ddd",
                    "concurrent timer creation",
                    AutomationSchedule::Once,
                    /*first_run_at_ms*/ 100,
                    /*created_at_ms*/ 24,
                ))
                .await
                .expect("unrelated timer creation");
        }
        writer.close().await;
    });
    start.wait().await;
    let terminal = Sha256Digest::for_bytes(b"provider terminal receipt");
    // Exactly one reconciliation attempt: no sleep, retry, or accepted error.
    match projection {
        RecoveryProjection::Step => {
            let reconciled = store
                .reconcile_taskflow_step(
                    "run",
                    "effect",
                    /*attempt*/ 1,
                    &fence,
                    &intent,
                    &payload,
                    "reconcile",
                    &terminal,
                    TaskFlowReconcileOutcome::Succeeded,
                    /*now_ms*/ 24,
                )
                .await;
            writing.await.expect("timer writer joined");
            let reconciled =
                reconciled.expect("single step reconcile must survive an unrelated writer");
            assert_eq!(reconciled.status, TaskFlowStepCommandStatus::Applied);
            assert_eq!(reconciled.receipt.state, TaskFlowStepState::Reconciled);
            assert_eq!(
                reconciled.receipt.final_outcome,
                Some(TaskFlowReconcileOutcome::Succeeded)
            );
            assert_eq!(reconciled.receipt.receipt_digest, Some(terminal));
            assert_eq!(reconciled.receipt.event_seq, 4);
            store.close().await;
            let reopened = AutomationStore::open(&layout).await.expect("reopen");
            let retained = reopened
                .read_taskflow_step("run", "effect", /*attempt*/ 1, &fence)
                .await
                .expect("read terminal")
                .expect("terminal remains");
            assert_eq!(retained, reconciled.receipt);
            reopened.close().await;
        }
        RecoveryProjection::Run => {
            let command = TaskFlowCommand::new(
                "run",
                "reconcile-run",
                fence,
                unknown.revision,
                TaskFlowTransition::Reconcile {
                    receipt_digest: terminal,
                    outcome: TaskFlowReconcileOutcome::Succeeded,
                },
                /*now_ms*/ 24,
            )
            .expect("reconciliation command");
            let reconciled = store.apply_taskflow_command(&command).await;
            writing.await.expect("timer writer joined");
            let reconciled =
                reconciled.expect("single run reconcile must survive an unrelated writer");
            assert_eq!(reconciled.status, TaskFlowCommandStatus::Applied);
            assert_eq!(reconciled.state, TaskFlowRunState::Succeeded);
            assert_eq!(reconciled.revision, unknown.revision + 1);
            let durable = store
                .taskflow_run("run")
                .await
                .expect("read reconciled run")
                .expect("run exists");
            store.close().await;
            let reopened = AutomationStore::open(&layout).await.expect("reopen");
            assert_eq!(
                reopened
                    .taskflow_run("run")
                    .await
                    .expect("read after reopen"),
                Some(durable)
            );
            reopened.close().await;
        }
    }
}
