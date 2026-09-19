use std::future::Future;
use std::pin::Pin;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixDispatchAuthority;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxRecord;
use tokio_util::sync::CancellationToken;

pub type MatrixSendFuture<'a> =
    Pin<Box<dyn Future<Output = Result<MatrixEventId, MatrixTransportError>> + Send + 'a>>;

pub trait MatrixOutboundTransport: Send + Sync {
    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a>;

    /// Bind the durable send to the exact authority identity known by this
    /// transport. The owner-local fallback preserves compatibility for injected
    /// test transports; the real SDK transport supplies its Matrix binding
    /// revision/digest. A future final-use grant can populate grant_id and
    /// grant_payload_digest without changing the durable transaction identity.
    fn dispatch_authority(
        &self,
        record: &OutboxRecord,
    ) -> Result<MatrixDispatchAuthority, MatrixTransportError> {
        Ok(MatrixDispatchAuthority::owner_local(&record.stable_txn_id))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixTransportError {
    /// Failure is known to have happened before the effect boundary, so the
    /// same stable transaction may be retried under the existing outbox policy.
    #[error("Matrix transport failed before dispatch")]
    Retryable,
    /// The request may have crossed the homeserver boundary. Blind retry is
    /// forbidden until sync/server evidence reconciles the stable transaction.
    #[error("Matrix transport outcome is indeterminate")]
    Indeterminate,
    /// A local validation or explicit homeserver rejection proves this attempt
    /// cannot have produced the intended Matrix event.
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
    /// Homeserver send API returned an event ID. This is acceptance evidence,
    /// not terminal delivery; the row remains parked until sync observes it.
    pub accepted: u64,
    pub indeterminate: u64,
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
        if cancel.is_cancelled() {
            stats.cancelled = true;
            break;
        }
        let authority = transport
            .dispatch_authority(&record)
            .map_err(|_| OutboxDispatchError::Invalid)?;
        store
            .prepare_matrix_dispatch(&record, &authority, now_ms)
            .await
            .map_err(store_error)?;
        let dispatched_digest =
            dispatch_observation_digest("dispatched", &record, None, now_ms);
        store
            .mark_matrix_dispatch_dispatched(
                &record.stable_txn_id,
                record.attempts,
                &dispatched_digest,
                now_ms,
            )
            .await
            .map_err(store_error)?;

        let result = tokio::select! {
            biased;
            _ = cancel.cancelled() => {
                let digest = dispatch_observation_digest(
                    "cancelled-after-dispatch",
                    &record,
                    None,
                    now_ms,
                );
                store
                    .mark_matrix_dispatch_indeterminate(
                        &record.stable_txn_id,
                        record.attempts,
                        &digest,
                        now_ms,
                    )
                    .await
                    .map_err(store_error)?;
                stats.indeterminate += 1;
                stats.cancelled = true;
                break;
            }
            result = transport.send(&record) => result,
        };

        match result {
            Ok(event_id) => {
                let digest =
                    dispatch_observation_digest("accepted", &record, Some(&event_id), now_ms);
                store
                    .mark_matrix_dispatch_accepted(
                        &record.stable_txn_id,
                        record.attempts,
                        &event_id,
                        &digest,
                        now_ms,
                    )
                    .await
                    .map_err(store_error)?;
                stats.accepted += 1;
            }
            Err(MatrixTransportError::Retryable) => {
                let digest =
                    dispatch_observation_digest("retryable-before-dispatch", &record, None, now_ms);
                if record.attempts >= config.max_attempts {
                    store
                        .mark_matrix_dispatch_failed(
                            &record.stable_txn_id,
                            record.attempts,
                            &digest,
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
                        .mark_matrix_dispatch_retryable(
                            &record.stable_txn_id,
                            record.attempts,
                            &digest,
                            now_ms,
                            next_attempt_at_ms,
                        )
                        .await
                        .map_err(store_error)?;
                    stats.retry_scheduled += 1;
                }
            }
            Err(MatrixTransportError::Indeterminate) => {
                let digest =
                    dispatch_observation_digest("indeterminate", &record, None, now_ms);
                store
                    .mark_matrix_dispatch_indeterminate(
                        &record.stable_txn_id,
                        record.attempts,
                        &digest,
                        now_ms,
                    )
                    .await
                    .map_err(store_error)?;
                stats.indeterminate += 1;
            }
            Err(MatrixTransportError::Permanent) => {
                let digest =
                    dispatch_observation_digest("permanent-failure", &record, None, now_ms);
                store
                    .mark_matrix_dispatch_failed(
                        &record.stable_txn_id,
                        record.attempts,
                        &digest,
                        now_ms,
                    )
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

fn dispatch_observation_digest(
    kind: &str,
    record: &OutboxRecord,
    event_id: Option<&MatrixEventId>,
    now_ms: u64,
) -> String {
    let payload = Sha256Digest::for_bytes(&record.payload);
    let evidence = format!(
        "hepta.matrix.dispatch-observation.v1\0{kind}\0{}\0{}\0{}\0{}\0{}\0{}",
        record.stable_txn_id.as_str(),
        record.room_id.as_str(),
        record.generation,
        record.attempts,
        payload.as_str(),
        event_id.map(MatrixEventId::as_str).unwrap_or(""),
    );
    let mut bytes = evidence.into_bytes();
    bytes.extend_from_slice(&now_ms.to_be_bytes());
    Sha256Digest::for_bytes(&bytes).as_str().to_string()
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
