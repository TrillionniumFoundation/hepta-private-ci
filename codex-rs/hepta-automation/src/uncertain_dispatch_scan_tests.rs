use super::*;
use crate::AutomationSchedule;
use crate::AutomationTaskDraft;
use pretty_assertions::assert_eq;

async fn unknown(store: &AutomationStore) -> AutomationDispatchUncertainty {
    let task = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "preserve this exact uncertain effect",
        AutomationSchedule::Once,
        /*first_run_at_ms*/ 100,
        /*created_at_ms*/ 1,
    );
    store.create_task(&task).await.expect("create task");
    let lease = store
        .claim_due(
            /*now_ms*/ 100, /*generation*/ 1, /*lease_duration_ms*/ 60_000,
        )
        .await
        .expect("claim")
        .expect("due occurrence");
    assert_eq!(lease.task.task_id, task.task_id);
    let occurrence = store
        .materialize_occurrence(&lease, /*now_ms*/ 100)
        .await
        .expect("occurrence");
    store
        .prepare_occurrence_taskflow(
            &occurrence,
            &lease,
            /*now_ms*/ 100,
            /*lease_duration_ms*/ 60_000,
        )
        .await
        .expect("step");
    store
        .record_dispatch_uncertain(&lease, /*observed_at_ms*/ 101)
        .await
        .expect("unknown dispatch");
    store
        .uncertain_dispatches(/*limit*/ 1_024)
        .await
        .expect("read evidence")
        .into_iter()
        .find(|uncertain| uncertain.task_id == task.task_id)
        .expect("exact unknown identity")
}

#[tokio::test]
async fn timeout_priority_advances_without_rewriting_unknown_evidence() {
    let (_temp, layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let first = unknown(&store).await;
    let second = unknown(&store).await;
    let before = store
        .uncertain_dispatches(/*limit*/ 1_024)
        .await
        .expect("before");
    let mut scan = store.uncertain_dispatch_scan();
    assert_eq!(
        store
            .next_uncertain_dispatch(&mut scan)
            .await
            .expect("first"),
        Some(first.clone())
    );
    // Simulate the caller's failed/timed-out read-only observation. No owner
    // receipt or original evidence timestamp is changed to rotate priority.
    assert_eq!(
        store
            .next_uncertain_dispatch(&mut scan)
            .await
            .expect("second"),
        Some(second)
    );
    assert_eq!(
        store
            .next_uncertain_dispatch(&mut scan)
            .await
            .expect("wrap"),
        Some(first)
    );
    assert_eq!(
        store
            .uncertain_dispatches(/*limit*/ 1_024)
            .await
            .expect("after"),
        before
    );
    store.close().await;
    let reopened = AutomationStore::open(&layout).await.expect("reopen");
    assert_eq!(
        reopened
            .uncertain_dispatches(/*limit*/ 1_024)
            .await
            .expect("durable"),
        before
    );
    assert_eq!(
        reopened.next_uncertain_dispatch(&mut scan).await,
        Err(AutomationError::AccessDenied)
    );
    reopened.close().await;
}

#[tokio::test]
async fn high_water_closes_even_when_new_unknown_work_keeps_arriving() {
    let (_temp, _layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let first = unknown(&store).await;
    let second = unknown(&store).await;
    let mut scan = store.uncertain_dispatch_scan();
    assert_eq!(
        store
            .next_uncertain_dispatch(&mut scan)
            .await
            .expect("first"),
        Some(first.clone())
    );
    let _later = unknown(&store).await;
    assert_eq!(
        store
            .next_uncertain_dispatch(&mut scan)
            .await
            .expect("second"),
        Some(second)
    );
    assert_eq!(
        store
            .next_uncertain_dispatch(&mut scan)
            .await
            .expect("finite wrap"),
        Some(first)
    );
    store.close().await;
}

#[tokio::test]
async fn store_clones_share_scan_identity_but_distinct_opens_do_not() {
    let (_temp, _layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let expected = unknown(&store).await;
    let mut scan = store.uncertain_dispatch_scan();
    let clone = store.clone();
    assert_eq!(
        clone
            .next_uncertain_dispatch(&mut scan)
            .await
            .expect("same instance"),
        Some(expected)
    );
    let (_other_temp, _other_layout, other, _other_fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    assert_eq!(
        other.next_uncertain_dispatch(&mut scan).await,
        Err(AutomationError::AccessDenied)
    );
    // Rejection must not move or reset the legitimate cursor.
    assert!(
        clone
            .next_uncertain_dispatch(&mut scan)
            .await
            .expect("original owner remains usable")
            .is_some()
    );
    other.close().await;
    store.close().await;
}
