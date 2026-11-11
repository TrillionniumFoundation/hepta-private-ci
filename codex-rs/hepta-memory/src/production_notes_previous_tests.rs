//! Explicit application fixture over the original SQLite owner. No production
//! issuer or application durability is inferred from the simulated channel.
use super::*;
use crate::NotesPrivateChannel;
use crate::NotesRecoveryChannel;
use crate::ProductionNotesTarget;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

struct RecoveryFixture {
    discovery: Value,
    golden: Value,
    receipt: String,
    queries: AtomicUsize,
    acknowledgements: AtomicUsize,
}
impl NotesRecoveryChannel for RecoveryFixture {
    fn exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, String> {
        let request: Value = serde_json::from_slice(bytes).unwrap();
        self.queries.fetch_add(1, Ordering::SeqCst);
        match request["action"].as_str().unwrap() {
            "read_previous_receipt" => {
                let mut response = self.discovery.clone();
                if let Some(object) = response.as_object_mut() {
                    // The fixture normally correlates random or golden nonces;
                    // a deliberately bad nonce is preserved for the negative.
                    if object.get("request_id") == Some(&json!("5".repeat(32))) {
                        object.insert("request_id".into(), request["request_id"].clone());
                    }
                }
                Ok(serde_json::to_vec(&response).unwrap())
            }
            "observe" => {
                assert_eq!(
                    request,
                    serde_json::from_str::<Value>(
                        self.golden["observe_previous_utf8"].as_str().unwrap()
                    )
                    .unwrap()
                );
                Ok(self.receipt.as_bytes().to_vec())
            }
            "acknowledge_terminal" => {
                assert_eq!(
                    request,
                    serde_json::from_str::<Value>(
                        self.golden["acknowledge_previous_utf8"].as_str().unwrap()
                    )
                    .unwrap()
                );
                if self.acknowledgements.fetch_add(1, Ordering::SeqCst) == 0 {
                    Err("fixture loses the first metadata ACK before application retirement".into())
                } else {
                    Ok(self.golden["retired_previous_utf8"]
                        .as_str()
                        .unwrap()
                        .as_bytes()
                        .to_vec())
                }
            }
            _ => panic!("recovery fixture received an effect"),
        }
    }
}
struct CurrentChannel(Arc<RecoveryFixture>);
impl NotesPrivateChannel for CurrentChannel {
    fn exchange(&self, _: &[u8]) -> Result<Vec<u8>, String> {
        panic!("old receipt recovery entered current effect")
    }
    fn invalidate(&self) {
        panic!("old receipt recovery invalidated current effect")
    }
    fn recovery_handle(&self) -> Result<Arc<dyn NotesRecoveryChannel>, String> {
        Ok(self.0.clone())
    }
}
fn channel(
    discovery: Option<Value>,
) -> TestResult<(crate::ProductionNotesObserver, Arc<RecoveryFixture>)> {
    let golden: Value = serde_json::from_str(include_str!(
        "../tests/fixtures/notes-previous-receipt-v1.json"
    ))?;
    let response: Value =
        serde_json::from_str(golden["response_utf8"].as_str().ok_or("response")?)?;
    let target = serde_json::from_value(response["target"].clone())?;
    let (_, _, original) = fixture()?;
    let channel = Arc::new(RecoveryFixture {
        discovery: discovery.unwrap_or(response),
        golden,
        receipt: original.receipt,
        queries: AtomicUsize::new(0),
        acknowledgements: AtomicUsize::new(0),
    });
    let observer = ProductionNotesTarget::new(target, Arc::new(CurrentChannel(channel.clone())))?
        .document_observer();
    Ok((observer, channel))
}

