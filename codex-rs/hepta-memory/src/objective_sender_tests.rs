use super::test_support::*;
use super::*;
use crate::CognitiveStore;
use crate::cognitive_test_support::layout;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use sqlx::Connection;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteConnection;

#[tokio::test]
async fn retain_binds_exact_raw_to_one_permit_without_effect_outbox_rows() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let request = request();
    let before = fixture.store.recovery_anchor().await.unwrap();
    let ticket = sender.retain_before_send(request.clone()).await.unwrap();
    let after = fixture.store.recovery_anchor().await.unwrap();
    assert_ne!(before, after);
    assert_eq!(fixture.checkpoint.seen.lock().unwrap()[0].0, after);
    let retained: String =
        sqlx::query_scalar("SELECT original_json FROM cognitive_objective_sender_requests")
            .fetch_one(&fixture.store.pool)
            .await
            .unwrap();
    assert_eq!(retained.as_bytes(), request.exact_original());
    let effect_rows: i64 = sqlx::query_scalar("SELECT (SELECT COUNT(*) FROM cognitive_local_outbox) + (SELECT COUNT(*) FROM cognitive_operation_ledger)")
        .fetch_one(&fixture.store.pool).await.unwrap();
    assert_eq!(effect_rows, 0);
    assert!(matches!(
        sender.retain_before_send(request).await,
        Err(ObjectiveSenderError::AlreadyRetained)
    ));
    sender.mark_send_started(&ticket).await.unwrap();
    assert!(matches!(
        sender.mark_send_started(&ticket).await,
        Err(ObjectiveSenderError::SendPermissionUnavailable)
    ));
    assert!(matches!(
        sender.retain_local_cancellation(&ticket).await,
        Err(ObjectiveSenderError::LocalCancellationUnavailable)
    ));
}

#[tokio::test]
async fn changed_outer_route_or_restarted_generation_cannot_regrant_original_run() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let original = request();
    let ticket = sender.retain_before_send(original.clone()).await.unwrap();
    let mut origin = original.origin.clone();
    origin.request_id += 1;
    origin.expected_peer_pid += 1;
    origin.endpoint_identity.push_str(".replacement");
    let changed =
        ObjectiveSenderRequest::from_original(original.original.clone(), origin.clone()).unwrap();
    assert!(matches!(
        sender.retain_before_send(changed).await,
        Err(ObjectiveSenderError::AlreadyRetained)
    ));
    let mut raw: serde_json::Value = serde_json::from_str(&original.original).unwrap();
    raw["message_id"] = serde_json::json!("another-message");
    raw["sequence"] = serde_json::json!(8);
    let changed =
        ObjectiveSenderRequest::from_original(serde_json::to_string(&raw).unwrap(), origin.clone())
            .unwrap();
    assert!(matches!(
        sender.retain_before_send(changed).await,
        Err(ObjectiveSenderError::AlreadyRetained)
    ));
    fixture.writer.release().await.unwrap();
    drop(ticket);
    drop(sender);
    let Fixture {
        writer,
        store,
        checkpoint,
        verifier,
        temp,
    } = fixture;
    drop(writer);
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store,
            authority(&origin.agent_id, 88),
            verifier,
            LEASE,
            2,
        )
        .await
        .unwrap(),
    );
    let sender = writer
        .objective_sender(checkpoint, Duration::from_secs(2))
        .unwrap();
    origin.spawn_generation = 2;
    raw["body"]["spawn_generation"] = serde_json::json!(2);
    let changed =
        ObjectiveSenderRequest::from_original(serde_json::to_string(&raw).unwrap(), origin)
            .unwrap();
    assert!(matches!(
        sender.retain_before_send(changed).await,
        Err(ObjectiveSenderError::AlreadyRetained)
    ));
    let recovered = sender.recover_pending(original).await.unwrap();
    assert!(matches!(
        sender.mark_send_started(&recovered).await,
        Err(ObjectiveSenderError::IdentityMismatch)
    ));
    sender
        .retain_observation(
            &recovered,
            &observation(
                ObjectiveSenderObservationKind::History,
                "{\"status\":\"unavailable_after_generation_change\"}",
            ),
        )
        .await
        .unwrap();
    let validated = CognitiveStore::open(&layout(&temp, writer.owner_agent_id()))
        .await
        .unwrap();
    drop(validated);
    drop(sender);
    drop(writer);
    drop(temp);
}

#[tokio::test]
async fn failed_mismatched_or_revoked_final_checkpoint_leaves_unknown_not_a_new_permit() {
    for mode in [
        CheckpointMode::Refuse,
        CheckpointMode::Mismatch,
        CheckpointMode::RevokeAfterAcknowledgement,
    ] {
        let fixture = Fixture::new().await;
        *fixture.checkpoint.mode.lock().unwrap() = mode;
        let sender = fixture.sender();
        assert!(matches!(
            sender.retain_before_send(request()).await,
            Err(ObjectiveSenderError::AcknowledgementUnknown)
        ));
        fixture.verifier.revoked.store(false, Ordering::SeqCst);
        *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Accept;
        let fresh_facade = fixture.sender();
        assert!(matches!(
            fresh_facade.retain_before_send(request()).await,
            Err(ObjectiveSenderError::AlreadyRetained)
        ));
        let recovered = fresh_facade.recover_pending(request()).await.unwrap();
        assert!(matches!(
            fresh_facade.mark_send_started(&recovered).await,
            Err(ObjectiveSenderError::SendPermissionUnavailable)
        ));
        assert!(matches!(
            fresh_facade.retain_local_cancellation(&recovered).await,
            Err(ObjectiveSenderError::LocalCancellationUnavailable)
        ));
    }
}

