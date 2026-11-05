use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use crate::*;
use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;

async fn store() -> (tempfile::TempDir, AutomationStore) {
    let directory = tempfile::tempdir().expect("private temporary owner");
    let store = AutomationStore::open_root(directory.path().join("automation"), fence(/*generation*/ 1).owner_agent_id)
        .await.expect("normal AutomationStore open/migrations");
    (directory, store)
}

fn command(run: &CircuitRunV2, id: &str, event: CircuitEventV2) -> CircuitCommandV2 {
    CircuitCommandV2 {
        run_id: run.run_id().to_string(), command_id: id.to_string(), fence: fence(/*generation*/ 1),
        expected_revision: run.revision(), now_ms: 11 + run.revision(), event,
    }
}

#[tokio::test]
async fn durable_dispatch_is_idempotent_and_reopens_without_reissuing_work() {
    let (directory, store) = store().await;
    let created = store.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1)).await.expect("create");
    let created_again = store.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1)).await.expect("idempotent create");
    assert_eq!((created_again.status, &created_again.run), (CircuitCommandStatusV2::AlreadyApplied, &created.run));
    let advance = command(&created.run, "advance-1", CircuitEventV2::Advance { quantum: 1 });
    let applied = store.apply_bounded_circuit_command(&advance).await.expect("commit before dispatch");
    assert_eq!(applied.dispatches.len(), 1);
    let duplicate = store.apply_bounded_circuit_command(&advance).await.expect("same command bytes");
    assert_eq!(duplicate, CircuitCommandReceiptV2 {
        status: CircuitCommandStatusV2::AlreadyApplied, run: applied.run.clone(), dispatches: vec![],
    });
    let mut changed = advance;
    changed.event = CircuitEventV2::Advance { quantum: 2 };
    assert!(matches!(store.apply_bounded_circuit_command(&changed).await, Err(TaskFlowError::Conflict(_))));
    let path = store.path().to_path_buf();
    let owner = store.owner_agent_id().clone();
    store.close().await;
    drop(store);
    let reopened = AutomationStore::open_root(path.parent().expect("root").to_path_buf(), owner).await.expect("new pooled process state");
    assert_eq!(reopened.bounded_circuit_run("run-1").await.expect("verified replay"), Some(applied.run));
    assert!(matches!(reopened.apply_bounded_circuit_command(&changed).await, Err(TaskFlowError::Conflict(_))));
    reopened.close().await;
    drop(directory);
}

#[tokio::test]
async fn successor_fences_old_writer_and_reconciles_original_invocation_after_ack_loss() {
    let (_directory, store) = store().await;
    let created = store.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1)).await.expect("create");
    let applied = store.apply_bounded_circuit_command(&command(&created.run, "advance", CircuitEventV2::Advance { quantum: 1 }))
        .await.expect("dispatch");
    let claim = CircuitLeaseClaimV2 {
        run_id: "run-1".to_string(), command_id: "successor".to_string(),
        fence: fence(/*generation*/ 2), expected_revision: applied.run.revision(), now_ms: 110, lease_duration_ms: 100,
    };
    let successor = store.claim_bounded_circuit_run(&claim).await.expect("expired owner takeover");
    assert_eq!(successor.run.activations()[&applied.dispatches[0].activation_id].status, CircuitActivationStatusV2::Indeterminate);
    assert_eq!(successor.run.budget().reserved(), 5);
    assert!(successor.dispatches.is_empty());
    let mut old = CircuitCommandV2 {
        run_id: "run-1".to_string(), command_id: "terminal-receipt".to_string(),
        fence: fence(/*generation*/ 1), expected_revision: successor.run.revision(), now_ms: 111,
        event: CircuitEventV2::Reconcile { completion: completion(&applied.dispatches[0], &["done"], "actual-result") },
    };
    assert!(matches!(store.apply_bounded_circuit_command(&old).await, Err(TaskFlowError::StaleFence)));
    old.fence = fence(/*generation*/ 2);
    let completed = store.apply_bounded_circuit_command(&old).await.expect("new owner observes original work");
    let finish = CircuitCommandV2 {
        run_id: "run-1".to_string(), command_id: "exit".to_string(), fence: fence(/*generation*/ 2),
        expected_revision: completed.run.revision(), now_ms: 112, event: CircuitEventV2::Advance { quantum: 1 },
    };
    let finished = store.apply_bounded_circuit_command(&finish).await.expect("exit");
    assert_eq!((finished.run.outcome(), finished.run.budget().spent(), finished.run.budget().reserved()),
        (Some(CircuitExitV2::Succeeded), 3, 0));
    assert_eq!(store.bounded_circuit_run("run-1").await.expect("full replay"), Some(finished.run));
    store.close().await;
}

#[tokio::test]
async fn concurrent_owner_connections_commit_only_one_revision_and_one_dispatch() {
    let (_directory, store) = store().await;
    let created = store.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1)).await.expect("create");
    let other = AutomationStore::open_root(store.path().parent().expect("root").to_path_buf(), store.owner_agent_id().clone())
        .await.expect("independent connection pool");
    let left = command(&created.run, "left", CircuitEventV2::Advance { quantum: 1 });
    let right = command(&created.run, "right", CircuitEventV2::Advance { quantum: 1 });
    let (a, b) = tokio::join!(store.apply_bounded_circuit_command(&left), other.apply_bounded_circuit_command(&right));
    assert_eq!(usize::from(a.is_ok()) + usize::from(b.is_ok()), 1);
    let run = store.bounded_circuit_run("run-1").await.expect("read").expect("run");
    assert_eq!((run.revision(), run.unresolved(), run.budget().reserved()), (1, 1, 5));
    store.close().await;
    other.close().await;
}

