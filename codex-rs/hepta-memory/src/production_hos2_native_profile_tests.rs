//! Real original-ledger coverage for native planning and shutdown admission.
//! These reuse the retained test device; they make no native-kernel claim.

use super::*;
use pretty_assertions::assert_eq;

// This is a new fixture issuance, not a renewal or an artificial clock.
// SQLite setup/prepare under concurrent tests must finish while it is live.
const HANDOFF_PREPARATION_LIFETIME_SECONDS: u64 = 20;

async fn original_lease_expiry(fixture: &Fixture) -> TestResult<u64> {
    let head = fixture
        .writer
        .store
        .inspect_local_lease_head(LEASE)
        .await?
        .head
        .ok_or("original persisted lease head missing")?;
    assert_eq!(head.generation, fixture.writer.generation());
    Ok(head
        .lease_expires_at_unix_seconds
        .ok_or("original persisted expiry missing")?)
}

#[tokio::test]
async fn native_candidate_is_read_only_and_prepare_keeps_the_original_cas() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let before = fixture.writer.recovery_anchor().await?;
    let first = fixture
        .writer
        .next_hos2_delivery_candidate([1; 16], [2; 16])
        .await?;
    let repeated = fixture
        .writer
        .next_hos2_delivery_candidate([1; 16], [2; 16])
        .await?;
    assert_eq!(first, Hos2DeliveryId::new([1; 16], [2; 16], 1)?);
    assert_eq!(repeated, first);
    assert_eq!(fixture.writer.recovery_anchor().await?, before);

    let queued = fixture.prepare(OPERATION, first.sequence()?).await?;
    let prepared = fixture.writer.recovery_anchor().await?;
    // A second caller may have read the same candidate. Only the original
    // prepare transaction binds D, and it must reject a competing K.
    assert!(
        fixture
            .prepare("hos2:stale-candidate", repeated.sequence()?)
            .await
            .is_err()
    );
    let next = fixture
        .writer
        .next_hos2_delivery_candidate([1; 16], [2; 16])
        .await?;
    assert_eq!(next, Hos2DeliveryId::new([1; 16], [2; 16], 2)?);
    assert!(
        fixture
            .prepare("hos2:unresolved-predecessor", next.sequence()?)
            .await
            .is_err()
    );
    let replay = fixture.prepare(OPERATION, first.sequence()?).await?;
    assert_eq!(
        (&replay.event_id, &replay.outbox_id, &replay.payload_json),
        (&queued.event_id, &queued.outbox_id, &queued.payload_json)
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, prepared);

    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 1).await?;
    let terminal = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, queued)
        .await?;
    assert_eq!(terminal.state, LocalOutcomeState::Committed);
    fixture
        .prepare("hos2:after-terminal", next.sequence()?)
        .await?;
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn native_candidate_keeps_boot_and_capability_namespaces_independent() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let before = fixture.writer.recovery_anchor().await?;
    assert_eq!(
        fixture
            .writer
            .next_hos2_delivery_candidate([1; 16], [2; 16])
            .await?,
        Hos2DeliveryId::new([1; 16], [2; 16], 2)?
    );
    for (boot, space) in [([3; 16], [2; 16]), ([1; 16], [4; 16])] {
        assert_eq!(
            fixture
                .writer
                .next_hos2_delivery_candidate(boot, space)
                .await?,
            Hos2DeliveryId::new(boot, space, 1)?
        );
    }
    assert!(
        fixture
            .writer
            .next_hos2_delivery_candidate([0; 16], [2; 16])
            .await
            .is_err()
    );
    assert!(
        fixture
            .writer
            .next_hos2_delivery_candidate([1; 16], [0; 16])
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn native_drain_counts_queued_and_unknown_until_the_original_terminal() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    assert_eq!(fixture.writer.hos2_drain_blockers().await?, 0);
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    let before = fixture.writer.recovery_anchor().await?;
    assert_eq!(fixture.writer.hos2_drain_blockers().await?, 1);
    assert_eq!(fixture.writer.recovery_anchor().await?, before);

    fixture.device.lose_ack.store(true, Ordering::SeqCst);
    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 1).await?;
    let outcome = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, queued)
        .await?;
    assert_eq!(outcome.state, LocalOutcomeState::Indeterminate);
    assert_eq!(fixture.writer.hos2_drain_blockers().await?, 1);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
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
    assert_eq!(fixture.writer.hos2_drain_blockers().await?, 0);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);

    fixture.device.lose_ack.store(false, Ordering::SeqCst);
    fixture.device.terminal_status.store(2, Ordering::SeqCst);
    let refused = fixture
        .prepare("hos2:drain-native-refusal", /*sequence*/ 2)
        .await?;
    assert_eq!(fixture.writer.hos2_drain_blockers().await?, 1);
    let (binding, signed) = fixture.signed(&refused, /*nonce*/ 2).await?;
    let outcome = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, refused)
        .await?;
    assert_eq!(outcome.state, LocalOutcomeState::Rejected);
    let terminal = fixture.writer.recovery_anchor().await?;
    assert_eq!(fixture.writer.hos2_drain_blockers().await?, 0);
    assert_eq!(fixture.writer.recovery_anchor().await?, terminal);
    Ok(())
}

