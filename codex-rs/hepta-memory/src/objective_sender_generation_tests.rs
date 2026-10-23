//! Process binding and whole-owner ACK do not manufacture Objective records.
use super::test_support::*;
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn owner_cut_acknowledgement_creates_no_request_or_permission() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let before = fixture.store.recovery_anchor().await.unwrap();
    sender.acknowledge_owner_cut().await.unwrap();
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), before);
    assert_eq!(fixture.checkpoint.seen.lock().unwrap()[0].0, before);
    assert!(
        sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await
            .unwrap()
            .requests
            .is_empty()
    );
    assert!(matches!(
        sender.recover_pending(request()).await,
        Err(ObjectiveSenderError::Missing)
    ));
}

#[tokio::test]
async fn writer_accessor_cannot_choose_a_different_sender_process_generation() {
    let fixture = Fixture::new().await;
    assert!(matches!(
        fixture.writer.objective_sender_for_spawn_generation(
            fixture.checkpoint.clone(),
            Duration::from_secs(2),
            3
        ),
        Err(ObjectiveSenderError::Writer(
            ProductionWriterError::AuthorityRejected(_)
        ))
    ));
    assert!(fixture.checkpoint.seen.lock().unwrap().is_empty());
}

#[tokio::test]
async fn owner_cut_unknown_fences_original_writer_without_retaining_a_request() {
    let fixture = Fixture::new().await;
    *fixture.checkpoint.mode.lock().unwrap() = CheckpointMode::Refuse;
    let sender = fixture.sender();
    assert!(matches!(
        sender.acknowledge_owner_cut().await,
        Err(ObjectiveSenderError::AcknowledgementUnknown)
    ));
    assert!(fixture.writer.checkpoint_fenced());
    assert!(matches!(
        fixture.writer.verify_current_authority().await,
        Err(ProductionWriterError::CheckpointFenced)
    ));
    let cut = fixture.store.recovery_anchor().await.unwrap();
    // Admit reaches the same pool commit hook, whose refusal is wrapped in the
    // original local-store error rather than the writer's preflight variant.
    assert!(
        fixture
            .writer
            .admit("after-unknown", "test", "{}")
            .await
            .is_err()
    );
    assert_eq!(fixture.store.recovery_anchor().await.unwrap(), cut);
    assert!(
        sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await
            .unwrap()
            .requests
            .is_empty()
    );
}

#[tokio::test]
async fn initial_permission_cannot_substitute_another_valid_local_lease_binding() {
    let fixture = Fixture::new().await;
    let sender = fixture.sender();
    let original = request();
    let ticket = sender.retain_before_send(original.clone()).await.unwrap();
    fixture.writer.release().await.unwrap();
    drop(ticket);
    drop(sender);
    let Fixture {
        writer,
        store,
        checkpoint,
        verifier,
        temp: _temp,
    } = fixture;
    let owner = writer.owner_agent_id().clone();
    drop(writer);
    let writer = Arc::new(
        ProductionDurableWriter::open_with_live_verifier(
            store.clone(),
            authority(&owner, 88),
            verifier,
            LEASE,
            2,
        )
        .await
        .unwrap(),
    );
    let lease = store
        .inspect_local_lease_head(LEASE)
        .await
        .unwrap()
        .head
        .unwrap();
    let authority = writer.authority();
    let forged = serde_json::to_string(&model::Binding {
        origin: original.origin.clone(),
        fence: ObjectiveSenderWriterFence {
            owner_agent_id: owner,
            lease_id: LEASE.into(),
            lease_sha256: lease.lease_sha256.clone(),
            generation: 2,
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            authority_grant_digest: authority.grant_digest.clone(),
            fencing_token_digest: authority.fencing_token_digest().unwrap(),
            expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
        },
    })
    .unwrap();
    let digest = model::event_digest(
        original.identity.original_sha256.as_str(),
        1,
        "permit_issued",
        "null",
        &forged,
        &"0".repeat(64),
    );
    // Controlled corruption keeps the chain digest and referenced lease valid;
    // only the first event's mismatch with its original request must reject it.
    let mut tx = store.pool.begin_with("BEGIN IMMEDIATE").await.unwrap();
    let trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'cognitive_objective_sender_events_no_update'",
    )
    .fetch_one(&mut *tx)
    .await
    .unwrap();
    sqlx::query("DROP TRIGGER cognitive_objective_sender_events_no_update")
        .execute(&mut *tx)
        .await
        .unwrap();
    let changed = sqlx::query("UPDATE cognitive_objective_sender_events SET binding_json = ?, lease_sha256 = ?, event_sha256 = ? WHERE event_sequence = 1")
        .bind(forged).bind(lease.lease_sha256.as_str()).bind(digest.as_str()).execute(&mut *tx).await.unwrap();
    assert_eq!(changed.rows_affected(), 1);
    sqlx::query(
        "CREATE TRIGGER cognitive_objective_sender_events_no_update
BEFORE UPDATE ON cognitive_objective_sender_events BEGIN
    SELECT RAISE(ABORT, 'Objective sender observations are immutable');
END;",
    )
    .execute(&mut *tx)
    .await
    .unwrap();
    let restored: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_schema WHERE name = 'cognitive_objective_sender_events_no_update'",
    )
    .fetch_one(&mut *tx)
    .await
    .unwrap();
    assert_eq!(restored, trigger);
    tx.commit().await.unwrap();
    let sender = writer
        .objective_sender(checkpoint, Duration::from_secs(2))
        .unwrap();
    assert!(matches!(
        sender
            .retained_page(ObjectiveSenderRetainedPosition::Beginning)
            .await,
        Err(ObjectiveSenderError::Store(CognitiveStoreError::Corrupt(_)))
    ));
}