#[tokio::test]
async fn checkpoint_holds_original_sqlite_write_serialization_until_acknowledgement() {
    let fixture = Fixture::new().await;
    let options = SqliteConnectOptions::new()
        .filename(fixture.store.path())
        .busy_timeout(Duration::ZERO);
    let mut other_writer = SqliteConnection::connect_with(&options).await.unwrap();
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Hold;
    let sender = fixture.sender();
    let retain = tokio::spawn(async move { sender.retain_before_send(request()).await });
    fixture.checkpoint.entered.notified().await;
    let locked = sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut other_writer)
        .await
        .unwrap_err();
    assert_eq!(
        locked.as_database_error().unwrap().code().as_deref(),
        Some("5")
    );
    fixture.checkpoint.release.notify_one();
    let ticket = retain.await.unwrap().unwrap();
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut other_writer)
        .await
        .unwrap();
    sqlx::query("ROLLBACK")
        .execute(&mut other_writer)
        .await
        .unwrap();
    assert_eq!(
        ticket.request().exact_original(),
        request().exact_original()
    );
}

#[tokio::test]
async fn timeout_and_cancelled_checkpoint_future_release_lock_but_keep_durable_fence() {
    let fixture = Fixture::new().await;
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Hold;
    let sender = fixture
        .writer
        .objective_sender(fixture.checkpoint.clone(), Duration::from_millis(1))
        .unwrap();
    assert!(matches!(
        sender.retain_before_send(request()).await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    assert!(matches!(
        fixture.sender().retain_before_send(request()).await,
        Err(ObjectiveSenderError::AlreadyRetained)
    ));

    let fixture = Fixture::new().await;
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Hold;
    let sender = fixture.sender();
    let retain = tokio::spawn(async move { sender.retain_before_send(request()).await });
    fixture.checkpoint.entered.notified().await;
    retain.abort();
    assert!(matches!(retain.await, Err(error) if error.is_cancelled()));
    assert!(matches!(
        fixture.sender().retain_before_send(request()).await,
        Err(ObjectiveSenderError::AlreadyRetained)
    ));
}

#[tokio::test]
async fn observations_and_local_cancellation_are_durable_and_never_rearm() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    sender.mark_send_started(&ticket).await.unwrap();
    let submission = observation(
        ObjectiveSenderObservationKind::Submission,
        "{\"status\":\"unknown_after_write\"}",
    );
    let publication = observation(
        ObjectiveSenderObservationKind::History,
        "{\"status\":\"original_journal_ack_fixture\",\"sequence\":17}",
    );
    let unknown = observation(
        ObjectiveSenderObservationKind::History,
        "{\"status\":\"unavailable\"}",
    );
    for observed in [&submission, &publication, &unknown, &unknown] {
        sender.retain_observation(&ticket, observed).await.unwrap();
    }
    let snapshot = sender.snapshot(&ticket).await.unwrap();
    assert!(snapshot.observations == vec![submission, publication, unknown]);
    assert!(!snapshot.locally_cancelled);
    let distinct = observation(
        ObjectiveSenderObservationKind::Submission,
        "{\"status\":\"different\"}",
    );
    assert!(matches!(
        sender.retain_observation(&ticket, &distinct).await,
        Err(ObjectiveSenderError::ObservationConflict)
    ));
    let actual = fixture.store.recovery_anchor().await.unwrap();
    assert_eq!(
        fixture.checkpoint.seen.lock().unwrap().last().unwrap().0,
        actual
    );

    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    assert!(matches!(
        sender.retain_local_cancellation(&ticket).await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    assert!(matches!(
        sender.mark_send_started(&ticket).await,
        Err(ObjectiveSenderError::SendPermissionUnavailable)
    ));
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Accept;
    sender.retain_local_cancellation(&ticket).await.unwrap();
    assert!(sender.snapshot(&ticket).await.unwrap().locally_cancelled);
    assert!(matches!(
        sender.retain_observation(&ticket, &distinct).await,
        Err(ObjectiveSenderError::ObservationConflict)
    ));
}

#[tokio::test]
async fn semantic_startup_audit_rejects_observation_tamper_with_original_schema_restored() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    sender.mark_send_started(&ticket).await.unwrap();
    sender
        .retain_observation(
            &ticket,
            &observation(
                ObjectiveSenderObservationKind::Submission,
                "{\"status\":\"unknown\"}",
            ),
        )
        .await
        .unwrap();
    let mut tamper = fixture
        .store
        .pool
        .begin_with("BEGIN IMMEDIATE")
        .await
        .unwrap();
    let original_trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'cognitive_objective_sender_events_no_update'",
    )
    .fetch_one(&mut *tamper)
    .await
    .unwrap();
    sqlx::query("DROP TRIGGER cognitive_objective_sender_events_no_update")
        .execute(&mut *tamper)
        .await
        .unwrap();
    let changed = sqlx::query("UPDATE cognitive_objective_sender_events SET observation_json = '{\"changed\":true}' WHERE event_sequence = 2")
        .execute(&mut *tamper).await.unwrap();
    assert_eq!(changed.rows_affected(), 1);
    sqlx::query(
        "CREATE TRIGGER cognitive_objective_sender_events_no_update
BEFORE UPDATE ON cognitive_objective_sender_events BEGIN
    SELECT RAISE(ABORT, 'Objective sender observations are immutable');
END;",
    )
    .execute(&mut *tamper)
    .await
    .unwrap();
    let restored_trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'cognitive_objective_sender_events_no_update'",
    )
    .fetch_one(&mut *tamper)
    .await
    .unwrap();
    assert_eq!(restored_trigger, original_trigger);
    tamper.commit().await.unwrap();
    let reopened =
        CognitiveStore::open(&layout(&fixture.temp, fixture.writer.owner_agent_id())).await;
    assert!(
        matches!(reopened, Err(CognitiveStoreError::Corrupt(reason)) if reason.contains("Objective sender"))
    );
}

