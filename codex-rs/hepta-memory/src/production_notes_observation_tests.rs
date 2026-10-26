//! Original SQLite owner observations; fixture evidence is not a real device.
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn notes_terminal_projection_reopens_exact_receipt_without_dispatch_or_retirement()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d39")?;
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let authority = source(&owner, /*epoch*/ 1)?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority.clone(),
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let (payload, target, observer) = fixture()?;
    let operation = notes_operation_intent(
        &target,
        &payload,
        StableId::new(owner.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = writer
        .prepare_operation(
            operation.clone(),
            crate::NOTES_REPLACE_TOPIC_V1,
            payload.clone(),
        )
        .await?;
    let before = writer.recovery_anchor().await?;
    assert_eq!(writer.observe_notes_terminal("absent").await?, None);
    assert_eq!(
        writer
            .observe_notes_terminal(&queued.occurrence_key)
            .await?,
        None
    );
    assert_eq!(writer.recovery_anchor().await?, before);
    writer
        .mark_indeterminate(&queued.occurrence_key, "fixture lost effect reply")
        .await?;
    let uncertain = writer.recovery_anchor().await?;
    assert_eq!(
        writer
            .observe_notes_terminal(&queued.occurrence_key)
            .await?,
        None
    );
    assert_eq!(writer.recovery_anchor().await?, uncertain);
    assert_eq!(
        writer
            .reconcile_target_batch(&observer, /*limit*/ 1)
            .await?,
        1
    );
    let before = writer.recovery_anchor().await?;
    let observation = writer
        .observe_notes_terminal(&queued.occurrence_key)
        .await?
        .ok_or("missing original Notes receipt")?;
    assert_eq!(
        (
            observation.operation.clone(),
            observation.payload_json.clone(),
            observation.state,
            observation.application_receipt_json.clone(),
            observation.application_receipt_sha256.clone(),
            observation.terminal_generation,
        ),
        (
            operation,
            payload,
            LocalOutcomeState::Committed,
            observer.receipt.clone(),
            Sha256Digest::for_bytes(observer.receipt.as_bytes()),
            1,
        )
    );
    assert_eq!(
        writer
            .observe_notes_terminal(&queued.occurrence_key)
            .await?,
        Some(observation.clone())
    );
    assert_eq!(writer.recovery_anchor().await?, before);
    assert_eq!(
        (
            observer.observations.load(Ordering::SeqCst),
            observer.retirements.load(Ordering::SeqCst)
        ),
        (1, 1)
    );
    drop(writer);
    store.close().await;
    let reopened_store = CognitiveStore::open(&layout).await?;
    let reopened = ProductionDurableWriter::open_with_live_verifier(
        reopened_store.clone(),
        authority,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let before = reopened.recovery_anchor().await?;
    assert_eq!(
        reopened
            .observe_notes_terminal(&queued.occurrence_key)
            .await?,
        Some(observation.clone())
    );
    assert_eq!(reopened.recovery_anchor().await?, before);
    assert_eq!(
        (
            observer.observations.load(Ordering::SeqCst),
            observer.retirements.load(Ordering::SeqCst)
        ),
        (1, 1)
    );
    // Simulate offline corruption, restoring the original immutable trigger so
    // the read must reject the changed terminal payload itself.
    let trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_master
         WHERE type = 'trigger' AND name = 'cognitive_local_events_no_update'",
    )
    .fetch_one(&reopened_store.pool)
    .await?;
    sqlx::query("DROP TRIGGER cognitive_local_events_no_update")
        .execute(&reopened_store.pool)
        .await?;
    sqlx::query(
        "UPDATE cognitive_local_events SET payload_json = 'changed receipt' WHERE event_id = ?",
    )
    .bind(&observation.terminal_event_id)
    .execute(&reopened_store.pool)
    .await?;
    sqlx::query(concat!(
        "CREATE TRIGGER cognitive_local_events_no_update\n",
        "BEFORE UPDATE ON cognitive_local_events BEGIN\n",
        "    SELECT RAISE(ABORT, 'local events are immutable');\n",
        "END;",
    ))
    .execute(&reopened_store.pool)
    .await?;
    let restored_trigger: String = sqlx::query_scalar(
        "SELECT sql FROM sqlite_master
         WHERE type = 'trigger' AND name = 'cognitive_local_events_no_update'",
    )
    .fetch_one(&reopened_store.pool)
    .await?;
    assert_eq!(restored_trigger, trigger);
    assert!(
        reopened
            .observe_notes_terminal(&queued.occurrence_key)
            .await
            .is_err()
    );
    Ok(())
}

#[tokio::test]
async fn notes_terminal_projection_preserves_original_application_rejection() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d40")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store,
        source(&owner, /*epoch*/ 1)?,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    let (payload, target, observer) = fixture()?;
    let operation_id = prepare(&writer, payload, &target).await?;
    let mut evidence: serde_json::Value = serde_json::from_str(&observer.receipt)?;
    evidence["result"] = serde_json::json!({
        "status": "not_applied", "reason": "revision_conflict", "current_revision": 19,
    });
    let evidence = serde_json::to_string(&evidence)?;
    let request = writer
        .reconciliation_request(&operation_id, &target.destination_id())
        .await?;
    let original = writer
        .settle_notes_terminal(&request, &evidence, LocalReconcileOutcome::Rejected)
        .await?;
    let before = writer.recovery_anchor().await?;
    let observed = writer
        .observe_notes_terminal(&operation_id)
        .await?
        .ok_or("missing rejection")?;
    assert_eq!(
        (
            observed.state,
            observed.application_receipt_json,
            observed.terminal_event_id
        ),
        (LocalOutcomeState::Rejected, evidence, original.event_id)
    );
    assert_eq!(writer.recovery_anchor().await?, before);
    assert_eq!(
        (
            observer.observations.load(Ordering::SeqCst),
            observer.retirements.load(Ordering::SeqCst)
        ),
        (0, 0)
    );
    Ok(())
}
