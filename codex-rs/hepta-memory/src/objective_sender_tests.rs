use super::test_support::*;
use super::*;
use crate::CognitiveStore;
use crate::cognitive_test_support::layout;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;
use sqlx::Connection;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteConnection;

#[derive(Clone, Copy)]
enum ObservationPath {
    SnapshotThenAppend,
    CheckInTransaction,
}

fn require_same_publication(
    snapshot: &ObjectiveSenderSnapshot,
    publication: &ObjectiveSenderObservation,
) -> Result<(), ObjectiveSenderError> {
    if snapshot.observations.iter().any(|retained| {
        retained.kind == ObjectiveSenderObservationKind::History && retained != publication
    }) {
        return Err(ObjectiveSenderError::IdentityMismatch);
    }
    Ok(())
}

async fn race_recovered_publications(
    fixture: &Fixture,
    path: ObservationPath,
) -> [(
    ObjectiveSenderObservation,
    Result<(), ObjectiveSenderError>,
    usize,
); 2] {
    // These are deliberately contradictory test metadata, never authenticated
    // publications. The original generic owner does not interpret their meaning.
    let publications = ["compiled", "explicit_abstain"].map(|outcome| {
        observation(
            ObjectiveSenderObservationKind::History,
            &serde_json::json!({
                "type": "historical_publication", "publication_sequence": 17,
                "chain_digest": "44".repeat(32), "outcome": outcome,
            })
            .to_string(),
        )
    });
    let barrier = Arc::new(tokio::sync::Barrier::new(2));
    let tasks = publications.map(|publication| {
        // Separate capabilities and recovered tickets over the same real owner.
        let sender = fixture.sender();
        let barrier = Arc::clone(&barrier);
        tokio::spawn(async move {
            let ticket = sender.recover_pending(request()).await.unwrap();
            let stale_snapshot = sender.snapshot(&ticket).await.unwrap();
            assert!(stale_snapshot.observations.is_empty());
            require_same_publication(&stale_snapshot, &publication).unwrap();
            // Neither contender can append until BOTH prechecks saw no history.
            barrier.wait().await;
            let mut checked_length = stale_snapshot.observations.len();
            let result = match path {
                ObservationPath::SnapshotThenAppend => {
                    sender.retain_observation(&ticket, &publication).await
                }
                ObservationPath::CheckInTransaction => {
                    sender
                        .retain_observation_checked(&ticket, &publication, |current| {
                            checked_length = current.observations.len();
                            require_same_publication(current, &publication)
                        })
                        .await
                }
            };
            (publication, result, checked_length)
        })
    });
    let [first, second] = tasks;
    let (first, second) = tokio::join!(first, second);
    [first.unwrap(), second.unwrap()]
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn checked_negative_control_separate_prechecks_allow_conflicting_generic_appends() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    drop(sender.retain_before_send(request()).await.unwrap());
    let outcomes = race_recovered_publications(&fixture, ObservationPath::SnapshotThenAppend).await;
    let recovered = sender.recover_pending(request()).await.unwrap();
    let snapshot = sender.snapshot(&recovered).await.unwrap();
    assert_eq!(snapshot.observations.len(), 2);
    for (publication, result, precheck_length) in outcomes {
        result.unwrap();
        assert_eq!(precheck_length, 0);
        assert!(snapshot.observations.contains(&publication));
    }
    // This counterexample uses the real unchanged generic append, not a model:
    // both conflicting histories committed and received independent test ACKs.
    assert_eq!(fixture.checkpoint.seen.lock().unwrap().len(), 3);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn checked_concurrent_history_keeps_one_publication_and_idempotent_acknowledgement() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    drop(sender.retain_before_send(request()).await.unwrap());
    let [
        (first, first_result, first_length),
        (second, second_result, second_length),
    ] = race_recovered_publications(&fixture, ObservationPath::CheckInTransaction).await;
    let winner = match (first_result, second_result) {
        (Ok(()), Err(ObjectiveSenderError::IdentityMismatch)) => first,
        (Err(ObjectiveSenderError::IdentityMismatch), Ok(())) => second,
        results => panic!("exactly one checked publication must survive: {results:?}"),
    };
    let mut checked_lengths = [first_length, second_length];
    checked_lengths.sort_unstable();
    assert_eq!(checked_lengths, [0, 1]);
    assert_eq!(fixture.checkpoint.seen.lock().unwrap().len(), 2);

    let recovered = sender.recover_pending(request()).await.unwrap();
    let snapshot = sender.snapshot(&recovered).await.unwrap();
    assert!(snapshot.observations == vec![winner.clone()]);
    assert!(!snapshot.locally_cancelled);
    let before_retry = fixture.store.recovery_anchor().await.unwrap();
    sender
        .retain_observation_checked(&recovered, &winner, |current| {
            require_same_publication(current, &winner)
        })
        .await
        .unwrap();
    assert_eq!(fixture.checkpoint.seen.lock().unwrap().len(), 3);
    assert!(sender.snapshot(&recovered).await.unwrap().observations == vec![winner]);
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), before_retry);
    assert!(matches!(
        sender.mark_send_started(&recovered).await,
        Err(ObjectiveSenderError::SendPermissionUnavailable)
    ));
    // Exercise the original complete semantic startup audit of the surviving
    // immutable chain. This is not a process-crash or production genesis claim.
    let audited =
        CognitiveStore::open(&layout(&fixture.temp, fixture.writer.owner_agent_id())).await;
    assert!(audited.is_ok());
}

