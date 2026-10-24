//! Real original-ledger coverage for native planning and shutdown admission.
//! These reuse the retained test device; they make no native-kernel claim.

use super::*;
use pretty_assertions::assert_eq;

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
        let expiry = now_unix_seconds()? + 4;
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
        drop(old);
        let delay = expiry.saturating_sub(now_unix_seconds()?);
        tokio::time::sleep(Duration::from_secs(delay) + Duration::from_millis(20)).await;
        assert!(now_unix_seconds()? >= expiry);
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
    let expiry = now_unix_seconds()? + 4;
    let old = Fixture::open_generation(temp.path(), /*generation*/ 1, expiry).await?;
    let queued = old.prepare(OPERATION, /*sequence*/ 1).await?;
    let (binding, signed) = old.signed(&queued, /*nonce*/ 1).await?;
    let dispatched = old
        .dispatcher
        .dispatch(&old.writer, &signed, &binding, queued)
        .await?;
    let original = old.writer.retained_hos2_terminal(OPERATION).await?;
    assert_eq!(original.1.event_id, dispatched.local_event_id);
    drop(old);
    let delay = expiry.saturating_sub(now_unix_seconds()?);
    tokio::time::sleep(Duration::from_secs(delay) + Duration::from_millis(20)).await;
    assert!(now_unix_seconds()? >= expiry);
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
