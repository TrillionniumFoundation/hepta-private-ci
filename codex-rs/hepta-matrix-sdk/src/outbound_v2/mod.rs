use std::future::Future;
use std::pin::Pin;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_matrix_protocol::MatrixEventId;
use codex_hepta_matrix_store::MatrixAttemptFailureClass;
use codex_hepta_matrix_store::MatrixDispatchAttemptEventKind;
use codex_hepta_matrix_store::MatrixDispatchAuthorityClaim;
use codex_hepta_matrix_store::MatrixDispatchRecord;
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

mod clock;
mod gate;
mod retry;
use clock::DispatchClock;
use gate::FinalSendGate;
use retry::*;

const PARKED_RECONCILIATION_AT_MS: u64 = i64::MAX as u64;

pub type MatrixSendFuture<'a> =
    Pin<Box<dyn Future<Output = Result<MatrixEventId, MatrixTransportError>> + Send + 'a>>;

pub trait MatrixOutboundTransport: Send + Sync {
    /// Return the exact authenticated Matrix transport/session identity.
    fn identity(&self) -> Result<MatrixOutboundIdentity, MatrixTransportError>;

    /// Construct a lazy physical-adapter future; construction must perform no I/O.
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
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct OutboxDispatchStats {
    pub claimed: u64,
    pub sent: u64,
    pub transport_accepted: u64,
    pub indeterminate: u64,
    pub observed_unqualified: u64,
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
    #[error("Matrix claim expired before physical adapter entry")]
    LeaseExpired,
    #[error("Matrix dispatch was canceled before physical adapter entry")]
    Canceled,
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
    let clock = DispatchClock::new(now_ms);
    if cancel.is_cancelled() {
        return Ok(OutboxDispatchStats {
            cancelled: true,
            ..OutboxDispatchStats::default()
        });
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
        let mut entered_effect = false;
        let attempt_result: Result<(), OutboxDispatchError> = async {
            if cancel.is_cancelled() {
                return Err(OutboxDispatchError::Canceled);
            }
            let deadline = clock.deadline(claim.lease_until_ms())?;
            let prepared_at_ms = clock.now_ms()?;
            let prepared = store
                .prepare_outbox_dispatch(record, prepared_at_ms)
                .await
                .map_err(store_error)?;
            if prepared.state.is_terminal() {
                close_observed_terminal(store, claim, &prepared, &clock, &mut stats).await?;
                return Ok(());
            }
            store
                .record_outbox_prepared(claim, clock.now_ms()?)
                .await
                .map_err(store_error)?;
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
                _ = cancel.cancelled() => return Err(OutboxDispatchError::Canceled),
                result = tokio::time::timeout_at(deadline, authorizer.signed_grant(&request)) => {
                    result.map_err(|_| OutboxDispatchError::LeaseExpired)?.map_err(authority_error)?
                }
            };
            // This is an early refresh for nonce admission. The final gate
            // refreshes again in the very poll which enters the adapter.
            authorizer.refresh_revocations().map_err(authority_error)?;
            let token = authorizer
                .authority()
                .claim(&signed, &request.binding)
                .map_err(|_| OutboxDispatchError::Authority)?;
            let claimed_authority_epoch = token.claimed_authority_epoch();
            let claimed_revocation_revision = token.claimed_revocation_revision();
            if claimed_authority_epoch != signed.grant.authority_epoch {
                return Err(OutboxDispatchError::Authority);
            }
            let witness = MatrixOutboxAuthorityWitness {
                authority_epoch: claimed_authority_epoch,
                revocation_revision: claimed_revocation_revision,
                grant_id: signed.grant.grant_id.clone(),
                verified_use_witness_sha256: hex_digest(token.witness_sha256()),
                revocation_head_sha256: hex_digest(token.claimed_revocation_head_sha256()),
            };
            store
                .record_outbox_authorized(claim, &witness, clock.now_ms()?)
                .await
                .map_err(store_error)?;
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
                        claimed_at_ms: system_time_ms()?,
                    },
                )
                .await
                .map_err(store_error)?;
            if cancel.is_cancelled() {
                return Err(OutboxDispatchError::Canceled);
            }
            // Durable intent is NOT a statement that physical entry happened.
            store
                .record_outbox_dispatching(claim, clock.now_ms()?)
                .await
                .map_err(store_error)?;
            clock.deadline(claim.lease_until_ms())?;
            let gate = FinalSendGate {
                transport,
                authorizer,
                expected_identity: &identity,
                record,
                cancel,
                deadline,
            };
            let entered = gate.enter_verified_use(token, &request.binding).await?;
            entered_effect = true;
            let outcome_at_ms = clock.now_ms()?;
            match entered.result {
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
                        close_observed_terminal(store, claim, &observed, &clock, &mut stats).await?;
                    } else {
                        let scheduled_at_ms = clock.now_ms()?;
                        let next = reconciliation_attempt_at(config, record, scheduled_at_ms)?;
                        store
                            .finish_outbox_transport_accepted(claim, &event_id, scheduled_at_ms, next)
                            .await
                            .map_err(store_error)?;
                        count_retry(&mut stats, next);
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
                    } else {
                        store
                            .finish_outbox_permanently_rejected(claim, clock.now_ms()?)
                            .await
                            .map_err(store_error)?;
                        stats.permanent_failure += 1;
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
                        close_observed_terminal(store, claim, &observed, &clock, &mut stats).await?;
                    } else {
                        let scheduled_at_ms = clock.now_ms()?;
                        let next = classified_retry_at(config, record, scheduled_at_ms, error)?;
                        store
                            .finish_outbox_indeterminate(
                                claim,
                                failure_class(error),
                                retry_after_hint(error),
                                scheduled_at_ms,
                                next,
                            )
                            .await
                            .map_err(store_error)?;
                        count_retry(&mut stats, next);
                    }
                }
            }
            Ok(())
        }
        .await;
        if let Err(error) = attempt_result {
            // Never release an entered/unknown effect as a pre-entry cancel.
            // Every other claimed row is still independently safe to release.
            let remaining = if entered_effect { index + 1 } else { index };
            release_pre_entry_claims(
                store,
                &claims[remaining..],
                &clock,
                !entered_effect && error == OutboxDispatchError::Authority,
            )
            .await?;
            if error == OutboxDispatchError::Canceled {
                stats.cancelled = true;
                break;
            }
            return Err(error);
        }
    }
    stats.cancelled |= cancel.is_cancelled();
    Ok(stats)
}

