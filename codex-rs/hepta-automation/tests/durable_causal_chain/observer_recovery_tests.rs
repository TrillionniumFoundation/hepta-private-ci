use super::*;
use pretty_assertions::assert_eq;

async fn admit(store: &AutomationStore, task_id: &str) -> AutomationTaskDraft {
    let task = draft(task_id, AutomationSchedule::Once, /*due*/ 100);
    store.create_task(&task).await.expect("task");
    let scheduler = AutomationScheduler::new(
        store.clone(),
        Arc::new(SuccessQueue),
        /*generation*/ 1,
        Duration::from_secs(/*secs*/ 30),
        Duration::from_secs(/*secs*/ 2),
    )
    .expect("scheduler");
    assert!(matches!(
        scheduler.tick(/*now_ms*/ 100).await.expect("admission"),
        AutomationTick::Submitted { .. }
    ));
    task
}

#[tokio::test]
async fn indeterminate_later_turn_remains_observable_after_reopen_without_readmission() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = admit(&store, "019153a4-3088-7000-a56a-9b1964f75190").await;
    let missing = Sha256Digest::for_bytes(b"exact queue lookup temporarily missing");
    store
        .mark_occurrence_indeterminate(
            task.task_id,
            /*occurrence*/ 1,
            &missing,
            /*observed_at_ms*/ 101,
        )
        .await
        .expect("missing observation");
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen quarantine");
    let before = store
        .automation_occurrence(task.task_id, /*occurrence*/ 1)
        .await
        .unwrap()
        .unwrap();
    let payload = Sha256Digest::for_bytes(b"same admitted canonical provider payload");
    assert_eq!(
        store
            .record_occurrence_turn(
                task.task_id,
                /*occurrence*/ 1,
                "wrong-client",
                "later-turn",
                payload.as_str(),
                /*observed_at_ms*/ 102
            )
            .await,
        Err(AutomationError::Conflict)
    );
    assert_eq!(
        store
            .automation_occurrence(task.task_id, /*occurrence*/ 1)
            .await
            .unwrap()
            .unwrap(),
        before
    );
    let recovered = store
        .record_occurrence_turn(
            task.task_id,
            /*occurrence*/ 1,
            &before.client_user_message_id,
            "later-turn",
            payload.as_str(),
            /*observed_at_ms*/ 102,
        )
        .await
        .expect("trusted persisted lookup");
    let mut expected = before.clone();
    expected.turn_id = Some("later-turn".to_string());
    expected.provider_payload_sha256 = Some(payload.as_str().to_string());
    expected.updated_at_ms = 102;
    assert_eq!(recovered, expected);
    assert_eq!(
        store
            .record_occurrence_turn(
                task.task_id,
                /*occurrence*/ 1,
                &before.client_user_message_id,
                "later-turn",
                payload.as_str(),
                /*observed_at_ms*/ 103
            )
            .await
            .unwrap(),
        expected
    );
    for (turn, digest) in [
        ("replacement-turn", payload.clone()),
        ("later-turn", Sha256Digest::for_bytes(b"different payload")),
    ] {
        assert_eq!(
            store
                .record_occurrence_turn(
                    task.task_id,
                    /*occurrence*/ 1,
                    &before.client_user_message_id,
                    turn,
                    digest.as_str(),
                    /*observed_at_ms*/ 103
                )
                .await,
            Err(AutomationError::Conflict)
        );
    }
    assert_eq!(
        store
            .automation_occurrence(task.task_id, /*occurrence*/ 1)
            .await
            .unwrap()
            .unwrap(),
        expected
    );
    assert!(
        store
            .claim_due(
                /*now_ms*/ 40_000, /*generation*/ 2, /*lease_duration_ms*/ 30_000
            )
            .await
            .unwrap()
            .is_none()
    );
    let work = store
        .pending_occurrence_work(/*limit*/ 1)
        .await
        .unwrap()
        .pop()
        .unwrap();
    let terminal = Sha256Digest::for_bytes(b"same turn terminal completion");
    store
        .reconcile_occurrence_taskflow_terminal(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &terminal,
            /*now_ms*/ 40_001,
        )
        .await
        .expect("historical step/run first");
    let done = store
        .complete_occurrence(
            task.task_id,
            /*occurrence*/ 1,
            AutomationOccurrenceTerminalState::Succeeded,
            &terminal,
            /*completed_at_ms*/ 40_001,
        )
        .await
        .expect("occurrence terminal");
    assert_eq!(done.state, AutomationOccurrenceState::Succeeded);
    assert_eq!(done.terminal_receipt_digest, Some(terminal));
    assert!(
        store
            .pending_occurrence_work(/*limit*/ 1)
            .await
            .unwrap()
            .is_empty()
    );
    store.close().await;
}