#[tokio::test]
async fn scope_version_and_owner_mismatch_reject_without_mutating_existing_run() {
    let (_directory, store) = store().await;
    let created = store.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1)).await.expect("create");
    let mut changed_start = start();
    changed_start.scope_digest = digest("other-principal");
    assert!(store.create_bounded_circuit_run(&definition(), &changed_start, &fence(/*generation*/ 1)).await.is_err());
    let mut changed_definition = definition();
    changed_definition.parameter_bundle_digest = digest("changed-bundle");
    assert!(store.register_bounded_circuit_definition(&changed_definition, &fence(/*generation*/ 1)).await.is_err());
    changed_definition.version = 2;
    changed_definition.predecessor_digest = Some(digest("wrong-predecessor"));
    assert!(store.register_bounded_circuit_definition(&changed_definition, &fence(/*generation*/ 1)).await.is_err());
    changed_definition.predecessor_digest = Some(definition().definition_digest().expect("original digest"));
    store.register_bounded_circuit_definition(&changed_definition, &fence(/*generation*/ 1)).await.expect("immutable successor");
    let mut foreign = fence(/*generation*/ 1);
    foreign.owner_agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("different agent");
    assert!(matches!(store.create_bounded_circuit_run(&definition(), &start(), &foreign).await, Err(TaskFlowError::StaleFence)));
    assert_eq!(store.bounded_circuit_run("run-1").await.expect("old run stays frozen"), Some(created.run));
    store.close().await;
}

#[tokio::test]
async fn separate_agent_partitions_can_use_the_same_run_id_without_state_bleed() {
    let (_first_directory, first) = store().await;
    let second_directory = tempfile::tempdir().expect("second private owner");
    let mut second_fence = fence(/*generation*/ 1);
    second_fence.owner_agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("second agent");
    let second = AutomationStore::open_root(second_directory.path().join("automation"), second_fence.owner_agent_id.clone())
        .await.expect("second store");
    let initial = first.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1)).await.expect("first run");
    let mut second_start = start();
    second_start.input_digest = digest("second-agent-input");
    let independent = second.create_bounded_circuit_run(&definition(), &second_start, &second_fence).await.expect("same run ID, other owner");
    first.apply_bounded_circuit_command(&command(&initial.run, "advance", CircuitEventV2::Advance { quantum: 1 }))
        .await.expect("first advances");
    assert_eq!(second.bounded_circuit_run("run-1").await.expect("second stays unchanged"), Some(independent.run));
    let wrong_root = AutomationStore::open_root(first.path().parent().expect("root").to_path_buf(), second_fence.owner_agent_id).await;
    assert!(wrong_root.is_err());
    first.close().await;
    second.close().await;
}

#[tokio::test]
async fn corrupt_projection_and_removed_event_tail_are_never_recovered_as_success() {
    for fault in ["projection", "tail"] {
        let (_directory, store) = store().await;
        let created = store.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1)).await.expect("create");
        store.apply_bounded_circuit_command(&command(&created.run, "advance", CircuitEventV2::Advance { quantum: 1 }))
            .await.expect("advance");
        assert!(sqlx::query("DELETE FROM circuit_v2_events WHERE seq = 1").execute(store.taskflow_pool()).await.is_err(),
            "append-only trigger");
        match fault {
            "projection" => {
                sqlx::query("UPDATE circuit_v2_runs SET state_json = '{}' WHERE run_id = 'run-1'")
                    .execute(store.taskflow_pool()).await.expect("projection corruption");
            }
            "tail" => {
                sqlx::query("DROP TRIGGER circuit_v2_event_no_delete")
                    .execute(store.taskflow_pool()).await.expect("fault-inject storage tampering");
                sqlx::query("DELETE FROM circuit_v2_events WHERE seq = 1")
                    .execute(store.taskflow_pool()).await.expect("remove last event only");
            }
            _ => unreachable!(),
        }
        assert!(matches!(store.bounded_circuit_run("run-1").await, Err(TaskFlowError::Corrupt(_))));
        assert!(store.apply_bounded_circuit_command(&command(&created.run, "try-continue", CircuitEventV2::Advance { quantum: 1 }))
            .await.is_err());
        store.close().await;
    }
}

#[tokio::test]
async fn bounded_circuit_migration_coexists_with_existing_v1_definition() {
    let (_directory, store) = store().await;
    let v1 = NeuralCircuitCandidateV1::new("legacy-dag", /*version*/ 1, /*predecessor_digest*/ None, "work",
        vec![CircuitNodeV1::new("work", CircuitNodeRoleV1::Decide),
            CircuitNodeV1::new("success", CircuitNodeRoleV1::ExitSuccess),
            CircuitNodeV1::new("failure", CircuitNodeRoleV1::ExitFailure)],
        vec![CircuitEdgeV1::new("work", "success"), CircuitEdgeV1::new("work", "failure")],
        vec![], digest("route"), digest("bundle"), digest("resources")).expect("V1 candidate");
    let (legacy, _) = v1.compile_taskflow().expect("compile V1");
    store.register_taskflow_definition(&legacy, &fence(/*generation*/ 1), /*registered_at_ms*/ 10)
        .await.expect("V1 register");
    let before = store.taskflow_definition("circuit:legacy-dag", /*version*/ 1).await.expect("V1 read");
    store.create_bounded_circuit_run(&definition(), &start(), &fence(/*generation*/ 1)).await.expect("V2 same owner");
    assert_eq!(store.taskflow_definition("circuit:legacy-dag", /*version*/ 1).await.expect("unchanged V1"), before);
    store.close().await;
}