#[tokio::test]
async fn snapshot_acknowledged_does_not_promote_a_committed_observation_without_checkpoint_ack() {
    for mode in [CheckpointMode::Refuse, CheckpointMode::Hold] {
        let fixture = Fixture::new().await;
        let sender = fixture
            .writer
            .objective_sender(fixture.checkpoint.clone(), Duration::from_millis(50))
            .unwrap();
        let ticket = sender.retain_before_send(request()).await.unwrap();
        sender.mark_send_started(&ticket).await.unwrap();
        let observed = observation(
            ObjectiveSenderObservationKind::History,
            "{\"status\":\"original_publication_test_metadata\"}",
        );
        *fixture.checkpoint.mode.lock().unwrap() = mode;
        assert!(matches!(
            sender.retain_observation(&ticket, &observed).await,
            Err(ObjectiveSenderError::AcknowledgementUnknown)
        ));
        drop(ticket);
        let committed = fixture.store.recovery_anchor().await.unwrap();
        let recovered = sender.recover_pending(request()).await.unwrap();
        let calls_before_read = fixture.checkpoint.seen.lock().unwrap().len();
        // Negative control: the real raw snapshot sees the committed row, but
        // it performs no independent ACK and cannot settle that uncertainty.
        assert!(sender.snapshot(&recovered).await.unwrap().observations == vec![observed.clone()]);
        assert_eq!(
            fixture.checkpoint.seen.lock().unwrap().len(),
            calls_before_read
        );
        assert!(matches!(
            sender.snapshot_acknowledged(&recovered).await,
            Err(ObjectiveSenderError::AcknowledgementUnknown)
        ));
        assert_eq!(fixture.store.recovery_anchor().await.unwrap(), committed);

        *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Accept;
        let before_retry = fixture.checkpoint.seen.lock().unwrap().len();
        let acknowledged = sender.snapshot_acknowledged(&recovered).await.unwrap();
        assert!(acknowledged.observations == vec![observed]);
        assert!(!acknowledged.locally_cancelled);
        assert_eq!(
            fixture.checkpoint.seen.lock().unwrap().len(),
            before_retry + 1
        );
        assert_eq!(fixture.store.recovery_anchor().await.unwrap(), committed);
        assert!(matches!(
            sender.mark_send_started(&recovered).await,
            Err(ObjectiveSenderError::SendPermissionUnavailable)
        ));
        assert!(matches!(
            sender.retain_local_cancellation(&recovered).await,
            Err(ObjectiveSenderError::LocalCancellationUnavailable)
        ));
        assert!(matches!(
            sender.retain_before_send(request()).await,
            Err(ObjectiveSenderError::Writer(
                ProductionWriterError::CheckpointFenced
            ))
        ));
        assert!(fixture.writer.checkpoint_fenced());
    }
}

