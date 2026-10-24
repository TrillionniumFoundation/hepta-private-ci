//! Original SQLite/final-use owner regression tests for Stop versus drain.
//! The existing durable test device is not a kernel/Root qualification.

use super::*;
use pretty_assertions::assert_eq;

type RetainedEvents = Vec<(
    i64,
    String,
    i64,
    String,
    String,
    String,
    String,
    String,
    String,
)>;

async fn retained_events(fixture: &Fixture) -> TestResult<RetainedEvents> {
    Ok(sqlx::query_as(
        "SELECT event_sequence, event_id, generation, fencing_token, event_kind,
                payload_json, payload_sha256, previous_sha256, event_sha256
         FROM cognitive_local_events WHERE lease_id = ? AND occurrence_key = ?
         ORDER BY event_sequence",
    )
    .bind(LEASE)
    .bind(OPERATION)
    .fetch_all(fixture.writer.store.observation_pool())
    .await?)
}

async fn expired_unknown() -> TestResult<(tempfile::TempDir, Fixture, ProductionQueuedReceipt)> {
    let temp = tempfile::tempdir()?;
    let issued_expiry = now_unix_seconds()? + HANDOFF_PREPARATION_LIFETIME_SECONDS;
    let old = Fixture::open_generation(temp.path(), 1, issued_expiry).await?;
    let queued = old.prepare(OPERATION, 1).await?;
    old.device.lose_ack.store(true, Ordering::SeqCst);
    let (binding, signed) = old.signed(&queued, 1).await?;
    let unknown = old
        .dispatcher
        .dispatch(&old.writer, &signed, &binding, queued.clone())
        .await?;
    assert_eq!(unknown.state, LocalOutcomeState::Indeterminate);
    assert_eq!(old.device.calls.load(Ordering::SeqCst), 1);
    let persisted_expiry = original_lease_expiry(&old).await?;
    assert_eq!(persisted_expiry, issued_expiry);
    drop(old);
    let delay = persisted_expiry.saturating_sub(now_unix_seconds()?);
    tokio::time::sleep(Duration::from_secs(delay) + Duration::from_millis(20)).await;
    assert!(now_unix_seconds()? >= persisted_expiry);
    // The original opener records actual expiry and takes the next fence.
    // No fixture clock or already issued lease is changed.
    let next = Fixture::open_generation(temp.path(), 2, 4_000_000_000).await?;
    assert_eq!(next.writer.generation(), 2);
    assert_eq!(next.writer.hos2_drain_blockers().await?, 1);
    assert_eq!(
        next.writer.status(OPERATION).await?,
        LocalOutcomeState::Indeterminate
    );
    Ok((temp, next, queued))
}

#[tokio::test]
async fn native_stop_refuses_current_queued_and_indeterminate_work() -> TestResult {
    // A failed managed transition is fail-closed. Each refusal therefore has
    // its own owner; this test never asks a refused owner to resume writing.
    for indeterminate in [false, true] {
        let temp = tempfile::tempdir()?;
        let fixture = Fixture::open(temp.path()).await?;
        let queued = fixture.prepare(OPERATION, 1).await?;
        if indeterminate {
            fixture.device.lose_ack.store(true, Ordering::SeqCst);
            let (binding, signed) = fixture.signed(&queued, 1).await?;
            let actual = fixture
                .dispatcher
                .dispatch(&fixture.writer, &signed, &binding, queued)
                .await?;
            assert_eq!(actual.state, LocalOutcomeState::Indeterminate);
        }
        let before = fixture.writer.recovery_anchor().await?;
        assert_eq!(fixture.writer.hos2_drain_blockers().await?, 1);
        assert!(matches!(
            fixture.writer.release().await,
            Err(ProductionWriterError::Local(
                LocalLeaseOutboxError::IllegalTransition(_)
            ))
        ));
        assert_eq!(fixture.writer.recovery_anchor().await?, before);
        assert_eq!(
            fixture.device.calls.load(Ordering::SeqCst),
            usize::from(indeterminate)
        );
    }
    Ok(())
}

