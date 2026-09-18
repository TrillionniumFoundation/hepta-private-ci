use std::future::Future;
use std::pin::Pin;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixDispatchContext;
use codex_hepta_matrix_store::MatrixDispatchIntent;
use codex_hepta_matrix_store::MatrixDispatchReceipt;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_matrix_store::matrix_dispatch_operation_id;
use tokio_util::sync::CancellationToken;

pub type MatrixSendFuture<'a> =
    Pin<Box<dyn Future<Output = Result<MatrixEventId, MatrixTransportError>> + Send + 'a>>;

pub type MatrixObserveFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<Option<MatrixServerObservation>, MatrixTransportError>>
            + Send
            + 'a,
    >,
>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixServerObservation {
    pub event_id: MatrixEventId,
    pub observation_digest: String,
}

pub trait MatrixOutboundTransport: Send + Sync {
    /// Bind transport/session identity to the durable dispatch record. The
    /// default keeps deterministic test transports source-compatible while
    /// making the absence of an external final-use grant explicit.
    fn dispatch_context(&self, record: &OutboxRecord) -> MatrixDispatchContext {
        MatrixDispatchContext::local_unverified(record.binding_revision, record.generation)
    }

    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a>;
}

/// Independent homeserver observer used to settle a transport-accepted send.
/// Implementations must not infer success from the preceding send response.
pub trait MatrixOutboundObserver: Send + Sync {
    fn observe_server_event<'a>(
        &'a self,
        _record: &'a OutboxRecord,
        _event_id: &'a MatrixEventId,
    ) -> MatrixObserveFuture<'a> {
        Box::pin(async { Ok(None) })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixTransportError {
    #[error("Matrix transport failed transiently")]
    Retryable,
    #[error("Matrix transport rejected the outbound event permanently")]
    Permanent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutboxDispatchConfig {
    pub lease_ms: u64,
    pub retry_delay_ms: u64,
    pub max_retry_delay_ms: u64,
    /// Number of fast retries before reconciliation uses the bounded maximum
    /// delay. It is not permission to turn an unknown external effect into a
    /// terminal failure.
    pub max_attempts: u64,
    pub claim_limit: usize,
    pub idle_poll: Duration,
}

impl Default for OutboxDispatchConfig {
    fn default() -> Self {
        Self {
            lease_ms: 30_000,
            retry_delay_ms: 2_000,
            max_retry_delay_ms: 5 * 60_000,
            max_attempts: 8,
            claim_limit: 32,
            idle_poll: Duration::from_millis(100),
        }
    }
}

impl OutboxDispatchConfig {
    fn is_valid(&self) -> bool {
        self.lease_ms > 0
            && self.retry_delay_ms > 0
            && self.max_retry_delay_ms >= self.retry_delay_ms
            && (1..=64).contains(&self.max_attempts)
            && (1..=256).contains(&self.claim_limit)
            && !self.idle_poll.is_zero()
            && self.idle_poll <= Duration::from_secs(5)
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct OutboxDispatchStats {
    pub claimed: u64,
    /// Count of claims whose terminal state was established by an independent
    /// Matrix observation while this sender was reconciling.
    pub sent: u64,
    pub accepted_pending_observation: u64,
    pub retry_scheduled: u64,
    pub indeterminate_held: u64,
    pub permanent_failure: u64,
    pub cancelled: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum OutboxDispatchError {
    #[error("invalid Matrix outbox sender configuration")]
    Invalid,
    #[error("Matrix durable outbox is unavailable")]
    Store,
}

pub async fn dispatch_outbox_once<T: MatrixOutboundTransport + MatrixOutboundObserver + ?Sized>(
    store: &MatrixDurableStore,
    transport: &T,
    config: &OutboxDispatchConfig,
    cancel: &CancellationToken,
    now_ms: u64,
) -> Result<OutboxDispatchStats, OutboxDispatchError> {
    if !config.is_valid() {
        return Err(OutboxDispatchError::Invalid);
    }
    let records = store
        .claim_outbox(now_ms, config.lease_ms, config.claim_limit)
        .await
        .map_err(store_error)?;
    let mut stats = OutboxDispatchStats {
        claimed: records.len() as u64,
        ..OutboxDispatchStats::default()
    };
    for record in records {
        let payload_digest = Sha256Digest::for_bytes(&record.payload)
            .as_str()
            .to_string();
        let intent = MatrixDispatchIntent {
            operation_id: matrix_dispatch_operation_id(&record.stable_txn_id),
            stable_txn_id: record.stable_txn_id.clone(),
            room_id: record.room_id.clone(),
            payload_digest,
            context: transport.dispatch_context(&record),
        };
        let prepared = store
            .prepare_matrix_dispatch(now_ms, &intent)
            .await
            .map_err(store_error)?;
        if account_terminal(&mut stats, &prepared) {
            continue;
        }
        let prior_external_uncertainty = matches!(
            prepared.state,
            MatrixDispatchState::Dispatched | MatrixDispatchState::Indeterminate
        );

        // If a previous transport call already returned an event id, reconcile
        // that exact accepted event before permitting another network send.
        // A lease reclaim may increment the local claim counter, but it must
        // not turn a known accepted effect into a blind replay.
        if let Some(accepted_event_id) = prepared.accepted_event_id.as_ref() {
            let observation = tokio::select! {
                biased;
                _ = cancel.cancelled() => {
                    stats.cancelled = true;
                    None
                }
                result = transport.observe_server_event(&record, accepted_event_id) => {
                    match result {
                        Ok(observation) => observation,
                        Err(MatrixTransportError::Retryable) => None,
                        Err(MatrixTransportError::Permanent) => {
                            return Err(OutboxDispatchError::Store);
                        }
                    }
                }
            };
            if stats.cancelled {
                break;
            }
            if let Some(observation) = observation {
                if observation.event_id != *accepted_event_id {
                    return Err(OutboxDispatchError::Store);
                }
                match store
                    .observe_matrix_server_event(
                        Some(&record.stable_txn_id),
                        accepted_event_id,
                        &record.room_id,
                        record.binding_revision,
                        record.generation,
                        &observation.observation_digest,
                        now_ms,
                    )
                    .await
                {
                    Ok(Some(receipt)) if account_terminal(&mut stats, &receipt) => continue,
                    Ok(Some(_)) | Ok(None) => return Err(OutboxDispatchError::Store),
                    Err(MatrixDurableError::Conflict) => {
                        if account_current_terminal(store, &record, &mut stats).await? {
                            continue;
                        }
                        return Err(OutboxDispatchError::Store);
                    }
                    Err(error) => return Err(store_error(error)),
                }
            }

            let next_attempt_at_ms = now_ms
                .checked_add(retry_delay_ms(config, record.attempts)?)
                .ok_or(OutboxDispatchError::Invalid)?;
            match store
                .mark_outbox_retry(
                    &record.stable_txn_id,
                    record.attempts,
                    now_ms,
                    next_attempt_at_ms,
                )
                .await
            {
                Ok(_) => {
                    stats.accepted_pending_observation += 1;
                    stats.retry_scheduled += 1;
                    continue;
                }
                Err(MatrixDurableError::Conflict) => {
                    if account_current_terminal(store, &record, &mut stats).await? {
                        continue;
                    }
                    return Err(OutboxDispatchError::Store);
                }
                Err(error) => return Err(store_error(error)),
            }
        }

        match store
            .record_matrix_dispatch_attempt(&record.stable_txn_id, record.attempts, now_ms)
            .await
        {
            Ok(receipt) if account_terminal(&mut stats, &receipt) => continue,
            Ok(_) => {}
            Err(MatrixDurableError::Conflict) => {
                if account_current_terminal(store, &record, &mut stats).await? {
                    continue;
                }
                return Err(OutboxDispatchError::Store);
            }
            Err(error) => return Err(store_error(error)),
        }

        let result = tokio::select! {
            biased;
            _ = cancel.cancelled() => {
                stats.cancelled = true;
                break;
            }
            result = transport.send(&record) => result,
        };
        match result {
            Ok(event_id) => {
                // SDK/HTTP acknowledgement is evidence of transport acceptance,
                // not terminal delivery. First bind the returned event id to the
                // durable transaction, then obtain a separate authenticated
                // homeserver observation (or wait for /sync) before settling.
                let acceptance = match store
                    .record_matrix_transport_acceptance(
                        &record.stable_txn_id,
                        record.attempts,
                        &event_id,
                        now_ms,
                    )
                    .await
                {
                    Ok(receipt) => receipt,
                    Err(MatrixDurableError::Conflict) => {
                        if account_current_terminal(store, &record, &mut stats).await? {
                            continue;
                        }
                        return Err(OutboxDispatchError::Store);
                    }
                    Err(error) => return Err(store_error(error)),
                };
                if account_terminal(&mut stats, &acceptance) {
                    continue;
                }

                let observation = tokio::select! {
                    biased;
                    _ = cancel.cancelled() => {
                        stats.cancelled = true;
                        None
                    }
                    result = transport.observe_server_event(&record, &event_id) => {
                        match result {
                            Ok(observation) => observation,
                            Err(MatrixTransportError::Retryable) => None,
                            Err(MatrixTransportError::Permanent) => {
                                return Err(OutboxDispatchError::Store);
                            }
                        }
                    }
                };
                if stats.cancelled {
                    break;
                }
                let Some(observation) = observation else {
                    stats.accepted_pending_observation += 1;
                    continue;
                };
                if observation.event_id != event_id {
                    return Err(OutboxDispatchError::Store);
                }
                match store
                    .observe_matrix_server_event(
                        Some(&record.stable_txn_id),
                        &event_id,
                        &record.room_id,
                        record.binding_revision,
                        record.generation,
                        &observation.observation_digest,
                        now_ms,
                    )
                    .await
                {
                    Ok(Some(receipt)) if account_terminal(&mut stats, &receipt) => {}
                    Ok(Some(_)) | Ok(None) => return Err(OutboxDispatchError::Store),
                    Err(MatrixDurableError::Conflict) => {
                        if !account_current_terminal(store, &record, &mut stats).await? {
                            return Err(OutboxDispatchError::Store);
                        }
                    }
                    Err(error) => return Err(store_error(error)),
                }
            }
            Err(MatrixTransportError::Retryable) => {
                let next_attempt_at_ms = now_ms
                    .checked_add(retry_delay_ms(config, record.attempts)?)
                    .ok_or(OutboxDispatchError::Invalid)?;
                match store
                    .record_matrix_transport_indeterminate_and_retry(
                        &record.stable_txn_id,
                        record.attempts,
                        now_ms,
                        next_attempt_at_ms,
                    )
                    .await
                {
                    Ok(receipt) if account_terminal(&mut stats, &receipt) => {}
                    Ok(_) => {
                        stats.retry_scheduled += 1;
                        if record.attempts >= config.max_attempts {
                            stats.indeterminate_held += 1;
                        }
                    }
                    Err(MatrixDurableError::Conflict) => {
                        if !account_current_terminal(store, &record, &mut stats).await? {
                            return Err(OutboxDispatchError::Store);
                        }
                    }
                    Err(error) => return Err(store_error(error)),
                }
            }
            Err(MatrixTransportError::Permanent) => {
                if prior_external_uncertainty {
                    // A later definitive rejection cannot prove that an earlier
                    // timeout/dispatched attempt failed to cross the external
                    // boundary. Preserve uncertainty and keep reconciling the
                    // same stable transaction instead of manufacturing failure.
                    let next_attempt_at_ms = now_ms
                        .checked_add(retry_delay_ms(config, record.attempts)?)
                        .ok_or(OutboxDispatchError::Invalid)?;
                    match store
                        .record_matrix_transport_indeterminate_and_retry(
                            &record.stable_txn_id,
                            record.attempts,
                            now_ms,
                            next_attempt_at_ms,
                        )
                        .await
                    {
                        Ok(receipt) if account_terminal(&mut stats, &receipt) => {}
                        Ok(_) => {
                            stats.retry_scheduled += 1;
                            stats.indeterminate_held += 1;
                        }
                        Err(MatrixDurableError::Conflict) => {
                            if !account_current_terminal(store, &record, &mut stats).await? {
                                return Err(OutboxDispatchError::Store);
                            }
                        }
                        Err(error) => return Err(store_error(error)),
                    }
                } else {
                    match store
                        .record_matrix_transport_rejection(
                            &record.stable_txn_id,
                            record.attempts,
                            now_ms,
                        )
                        .await
                    {
                        Ok(receipt) if account_terminal(&mut stats, &receipt) => {}
                        Ok(_) => return Err(OutboxDispatchError::Store),
                        Err(MatrixDurableError::Conflict) => {
                            if !account_current_terminal(store, &record, &mut stats).await? {
                                return Err(OutboxDispatchError::Store);
                            }
                        }
                        Err(error) => return Err(store_error(error)),
                    }
                }
            }
        }
    }
    Ok(stats)
}

pub async fn run_outbox_sender<T: MatrixOutboundTransport + MatrixOutboundObserver + ?Sized>(
    store: &MatrixDurableStore,
    transport: &T,
    config: &OutboxDispatchConfig,
    cancel: &CancellationToken,
) -> Result<(), OutboxDispatchError> {
    loop {
        if cancel.is_cancelled() {
            return Ok(());
        }
        let stats =
            dispatch_outbox_once(store, transport, config, cancel, system_time_ms()?).await?;
        if stats.cancelled {
            return Ok(());
        }
        if stats.claimed == 0 {
            tokio::select! {
                _ = cancel.cancelled() => return Ok(()),
                _ = tokio::time::sleep(config.idle_poll) => {}
            }
        }
    }
}

async fn account_current_terminal(
    store: &MatrixDurableStore,
    record: &OutboxRecord,
    stats: &mut OutboxDispatchStats,
) -> Result<bool, OutboxDispatchError> {
    Ok(store
        .matrix_dispatch_receipt(&record.stable_txn_id)
        .await
        .map_err(store_error)?
        .as_ref()
        .is_some_and(|receipt| account_terminal(stats, receipt)))
}

fn account_terminal(stats: &mut OutboxDispatchStats, receipt: &MatrixDispatchReceipt) -> bool {
    if !receipt.archived {
        return false;
    }
    match receipt.state {
        MatrixDispatchState::ObservedSucceeded | MatrixDispatchState::Redacted => {
            stats.sent += 1;
            true
        }
        MatrixDispatchState::Rejected => {
            stats.permanent_failure += 1;
            true
        }
        MatrixDispatchState::Prepared
        | MatrixDispatchState::Dispatched
        | MatrixDispatchState::Indeterminate => false,
    }
}

fn system_time_ms() -> Result<u64, OutboxDispatchError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OutboxDispatchError::Invalid)?
        .as_millis();
    u64::try_from(millis).map_err(|_| OutboxDispatchError::Invalid)
}

fn retry_delay_ms(
    config: &OutboxDispatchConfig,
    attempts: u64,
) -> Result<u64, OutboxDispatchError> {
    let exponent = u32::try_from(attempts.saturating_sub(1).min(63))
        .map_err(|_| OutboxDispatchError::Invalid)?;
    Ok(config
        .retry_delay_ms
        .saturating_mul(1_u64.checked_shl(exponent).unwrap_or(u64::MAX))
        .min(config.max_retry_delay_ms))
}

fn store_error(_: MatrixDurableError) -> OutboxDispatchError {
    OutboxDispatchError::Store
}