#[tokio::test]
async fn indeterminate_known_turn_can_resume_cursor_cas_and_terminal_recovery_after_reopen() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = admit(&store, "019153a4-3088-7000-a56a-9b1964f75191").await;
    let admitted = store
        .automation_occurrence(task.task_id, /*occurrence*/ 1)
        .await
        .unwrap()
        .unwrap();
    let payload = Sha256Digest::for_bytes(b"known turn canonical provider payload");
    store
        .record_occurrence_turn(
            task.task_id,
            /*occurrence*/ 1,
            &admitted.client_user_message_id,
            "known-turn",
            payload.as_str(),
            /*observed_at_ms*/ 101,
        )
        .await
        .unwrap();
    let missing = Sha256Digest::for_bytes(b"history fully exhausted for known turn");
    store
        .mark_occurrence_indeterminate(
            task.task_id,
            /*occurrence*/ 1,
            &missing,
            /*observed_at_ms*/ 102,
        )
        .await
        .unwrap();
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen known turn");
    let before = store
        .automation_occurrence(task.task_id, /*occurrence*/ 1)
        .await
        .unwrap()
        .unwrap();
    let first = store
        .record_terminal_scan_cursor(
            task.task_id,
            /*occurrence*/ 1,
            "known-turn",
            /*expected_cursor*/ None,
            "after-1600",
            /*observed_at_ms*/ 103,
        )
        .await
        .expect("bounded unknown observation");
    let mut expected = before;
    expected.terminal_scan_cursor = Some("after-1600".to_string());
    expected.updated_at_ms = 103;
    assert_eq!(first, expected);
    for (turn, cursor) in [
        ("replacement-turn", Some("after-1600")),
        ("known-turn", None),
    ] {
        assert_eq!(
            store
                .record_terminal_scan_cursor(
                    task.task_id,
                    /*occurrence*/ 1,
                    turn,
                    cursor,
                    "after-3200",
                    /*observed_at_ms*/ 104
                )
                .await,
            Err(AutomationError::Conflict)
        );
    }
    assert_eq!(
        store
            .automation_occurrence(task.task_id, /*occurrence*/ 1)
            .await
            .unwrap()
            .unwrap(),
        expected
    );
    store.close().await;
    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen continued scan");
    let next = store
        .record_terminal_scan_cursor(
            task.task_id,
            /*occurrence*/ 1,
            "known-turn",
            Some("after-1600"),
            "after-3200",
            /*observed_at_ms*/ 105,
        )
        .await
        .expect("exact cursor continuation");
    expected.terminal_scan_cursor = Some("after-3200".to_string());
    expected.updated_at_ms = 105;
    assert_eq!(next, expected);
    let work = store
        .pending_occurrence_work(/*limit*/ 1)
        .await
        .unwrap()
        .pop()
        .unwrap();
    let terminal = Sha256Digest::for_bytes(b"known turn recovered completion");
    store
        .reconcile_occurrence_taskflow_terminal(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &terminal,
            /*now_ms*/ 40_001,
        )
        .await
        .expect("historical step/run first");
    let done = store
        .complete_occurrence(
            task.task_id,
            /*occurrence*/ 1,
            AutomationOccurrenceTerminalState::Succeeded,
            &terminal,
            /*completed_at_ms*/ 40_001,
        )
        .await
        .expect("occurrence terminal");
    assert_eq!(done.state, AutomationOccurrenceState::Succeeded);
    assert_eq!(done.terminal_receipt_digest, Some(terminal));
    assert!(
        store
            .record_terminal_scan_cursor(
                task.task_id,
                /*occurrence*/ 1,
                "known-turn",
                Some("after-3200"),
                "after-terminal",
                /*observed_at_ms*/ 40_002
            )
            .await
            .is_err()
    );
    store.close().await;
}