#[tokio::test]
async fn native_stop_releases_a_terminal_reconciled_from_an_expired_generation() -> TestResult {
    let (temp, successor, _) = expired_unknown().await?;
    assert_eq!(
        successor.dispatcher.reconcile(&successor.writer, 8).await?,
        1
    );
    let terminal = successor.writer.retained_hos2_terminal(OPERATION).await?;
    assert_eq!(terminal.1.state, LocalOutcomeState::Committed);
    assert_eq!(successor.writer.hos2_drain_blockers().await?, 0);
    assert_eq!(successor.device.calls.load(Ordering::SeqCst), 0);
    let released = successor.writer.release().await?;
    assert_eq!(released.generation, 2);
    assert_eq!(released.state, "released");
    drop(successor);
    let next = Fixture::open_generation(temp.path(), 3, 4_000_000_000).await?;
    assert_eq!(
        next.writer.retained_hos2_terminal(OPERATION).await?,
        terminal
    );
    assert_eq!(next.writer.hos2_drain_blockers().await?, 0);
    assert_eq!(next.device.calls.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn native_stop_refuses_an_inherited_unknown_claimed_by_the_current_fence() -> TestResult {
    let (_temp, successor, _) = expired_unknown().await?;
    let receipt = successor
        .writer
        .reconcile(OPERATION, LocalReconcileOutcome::StillIndeterminate)
        .await?;
    assert_eq!(receipt.state, LocalOutcomeState::Indeterminate);
    let events = retained_events(&successor).await?;
    assert!(
        events
            .iter()
            .any(|row| row.2 == 2 && row.4 == "reconcile_still_indeterminate")
    );
    let before = successor.writer.recovery_anchor().await?;
    // This is an actual current-generation responsibility, even though its
    // immutable admission belongs to the expired predecessor.
    assert!(matches!(
        successor.writer.release().await,
        Err(ProductionWriterError::Local(
            LocalLeaseOutboxError::IllegalTransition(_)
        ))
    ));
    assert_eq!(successor.writer.recovery_anchor().await?, before);
    assert_eq!(successor.device.calls.load(Ordering::SeqCst), 0);
    assert_eq!(successor.device.queries.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn native_stop_retains_old_unknown_through_new_namespace_effect_release_and_reopen()
-> TestResult {
    let (temp, successor, original_queued) = expired_unknown().await?;
    let old_effect = fs::read(temp.path().join("device-effect.json"))?;
    let original = successor
        .writer
        .retained_operation(OPERATION)
        .await?
        .ok_or("old K absent")?;
    let original_events = retained_events(&successor).await?;
    let mut request = successor.request(1)?;
    request.delivery = Hos2DeliveryId::new([3; 16], [4; 16], 1)?;
    let key = "hos2:stop:new-namespace";
    let queued = successor
        .writer
        .prepare_operation(
            successor.operation(key, &request)?,
            HOS2_INSTALL_TOPIC_V1,
            request.to_json()?,
        )
        .await?;
    // Same explicit durable device implementation, with a distinct history
    // namespace and physical effect file. The old effect is never reissued.
    let device = Arc::new(DiskDevice {
        path: temp.path().join("next-boot-device-effect.json"),
        namespace: ([3; 16], [4; 16]),
        calls: AtomicUsize::new(0),
        queries: AtomicUsize::new(0),
        lose_ack: AtomicBool::new(false),
        terminal_status: AtomicUsize::new(0),
        retire_calls: AtomicUsize::new(0),
        lose_retire_ack: AtomicBool::new(false),
    });
    let target = Arc::new(ProductionHos2Target::new(device.clone()));
    let dispatcher =
        ProductionFinalUseOutboxDispatcher::attach(successor.authority.clone(), target);
    let (binding, signed) = successor.signed(&queued, 2).await?;
    let result = dispatcher
        .dispatch(&successor.writer, &signed, &binding, queued)
        .await?;
    assert_eq!(result.state, LocalOutcomeState::Committed);
    let terminal = successor.writer.retained_hos2_terminal(key).await?;
    assert_eq!(device.calls.load(Ordering::SeqCst), 1);
    assert_eq!(device.queries.load(Ordering::SeqCst), 1);
    assert_eq!(successor.device.calls.load(Ordering::SeqCst), 0);
    assert_eq!(successor.device.queries.load(Ordering::SeqCst), 0);
    assert_eq!(successor.writer.hos2_drain_blockers().await?, 1);
    assert_eq!(retained_events(&successor).await?, original_events);
    let released = successor.writer.release().await?;
    assert_eq!(released.generation, 2);
    assert_eq!(released.state, "released");
    // This dispatcher holds a clone of the original FinalUse owner. Retire
    // that custody before the next factory opens the same durable frontier.
    drop(dispatcher);
    drop(successor);
    let next = Fixture::open_generation(temp.path(), 3, 4_000_000_000).await?;
    let retained = next
        .writer
        .retained_operation(OPERATION)
        .await?
        .ok_or("old K lost at next owner")?;
    assert_eq!(
        (
            retained.operation,
            retained.topic,
            retained.payload_json,
            retained.state
        ),
        (
            original.operation,
            original.topic,
            original_queued.payload_json,
            LocalOutcomeState::Indeterminate
        )
    );
    assert_eq!(retained_events(&next).await?, original_events);
    assert_eq!(next.writer.retained_hos2_terminal(key).await?, terminal);
    assert!(next.writer.retained_hos2_terminal(OPERATION).await.is_err());
    assert_eq!(next.writer.hos2_drain_blockers().await?, 1);
    assert_eq!(
        fs::read(temp.path().join("device-effect.json"))?,
        old_effect
    );
    assert_eq!(device.calls.load(Ordering::SeqCst), 1);
    assert_eq!(next.device.calls.load(Ordering::SeqCst), 0);
    Ok(())
}