#[tokio::test]
async fn notes_explicit_previous_source_reopens_and_retires_without_discovery() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d14")?;
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let authority = source(&owner, 1)?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority.clone(),
        Arc::new(Verifier),
        LEASE,
        1,
    )
    .await?;
    let (payload, identity, _) = fixture()?;
    let operation = prepare(&writer, payload, &identity).await?;
    let (_, channel) = channel(None)?;
    let before = store.recovery_anchor().await?;
    let recovery = writer
        .notes_recovery_target_for_retained_operation(identity.clone(), &operation, channel.clone())
        .await?;
    assert_eq!(store.recovery_anchor().await?, before);
    assert_eq!(channel.queries.load(Ordering::SeqCst), 0);
    let request = writer
        .reconciliation_request(&operation, &identity.destination_id())
        .await?;
    assert!(matches!(
        recovery.dispatch(request).await,
        ProductionTargetOutcome::Rejected { .. }
    ));
    assert_eq!(channel.queries.load(Ordering::SeqCst), 0);
    assert_eq!(writer.reconcile_target_batch(&recovery, 1).await?, 1);
    assert_eq!(
        writer.status(&operation).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        channel.queries.load(Ordering::SeqCst),
        2,
        "only observe and ACK, no discovery"
    );
    assert_eq!(channel.acknowledgements.load(Ordering::SeqCst), 1);
    drop(recovery);
    drop(writer);
    store.close().await;
    let reopened = CognitiveStore::open(&layout).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        reopened.clone(),
        authority,
        Arc::new(Verifier),
        LEASE,
        1,
    )
    .await?;
    let recovery = writer
        .notes_recovery_target_for_retained_operation(identity, &operation, channel.clone())
        .await?;
    assert_eq!(writer.reconcile_target_batch(&recovery, 1).await?, 0);
    assert_eq!(
        channel.queries.load(Ordering::SeqCst),
        3,
        "committed source only retries its exact ACK"
    );
    assert_eq!(channel.acknowledgements.load(Ordering::SeqCst), 2);
    let events: Vec<String> = sqlx::query_scalar("SELECT payload_json FROM cognitive_local_events WHERE occurrence_key = ? AND event_kind = 'reconcile_committed'")
        .bind(&operation).fetch_all(&reopened.pool).await?;
    assert_eq!(events, vec![channel.receipt.clone()]);
    Ok(())
}

#[tokio::test]
async fn notes_explicit_previous_refuses_unknown_queued_and_wrong_target_before_io() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d15")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        source(&owner, 1)?,
        Arc::new(Verifier),
        LEASE,
        1,
    )
    .await?;
    let (payload, identity, _) = fixture()?;
    let (_, channel) = channel(None)?;
    assert!(
        writer
            .notes_recovery_target_for_retained_operation(
                identity.clone(),
                "missing-original-operation",
                channel.clone(),
            )
            .await
            .is_err()
    );
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(owner.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = writer
        .prepare_operation(intent, crate::NOTES_REPLACE_TOPIC_V1, payload)
        .await?;
    assert!(
        writer
            .notes_recovery_target_for_retained_operation(
                identity.clone(),
                &queued.occurrence_key,
                channel.clone(),
            )
            .await
            .is_err()
    );
    writer
        .mark_indeterminate(&queued.occurrence_key, "explicit fixture lost effect reply")
        .await?;
    let anchor = store.recovery_anchor().await?;
    let mut wrong = identity;
    wrong.incarnation = "e".repeat(32);
    assert!(
        writer
            .notes_recovery_target_for_retained_operation(
                wrong,
                &queued.occurrence_key,
                channel.clone(),
            )
            .await
            .is_err()
    );
    assert_eq!(store.recovery_anchor().await?, anchor);
    assert_eq!(channel.queries.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn notes_objective_previous_receipt_recovers_original_owner_and_retires_without_effect()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d12")?;
    let layout = fleet.layout().agent(&owner);
    let store = CognitiveStore::open(&layout).await?;
    let authority = source(&owner, 1)?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        authority.clone(),
        Arc::new(Verifier),
        LEASE,
        1,
    )
    .await?;
    let (payload, identity, _) = fixture()?;
    let operation = prepare(&writer, payload, &identity).await?;
    let (observer, channel) = channel(None)?;
    let before = store.recovery_anchor().await?;
    let recovery = writer
        .previous_notes_recovery_target(&observer, &"5".repeat(32))
        .await?
        .ok_or("recovery target")?;
    assert_eq!(
        store.recovery_anchor().await?,
        before,
        "discovery is only original-owner reading"
    );
    let request = writer
        .reconciliation_request(&operation, &identity.destination_id())
        .await?;
    assert!(matches!(
        recovery.dispatch(request).await,
        ProductionTargetOutcome::Rejected { .. }
    ));
    assert_eq!(
        channel.queries.load(Ordering::SeqCst),
        1,
        "even an explicit dispatch attempt has no endpoint"
    );
    assert_eq!(writer.reconcile_target_batch(&recovery, 1).await?, 1);
    assert_eq!(
        writer.status(&operation).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(channel.acknowledgements.load(Ordering::SeqCst), 1);
    drop(recovery);
    drop(writer);
    store.close().await;
    let reopened_store = CognitiveStore::open(&layout).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        reopened_store.clone(),
        authority,
        Arc::new(Verifier),
        LEASE,
        1,
    )
    .await?;
    let recovery = writer
        .previous_notes_recovery_target(&observer, &"6".repeat(32))
        .await?
        .ok_or("retirement recovery")?;
    assert_eq!(
        writer.reconcile_target_batch(&recovery, 1).await?,
        0,
        "terminal source never re-executes"
    );
    assert_eq!(channel.acknowledgements.load(Ordering::SeqCst), 2);
    let events: Vec<String> = sqlx::query_scalar("SELECT payload_json FROM cognitive_local_events WHERE occurrence_key = ? AND event_kind = 'reconcile_committed'").bind(&operation).fetch_all(&reopened_store.pool).await?;
    assert_eq!(events, vec![channel.receipt.clone()]);
    Ok(())
}

