use super::*;
use crate::AutomationSchedule;
use crate::AutomationTaskDraft;
use codex_hepta_contracts::AgentId;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;

async fn prepared(
    timer_lease_ms: u64,
    run_lease_ms: u64,
) -> (
    tempfile::TempDir,
    AutomationStore,
    AutomationLease,
    AutomationQueueContact,
) {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().canonicalize().unwrap().join("automation");
    let store = AutomationStore::open_root(
        root,
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap(),
    )
    .await
    .unwrap();
    let task = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "exact prepared queue request",
        AutomationSchedule::Once,
        /*first_run_at_ms*/ 100,
        /*created_at_ms*/ 1,
    );
    store.create_task(&task).await.unwrap();
    let lease = store
        .claim_due(/*now_ms*/ 100, /*generation*/ 1, timer_lease_ms)
        .await
        .unwrap()
        .unwrap();
    let occurrence = store
        .materialize_occurrence(&lease, /*now_ms*/ 100)
        .await
        .unwrap();
    store
        .prepare_occurrence_taskflow(&occurrence, &lease, /*now_ms*/ 100, run_lease_ms)
        .await
        .unwrap();
    store
        .record_dispatch_uncertain(&lease, /*observed_at_ms*/ 100)
        .await
        .unwrap();
    let contact = AutomationQueueContact::new(
        store.clone(),
        lease.clone(),
        /*tick_at_ms*/ 100,
        Instant::now(),
    );
    (temp, store, lease, contact)
}

#[tokio::test]
async fn contact_checks_both_leases_after_connection_wait_without_erasing_uncertainty() {
    for (timer_lease_ms, run_lease_ms) in [(10, 1000), (1000, 10)] {
        let (_temp, store, lease, contact) = prepared(timer_lease_ms, run_lease_ms).await;
        let before = store.uncertain_dispatches(/*limit*/ 1).await.unwrap();
        tokio::time::sleep(Duration::from_millis(/*millis*/ 25)).await;
        assert_eq!(
            contact.verify(&lease.admission()).await,
            Err(AutomationError::Conflict)
        );
        assert_eq!(
            store.uncertain_dispatches(/*limit*/ 1).await.unwrap(),
            before
        );
        assert!(
            store
                .claim_due(
                    /*now_ms*/ 2000, /*generation*/ 2, /*lease_duration_ms*/ 1000
                )
                .await
                .unwrap()
                .is_none()
        );
        store.close().await;
    }
}

#[tokio::test]
async fn contact_checks_elapsed_time_after_its_writer_wait() {
    let (_temp, store, lease, contact) =
        prepared(/*timer_lease_ms*/ 10, /*run_lease_ms*/ 1000).await;
    let before = store.uncertain_dispatches(/*limit*/ 1).await.unwrap();
    let root = store.path().parent().unwrap().to_path_buf();
    let blocker = SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(root).unwrap())
        .open_durable_evidence_pool(store.path())
        .await
        .unwrap();
    let reservation = blocker.begin_with("BEGIN IMMEDIATE").await.unwrap();
    let admission = lease.admission();
    let verification = contact.verify(&admission);
    tokio::pin!(verification);
    tokio::select! {
        biased;
        result = &mut verification => panic!("writer must block contact check: {result:?}"),
        () = tokio::time::sleep(Duration::from_millis(/*millis*/ 25)) => {}
    }
    reservation.commit().await.unwrap();
    assert_eq!(verification.await, Err(AutomationError::Conflict));
    assert_eq!(
        store.uncertain_dispatches(/*limit*/ 1).await.unwrap(),
        before
    );
    blocker.close().await;
    store.close().await;
}

