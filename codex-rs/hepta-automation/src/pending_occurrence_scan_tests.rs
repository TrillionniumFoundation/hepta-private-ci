use super::*;
use crate::AutomationOccurrenceTerminalState;
use pretty_assertions::assert_eq;

async fn admitted(store: &AutomationStore, now_ms: u64) -> AutomationOccurrenceWork {
    let task = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "retained historical admission",
        AutomationSchedule::Once,
        now_ms,
        /*created_at_ms*/ 1,
    );
    store.create_task(&task).await.expect("task");
    let lease = store
        .claim_due(
            now_ms, /*generation*/ 1, /*lease_duration_ms*/ 60_000,
        )
        .await
        .expect("claim")
        .expect("due");
    let occurrence = store
        .materialize_occurrence(&lease, now_ms)
        .await
        .expect("occurrence");
    store
        .prepare_occurrence_taskflow(
            &occurrence,
            &lease,
            now_ms,
            /*lease_duration_ms*/ 60_000,
        )
        .await
        .expect("outbox");
    store
        .record_dispatch_uncertain(&lease, now_ms)
        .await
        .expect("unknown before contact");
    store
        .record_occurrence_admitted(
            &lease,
            &AutomationQueueReceipt {
                queued_submission_id: format!("existing:{}", task.task_id),
                client_user_message_id: lease.client_user_message_id.clone(),
            },
            now_ms + 1,
        )
        .await
        .expect("admitted");
    store
        .pending_occurrence_work_for(task.task_id, lease.occurrence)
        .await
        .expect("exact pending")
        .expect("work")
}

#[tokio::test]
async fn pending_scan_rotates_without_touching_evidence_and_reopen_needs_new_cursor() {
    let (_temp, layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let first = admitted(&store, /*now_ms*/ 100).await;
    let second = admitted(&store, /*now_ms*/ 200).await;
    let before = store
        .pending_occurrence_work(/*limit*/ 10)
        .await
        .expect("snapshot");
    let mut scan = store.pending_occurrence_scan();
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("first"),
        Some(first.clone())
    );
    assert_eq!(
        store
            .clone()
            .next_pending_occurrence(&mut scan)
            .await
            .expect("same live owner clone"),
        Some(second)
    );
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("finite wrap"),
        Some(first.clone())
    );
    assert_eq!(
        store
            .pending_occurrence_work(/*limit*/ 10)
            .await
            .expect("after"),
        before
    );
    let saved_position = format!("{scan:?}");
    store.close().await;
    assert!(store.next_pending_occurrence(&mut scan).await.is_err());
    assert_eq!(
        format!("{scan:?}"),
        saved_position,
        "failed snapshot must not advance progress"
    );
    let reopened = AutomationStore::open(&layout).await.expect("reopen");
    assert_eq!(
        reopened.next_pending_occurrence(&mut scan).await,
        Err(AutomationError::AccessDenied)
    );
    let mut restarted = reopened.pending_occurrence_scan();
    assert_eq!(
        reopened
            .next_pending_occurrence(&mut restarted)
            .await
            .expect("fresh cursor"),
        Some(first)
    );
    assert_eq!(
        reopened
            .pending_occurrence_work(/*limit*/ 10)
            .await
            .expect("retained evidence"),
        before
    );
    reopened.close().await;
}

#[tokio::test]
async fn pending_high_water_closes_while_new_work_arrives() {
    let (_temp, _layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let first = admitted(&store, /*now_ms*/ 100).await;
    let second = admitted(&store, /*now_ms*/ 200).await;
    let mut scan = store.pending_occurrence_scan();
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("first"),
        Some(first.clone())
    );
    let third = admitted(&store, /*now_ms*/ 300).await;
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("captured endpoint"),
        Some(second.clone())
    );
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("new finite epoch"),
        Some(first)
    );
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("second"),
        Some(second)
    );
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("new work eventually visible"),
        Some(third)
    );
    store.close().await;
}

