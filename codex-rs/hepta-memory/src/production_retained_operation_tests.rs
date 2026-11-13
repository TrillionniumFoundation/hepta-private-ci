use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn retained_operation_reads_exact_original_bytes_without_a_new_event_or_dispatch_right()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d38")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store,
        source(&owner, /*epoch*/ 1)?,
        Arc::new(Verifier),
        LEASE,
        /*generation*/ 1,
    )
    .await?;
    assert!(writer.retained_operation("absent").await?.is_none());
    let (payload, target, _) = fixture()?;
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
    let retained = writer
        .retained_operation(operation.operation_id().as_str())
        .await?
        .ok_or("missing original operation")?;
    assert_eq!(
        (
            retained.operation,
            retained.payload_json,
            retained.topic,
            retained.state
        ),
        (
            operation.clone(),
            payload.clone(),
            crate::NOTES_REPLACE_TOPIC_V1.to_string(),
            LocalOutcomeState::Queued
        )
    );
    assert_eq!(writer.recovery_anchor().await?, before);
    writer
        .mark_indeterminate(queued.occurrence_key, "fixture effect outcome unknown")
        .await?;
    let before = writer.recovery_anchor().await?;
    assert_eq!(
        writer
            .retained_operation(operation.operation_id().as_str())
            .await?
            .ok_or("missing original operation")?
            .state,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(writer.recovery_anchor().await?, before);
    let transaction = writer.store().pool.begin_with("BEGIN IMMEDIATE").await?;
    drop(writer.store().commit_gate.checkpoint_attempt());
    transaction.rollback().await?;
    assert!(writer.checkpoint_fenced());
    let retained = writer
        .retained_operation(operation.operation_id().as_str())
        .await?
        .ok_or("fenced generation lost its read-only operation")?;
    assert_eq!(
        (retained.operation, retained.payload_json, retained.state),
        (
            operation.clone(),
            payload.clone(),
            LocalOutcomeState::Indeterminate
        )
    );
    assert_eq!(writer.recovery_anchor().await?, before);
    assert!(
        writer
            .prepare_operation(operation, crate::NOTES_REPLACE_TOPIC_V1, payload)
            .await
            .is_err()
    );
    Ok(())
}
