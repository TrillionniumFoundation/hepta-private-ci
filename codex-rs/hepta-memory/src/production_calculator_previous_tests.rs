//! Explicit recovery-channel fixture over the original SQLite source owner.
//! This proves owner binding and durable ordering, not a real helper execution.
use super::*;
use crate::CalculatorRecoveryChannel;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

struct RecoveryFixture {
    target: CalculatorTargetIdentity,
    operation: String,
    payload: Sha256Digest,
    receipt: String,
    queries: AtomicUsize,
    acknowledgements: AtomicUsize,
    lose_first_ack: AtomicBool,
}
impl CalculatorRecoveryChannel for RecoveryFixture {
    fn exchange(&self, bytes: &[u8]) -> Result<Vec<u8>, String> {
        let request: Value = serde_json::from_slice(bytes).map_err(|error| error.to_string())?;
        self.queries.fetch_add(1, Ordering::SeqCst);
        assert_eq!(request["target"], json!(self.target));
        assert_eq!(request["operation_id"], self.operation);
        assert_eq!(request["payload_sha256"], self.payload.as_str());
        match request["action"].as_str() {
            Some("observe") => Ok(self.receipt.as_bytes().to_vec()),
            Some("acknowledge") => {
                let digest = Sha256Digest::for_bytes(self.receipt.as_bytes());
                assert_eq!(request["receipt_sha256"], digest.as_str());
                self.acknowledgements.fetch_add(1, Ordering::SeqCst);
                if self.lose_first_ack.swap(false, Ordering::SeqCst) {
                    return Err("fixture lost acknowledgement after application retirement".into());
                }
                serde_json::to_vec(&json!({
                    "schema_version":1, "action":"acknowledged", "target":self.target,
                    "operation_id":self.operation, "payload_sha256":self.payload.as_str(),
                    "receipt_sha256":digest.as_str(), "status":"already_retired"
                }))
                .map_err(|error| error.to_string())
            }
            _ => panic!("recovery cannot discover or dispatch another operation"),
        }
    }
}
fn recovery_channel(
    target: &CalculatorTargetIdentity,
    payload: &str,
    receipt: String,
) -> TestResult<Arc<RecoveryFixture>> {
    let request: Value = serde_json::from_str(payload)?;
    Ok(Arc::new(RecoveryFixture {
        target: target.clone(),
        operation: request["operation_id"]
            .as_str()
            .ok_or("operation")?
            .to_owned(),
        payload: Sha256Digest::for_bytes(payload.as_bytes()),
        receipt,
        queries: AtomicUsize::new(0),
        acknowledgements: AtomicUsize::new(0),
        lose_first_ack: AtomicBool::new(true),
    }))
}

#[tokio::test]
async fn calculator_previous_recovery_preserves_exact_terminal_and_retries_only_retirement()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18")?;
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
    let (payload, identity, observer) = fixture()?;
    let channel = recovery_channel(&identity, &payload, observer.receipt)?;
    let operation = prepare(&writer, payload, &identity).await?;
    let before = store.recovery_anchor().await?;
    let recovery = writer
        .calculator_recovery_target_for_retained_operation(
            identity.clone(),
            &operation,
            channel.clone(),
        )
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
    let mut foreign = writer
        .reconciliation_request(&operation, &identity.destination_id())
        .await?;
    foreign.occurrence_key = "foreign-operation".into();
    assert!(matches!(
        recovery.observe_terminal(&foreign).await,
        ProductionTerminalObservation::Unavailable { .. }
    ));
    assert_eq!(channel.queries.load(Ordering::SeqCst), 0);
    assert_eq!(writer.reconcile_target_batch(&recovery, 1).await?, 1);
    assert_eq!(
        writer.status(&operation).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(channel.queries.load(Ordering::SeqCst), 2);
    assert_eq!(channel.acknowledgements.load(Ordering::SeqCst), 1);
    assert_eq!(
        writer
            .retained_calculator_terminal_receipt(&operation)
            .await?,
        Some(channel.receipt.clone())
    );
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
        .calculator_recovery_target_for_retained_operation(identity, &operation, channel.clone())
        .await?;
    assert_eq!(writer.reconcile_target_batch(&recovery, 1).await?, 0);
    assert_eq!(
        channel.queries.load(Ordering::SeqCst),
        3,
        "committed source retries only exact ACK"
    );
    assert_eq!(channel.acknowledgements.load(Ordering::SeqCst), 2);
    let events: Vec<String> = sqlx::query_scalar(
        "SELECT payload_json FROM cognitive_local_events WHERE occurrence_key = ? AND event_kind = 'reconcile_committed'"
    ).bind(&operation).fetch_all(&reopened.pool).await?;
    assert_eq!(events, vec![channel.receipt.clone()]);
    Ok(())
}

#[tokio::test]
async fn calculator_previous_recovery_refuses_missing_queued_and_other_incarnation_before_io()
-> TestResult {
    let temp = tempfile::tempdir()?;
    let fleet_path = temp.path().join("fleet");
    std::fs::create_dir(&fleet_path)?;
    let fleet = HeptaFleetRoot::parse(fleet_path.canonicalize()?)?;
    let owner = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2d18")?;
    let store = CognitiveStore::open(&fleet.layout().agent(&owner)).await?;
    let writer = ProductionDurableWriter::open_with_live_verifier(
        store.clone(),
        source(&owner, 1)?,
        Arc::new(Verifier),
        LEASE,
        1,
    )
    .await?;
    let (payload, identity, observer) = fixture()?;
    let channel = recovery_channel(&identity, &payload, observer.receipt)?;
    assert!(
        writer
            .calculator_recovery_target_for_retained_operation(
                identity.clone(),
                "missing-original-operation",
                channel.clone(),
            )
            .await
            .is_err()
    );
    let intent = calculator_operation_intent(
        &identity,
        &payload,
        StableId::new(owner.as_str())?,
        Generation::new(1)?,
    )?;
    let queued = writer
        .prepare_operation(intent, crate::CALCULATOR_EVALUATE_TOPIC_V1, payload)
        .await?;
    assert!(
        writer
            .calculator_recovery_target_for_retained_operation(
                identity.clone(),
                &queued.occurrence_key,
                channel.clone(),
            )
            .await
            .is_err()
    );
    writer
        .mark_indeterminate(&queued.occurrence_key, "fixture lost effect reply")
        .await?;
    let anchor = store.recovery_anchor().await?;
    let mut wrong = identity;
    wrong.incarnation = "e".repeat(32);
    assert!(
        writer
            .calculator_recovery_target_for_retained_operation(
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