#[tokio::test]
async fn stale_schema_anchor_is_refused_before_any_recovery_path_access() {
    let fixture = Fixture::new().await;
    let mut old = fixture.store.recovery_anchor().await.unwrap();
    old.schema_digest =
        Sha256Digest::parse("c448a01d9749d7c409bb9c384ceaa7245ef6aca0eda722ac3ec8b2501602bed0")
            .unwrap();
    let owner = fixture.writer.owner_agent_id();
    let recovered = CognitiveStore::open_with_recovery(
        &layout(&fixture.temp, owner),
        crate::CognitiveRecoveryRequirement::ExactCurrentCut(&old),
        &authority(owner, 87),
        fixture.verifier.as_ref(),
    )
    .await;
    assert!(matches!(
        recovered,
        Err(crate::CognitiveRecoveryError::Invalid(_))
    ));
}

#[tokio::test]
async fn an_unused_ticket_cannot_move_to_a_reopened_original_writer_instance() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    drop(sender);
    let Fixture {
        writer,
        store,
        checkpoint,
        verifier,
        temp,
    } = fixture;
    drop(writer);
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store,
            authority(&request().origin.agent_id, 87),
            verifier,
            LEASE,
            1,
        )
        .await
        .unwrap(),
    );
    let reopened = writer
        .objective_sender(checkpoint, Duration::from_secs(2))
        .unwrap();
    assert!(matches!(
        reopened.mark_send_started(&ticket).await,
        Err(ObjectiveSenderError::IdentityMismatch)
    ));
    assert!(matches!(
        reopened.retain_local_cancellation(&ticket).await,
        Err(ObjectiveSenderError::IdentityMismatch)
    ));
    let recovered = reopened.recover_pending(request()).await.unwrap();
    assert!(matches!(
        reopened.mark_send_started(&recovered).await,
        Err(ObjectiveSenderError::SendPermissionUnavailable)
    ));
    drop(reopened);
    drop(writer);
    drop(temp);
}

#[tokio::test]
async fn bounded_pages_recover_exact_owner_bytes_without_caller_memory_or_send_rights() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let original = request();
    let mut expected = std::collections::BTreeMap::new();
    for index in 0..17 {
        let mut value: serde_json::Value = serde_json::from_str(&original.original).unwrap();
        value["message_id"] = serde_json::json!(format!("page-message-{index}"));
        value["sequence"] = serde_json::json!(index + 1);
        value["body"]["run_id"] = serde_json::json!(format!("page-run-{index}"));
        let request = ObjectiveSenderRequest::from_original(
            serde_json::to_string(&value).unwrap(),
            original.origin.clone(),
        )
        .unwrap();
        expected.insert(
            request.identity.original_sha256.as_str().to_string(),
            request.exact_original().to_vec(),
        );
        sender.retain_before_send(request).await.unwrap();
    }
    let first = sender
        .retained_page(ObjectiveSenderRetainedPosition::Beginning)
        .await
        .unwrap();
    assert_eq!(first.requests.len(), 16);
    let second = sender
        .retained_page(ObjectiveSenderRetainedPosition::After(first.next.unwrap()))
        .await
        .unwrap();
    assert_eq!(second.requests.len(), 1);
    assert!(second.next.is_none());
    let mut actual = std::collections::BTreeMap::new();
    for retained in first.requests.into_iter().chain(second.requests) {
        actual.insert(
            retained.identity.original_sha256.as_str().to_string(),
            retained.exact_original().to_vec(),
        );
        let recovered = sender.recover_pending(retained).await.unwrap();
        assert!(matches!(
            sender.mark_send_started(&recovered).await,
            Err(ObjectiveSenderError::SendPermissionUnavailable)
        ));
    }
    assert_eq!(actual, expected);
}