#[tokio::test]
async fn notes_objective_previous_receipt_refuses_mismatched_discovery_and_unexecuted_originals()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d13")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        source(&owner, 1)?,
        Arc::new(Verifier),
        LEASE,
        1,
    )
    .await?;
    let (payload, identity, _) = fixture()?;
    let intent = notes_operation_intent(
        &identity,
        &payload,
        StableId::new(owner.as_str())?,
        Generation::new(1)?,
    )?;
    writer
        .prepare_operation(intent, crate::NOTES_REPLACE_TOPIC_V1, payload.clone())
        .await?;
    let (observer, valid) = channel(None)?;
    assert!(
        writer
            .previous_notes_recovery_target(&observer, &"5".repeat(32))
            .await
            .is_err(),
        "a queued source cannot become applied via discovery"
    );
    writer
        .mark_indeterminate("fixture-notes-v1", "explicit fixture effect uncertainty")
        .await?;
    let anchor = store.recovery_anchor().await?;
    for change in 0..11 {
        let mut invalid = valid.discovery.clone();
        match change {
            0 => {
                invalid.as_object_mut().unwrap().remove("pending_receipt");
            }
            1 => invalid["target"]["task_id"] = json!(2),
            2 => invalid["request_id"] = json!("7".repeat(32)),
            3 => invalid["action"] = json!("document_state"),
            4 => invalid["schema_version"] = json!(2),
            5 => invalid["pending_receipt"]["payload_sha256"] = json!("0".repeat(64)),
            6 => invalid["pending_receipt"]["operation_id"] = json!("absent-operation"),
            7 => invalid["pending_receipt"]["result"]["revision"] = json!(5),
            8 => invalid["pending_receipt"]["target"] = invalid["target"].clone(),
            9 => {
                invalid["pending_receipt"]["result"] =
                    json!({"status":"unknown","current_revision":1})
            }
            10 => invalid["pending_receipt"]["extra_authority"] = json!(true),
            _ => unreachable!(),
        }
        let (observer, _) = channel(Some(invalid))?;
        assert!(
            writer
                .previous_notes_recovery_target(&observer, &"5".repeat(32))
                .await
                .is_err(),
            "invalid prior receipt case {change}"
        );
    }
    let mut absent = valid.discovery.clone();
    absent["pending_receipt"] = Value::Null;
    let (observer, _) = channel(Some(absent))?;
    assert!(
        writer
            .previous_notes_recovery_target(&observer, &"5".repeat(32))
            .await?
            .is_none()
    );
    assert_eq!(store.recovery_anchor().await?, anchor);
    Ok(())
}