#[tokio::test]
async fn snapshot_acknowledged_recovers_local_cancellation_without_a_new_cancellation_right() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let ticket = sender.retain_before_send(request()).await.unwrap();
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    assert!(matches!(
        sender.retain_local_cancellation(&ticket).await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    drop(ticket);
    let committed = fixture.store.recovery_anchor().await.unwrap();
    let recovered = sender.recover_pending(request()).await.unwrap();
    let calls_before_read = fixture.checkpoint.seen.lock().unwrap().len();
    assert!(sender.snapshot(&recovered).await.unwrap().locally_cancelled);
    assert_eq!(
        fixture.checkpoint.seen.lock().unwrap().len(),
        calls_before_read
    );
    assert!(matches!(
        sender.snapshot_acknowledged(&recovered).await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Accept;
    let acknowledged = sender.snapshot_acknowledged(&recovered).await.unwrap();
    assert!(acknowledged.locally_cancelled);
    assert!(acknowledged.observations.is_empty());
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), committed);
    assert!(matches!(
        sender.mark_send_started(&recovered).await,
        Err(ObjectiveSenderError::SendPermissionUnavailable)
    ));
    assert!(matches!(
        sender.retain_local_cancellation(&recovered).await,
        Err(ObjectiveSenderError::LocalCancellationUnavailable)
    ));
}

#[tokio::test]
async fn snapshot_acknowledged_holds_the_original_write_lock_through_the_current_cut_ack() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    drop(sender.retain_before_send(request()).await.unwrap());
    let recovered = sender.recover_pending(request()).await.unwrap();
    let options = SqliteConnectOptions::new()
        .filename(fixture.store.path())
        .busy_timeout(Duration::ZERO);
    let mut competing_writer = SqliteConnection::connect_with(&options).await.unwrap();
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Hold;
    let read = tokio::spawn(async move { sender.snapshot_acknowledged(&recovered).await });
    fixture.checkpoint.entered.notified().await;
    let locked = sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut competing_writer)
        .await
        .unwrap_err();
    assert_eq!(
        locked.as_database_error().unwrap().code().as_deref(),
        Some("5")
    );
    fixture.checkpoint.release.notify_one();
    let acknowledged = read.await.unwrap().unwrap();
    assert!(acknowledged.observations.is_empty());
    assert!(!acknowledged.locally_cancelled);
    sqlx::query("BEGIN IMMEDIATE")
        .execute(&mut competing_writer)
        .await
        .unwrap();
    sqlx::query("ROLLBACK")
        .execute(&mut competing_writer)
        .await
        .unwrap();
    let current = fixture.store.recovery_anchor().await.unwrap();
    assert_eq!(
        fixture.checkpoint.seen.lock().unwrap().last().unwrap().0,
        current
    );
}

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
            Err(ObjectiveSenderError::Writer(
                ProductionWriterError::CheckpointFenced
            ))
        ));
        let recovered = fresh_facade.recover_pending(request()).await.unwrap();
        assert!(fresh_facade.snapshot_acknowledged(&recovered).await.is_ok());
        assert!(fixture.writer.checkpoint_fenced());
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
        Err(ObjectiveSenderError::Writer(
            ProductionWriterError::CheckpointFenced
        ))
    ));
    assert!(fixture.sender().recover_pending(request()).await.is_ok());

    let fixture = Fixture::new().await;
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Hold;
    let sender = fixture.sender();
    let retain = tokio::spawn(async move { sender.retain_before_send(request()).await });
    fixture.checkpoint.entered.notified().await;
    retain.abort();
    assert!(matches!(retain.await, Err(error) if error.is_cancelled()));
    assert!(matches!(
        fixture.sender().retain_before_send(request()).await,
        Err(ObjectiveSenderError::Writer(
            ProductionWriterError::CheckpointFenced
        ))
    ));
    assert!(fixture.sender().recover_pending(request()).await.is_ok());
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
    assert!(matches!(
        sender.retain_local_cancellation(&ticket).await,
        Err(ObjectiveSenderError::Writer(
            ProductionWriterError::CheckpointFenced
        ))
    ));
    let before = fixture.store.recovery_anchor().await.unwrap();
    assert!(
        sender
            .snapshot_acknowledged(&ticket)
            .await
            .unwrap()
            .locally_cancelled
    );
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), before);
    assert!(fixture.writer.checkpoint_fenced());
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
        .retained_page_after_token(first.next.unwrap().navigation_token())
        .await
        .unwrap();
    assert_eq!(second.requests.len(), 1);
    assert!(second.next.is_none());
    assert!(sender.retained_page_after_token("../owner").await.is_err());
    assert!(
        sender
            .retained_page_after_token(&"A".repeat(64))
            .await
            .is_err()
    );
    assert!(
        sender
            .retained_request_for_run("not-retained")
            .await
            .unwrap()
            .is_none()
    );
    let anchor = fixture.writer.store.recovery_anchor().await.unwrap();
    let mut actual = std::collections::BTreeMap::new();
    for retained in first.requests.into_iter().chain(second.requests) {
        actual.insert(
            retained.identity.original_sha256.as_str().to_string(),
            retained.exact_original().to_vec(),
        );
        let looked_up = sender
            .retained_request_for_run(&retained.identity.run_id)
            .await
            .unwrap()
            .unwrap();
        assert!(looked_up == retained);
        let recovered = sender.recover_pending(looked_up).await.unwrap();
        assert!(matches!(
            sender.mark_send_started(&recovered).await,
            Err(ObjectiveSenderError::SendPermissionUnavailable)
        ));
    }
    assert_eq!(actual, expected);
    assert_eq!(
        fixture.writer.store.recovery_anchor().await.unwrap(),
        anchor
    );
}
