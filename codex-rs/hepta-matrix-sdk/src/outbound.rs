use std::future::Future;
use std::pin::Pin;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixDispatchError;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::OutboxRecord;
use codex_hepta_matrix_store::OutboxState;
use codex_hepta_matrix_store::SendIntent;
use codex_hepta_matrix_store::SendState;
use tokio_util::sync::CancellationToken;

pub type MatrixSendFuture<'a> =
    Pin<Box<dyn Future<Output = Result<MatrixEventId, MatrixTransportError>> + Send + 'a>>;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MatrixDispatchContext {
    pub homeserver_id: String,
    pub device_id: String,
    pub session_generation: u64,
    pub authority_identity: String,
    pub authority_epoch: u64,
}

pub trait MatrixOutboundTransport: Send + Sync {
    fn dispatch_context(
        &self,
        record: &OutboxRecord,
    ) -> Result<MatrixDispatchContext, MatrixTransportError>;

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
    pub accepted: u64,
    pub indeterminate: u64,
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
        let context = match transport.dispatch_context(&record) {
            Ok(context) => context,
            Err(_) => {
                mark_permanent_or_observed(store, &record, now_ms, &mut stats).await?;
                continue;
            }
        };
        let operation_id = format!("matrix-send-{}", record.stable_txn_id.as_str());
        let payload_digest = Sha256Digest::for_bytes(&record.payload).as_str().to_string();
        let intent = SendIntent {
            operation_id: operation_id.clone(),
            transaction_id: record.stable_txn_id.as_str().to_string(),
            homeserver_id: context.homeserver_id,
            room_id: record.room_id.as_str().to_string(),
            device_id: context.device_id,
            session_generation: context.session_generation,
            authority_identity: context.authority_identity,
            authority_epoch: context.authority_epoch,
            payload_digest: payload_digest.clone(),
            grant_payload_digest: payload_digest,
            deadline_ms: record
                .created_at_ms
                .checked_add(100 * 365 * 24 * 60 * 60 * 1_000)
                .ok_or(OutboxDispatchError::Invalid)?,
        };
        let prepared = store
            .prepare_send(now_ms, &intent)
            .await
            .map_err(dispatch_error)?;
        match prepared.state {
            SendState::Succeeded | SendState::Redacted => {
                stats.sent += 1;
                continue;
            }
            SendState::Failed => {
                mark_permanent_or_observed(store, &record, now_ms, &mut stats).await?;
                continue;
            }
            SendState::Prepared
            | SendState::Dispatched
            | SendState::Accepted
            | SendState::Indeterminate => {}
        }

        let attempt_digest = dispatch_observation_digest(
            "attempt",
            &record,
            record.attempts,
            now_ms,
            None,
        );
        store
            .mark_send_dispatched(&operation_id, &attempt_digest, now_ms)
            .await
            .map_err(dispatch_error)?;

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
                let accepted_digest = dispatch_observation_digest(
                    "transport-accepted",
                    &record,
                    record.attempts,
                    now_ms,
                    Some(&event_id),
                );
                let receipt = store
                    .record_transport_accepted(
                        &operation_id,
                        &event_id,
                        &accepted_digest,
                        now_ms,
                    )
                    .await
                    .map_err(dispatch_error)?;
                stats.accepted += 1;
                if matches!(receipt.state, SendState::Succeeded | SendState::Redacted) {
                    stats.sent += 1;
                    continue;
                }
                if record.attempts >= config.max_attempts {
                    mark_permanent_or_observed(store, &record, now_ms, &mut stats).await?;
                } else {
                    schedule_retry_or_observed(store, &record, config, now_ms, &mut stats).await?;
                }
            }
            Err(MatrixTransportError::Retryable) => {
                let digest = dispatch_observation_digest(
                    "transport-indeterminate",
                    &record,
                    record.attempts,
                    now_ms,
                    None,
                );
                store
                    .record_transport_indeterminate(&operation_id, &digest, now_ms)
                    .await
                    .map_err(dispatch_error)?;
                stats.indeterminate += 1;
                if record.attempts >= config.max_attempts {
                    mark_permanent_or_observed(store, &record, now_ms, &mut stats).await?;
                } else {
                    schedule_retry_or_observed(store, &record, config, now_ms, &mut stats).await?;
                }
            }
            Err(MatrixTransportError::Permanent) => {
                let digest = dispatch_observation_digest(
                    "transport-permanent",
                    &record,
                    record.attempts,
                    now_ms,
                    None,
                );
                store
                    .record_transport_indeterminate(&operation_id, &digest, now_ms)
                    .await
                    .map_err(dispatch_error)?;
                stats.indeterminate += 1;
                mark_permanent_or_observed(store, &record, now_ms, &mut stats).await?;
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

async fn schedule_retry_or_observed(
    store: &MatrixDurableStore,
    record: &OutboxRecord,
    config: &OutboxDispatchConfig,
    now_ms: u64,
    stats: &mut OutboxDispatchStats,
) -> Result<(), OutboxDispatchError> {
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
            stats.retry_scheduled += 1;
            Ok(())
        }
        Err(MatrixDurableError::Conflict) => observed_race(store, record, stats).await,
        Err(error) => Err(store_error(error)),
    }
}

async fn mark_permanent_or_observed(
    store: &MatrixDurableStore,
    record: &OutboxRecord,
    now_ms: u64,
    stats: &mut OutboxDispatchStats,
) -> Result<(), OutboxDispatchError> {
    match store
        .mark_outbox_permanent_failure(&record.stable_txn_id, record.attempts, now_ms)
        .await
    {
        Ok(_) => {
            stats.permanent_failure += 1;
            Ok(())
        }
        Err(MatrixDurableError::Conflict) => observed_race(store, record, stats).await,
        Err(error) => Err(store_error(error)),
    }
}

async fn observed_race(
    store: &MatrixDurableStore,
    record: &OutboxRecord,
    stats: &mut OutboxDispatchStats,
) -> Result<(), OutboxDispatchError> {
    let current = store
        .outbox_for_txn(&record.stable_txn_id)
        .await
        .map_err(store_error)?
        .ok_or(OutboxDispatchError::Store)?;
    if current.state == OutboxState::Sent {
        stats.sent += 1;
        Ok(())
    } else {
        Err(OutboxDispatchError::Store)
    }
}

fn dispatch_observation_digest(
    kind: &str,
    record: &OutboxRecord,
    attempt: u64,
    now_ms: u64,
    event_id: Option<&MatrixEventId>,
) -> String {
    let identity = format!(
        "hepta.matrix.dispatch-observation.v1\0{kind}\0{}\0{attempt}\0{now_ms}\0{}",
        record.stable_txn_id.as_str(),
        event_id.map(MatrixEventId::as_str).unwrap_or("")
    );
    Sha256Digest::for_bytes(identity.as_bytes()).as_str().to_string()
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

fn dispatch_error(_: MatrixDispatchError) -> OutboxDispatchError {
    OutboxDispatchError::Store
}