#[tokio::test]
async fn claimed_uncertainty_without_submitted_witness_cannot_bind_a_turn() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = draft(
        "019153a4-3088-7000-a56a-9b1964f75192",
        AutomationSchedule::Once,
        /*due*/ 100,
    );
    store.create_task(&task).await.unwrap();
    let lease = store
        .claim_due(
            /*now_ms*/ 100, /*generation*/ 1, /*lease_duration_ms*/ 30_000,
        )
        .await
        .unwrap()
        .unwrap();
    store
        .materialize_occurrence(&lease, /*now_ms*/ 100)
        .await
        .unwrap();
    let unknown = store
        .mark_occurrence_indeterminate(
            task.task_id,
            /*occurrence*/ 1,
            &Sha256Digest::for_bytes(b"not an admission receipt"),
            /*observed_at_ms*/ 101,
        )
        .await
        .unwrap();
    let payload = Sha256Digest::for_bytes(b"payload");
    assert_eq!(
        store
            .record_occurrence_turn(
                task.task_id,
                /*occurrence*/ 1,
                &unknown.client_user_message_id,
                "unadmitted-turn",
                payload.as_str(),
                /*observed_at_ms*/ 102
            )
            .await,
        Err(AutomationError::Conflict)
    );
    assert_eq!(
        store
            .automation_occurrence(task.task_id, /*occurrence*/ 1)
            .await
            .unwrap()
            .unwrap(),
        unknown
    );
    store.close().await;
}