#[tokio::test]
async fn native_drain_keeps_pending_work_across_an_actual_expired_writer_handoff() -> TestResult {
    for unknown in [false, true] {
        let temp = tempfile::tempdir()?;
        let expiry = now_unix_seconds()? + HANDOFF_PREPARATION_LIFETIME_SECONDS;
        let old = Fixture::open_generation(temp.path(), /*generation*/ 1, expiry).await?;
        let queued = old.prepare(OPERATION, /*sequence*/ 1).await?;
        let expected = if unknown {
            old.device.lose_ack.store(true, Ordering::SeqCst);
            let (binding, signed) = old.signed(&queued, /*nonce*/ 1).await?;
            let outcome = old
                .dispatcher
                .dispatch(&old.writer, &signed, &binding, queued.clone())
                .await?;
            assert_eq!(outcome.state, LocalOutcomeState::Indeterminate);
            LocalOutcomeState::Indeterminate
        } else {
            LocalOutcomeState::Queued
        };
        assert_eq!(old.writer.hos2_drain_blockers().await?, 1);
        let persisted_expiry = original_lease_expiry(&old).await?;
        assert_eq!(persisted_expiry, expiry);
        drop(old);
        let delay = persisted_expiry.saturating_sub(now_unix_seconds()?);
        tokio::time::sleep(Duration::from_secs(delay) + Duration::from_millis(20)).await;
        assert!(now_unix_seconds()? >= persisted_expiry);
        // The production opener terminalizes the expired predecessor and
        // allocates the next original local lease generation itself.
        let successor = Fixture::open_generation(
            temp.path(),
            /*generation*/ 2,
            /*expiry*/ 4_000_000_000,
        )
        .await?;
        assert_eq!(successor.writer.generation(), 2);
        let retained = successor
            .writer
            .retained_operation(OPERATION)
            .await?
            .ok_or("missing inherited operation")?;
        assert_eq!(
            (&retained.payload_json, retained.state),
            (&queued.payload_json, expected)
        );
        assert_eq!(successor.writer.hos2_drain_blockers().await?, 1);
        let cut = successor.writer.recovery_anchor().await?;
        let startup = successor.writer.retained_pending_hos2(16).await?;
        assert_eq!(startup.len(), 1);
        assert_eq!(startup[0].0, OPERATION);
        assert_eq!(
            (&startup[0].1.payload_json, startup[0].1.state),
            (&queued.payload_json, expected)
        );
        assert_eq!(successor.writer.recovery_anchor().await?, cut);
        assert!(
            successor
                .prepare("hos2:successor-before-terminal", /*sequence*/ 2)
                .await
                .is_err()
        );
        assert_eq!(successor.device.calls.load(Ordering::SeqCst), 0);
        if unknown {
            assert_eq!(
                successor
                    .dispatcher
                    .reconcile(&successor.writer, /*limit*/ 8)
                    .await?,
                1
            );
            assert_eq!(
                successor.writer.status(OPERATION).await?,
                LocalOutcomeState::Committed
            );
            assert_eq!(successor.writer.hos2_drain_blockers().await?, 0);
            assert_eq!(successor.device.calls.load(Ordering::SeqCst), 0);
        }
    }
    Ok(())
}