#[tokio::test]
async fn cancelled_or_substituted_admission_cannot_reach_contact() {
    let (_temp, store, lease, contact) =
        prepared(/*timer_lease_ms*/ 30_000, /*run_lease_ms*/ 30_000).await;
    let before = store.uncertain_dispatches(/*limit*/ 1).await.unwrap();
    store
        .cancel_task(lease.task.task_id, /*now_ms*/ 101)
        .await
        .unwrap();
    assert_eq!(
        contact.verify(&lease.admission()).await,
        Err(AutomationError::Conflict)
    );
    assert_eq!(
        store.uncertain_dispatches(/*limit*/ 1).await.unwrap(),
        before
    );
    store.close().await;

    let (_temp, store, lease, contact) =
        prepared(/*timer_lease_ms*/ 30_000, /*run_lease_ms*/ 30_000).await;
    let before = store.uncertain_dispatches(/*limit*/ 1).await.unwrap();
    let mut replaced = lease.admission();
    replaced.prompt.push_str(" substituted");
    assert_eq!(
        contact.verify(&replaced).await,
        Err(AutomationError::AccessDenied)
    );
    assert_eq!(
        store.uncertain_dispatches(/*limit*/ 1).await.unwrap(),
        before
    );
    store.close().await;
}

#[tokio::test]
async fn live_exact_contact_preserves_the_same_durable_intent() {
    let (_temp, store, lease, contact) =
        prepared(/*timer_lease_ms*/ 30_000, /*run_lease_ms*/ 30_000).await;
    let before = store.uncertain_dispatches(/*limit*/ 1).await.unwrap();
    contact.verify(&lease.admission()).await.unwrap();
    assert_eq!(
        store.uncertain_dispatches(/*limit*/ 1).await.unwrap(),
        before
    );
    store.close().await;
}

#[tokio::test]
async fn host_readiness_is_checked_after_writer_wait_and_before_final_lease_sample() {
    let (_temp, store, lease, contact) =
        prepared(/*timer_lease_ms*/ 30_000, /*run_lease_ms*/ 30_000).await;
    let before = store.uncertain_dispatches(/*limit*/ 1).await.unwrap();
    let root = store.path().parent().unwrap().to_path_buf();
    let blocker = SqliteConfig::from_sqlite_home(AbsolutePathBuf::try_from(root).unwrap())
        .open_durable_evidence_pool(store.path())
        .await
        .unwrap();
    let reservation = blocker.begin_with("BEGIN IMMEDIATE").await.unwrap();
    let live = Arc::new(AtomicBool::new(/*v*/ true));
    let current = Arc::clone(&live);
    let admission = lease.admission();
    let verification = contact.verify_before_contact(&admission, move || {
        if current.load(Ordering::SeqCst) {
            Ok(())
        } else {
            Err(AutomationError::AccessDenied)
        }
    });
    tokio::pin!(verification);
    tokio::select! {
        biased;
        result = &mut verification => panic!("writer must block readiness check: {result:?}"),
        () = tokio::time::sleep(Duration::from_millis(/*millis*/ 25)) => {}
    }
    live.store(/*val*/ false, Ordering::SeqCst);
    reservation.commit().await.unwrap();
    assert_eq!(verification.await, Err(AutomationError::AccessDenied));
    assert_eq!(
        store.uncertain_dispatches(/*limit*/ 1).await.unwrap(),
        before
    );
    blocker.close().await;
    store.close().await;

    let (_temp, store, lease, contact) =
        prepared(/*timer_lease_ms*/ 10, /*run_lease_ms*/ 1000).await;
    let before = store.uncertain_dispatches(/*limit*/ 1).await.unwrap();
    let result = contact
        .verify_before_contact(&lease.admission(), || {
            // Model a bounded synchronous generation/readiness lock wait.
            std::thread::sleep(Duration::from_millis(/*millis*/ 25));
            Ok(())
        })
        .await;
    assert_eq!(result, Err(AutomationError::Conflict));
    assert_eq!(
        store.uncertain_dispatches(/*limit*/ 1).await.unwrap(),
        before
    );
    store.close().await;
}
