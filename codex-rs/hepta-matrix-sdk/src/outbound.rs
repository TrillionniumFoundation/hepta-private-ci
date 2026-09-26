use std::future::Future;
use std::pin::Pin;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixDispatchAuthorityClaim;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::OutboxRecord;
use tokio_util::sync::CancellationToken;

use crate::authority::MatrixAuthorityError;
use crate::authority::MatrixOutboundAuthorizer;
use crate::authority::MatrixOutboundIdentity;
use crate::authority::build_matrix_final_use_request;

const PARKED_RECONCILIATION_AT_MS: u64 = i64::MAX as u64;

pub type MatrixSendFuture<'a> =
    Pin<Box<dyn Future<Output = Result<MatrixEventId, MatrixTransportError>> + Send + 'a>>;

pub trait MatrixOutboundTransport: Send + Sync {
    /// Return the exact authenticated Matrix transport/session identity.
    fn identity(&self) -> Result<MatrixOutboundIdentity, MatrixTransportError>;

    /// Enter the physical Matrix adapter.
    ///
    /// Implementations must be lazy: this method may construct a future but
    /// must not perform external I/O until the returned future is polled.
    fn send<'a>(&'a self, record: &'a OutboxRecord) -> MatrixSendFuture<'a>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum MatrixTransportError {
    #[error("Matrix transport failed transiently or its effect is unknown")]
    Retryable,
    #[error("Matrix homeserver rate limited the request for {retry_after_ms} ms")]
    RateLimited { retry_after_ms: u64 },
    #[error("Matrix DNS resolution failed")]
    Dns,
    #[error("Matrix TLS establishment failed")]
    Tls,
    #[error("Matrix connection timed out")]
    ConnectTimeout,
    #[error("Matrix response timed out")]
    ReadTimeout,
    #[error("Matrix connection reset after adapter entry")]
    ConnectionReset,
    #[error("Matrix response was lost after adapter entry")]
    ResponseLost,
    #[error("Matrix homeserver is temporarily unavailable")]
    ServerUnavailable,
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
        self.lease_ms > 1
            && self.retry_delay_ms > 0
            && self.max_retry_delay_ms >= self.retry_delay_ms
            && (1..=64).contains(&self.max_attempts)
            && (1..=256).contains(&self.claim_limit)
            && !self.idle_poll.is_zero()
            && self.idle_poll <= Duration::from_secs(5)
    }

