use pretty_assertions::assert_eq;

use crate::circuit_runtime_tests::completion;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;
use crate::*;

#[tokio::test]
async fn stopped_circuit_blocks_drain_after_reopen_until_original_work_settles() {
    let directory = tempfile::tempdir().expect("private owner");
    let canonical_directory = directory
        .path()
        .canonicalize()
        .expect("canonical private owner");
    let root = canonical_directory.join("automation");
    let writer = fence(/*generation*/ 1);
    let store = AutomationStore::open_root(root.clone(), writer.owner_agent_id.clone())
        .await
        .expect("open");
    assert_eq!(store.circuit_drain_blockers().await.expect("empty"), 0);
    let created = store
        .create_bounded_circuit_run(&definition(), &start(), &writer)
        .await
        .expect("create");
    assert_eq!(store.circuit_drain_blockers().await.expect("ready"), 1);
    let active = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: "run-1".into(),
            command_id: "advance".into(),
            fence: writer.clone(),
            expected_revision: created.run.revision(),
            now_ms: 11,
            event: CircuitEventV2::Advance { quantum: 1 },
        })
        .await
        .expect("original dispatch");
    let stopped = store
        .apply_bounded_circuit_command(&CircuitCommandV2 {
            run_id: "run-1".into(),
            command_id: "cancel".into(),
            fence: writer.clone(),
            expected_revision: active.run.revision(),
            now_ms: 12,
            event: CircuitEventV2::Cancel,
        })
        .await
        .expect("stop cannot erase original work");
    store.close().await;
    let reopened = AutomationStore::open_root(root, writer.owner_agent_id.clone())
        .await
        .expect("reopen");
    assert_eq!(reopened.circuit_drain_blockers().await.expect("pending"), 1);
    let settle = CircuitCommandV2 {
        run_id: "run-1".into(),
        command_id: "original-receipt".into(),
        fence: writer,
        expected_revision: stopped.run.revision(),
        now_ms: 13,
        event: CircuitEventV2::Complete {
            completion: completion(&active.dispatches[0], &["done"], "original-result"),
        },
    };
    reopened
        .apply_bounded_circuit_command(&settle)
        .await
        .expect("settle only original result");
    let replay = reopened
        .apply_bounded_circuit_command(&settle)
        .await
        .expect("lost acknowledgement replay");
    assert_eq!(
        (replay.status, replay.dispatches, replay.run.unresolved()),
        (CircuitCommandStatusV2::AlreadyApplied, vec![], 0)
    );
    assert_eq!(reopened.circuit_drain_blockers().await.expect("settled"), 0);
    sqlx::query("UPDATE circuit_v2_runs SET state_digest = ? WHERE run_id = ?")
        .bind("ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff")
        .bind("run-1")
        .execute(reopened.taskflow_pool())
        .await
        .expect("corruption fixture");
    assert!(matches!(
        reopened.circuit_drain_blockers().await,
        Err(TaskFlowError::Corrupt(_))
    ));
    reopened.close().await;
}

#[tokio::test]
async fn drain_observation_includes_runs_beyond_the_first_page() {
    let directory = tempfile::tempdir().expect("private owner");
    let canonical_directory = directory
        .path()
        .canonicalize()
        .expect("canonical private owner");
    let writer = fence(/*generation*/ 1);
    let store = AutomationStore::open_root(
        canonical_directory.join("automation"),
        writer.owner_agent_id.clone(),
    )
    .await
    .expect("open");
    for index in 0..129 {
        let mut request = start();
        request.run_id = format!("run-{index:03}");
        store
            .create_bounded_circuit_run(&definition(), &request, &writer)
            .await
            .expect("create distinct original run");
    }
    assert_eq!(
        store.circuit_drain_blockers().await.expect("all pages"),
        129
    );
    // Corrupt projections must be visited even when their ID is empty. The
    // runtime constructor rejects this ID, but drain verifies stored history.
    sqlx::query(
        "INSERT INTO circuit_v2_runs
         SELECT owner_agent_id, '', definition_digest, revision, state_json,
                state_digest, last_event_digest FROM circuit_v2_runs WHERE run_id = ?",
    )
    .bind("run-000")
    .execute(store.taskflow_pool())
    .await
    .expect("empty projection fixture");
    assert!(matches!(
        store.circuit_drain_blockers().await,
        Err(TaskFlowError::Corrupt(_))
    ));
    store.close().await;
}
