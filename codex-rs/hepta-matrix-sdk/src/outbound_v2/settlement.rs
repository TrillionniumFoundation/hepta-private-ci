use super::gate::EnteredSend;
use super::*;

/// The proof remains borrowed through all durable outcome writes. Failures in
/// this function leave the entered claim recoverable by lease expiry and sync;
/// this function has no pre-entry release path.
pub(super) async fn settle_entered(
    store: &MatrixDurableStore,
    entered: &EnteredSend<'_>,
    config: &OutboxDispatchConfig,
    clock: &DispatchClock,
    stats: &mut OutboxDispatchStats,
) -> Result<(), OutboxDispatchError> {
    let claim = entered.claim();
    let record = claim.record();
    let outcome_at_ms = clock.now_ms()?;
    match entered.outcome() {
        Ok(event_id) => {
            let observed = store
                .record_outbox_transport_accepted(
                    &record.stable_txn_id,
                    record.attempts,
                    event_id,
                    outcome_at_ms,
                )
                .await
                .map_err(store_error)?;
            stats.transport_accepted += 1;
            if observed.state.is_terminal() {
                close_observed_terminal(store, claim, &observed, clock, stats).await?;
            } else {
                let scheduled_at_ms = clock.now_ms()?;
                let next = reconciliation_attempt_at(config, record, scheduled_at_ms)?;
                store
                    .finish_outbox_transport_accepted(claim, event_id, scheduled_at_ms, next)
                    .await
                    .map_err(store_error)?;
                count_retry(stats, next);
            }
        }
        Err(MatrixTransportError::Permanent) => {
            let observed = store
                .record_outbox_transport_rejected(
                    &record.stable_txn_id,
                    record.attempts,
                    outcome_at_ms,
                )
                .await
                .map_err(store_error)?;
            if matches!(
                observed.state,
                MatrixDispatchState::Accepted | MatrixDispatchState::Indeterminate
            ) {
                store
                    .finish_outbox_indeterminate(
                        claim,
                        MatrixAttemptFailureClass::Permanent,
                        /*retry_after_ms*/ None,
                        clock.now_ms()?,
                        PARKED_RECONCILIATION_AT_MS,
                    )
                    .await
                    .map_err(store_error)?;
                stats.indeterminate += 1;
            } else if observed.state == MatrixDispatchState::Failed {
                store
                    .finish_outbox_permanently_rejected(claim, clock.now_ms()?)
                    .await
                    .map_err(store_error)?;
                stats.permanent_failure += 1;
            } else if observed.state.is_terminal() {
                close_observed_terminal(store, claim, &observed, clock, stats).await?;
            } else {
                return Err(OutboxDispatchError::Store);
            }
        }
        Err(error) => {
            let observed = store
                .record_outbox_transport_indeterminate(
                    &record.stable_txn_id,
                    record.attempts,
                    outcome_at_ms,
                )
                .await
                .map_err(store_error)?;
            if observed.state.is_terminal() {
                close_observed_terminal(store, claim, &observed, clock, stats).await?;
            } else {
                let scheduled_at_ms = clock.now_ms()?;
                let next = classified_retry_at(config, record, scheduled_at_ms, *error)?;
                store
                    .finish_outbox_indeterminate(
                        claim,
                        failure_class(*error),
                        retry_after_hint(*error),
                        scheduled_at_ms,
                        next,
                    )
                    .await
                    .map_err(store_error)?;
                count_retry(stats, next);
            }
        }
    }
    Ok(())
}