    fn physical_send_deadline(&self) -> Duration {
        Duration::from_millis(self.lease_ms.saturating_sub(1))
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct OutboxDispatchStats {
    pub claimed: u64,
    pub sent: u64,
    pub transport_accepted: u64,
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
    #[error("Matrix final-use authority rejected or was unavailable")]
    Authority,
    #[error("Matrix transport identity is unavailable")]
    TransportIdentity,
}

pub async fn dispatch_outbox_once<
    T: MatrixOutboundTransport + ?Sized,
    A: MatrixOutboundAuthorizer + ?Sized,
>(
    store: &MatrixDurableStore,
    transport: &T,
    authorizer: &A,
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
    for (index, record) in records.iter().enumerate() {
        let prepared = store
            .prepare_outbox_dispatch(record, now_ms)
            .await
            .map_err(store_error)?;
        if prepared.state.is_terminal() {
            if prepared.state == MatrixDispatchState::Succeeded
                || prepared.state == MatrixDispatchState::Redacted
            {
                stats.sent += 1;
            } else {
                stats.permanent_failure += 1;
            }
            continue;
        }
        if cancel.is_cancelled() {
            release_pre_entry_claims(store, &records[index..], now_ms).await?;
            stats.cancelled = true;
            break;
        }

        let identity = transport
            .identity()
            .map_err(|_| OutboxDispatchError::TransportIdentity)?;
        let request = build_matrix_final_use_request(
            store.owner_agent_id().as_str(),
            &prepared,
            record,
            &identity,
        )
        .map_err(authority_error)?;
        let signed = tokio::select! {
            biased;
            _ = cancel.cancelled() => {
                release_pre_entry_claims(store, &records[index..], now_ms).await?;
                stats.cancelled = true;
                break;
            }
            result = authorizer.signed_grant(&request) => result.map_err(authority_error)?,
        };
        let token = authorizer
            .authority()
            .claim(&signed, &request.binding)
            .map_err(|_| OutboxDispatchError::Authority)?;
        let claimed_authority_epoch = token.claimed_authority_epoch();
        let claimed_revocation_revision = token.claimed_revocation_revision();
        if claimed_authority_epoch != signed.grant.authority_epoch {
            return Err(OutboxDispatchError::Authority);
        }

        let claimed_at_ms = system_time_ms()?;
        store
            .record_dispatch_authority_claim(
                &record.stable_txn_id,
                &MatrixDispatchAuthorityClaim {
                    operation_id: request.operation_id.clone(),
                    subject_id: request.subject_id.clone(),
                    destination_id: request.destination_id.clone(),
                    homeserver_id: request.homeserver_id.clone(),
                    matrix_user_id: request.matrix_user_id.clone(),
                    device_id: request.device_id.clone(),
                    session_generation: request.session_generation,
                    authority_epoch: claimed_authority_epoch,
                    revocation_revision: claimed_revocation_revision,
                    grant_id: signed.grant.grant_id.clone(),
                    request_digest: request.request_digest.clone(),
                    scope_digest: request.scope_digest.clone(),
                    payload_digest: request.payload_digest.clone(),
                    attempt: record.attempts,
                    expires_at_ms: signed.grant.expires_at_unix_ms,
                    claimed_at_ms,
                },
            )
            .await
            .map_err(store_error)?;

        if cancel.is_cancelled() {
            release_pre_entry_claims(store, &records[index..], now_ms).await?;
            stats.cancelled = true;
            break;
        }
        authorizer
            .refresh_revocations()
            .map_err(authority_error)?;
        let entered = authorizer
            .authority()
            .enter_verified_use(token, &request.binding)
            .map_err(|_| OutboxDispatchError::Authority)?;
        if !entered.matches(&request.binding) {
            return Err(OutboxDispatchError::Authority);
        }

        let result = tokio::select! {
            biased;
            _ = cancel.cancelled() => Err(MatrixTransportError::ResponseLost),
            result = tokio::time::timeout(config.physical_send_deadline(), transport.send(record)) => {
                match result {
                    Ok(result) => result,
                    Err(_) => Err(MatrixTransportError::ReadTimeout),
                }
            }
        };
        match result {
            Ok(event_id) => {
                let observed = store
                    .record_outbox_transport_accepted(
                        &record.stable_txn_id,
                        record.attempts,
                        &event_id,
                        now_ms,
                    )
                    .await
                    .map_err(store_error)?;
                stats.transport_accepted += 1;
                if observed.state.is_terminal() {
                    stats.sent += 1;
                    continue;
                }
                let next_attempt_at_ms = reconciliation_attempt_at(config, record, now_ms)?;
                store
                    .mark_outbox_retry(
                        &record.stable_txn_id,
                        record.attempts,
                        now_ms,
                        next_attempt_at_ms,
                    )
                    .await
                    .map_err(store_error)?;
                count_retry(&mut stats, next_attempt_at_ms);
            }
            Err(error @ MatrixTransportError::RateLimited { .. }) => {
                store
                    .record_outbox_transport_indeterminate(
                        &record.stable_txn_id,
                        record.attempts,
                        now_ms,
                    )
                    .await
                    .map_err(store_error)?;
                let next_attempt_at_ms = classified_retry_at(config, record, now_ms, error)?;
                store
                    .mark_outbox_retry(
                        &record.stable_txn_id,
                        record.attempts,
                        now_ms,
                        next_attempt_at_ms,
                    )
                    .await
                    .map_err(store_error)?;
                count_retry(&mut stats, next_attempt_at_ms);
            }
            Err(
                error @ (MatrixTransportError::Retryable
                | MatrixTransportError::Dns
                | MatrixTransportError::Tls
                | MatrixTransportError::ConnectTimeout
                | MatrixTransportError::ReadTimeout
                | MatrixTransportError::ConnectionReset
                | MatrixTransportError::ResponseLost
                | MatrixTransportError::ServerUnavailable),
            ) => {
                store
                    .record_outbox_transport_indeterminate(
                        &record.stable_txn_id,
                        record.attempts,
                        now_ms,
                    )
                    .await
                    .map_err(store_error)?;
                let next_attempt_at_ms = classified_retry_at(config, record, now_ms, error)?;
                store
                    .mark_outbox_retry(
                        &record.stable_txn_id,
                        record.attempts,
                        now_ms,
                        next_attempt_at_ms,
                    )
                    .await
                    .map_err(store_error)?;
                count_retry(&mut stats, next_attempt_at_ms);
            }
            Err(MatrixTransportError::Permanent) => {
                let observed = store
                    .record_outbox_transport_rejected(
                        &record.stable_txn_id,
                        record.attempts,
                        now_ms,
                    )
                    .await
                    .map_err(store_error)?;
                if observed.state == MatrixDispatchState::Accepted {
                    store
                        .mark_outbox_retry(
                            &record.stable_txn_id,
                            record.attempts,
                            now_ms,
                            PARKED_RECONCILIATION_AT_MS,
                        )
                        .await
                        .map_err(store_error)?;
                    stats.indeterminate += 1;
                } else {
                    store
                        .mark_outbox_permanent_failure(
                            &record.stable_txn_id,
                            record.attempts,
                            now_ms,
                        )
                        .await
                        .map_err(store_error)?;
                    stats.permanent_failure += 1;
                }
            }
        }
    }
    Ok(stats)
}

pub async fn run_outbox_sender<
    T: MatrixOutboundTransport + ?Sized,
    A: MatrixOutboundAuthorizer + ?Sized,
>(
    store: &MatrixDurableStore,
    transport: &T,
    authorizer: &A,
    config: &OutboxDispatchConfig,
    cancel: &CancellationToken,
) -> Result<(), OutboxDispatchError> {
    loop {
        if cancel.is_cancelled() {
            return Ok(());
        }
        let stats = dispatch_outbox_once(
            store,
            transport,
            authorizer,
            config,
            cancel,
            system_time_ms()?,
        )
        .await?;
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

async fn release_pre_entry_claims(
    store: &MatrixDurableStore,
    records: &[OutboxRecord],
    now_ms: u64,
) -> Result<(), OutboxDispatchError> {
    for record in records {
        store
            .mark_outbox_retry(
                &record.stable_txn_id,
                record.attempts,
                now_ms,
                now_ms,
            )
            .await
            .map_err(store_error)?;
    }
    Ok(())
}

fn system_time_ms() -> Result<u64, OutboxDispatchError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OutboxDispatchError::Invalid)?
        .as_millis();
    u64::try_from(millis).map_err(|_| OutboxDispatchError::Invalid)
}

fn reconciliation_attempt_at(
    config: &OutboxDispatchConfig,
    record: &OutboxRecord,
    now_ms: u64,
) -> Result<u64, OutboxDispatchError> {
    if record.attempts >= config.max_attempts {
        return Ok(PARKED_RECONCILIATION_AT_MS);
    }
    now_ms
        .checked_add(retry_delay_ms(config, record.attempts)?)
        .ok_or(OutboxDispatchError::Invalid)
}

fn classified_retry_at(
    config: &OutboxDispatchConfig,
    record: &OutboxRecord,
    now_ms: u64,
    error: MatrixTransportError,
) -> Result<u64, OutboxDispatchError> {
    if record.attempts >= config.max_attempts {
        return Ok(PARKED_RECONCILIATION_AT_MS);
    }
    let base = match error {
        MatrixTransportError::RateLimited { retry_after_ms } => retry_after_ms
            .max(config.retry_delay_ms)
            .min(config.max_retry_delay_ms),
        MatrixTransportError::Retryable => retry_delay_ms(config, record.attempts)?,
        MatrixTransportError::Dns
        | MatrixTransportError::Tls
        | MatrixTransportError::ConnectTimeout
        | MatrixTransportError::ReadTimeout
        | MatrixTransportError::ConnectionReset
        | MatrixTransportError::ResponseLost
        | MatrixTransportError::ServerUnavailable => {
            let delay = retry_delay_ms(config, record.attempts)?;
            delay
                .saturating_add(stable_jitter_ms(record, delay))
                .min(config.max_retry_delay_ms)
        }
        MatrixTransportError::Permanent => return Err(OutboxDispatchError::Invalid),
    };
    now_ms
        .checked_add(base)
        .ok_or(OutboxDispatchError::Invalid)
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

fn stable_jitter_ms(record: &OutboxRecord, delay_ms: u64) -> u64 {
    let ceiling = delay_ms.saturating_div(5).min(1_000);
    if ceiling == 0 {
        return 0;
    }
    let mut state = record.attempts ^ 0xcbf29ce484222325;
    for byte in record.stable_txn_id.as_str().bytes() {
        state ^= u64::from(byte);
        state = state.wrapping_mul(0x100000001b3);
    }
    state % (ceiling + 1)
}

fn count_retry(stats: &mut OutboxDispatchStats, next_attempt_at_ms: u64) {
    if next_attempt_at_ms == PARKED_RECONCILIATION_AT_MS {
        stats.indeterminate += 1;
    } else {
        stats.retry_scheduled += 1;
    }
}

fn authority_error(_: MatrixAuthorityError) -> OutboxDispatchError {
    OutboxDispatchError::Authority
}

fn store_error(_: MatrixDurableError) -> OutboxDispatchError {
    OutboxDispatchError::Store
}