#[tokio::test]
async fn exact_pending_lookup_reaches_beyond_1024_older_occurrences() {
    let (_temp, _layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    for index in 0..1_024 {
        admitted(&store, 100 + index).await;
    }
    let target = admitted(&store, /*now_ms*/ 2_000).await;
    let first_page = store
        .pending_occurrence_work(/*limit*/ 1_024)
        .await
        .expect("legacy bounded list");
    assert_eq!(first_page.len(), 1_024);
    assert!(
        !first_page
            .iter()
            .any(|work| work.occurrence.task_id == target.occurrence.task_id)
    );
    assert_eq!(
        store
            .pending_occurrence_work_for(target.occurrence.task_id, target.occurrence.occurrence)
            .await
            .expect("exact identity"),
        Some(target)
    );
    assert_eq!(
        store
            .pending_occurrence_work(/*limit*/ 1_024)
            .await
            .expect("unchanged frontier"),
        first_page
    );
    store.close().await;
}

#[tokio::test]
async fn exact_pending_lookup_excludes_terminal_and_unadmitted_claims() {
    let (_temp, _layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let work = admitted(&store, /*now_ms*/ 100).await;
    let digest = Sha256Digest::for_bytes(b"actual terminal observation fixture");
    store
        .ensure_admitted_taskflow_uncertainty(&work, /*now_ms*/ 102)
        .await
        .expect("uncertainty");
    store
        .reconcile_occurrence_taskflow_terminal_with_recovery(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &digest,
            /*now_ms*/ 103,
            /*recovery_generation*/ 1,
            /*recovery_lease_ms*/ 30_000,
        )
        .await
        .expect("terminal TaskFlow");
    store
        .complete_occurrence(
            work.occurrence.task_id,
            work.occurrence.occurrence,
            AutomationOccurrenceTerminalState::Succeeded,
            &digest,
            /*completed_at_ms*/ 103,
        )
        .await
        .expect("terminal occurrence");
    assert_eq!(
        store
            .pending_occurrence_work_for(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .expect("terminal excluded"),
        None
    );
    let task = AutomationTaskDraft::new(
        "019153a4-3088-7e03-a56a-9b1964f75ddd",
        "unadmitted",
        AutomationSchedule::Once,
        /*first_run_at_ms*/ 200,
        /*created_at_ms*/ 1,
    );
    store.create_task(&task).await.expect("task");
    let lease = store
        .claim_due(
            /*now_ms*/ 200, /*generation*/ 1, /*lease_duration_ms*/ 60_000,
        )
        .await
        .expect("claim")
        .expect("due");
    store
        .materialize_occurrence(&lease, /*now_ms*/ 200)
        .await
        .expect("claimed occurrence");
    assert_eq!(
        store
            .pending_occurrence_work_for(task.task_id, lease.occurrence)
            .await
            .expect("claim excluded"),
        None
    );
    // More than one complete physical page may contain no eligible work.
    // Such a page must still advance, rather than falsely ending discovery.
    for offset in 0..63 {
        let now_ms = 300 + offset;
        let draft = AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "unadmitted physical history",
            AutomationSchedule::Once,
            now_ms,
            /*created_at_ms*/ 1,
        );
        store.create_task(&draft).await.expect("history task");
        let lease = store
            .claim_due(
                now_ms, /*generation*/ 1, /*lease_duration_ms*/ 60_000,
            )
            .await
            .expect("claim history")
            .expect("due history");
        store
            .materialize_occurrence(&lease, now_ms)
            .await
            .expect("unadmitted history");
    }
    let younger = admitted(&store, /*now_ms*/ 1_000).await;
    let before = store
        .pending_occurrence_work(/*limit*/ 10)
        .await
        .expect("before scan");
    let mut scan = store.pending_occurrence_scan();
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("ineligible page"),
        None
    );
    assert_eq!(
        store
            .next_pending_occurrence(&mut scan)
            .await
            .expect("later physical page"),
        Some(younger)
    );
    assert_eq!(
        store
            .pending_occurrence_work(/*limit*/ 10)
            .await
            .expect("after scan"),
        before
    );
    store.close().await;
}

#[tokio::test]
async fn pending_scan_rejects_distinct_live_store_and_nonpositive_rowids() {
    let (_temp, _layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let work = admitted(&store, /*now_ms*/ 100).await;
    let mut scan = store.pending_occurrence_scan();
    let (_other_temp, _other_layout, other, _other_fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    assert_eq!(
        other.next_pending_occurrence(&mut scan).await,
        Err(AutomationError::AccessDenied)
    );
    assert_eq!(
        other
            .pending_occurrence_work_for(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .expect("different owner has no such work"),
        None
    );
    sqlx::query("UPDATE automation_occurrence_lifecycle SET rowid = 0 WHERE task_id = ?")
        .bind(work.occurrence.task_id.to_string())
        .execute(&store.pool)
        .await
        .expect("isolated malformed physical cursor key");
    assert_eq!(
        store.next_pending_occurrence(&mut scan).await,
        Err(AutomationError::Corrupt)
    );
    other.close().await;
    store.close().await;
}

#[tokio::test]
async fn exact_pending_lookup_preserves_legitimate_expired_lease_recovery() {
    let (_temp, _layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let work = admitted(&store, /*now_ms*/ 100).await;
    let run = store
        .taskflow_run(&work.occurrence.taskflow_run_id)
        .await
        .expect("run")
        .expect("exists");
    assert_eq!(run.lease_expires_at_ms, Some(60_100));
    assert_eq!(
        store
            .pending_occurrence_work_for(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .expect("historical eligible identity"),
        Some(work.clone())
    );
    let proof = Sha256Digest::for_bytes(b"trusted late terminal observation");
    store
        .ensure_admitted_taskflow_uncertainty(&work, /*now_ms*/ 100_000)
        .await
        .expect("historical uncertainty");
    store
        .reconcile_occurrence_taskflow_terminal_with_recovery(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &proof,
            /*now_ms*/ 100_000,
            /*recovery_generation*/ 2,
            /*recovery_lease_ms*/ 30_000,
        )
        .await
        .expect("newer owner repairs expired run after historical evidence");
    store
        .complete_occurrence(
            work.occurrence.task_id,
            work.occurrence.occurrence,
            AutomationOccurrenceTerminalState::Succeeded,
            &proof,
            /*completed_at_ms*/ 100_000,
        )
        .await
        .expect("converged occurrence");
    assert_eq!(
        store
            .pending_occurrence_work_for(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .expect("terminal excluded"),
        None
    );
    store.close().await;
}

#[tokio::test]
async fn exact_pending_lookup_rejects_task_owner_substitution() {
    let (_temp, _layout, store, _fence) =
        crate::effect_dispatch_ledger::tests::prepared_store().await;
    let work = admitted(&store, /*now_ms*/ 100).await;
    let mut scan = store.pending_occurrence_scan();
    let before = format!("{scan:?}");
    sqlx::query("UPDATE automation_tasks SET owner_agent_id = ? WHERE task_id = ?")
        .bind("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13")
        .bind(work.occurrence.task_id.to_string())
        .execute(&store.pool)
        .await
        .expect("isolated malformed task owner");
    assert_eq!(
        store
            .pending_occurrence_work_for(work.occurrence.task_id, work.occurrence.occurrence)
            .await,
        Err(AutomationError::AccessDenied)
    );
    assert_eq!(
        store.next_pending_occurrence(&mut scan).await,
        Err(AutomationError::AccessDenied)
    );
    assert_eq!(
        format!("{scan:?}"),
        before,
        "a rejected snapshot cannot consume cursor progress"
    );
    assert_eq!(
        store
            .automation_occurrence(work.occurrence.task_id, work.occurrence.occurrence)
            .await
            .expect("unchanged historical evidence"),
        Some(work.occurrence)
    );
    store.close().await;
}