async fn close_observed_terminal(
    store: &MatrixDurableStore,
    claim: &MatrixFencedOutboxClaim,
    observed: &MatrixDispatchRecord,
    clock: &DispatchClock,
    stats: &mut OutboxDispatchStats,
) -> Result<(), OutboxDispatchError> {
    let kind = match observed.state {
        MatrixDispatchState::Succeeded => MatrixDispatchAttemptEventKind::Confirmed,
        MatrixDispatchState::Redacted => MatrixDispatchAttemptEventKind::Redacted,
        // The remote effect exists, but no qualified authority claim follows
        // from that fact. Do not misreport it as a permanent transport failure.
        MatrixDispatchState::ObservedUnqualified => {
            if observed.redaction_observation_digest.is_some() {
                MatrixDispatchAttemptEventKind::Redacted
            } else {
                MatrixDispatchAttemptEventKind::Confirmed
            }
        }
        MatrixDispatchState::Failed => MatrixDispatchAttemptEventKind::PermanentlyRejected,
        _ => return Err(OutboxDispatchError::Store),
    };
    store
        .close_terminal_outbox_claim(
            claim,
            kind,
            observed.terminal_event_id.as_ref(),
            clock.now_ms()?,
        )
        .await
        .map_err(store_error)?;
    match observed.state {
        MatrixDispatchState::Succeeded | MatrixDispatchState::Redacted => stats.sent += 1,
        MatrixDispatchState::ObservedUnqualified => stats.observed_unqualified += 1,
        MatrixDispatchState::Failed => stats.permanent_failure += 1,
        _ => return Err(OutboxDispatchError::Store),
    }
    Ok(())
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
