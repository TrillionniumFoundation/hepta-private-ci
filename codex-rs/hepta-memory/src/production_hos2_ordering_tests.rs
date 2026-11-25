//! Original SQLite admission, terminal event provenance and native retirement.

use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn original_transaction_serializes_namespace_admission_and_blocks_unknown_predecessors()
-> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    let (first, competing) = tokio::join!(
        fixture.prepare("hos2:competing:first", /*sequence*/ 1),
        fixture.prepare("hos2:competing:second", /*sequence*/ 1),
    );
    let queued = match (first, competing) {
        (Ok(queued), Err(_)) | (Err(_), Ok(queued)) => queued,
        pair => return Err(format!("one original D must admit exactly one K: {pair:?}").into()),
    };
    assert!(
        fixture
            .prepare("hos2:premature", /*sequence*/ 2)
            .await
            .is_err()
    );
    assert!(
        fixture
            .prepare("hos2:skipped", /*sequence*/ 3)
            .await
            .is_err()
    );
    let replay = fixture
        .prepare(&queued.occurrence_key, /*sequence*/ 1)
        .await?;
    let mut expected_replay = queued.clone();
    expected_replay.replayed = true;
    assert_eq!(replay, expected_replay);
    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 10).await?;
    assert_eq!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued)
            .await?
            .state,
        LocalOutcomeState::Committed
    );
    let next = fixture
        .prepare("hos2:unknown-predecessor", /*sequence*/ 2)
        .await?;
    fixture
        .writer
        .mark_indeterminate(&next.occurrence_key, "lost process before a durable proof")
        .await?;
    assert_eq!(
        fixture
            .dispatcher
            .reconcile(&fixture.writer, /*limit*/ 8)
            .await?,
        1
    );
    assert!(
        fixture
            .prepare("hos2:still-blocked", /*sequence*/ 3)
            .await
            .is_err()
    );
    assert_eq!(
        fixture.writer.status(&next.occurrence_key).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    let rows: i64 =
        sqlx::query_scalar("SELECT COUNT(*) FROM cognitive_local_outbox WHERE topic = ?")
            .bind(HOS2_INSTALL_TOPIC_V1)
            .fetch_one(&fixture.writer.store.pool)
            .await?;
    assert_eq!(
        rows, 2,
        "failed admission leaves no outbox or reserved sequence"
    );
    Ok(())
}

#[tokio::test]
async fn public_outcome_strings_cannot_create_native_terminal_provenance_or_retirement()
-> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let request = fixture.request(/*sequence*/ 1)?;
    let observation = Hos2DeliveryObservation::Applied {
        stable_object_id: [9; 16],
        previous_revision: 1,
        revision: 2,
        effective_ns: HOS2_CPU_PERIOD_NS + 1_001,
        consumed_ns: 999,
    };
    let forged = format!(
        "{{\"schema_version\":1,\"request\":{},\"observation\":{}}}",
        request.to_json()?,
        serde_json::to_string(&observation)?
    );
    assert!(fixture.writer.apply(OPERATION, &forged).await.is_err());
    assert!(fixture.writer.reject(OPERATION, &forged).await.is_err());
    assert_eq!(
        fixture.writer.status(OPERATION).await?,
        LocalOutcomeState::Queued
    );
    fixture
        .writer
        .mark_indeterminate(OPERATION, "caller says NotSeen")
        .await?;
    assert!(
        fixture
            .writer
            .reconcile(OPERATION, LocalReconcileOutcome::Committed)
            .await
            .is_err()
    );
    assert!(
        fixture
            .writer
            .reconcile(OPERATION, LocalReconcileOutcome::Rejected)
            .await
            .is_err()
    );
    assert!(
        fixture
            .writer
            .rollback_occurrence(OPERATION, "cancel unknown native effect")
            .await
            .is_err()
    );
    assert!(
        fixture
            .writer
            .retire_hos2_through(&fixture.target, &request.delivery)
            .await
            .is_err()
    );
    assert!(
        fixture
            .prepare("hos2:forged-next", /*sequence*/ 2)
            .await
            .is_err()
    );
    assert_eq!(
        fixture.writer.status(OPERATION).await?,
        LocalOutcomeState::Indeterminate
    );
    assert_eq!(
        (
            fixture.device.calls.load(Ordering::SeqCst),
            fixture.device.retire_calls.load(Ordering::SeqCst)
        ),
        (0, 0)
    );
    Ok(())
}