#[tokio::test]
async fn native_retained_terminal_reads_the_original_event_without_mutating_the_cut() -> TestResult
{
    for status in [0, 2] {
        let temp = tempfile::tempdir()?;
        let fixture = Fixture::open(temp.path()).await?;
        let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
        assert!(
            fixture
                .writer
                .retained_hos2_terminal(OPERATION)
                .await
                .is_err()
        );
        fixture
            .device
            .terminal_status
            .store(status, Ordering::SeqCst);
        let (binding, signed) = fixture.signed(&queued, /*nonce*/ 1).await?;
        let dispatched = fixture
            .dispatcher
            .dispatch(&fixture.writer, &signed, &binding, queued)
            .await?;
        let expected = ProductionOutcomeReceipt {
            lease_id: LEASE.into(),
            occurrence_key: OPERATION.into(),
            state: dispatched.state,
            event_id: dispatched.local_event_id,
            external_effect: false,
        };
        let terminal = dispatched
            .target_receipt
            .or(dispatched.target_reason)
            .ok_or("native terminal absent")?;
        let cut = fixture.writer.recovery_anchor().await?;
        let retained = fixture.writer.retained_hos2_terminal(OPERATION).await?;
        assert_eq!(retained, (fixture.request(1)?, expected, terminal));
        assert_eq!(
            fixture.writer.retained_hos2_terminal(OPERATION).await?,
            retained
        );
        assert_eq!(fixture.writer.recovery_anchor().await?, cut);
        assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    }
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    let queued = fixture.prepare(OPERATION, /*sequence*/ 1).await?;
    fixture.device.lose_ack.store(true, Ordering::SeqCst);
    let (binding, signed) = fixture.signed(&queued, /*nonce*/ 1).await?;
    let unknown = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, queued)
        .await?;
    assert_eq!(unknown.state, LocalOutcomeState::Indeterminate);
    let cut = fixture.writer.recovery_anchor().await?;
    assert!(
        fixture
            .writer
            .retained_hos2_terminal(OPERATION)
            .await
            .is_err()
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, cut);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn native_retained_terminal_keeps_the_same_event_across_expired_owner_recovery() -> TestResult
{
    let temp = tempfile::tempdir()?;
    let expiry = now_unix_seconds()? + HANDOFF_PREPARATION_LIFETIME_SECONDS;
    let old = Fixture::open_generation(temp.path(), /*generation*/ 1, expiry).await?;
    let queued = old.prepare(OPERATION, /*sequence*/ 1).await?;
    let (binding, signed) = old.signed(&queued, /*nonce*/ 1).await?;
    let dispatched = old
        .dispatcher
        .dispatch(&old.writer, &signed, &binding, queued)
        .await?;
    let original = old.writer.retained_hos2_terminal(OPERATION).await?;
    assert_eq!(original.1.event_id, dispatched.local_event_id);
    let persisted_expiry = original_lease_expiry(&old).await?;
    assert_eq!(persisted_expiry, expiry);
    drop(old);
    let delay = persisted_expiry.saturating_sub(now_unix_seconds()?);
    tokio::time::sleep(Duration::from_secs(delay) + Duration::from_millis(20)).await;
    assert!(now_unix_seconds()? >= persisted_expiry);
    let successor = Fixture::open_generation(
        temp.path(),
        /*generation*/ 2,
        /*expiry*/ 4_000_000_000,
    )
    .await?;
    let cut = successor.writer.recovery_anchor().await?;
    assert_eq!(
        successor.writer.retained_hos2_terminal(OPERATION).await?,
        original
    );
    assert_eq!(successor.writer.recovery_anchor().await?, cut);
    assert_eq!(successor.device.calls.load(Ordering::SeqCst), 0);
    assert_eq!(successor.device.queries.load(Ordering::SeqCst), 0);
    Ok(())
}

