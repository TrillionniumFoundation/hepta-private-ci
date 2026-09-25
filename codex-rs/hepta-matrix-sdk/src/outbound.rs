use std::future::Future;
use std::pin::Pin;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxRecord;
use tokio_util::sync::CancellationToken;

pub type MatrixSendFuture<'a> =
    Pin<Box<dyn Future<Output = Result<MatrixEventId, MatrixTransportError>> + Send + 'a>>;

pub trait MatrixOutboundTransport: Send + Sync {
    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a>;
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
    pub sent: u64,
    pub retry_scheduled: u64,
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

pub async fn dispatch_outbox_once<T: MatrixOutboundTransport + ?Sized>(
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
                store
                    .mark_outbox_sent(&record.stable_txn_id, record.attempts, &event_id, now_ms)
                    .await
                    .map_err(store_error)?;
                stats.sent += 1;
            }
            Err(MatrixTransportError::Retryable) => {
                if record.attempts >= config.max_attempts {
                    store
                        .mark_outbox_permanent_failure(
                            &record.stable_txn_id,
                            record.attempts,
                            now_ms,
                        )
                        .await
                        .map_err(store_error)?;
                    stats.permanent_failure += 1;
                } else {
                    let next_attempt_at_ms = now_ms
                        .checked_add(retry_delay_ms(config, record.attempts)?)
                        .ok_or(OutboxDispatchError::Invalid)?;
                    store
                        .mark_outbox_retry(
                            &record.stable_txn_id,
                            record.attempts,
                            now_ms,
                            next_attempt_at_ms,
                        )
                        .await
                        .map_err(store_error)?;
                    stats.retry_scheduled += 1;
                }
            }
            Err(MatrixTransportError::Permanent) => {
                store
                    .mark_outbox_permanent_failure(&record.stable_txn_id, record.attempts, now_ms)
                    .await
                    .map_err(store_error)?;
                stats.permanent_failure += 1;
            }
        }
    }
    Ok(stats)
}

pub async fn run_outbox_sender<T: MatrixOutboundTransport + ?Sized>(
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