#[tokio::test]
async fn exhausted_indeterminate_scan_resets_exact_snapshot_and_recovers_from_head_after_reopen() {
    let fixture = Fixture::new();
    let store = AutomationStore::open(&fixture.layout).await.expect("store");
    let task = admit(&store, "019153a4-3088-7000-a56a-9b1964f75193").await;
    let admitted = store
        .automation_occurrence(task.task_id, /*occurrence*/ 1)
        .await
        .unwrap()
        .unwrap();
    let payload = Sha256Digest::for_bytes(b"same known turn provider payload");
    store
        .record_occurrence_turn(
            task.task_id,
            /*occurrence*/ 1,
            &admitted.client_user_message_id,
            "front-turn",
            payload.as_str(),
            /*observed_at_ms*/ 101,
        )
        .await
        .unwrap();
    let missing = Sha256Digest::for_bytes(b"known turn absent after complete history scan");
    store
        .mark_occurrence_indeterminate(
            task.task_id,
            /*occurrence*/ 1,
            &missing,
            /*observed_at_ms*/ 102,
        )
        .await
        .unwrap();
    let old = store
        .record_terminal_scan_cursor(
            task.task_id,
            /*occurrence*/ 1,
            "front-turn",
            /*expected_cursor*/ None,
            "page-1600",
            /*observed_at_ms*/ 103,
        )
        .await
        .unwrap();
    let tail = store
        .record_terminal_scan_cursor(
            task.task_id,
            /*occurrence*/ 1,
            "front-turn",
            Some("page-1600"),
            "page-3200",
            /*observed_at_ms*/ 104,
        )
        .await
        .unwrap();
    assert_eq!(
        store
            .reset_terminal_scan_after_exhaustion(&old, /*observed_at_ms*/ 105)
            .await,
        Err(AutomationError::Conflict)
    );
    assert_eq!(
        store
            .automation_occurrence(task.task_id, /*occurrence*/ 1)
            .await
            .unwrap()
            .unwrap(),
        tail
    );
    // Even a newer observation with the same cursor cannot be erased by an
    // older completed-scan snapshot (cursor-only CAS would permit this ABA).
    assert!(
        store
            .defer_occurrence_observation(&tail, /*observed_at_ms*/ 105)
            .await
            .unwrap()
    );
    assert_eq!(
        store
            .reset_terminal_scan_after_exhaustion(&tail, /*observed_at_ms*/ 106)
            .await,
        Err(AutomationError::Conflict)
    );
    let latest = store
        .automation_occurrence(task.task_id, /*occurrence*/ 1)
        .await
        .unwrap()
        .unwrap();
    let mut forged = latest.clone();
    forged.turn_id = Some("different-turn".to_string());
    assert_eq!(
        store
            .reset_terminal_scan_after_exhaustion(&forged, /*observed_at_ms*/ 106)
            .await,
        Err(AutomationError::Conflict)
    );
    let reset = store
        .reset_terminal_scan_after_exhaustion(&latest, /*observed_at_ms*/ 106)
        .await
        .expect("completed tail scan returns to head");
    let mut expected = latest;
    expected.terminal_scan_cursor = None;
    expected.updated_at_ms = 106;
    assert_eq!(reset, expected);
    // General indeterminate marking remains a receipt-preserving no-op.
    assert_eq!(
        store
            .mark_occurrence_indeterminate(
                task.task_id,
                /*occurrence*/ 1,
                &Sha256Digest::for_bytes(b"later unknown observation"),
                /*observed_at_ms*/ 107
            )
            .await
            .unwrap(),
        expected
    );
    assert_eq!(
        store
            .reset_terminal_scan_after_exhaustion(&reset, /*observed_at_ms*/ 107)
            .await
            .unwrap(),
        expected
    );
    store.close().await;

    let store = AutomationStore::open(&fixture.layout)
        .await
        .expect("reopen reset head");
    let work = store
        .pending_occurrence_work(/*limit*/ 1)
        .await
        .unwrap()
        .pop()
        .unwrap();
    assert_eq!(work.occurrence, expected);
    assert_eq!(work.occurrence.terminal_scan_cursor, None);
    // The next lookup now starts at None and observes the front of history.
    // Re-observing the same known turn is read-only and preserves quarantine.
    assert_eq!(
        store
            .record_occurrence_turn(
                task.task_id,
                /*occurrence*/ 1,
                &work.occurrence.client_user_message_id,
                "front-turn",
                payload.as_str(),
                /*observed_at_ms*/ 108
            )
            .await
            .unwrap(),
        expected
    );
    let terminal = Sha256Digest::for_bytes(b"front of history contains terminal known turn");
    store
        .reconcile_occurrence_taskflow_terminal(
            &work,
            AutomationOccurrenceTerminalState::Succeeded,
            &terminal,
            /*now_ms*/ 40_001,
        )
        .await
        .expect("historical step/run first");
    let done = store
        .complete_occurrence(
            task.task_id,
            /*occurrence*/ 1,
            AutomationOccurrenceTerminalState::Succeeded,
            &terminal,
            /*completed_at_ms*/ 40_001,
        )
        .await
        .expect("occurrence terminal");
    assert_eq!(done.state, AutomationOccurrenceState::Succeeded);
    assert_eq!(done.terminal_receipt_digest, Some(terminal));
    assert_eq!(
        store
            .reset_terminal_scan_after_exhaustion(&reset, /*observed_at_ms*/ 40_002)
            .await,
        Err(AutomationError::Conflict)
    );
    assert!(
        store
            .pending_occurrence_work(/*limit*/ 1)
            .await
            .unwrap()
            .is_empty()
    );
    store.close().await;
}