#[tokio::test]
async fn native_pending_snapshot_keeps_original_payload_and_stops_at_terminal() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    assert!(fixture.writer.retained_pending_hos2(16).await?.is_empty());
    let queued = fixture.prepare(OPERATION, 1).await?;
    let cut = fixture.writer.recovery_anchor().await?;
    let snapshot = fixture.writer.retained_pending_hos2(16).await?;
    assert_eq!(snapshot.len(), 1);
    assert_eq!(
        (
            &snapshot[0].0,
            snapshot[0].1.topic.as_str(),
            &snapshot[0].1.payload_json,
            snapshot[0].1.state
        ),
        (
            &OPERATION.to_string(),
            HOS2_INSTALL_TOPIC_V1,
            &queued.payload_json,
            LocalOutcomeState::Queued
        )
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, cut);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);

    fixture.device.lose_ack.store(true, Ordering::SeqCst);
    let (binding, signed) = fixture.signed(&queued, 1).await?;
    let unknown = fixture
        .dispatcher
        .dispatch(&fixture.writer, &signed, &binding, queued)
        .await?;
    assert_eq!(unknown.state, LocalOutcomeState::Indeterminate);
    let cut = fixture.writer.recovery_anchor().await?;
    let snapshot = fixture.writer.retained_pending_hos2(16).await?;
    assert_eq!(snapshot.len(), 1);
    assert_eq!(snapshot[0].0, OPERATION);
    assert_eq!(snapshot[0].1.state, LocalOutcomeState::Indeterminate);
    assert_eq!(fixture.writer.recovery_anchor().await?, cut);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    assert_eq!(fixture.dispatcher.reconcile(&fixture.writer, 8).await?, 1);
    let cut = fixture.writer.recovery_anchor().await?;
    assert!(fixture.writer.retained_pending_hos2(16).await?.is_empty());
    assert_eq!(fixture.writer.recovery_anchor().await?, cut);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 1);
    Ok(())
}

#[tokio::test]
async fn native_pending_snapshot_refuses_invalid_or_truncating_bounds() -> TestResult {
    let temp = tempfile::tempdir()?;
    let fixture = Fixture::open(temp.path()).await?;
    for (id, space) in [("hos2:pending:a", [2; 16]), ("hos2:pending:b", [3; 16])] {
        let mut request = fixture.request(1)?;
        request.delivery = Hos2DeliveryId::new([1; 16], space, 1)?;
        fixture
            .writer
            .prepare_operation(
                fixture.operation(id, &request)?,
                HOS2_INSTALL_TOPIC_V1,
                request.to_json()?,
            )
            .await?;
    }
    let cut = fixture.writer.recovery_anchor().await?;
    for limit in [0, 1, 257, usize::MAX] {
        assert!(fixture.writer.retained_pending_hos2(limit).await.is_err());
    }
    let snapshot = fixture.writer.retained_pending_hos2(2).await?;
    assert_eq!(snapshot.len(), 2);
    assert_eq!(
        snapshot
            .iter()
            .map(|(id, _)| id.as_str())
            .collect::<Vec<_>>(),
        vec!["hos2:pending:a", "hos2:pending:b"]
    );
    assert!(
        snapshot
            .iter()
            .all(|(_, retained)| retained.state == LocalOutcomeState::Queued)
    );
    assert_eq!(fixture.writer.recovery_anchor().await?, cut);
    assert_eq!(fixture.writer.hos2_drain_blockers().await?, 2);
    assert_eq!(fixture.device.calls.load(Ordering::SeqCst), 0);
    Ok(())
}
