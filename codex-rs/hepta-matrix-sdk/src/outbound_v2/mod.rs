use std::future::Future;
use std::pin::Pin;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixAttemptFailureClass;
use codex_hepta_matrix_store::MatrixDispatchAttemptEventKind;
use codex_hepta_matrix_store::MatrixDispatchAuthorityClaim;
use codex_hepta_matrix_store::MatrixDispatchState;
use codex_hepta_matrix_store::MatrixDurableError;
use codex_hepta_matrix_store::MatrixDurableStore;
use codex_hepta_matrix_store::MatrixFencedOutboxClaim;
use codex_hepta_matrix_store::MatrixOutboxAuthorityWitness;
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
    #[error("Matrix connection failed")]
    ConnectFailure,
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
        self.lease_ms > 2
            && self.retry_delay_ms > 0
            && self.max_retry_delay_ms >= self.retry_delay_ms
            && (1..=64).contains(&self.max_attempts)
            && (1..=256).contains(&self.claim_limit)
            && !self.idle_poll.is_zero()
            && self.idle_poll <= Duration::from_secs(5)
    }

    fn physical_send_deadline(
        &self,
        remaining_lease_ms: u64,
    ) -> Result<Duration, OutboxDispatchError> {
        let deadline_ms = self
            .lease_ms
            .saturating_sub(1)
            .min(remaining_lease_ms.saturating_sub(1));
        if deadline_ms == 0 {
            return Err(OutboxDispatchError::Invalid);
        }
        Ok(Duration::from_millis(deadline_ms))
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
    let claims = store
        .claim_outbox_fenced(now_ms, config.lease_ms, config.claim_limit)
        .await
        .map_err(store_error)?;
    let mut stats = OutboxDispatchStats {
        claimed: claims.len() as u64,
        ..OutboxDispatchStats::default()
    };

    for index in 0..claims.len() {
        let claim = &claims[index];
        let record = claim.record();
        let prepared_at_ms = per_record_time(now_ms, index, 0)?;
        let prepared = store
            .prepare_outbox_dispatch(record, prepared_at_ms)
            .await
            .map_err(store_error)?;
        store
            .record_outbox_prepared(claim, prepared_at_ms)
            .await
            .map_err(store_error)?;
        if prepared.state.is_terminal() {
            let (kind, successful) = match prepared.state {
                MatrixDispatchState::Succeeded => {
                    (MatrixDispatchAttemptEventKind::Confirmed, true)
                }
                MatrixDispatchState::Redacted => {
                    (MatrixDispatchAttemptEventKind::Redacted, true)
                }
                MatrixDispatchState::ObservedUnqualified | MatrixDispatchState::Failed => (
                    MatrixDispatchAttemptEventKind::PermanentlyRejected,
                    false,
                ),
                MatrixDispatchState::Dispatched
                | MatrixDispatchState::Accepted
                | MatrixDispatchState::Indeterminate => {
                    return Err(OutboxDispatchError::Store);
                }
            };
            store
                .close_terminal_outbox_claim(
                    claim,
                    kind,
                    prepared.terminal_event_id.as_ref(),
                    per_record_time(now_ms, index, 1)?,
                )
                .await
                .map_err(store_error)?;
            if successful {
                stats.sent += 1;
            } else {
                stats.permanent_failure += 1;
            }
            continue;
        }
        if cancel.is_cancelled() {
            release_pre_entry_claims(store, &claims[index..], prepared_at_ms).await?;
            stats.cancelled = true;
            break;
        }

        let identity = match transport.identity() {
            Ok(identity) => identity,
            Err(_) => {
                release_pre_entry_claims(store, &claims[index..], prepared_at_ms).await?;
                return Err(OutboxDispatchError::TransportIdentity);
            }
        };
        let request = match build_matrix_final_use_request(
            store.owner_agent_id().as_str(),
            &prepared,
            record,
            &identity,
        ) {
            Ok(request) => request,
            Err(error) => {
                release_pre_entry_claims(store, &claims[index..], prepared_at_ms).await?;
                return Err(authority_error(error));
            }
        };
        let signed_result = tokio::select! {
            biased;
            _ = cancel.cancelled() => {
                release_pre_entry_claims(store, &claims[index..], prepared_at_ms).await?;
                stats.cancelled = true;
                break;
            }
            result = authorizer.signed_grant(&request) => result,
        };
        let signed = match signed_result {
            Ok(signed) => signed,
            Err(error) => {
                release_pre_entry_claims(store, &claims[index..], prepared_at_ms).await?;
                return Err(authority_error(error));
            }
        };
        let token = match authorizer.authority().claim(&signed, &request.binding) {
            Ok(token) => token,
            Err(_) => {
                store
                    .release_outbox_claim_revoked(
                        claim,
                        per_record_time(now_ms, index, 1)?,
                    )
                    .await
                    .map_err(store_error)?;
                return Err(OutboxDispatchError::Authority);
            }
        };
        let claimed_authority_epoch = token.claimed_authority_epoch();
        let claimed_revocation_revision = token.claimed_revocation_revision();
        if claimed_authority_epoch != signed.grant.authority_epoch {
            store
                .release_outbox_claim_revoked(claim, per_record_time(now_ms, index, 1)?)
                .await
                .map_err(store_error)?;
            return Err(OutboxDispatchError::Authority);
        }

        let witness = MatrixOutboxAuthorityWitness {
            authority_epoch: claimed_authority_epoch,
            revocation_revision: claimed_revocation_revision,
            grant_id: signed.grant.grant_id.clone(),
            verified_use_witness_sha256: hex_digest(token.witness_sha256()),
            revocation_head_sha256: hex_digest(token.claimed_revocation_head_sha256()),
        };
        let authorized_at_ms = per_record_time(now_ms, index, 1)?;
        store
            .record_outbox_authorized(claim, &witness, authorized_at_ms)
            .await
            .map_err(store_error)?;

        let authority_claimed_at_ms = system_time_ms()?;
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
                    claimed_at_ms: authority_claimed_at_ms,
                },
            )
            .await
            .map_err(store_error)?;

        if cancel.is_cancelled() {
            release_pre_entry_claims(store, &claims[index..], authorized_at_ms).await?;
            stats.cancelled = true;
            break;
        }

        // This is the final persistence point before the physical effect. The
        // authority frontier is refreshed and the opaque token is consumed
        // after this await, so no await or persistence can stale the permit.
        let dispatching_at_ms = per_record_time(now_ms, index, 2)?;
        let remaining_lease_ms = store
            .record_outbox_dispatching(claim, dispatching_at_ms)
            .await
            .map_err(store_error)?;
        if let Err(error) = authorizer.refresh_revocations() {
            store
                .release_outbox_claim_revoked(claim, dispatching_at_ms)
                .await
                .map_err(store_error)?;
            return Err(authority_error(error));
        }
        let entered = match authorizer
            .authority()
            .enter_verified_use(token, &request.binding)
        {
            Ok(entered) => entered,
            Err(_) => {
                store
                    .release_outbox_claim_revoked(claim, dispatching_at_ms)
                    .await
                    .map_err(store_error)?;
                return Err(OutboxDispatchError::Authority);
            }
        };
        if !entered.matches(&request.binding) {
            store
                .release_outbox_claim_revoked(claim, dispatching_at_ms)
                .await
                .map_err(store_error)?;
            return Err(OutboxDispatchError::Authority);
        }

        let deadline = config.physical_send_deadline(remaining_lease_ms)?;
        let result = tokio::select! {
            biased;
            _ = cancel.cancelled() => Err(MatrixTransportError::ResponseLost),
            result = tokio::time::timeout(deadline, transport.send(record)) => {
                match result {
                    Ok(result) => result,
                    Err(_) => Err(MatrixTransportError::ReadTimeout),
                }
            }
        };
        let outcome_at_ms = per_record_time(now_ms, index, 3)?;
        match result {
            Ok(event_id) => {
                let observed = store
                    .record_outbox_transport_accepted(
                        &record.stable_txn_id,
                        record.attempts,
                        &event_id,
                        outcome_at_ms,
                    )
                    .await
                    .map_err(store_error)?;
                stats.transport_accepted += 1;
                if observed.state.is_terminal() {
                    let kind = if observed.state == MatrixDispatchState::Redacted {
                        MatrixDispatchAttemptEventKind::Redacted
                    } else {
                        MatrixDispatchAttemptEventKind::Confirmed
                    };
                    store
                        .close_terminal_outbox_claim(
                            claim,
                            kind,
                            observed.terminal_event_id.as_ref(),
                            outcome_at_ms,
                        )
                        .await
                        .map_err(store_error)?;
                    stats.sent += 1;
                    continue;
                }
                let next_attempt_at_ms =
                    reconciliation_attempt_at(config, record, outcome_at_ms)?;
                store
                    .finish_outbox_transport_accepted(
                        claim,
                        &event_id,
                        outcome_at_ms,
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
                        outcome_at_ms,
                    )
                    .await
                    .map_err(store_error)?;
                let next_attempt_at_ms =
                    classified_retry_at(config, record, outcome_at_ms, error)?;
                store
                    .finish_outbox_indeterminate(
                        claim,
                        failure_class(error),
                        retry_after_hint(error),
                        outcome_at_ms,
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
                | MatrixTransportError::ConnectFailure
                | MatrixTransportError::ReadTimeout
                | MatrixTransportError::ConnectionReset
                | MatrixTransportError::ResponseLost
                | MatrixTransportError::ServerUnavailable),
            ) => {
                store
                    .record_outbox_transport_indeterminate(
                        &record.stable_txn_id,
                        record.attempts,
                        outcome_at_ms,
                    )
                    .await
                    .map_err(store_error)?;
                let next_attempt_at_ms =
                    classified_retry_at(config, record, outcome_at_ms, error)?;
                store
                    .finish_outbox_indeterminate(
                        claim,
                        failure_class(error),
                        None,
                        outcome_at_ms,
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
                        outcome_at_ms,
                    )
                    .await
                    .map_err(store_error)?;
                if observed.state == MatrixDispatchState::Accepted {
                    store
                        .finish_outbox_indeterminate(
                            claim,
                            MatrixAttemptFailureClass::Permanent,
                            None,
                            outcome_at_ms,
                            PARKED_RECONCILIATION_AT_MS,
                        )
                        .await
                        .map_err(store_error)?;
                    stats.indeterminate += 1;
                } else {
                    store
                        .finish_outbox_permanently_rejected(claim, outcome_at_ms)
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

mod retry;
use retry::*;
