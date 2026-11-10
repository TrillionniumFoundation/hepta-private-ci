use pretty_assertions::assert_eq;

use super::*;
use crate::circuit_runtime_tests::definition;
use crate::circuit_runtime_tests::digest;
use crate::circuit_runtime_tests::fence;
use crate::circuit_runtime_tests::start;

async fn rows(store: &AutomationStore) -> (i64, i64, i64) {
    let definitions = sqlx::query_scalar("SELECT COUNT(*) FROM circuit_v2_definitions")
        .fetch_one(store.taskflow_pool())
        .await
        .expect("definitions");
    let runs = sqlx::query_scalar("SELECT COUNT(*) FROM circuit_v2_runs")
        .fetch_one(store.taskflow_pool())
        .await
        .expect("runs");
    let events = sqlx::query_scalar("SELECT COUNT(*) FROM circuit_v2_events")
        .fetch_one(store.taskflow_pool())
        .await
        .expect("events");
    (definitions, runs, events)
}

#[tokio::test]
async fn task_readback_never_initializes_missing_or_repairs_lost_history() {
    let directory = tempfile::tempdir().expect("private owner fixture");
    let fence = fence(/*generation*/ 1);
    let store = AutomationStore::open_root(
        directory
            .path()
            .canonicalize()
            .expect("canonical private owner")
            .join("automation"),
        fence.owner_agent_id.clone(),
    )
    .await
    .expect("original owner");
    assert_eq!(
        store
            .read_bounded_circuit_task(&definition(), &start(), &fence)
            .await
            .expect("missing read"),
        None,
    );
    assert_eq!(rows(&store).await, (0, 0, 0));
    store
        .create_bounded_circuit_run(&definition(), &start(), &fence)
        .await
        .expect("original create");
    let original = store
        .bounded_circuit_committed_trace("run-1")
        .await
        .expect("original history");
    assert_eq!(
        store
            .read_bounded_circuit_task(&definition(), &start(), &fence)
            .await
            .expect("bound read"),
        original,
    );
    let mut changed = start();
    changed.input_digest = digest("replacement task input");
    assert!(matches!(
        store
            .read_bounded_circuit_task(&definition(), &changed, &fence)
            .await,
        Err(TaskFlowError::Conflict(_)),
    ));
    assert_eq!(rows(&store).await, (1, 1, 1));

    // Fault injection bypasses only this fixture's immutable-delete trigger,
    // modelling lost storage bytes rather than an allowed runtime mutation.
    sqlx::query("DROP TRIGGER circuit_v2_event_no_delete")
        .execute(store.taskflow_pool())
        .await
        .expect("inject event storage loss");
    sqlx::query("DELETE FROM circuit_v2_events WHERE run_id = ?")
        .bind("run-1")
        .execute(store.taskflow_pool())
        .await
        .expect("simulate lost history");
    assert!(matches!(
        store
            .read_bounded_circuit_task(&definition(), &start(), &fence)
            .await,
        Err(TaskFlowError::Corrupt(_)),
    ));
    assert_eq!(
        rows(&store).await,
        (1, 1, 0),
        "readback cannot repair the missing creation event"
    );
    sqlx::query("DROP TRIGGER circuit_v2_run_no_delete")
        .execute(store.taskflow_pool())
        .await
        .expect("inject projection storage loss");
    sqlx::query("DELETE FROM circuit_v2_runs WHERE run_id = ?")
        .bind("run-1")
        .execute(store.taskflow_pool())
        .await
        .expect("simulate lost projection");
    assert_eq!(
        store
            .read_bounded_circuit_task(&definition(), &start(), &fence)
            .await
            .expect("missing read"),
        None,
    );
    assert_eq!(
        rows(&store).await,
        (1, 0, 0),
        "readback cannot recreate genesis"
    );
    store.close().await;
}