#[tokio::test]
async fn durable_terminal_prefix_rebuilds_after_lost_native_retirement_ack() -> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    let first = fixture
        .prepare("hos2:terminal:first", /*sequence*/ 1)
        .await?;
    let (binding, signed) = fixture.signed(&first, /*nonce*/ 20).await?;
    assert_eq!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, first)
            .await?
            .state,
        LocalOutcomeState::Committed
    );
    let second = fixture
        .prepare("hos2:terminal:second", /*sequence*/ 2)
        .await?;
    fixture.device.terminal_status.store(3, Ordering::SeqCst);
    let (binding, signed) = fixture.signed(&second, /*nonce*/ 21).await?;
    assert_eq!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, second)
            .await?
            .state,
        LocalOutcomeState::Rejected
    );
    let through = fixture.request(/*sequence*/ 2)?.delivery;
    let gap = fixture.request(/*sequence*/ 3)?.delivery;
    let foreign = Hos2DeliveryId::new([1; 16], [3; 16], /*sequence*/ 1)?;
    assert!(
        fixture
            .writer
            .retire_hos2_through(&fixture.target, &gap)
            .await
            .is_err()
    );
    assert!(
        fixture
            .writer
            .retire_hos2_through(&fixture.target, &foreign)
            .await
            .is_err()
    );
    assert_eq!(fixture.device.retire_calls.load(Ordering::SeqCst), 0);
    let cut = fixture.writer.recovery_anchor().await?;
    fixture.device.lose_retire_ack.store(true, Ordering::SeqCst);
    assert!(
        fixture
            .writer
            .retire_hos2_through(&fixture.target, &through)
            .await
            .is_err()
    );
    assert_eq!(fixture.device.retired_through()?, 2);
    assert_eq!(
        fixture.writer.recovery_anchor().await?,
        cut,
        "retirement adds no second source ledger"
    );
    drop(fixture);
    let reopened = Fixture::open(directory.path()).await?;
    assert_eq!(
        reopened.device.query(&through)?,
        Hos2DeliveryObservation::Retired
    );
    assert_eq!(reopened.writer.recovery_anchor().await?, cut);
    assert_eq!(
        reopened
            .writer
            .retire_hos2_through(&reopened.target, &through)
            .await?,
        Hos2RetirementObservation {
            retired_through: 2,
            next_sequence: 3
        }
    );
    let lower = reopened.request(/*sequence*/ 1)?.delivery;
    assert_eq!(
        reopened
            .writer
            .retire_hos2_through(&reopened.target, &lower)
            .await?,
        Hos2RetirementObservation {
            retired_through: 2,
            next_sequence: 3
        }
    );
    assert_eq!(reopened.writer.recovery_anchor().await?, cut);
    assert_eq!(reopened.device.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn lost_effect_ack_blocks_retirement_until_original_observer_persists_full_evidence()
-> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let through = fixture.request(/*sequence*/ 1)?.delivery;
    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 30).await?;
    fixture.device.lose_ack.store(true, Ordering::SeqCst);
    assert_eq!(
        fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued)
            .await?
            .state,
        LocalOutcomeState::Indeterminate
    );
    assert!(
        fixture
            .writer
            .retire_hos2_through(&fixture.target, &through)
            .await
            .is_err()
    );
    assert_eq!(fixture.device.retire_calls.load(Ordering::SeqCst), 0);
    assert_eq!(
        fixture
            .dispatcher
            .reconcile(&fixture.writer, /*limit*/ 8)
            .await?,
        1
    );
    assert_eq!(
        fixture.writer.status(OPERATION).await?,
        LocalOutcomeState::Committed
    );
    assert_eq!(
        fixture
            .writer
            .retire_hos2_through(&fixture.target, &through)
            .await?,
        Hos2RetirementObservation {
            retired_through: 1,
            next_sequence: 2
        }
    );
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn queued_native_cancellation_remains_available_before_effect_boundary() -> TestResult {
    let directory = tempfile::tempdir()?;
    let fixture = Fixture::open(directory.path()).await?;
    fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let cancelled = fixture
        .writer
        .rollback_occurrence(OPERATION, "cancel before dispatch")
        .await?;
    assert_eq!(cancelled.state, LocalOutcomeState::RolledBack);
    assert_eq!(
        fixture.writer.status(OPERATION).await?,
        LocalOutcomeState::RolledBack
    );
    assert_eq!(
        (
            fixture.device.calls.load(Ordering::SeqCst),
            fixture.device.retire_calls.load(Ordering::SeqCst)
        ),
        (0, 0)
    );
    Ok(())
}
