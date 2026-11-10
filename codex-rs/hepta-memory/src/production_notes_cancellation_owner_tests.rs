use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn notes_cancellation_is_distinct_and_recovered_through_original_typed_owner() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18")?;
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let authority = source(&owner, 1)?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(), authority, Arc::new(Verifier), LEASE, /*generation*/ 1,
    ).await?;
    let (payload, identity, _) = fixture()?;
    let original = prepare(&writer, payload.clone(), &identity).await?;
    let cancellation = writer.prepare_notes_cancellation(&original, "original-cancel").await?;
    assert_eq!(writer.status(&original).await?, LocalOutcomeState::Indeterminate);
    assert_eq!(cancellation.occurrence_key, "original-cancel");
    let retained = writer.retained_operation(&cancellation.occurrence_key).await?.ok_or("retained cancellation")?;
    assert_eq!(retained.topic, crate::NOTES_FENCE_TOPIC_V1);
    let request: serde_json::Value = serde_json::from_str(&retained.payload_json)?;
    let original_request: serde_json::Value = serde_json::from_str(&payload)?;
    assert_eq!(request["original_operation_id"], original);
    assert_eq!(request["original_payload_sha256"], Sha256Digest::for_bytes(payload.as_bytes()).as_str());
    assert!(
        writer
            .settle_notes_original_from_fence(&original, &cancellation.occurrence_key)
            .await
            .is_err(),
        "a queued fence cannot settle the original"
    );
    writer.mark_indeterminate(&cancellation.occurrence_key, "explicit fixture lost fence reply").await?;
    assert!(writer.reconcile(&cancellation.occurrence_key, LocalReconcileOutcome::Committed).await.is_err());
    let revision = original_request["expected_revision"].as_u64().ok_or("expected revision")?;
    let fence_receipt = serde_json::json!({"schema_version":1,"target":identity,"operation_id":cancellation.occurrence_key,
        "payload_sha256":Sha256Digest::for_bytes(retained.payload_json.as_bytes()).as_str(),
        "result":{"status":"fenced","original_operation_id":original,
            "original_payload_sha256":Sha256Digest::for_bytes(payload.as_bytes()).as_str(),
            "previous_revision":revision,"revision":revision+1,"text_sha256":Sha256Digest::for_bytes(b"").as_str()}}).to_string();
    let dispatch = writer.reconciliation_request(&cancellation.occurrence_key, &identity.destination_id()).await?;
    writer.settle_notes_terminal(&dispatch, &fence_receipt, LocalReconcileOutcome::Committed).await?;
    assert_eq!(writer.retained_notes_terminal_receipt(&cancellation.occurrence_key).await?, Some(fence_receipt.clone()));
    let settled = writer
        .settle_notes_original_from_fence(&original, &cancellation.occurrence_key)
        .await?;
    assert_eq!(settled.state, LocalOutcomeState::Rejected);
    assert!(!settled.external_effect);
    assert_eq!(writer.status(&original).await?, LocalOutcomeState::Rejected);
    assert_eq!(writer.retained_notes_terminal_receipt(&original).await?, None);
    let source_settlement: String = sqlx::query_scalar(
        "SELECT payload_json FROM cognitive_local_events
         WHERE lease_id = ? AND occurrence_key = ?
           AND event_kind = 'notes_fence_excluded'",
    )
    .bind(writer.lease_id())
    .bind(&original)
    .fetch_one(&store.pool)
    .await?;
    let source_settlement: serde_json::Value = serde_json::from_str(&source_settlement)?;
    assert_eq!(
        source_settlement["disposition"],
        "original_excluded_by_committed_fence"
    );
    assert_eq!(
        source_settlement["cancellation_operation_id"],
        cancellation.occurrence_key
    );
    assert!(source_settlement.get("status").is_none());
    let target = Observer { destination: identity.destination_id(), receipt: fence_receipt,
        observations: AtomicUsize::new(0), retirements: AtomicUsize::new(0), lose_first_ack: AtomicBool::new(false) };
    writer.retire_notes_receipt(&target, &cancellation.occurrence_key).await?;
    assert_eq!(target.retirements.load(Ordering::SeqCst), 1);
    assert_eq!(target.observations.load(Ordering::SeqCst), 0);
    drop(writer);
    drop(store);
    let reopened = CognitiveStore::open(&layout).await?;
    let replayed: String = sqlx::query_scalar(
        "SELECT event_kind FROM cognitive_local_events
         WHERE occurrence_key = ? ORDER BY event_sequence DESC LIMIT 1",
    )
    .bind(&original)
    .fetch_one(&reopened.pool)
    .await?;
    assert_eq!(replayed, "notes_fence_excluded");
    Ok(())
}
