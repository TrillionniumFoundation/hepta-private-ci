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

mod admission;
mod clock;
mod gate;
mod permit;
mod retry;
mod settlement;
mod telemetry;
use admission::Admission;
use admission::admit_claim;
use clock::DispatchClock;
use gate::FinalSendGate;
use permit::MatrixSendPermit;
use retry::*;
use settlement::settle_entered;
use telemetry::TelemetryWindow;

const PARKED_RECONCILIATION_AT_MS: u64 = i64::MAX as u64;

pub type MatrixSendFuture<'a> =
    Pin<Box<dyn Future<Output = Result<MatrixEventId, MatrixTransportError>> + Send + 'a>>;

/// Unforgeable safe-code admission to the raw transport implementation.
///
/// This type is public only because [`MatrixOutboundTransport`] is implementable
/// by external deterministic fixtures. Its field is private.
///
/// ```compile_fail
/// use codex_hepta_matrix_sdk::MatrixRawSendSeal;
/// let _forged = MatrixRawSendSeal { _private: () };
/// ```
#[doc(hidden)]
pub struct MatrixRawSendSeal {
    _private: (),
}

/// Lazy Matrix transport driven by the durable sender's final gate.
///
/// Implementations expose only the sealed raw seam. Permit validation and
/// construction of this seal live in a module-private blanket adapter, so an
/// external transport cannot override or bypass the authorized entry step.
pub trait MatrixOutboundTransport: Send + Sync {
    /// Return the exact authenticated Matrix transport/session identity.
    fn identity(&self) -> Result<MatrixOutboundIdentity, MatrixTransportError>;

    /// Raw implementation seam; safe downstream code cannot construct the seal.
    /// The durable gate invokes this method only from a live-gated poll.
    #[doc(hidden)]
    fn send<'a>(
        &'a self,
        record: &'a OutboxRecord,
        seal: MatrixRawSendSeal,
    ) -> MatrixSendFuture<'a>;
}

/// Final, module-private permit adapter. The blanket implementation prevents a
/// transport implementation from replacing permit validation with its own
/// behavior. Validation failure after kernel entry is returned to the gate as
/// an entered error, never as a remote permanent rejection.
trait MatrixAuthorizedTransport: MatrixOutboundTransport {
    fn send_authorized<'a>(
        &'a self,
        record: &'a OutboxRecord,
        permit: MatrixSendPermit,
    ) -> Result<MatrixSendFuture<'a>, OutboxDispatchError> {
        let identity = self
            .identity()
            .map_err(|_| OutboxDispatchError::TransportIdentity)?;
        if permit.validate(record, &identity).is_err() {
            return Err(OutboxDispatchError::Authority);
        }
        Ok(self.send(record, MatrixRawSendSeal { _private: () }))
    }
}

impl<T: MatrixOutboundTransport + ?Sized> MatrixAuthorizedTransport for T {}

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
    /// Maximum work per pass, not the number of leases reserved in advance.
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

/// Per-pass counters. Timings are measurements, never deployment SLOs.
/// No transaction, room, user, grant, capability or message bytes are retained.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, serde::Serialize)]
pub struct OutboxDispatchStats {
    pub claimed: u64,
    pub sent: u64,
    pub transport_accepted: u64,
    pub indeterminate: u64,
    pub observed_unqualified: u64,
    pub retry_scheduled: u64,
    pub permanent_failure: u64,
    pub cancelled: bool,
    pub entered_attempts: u64,
    pub pre_entry_failures: u64,
    pub post_entry_failures: u64,
    pub claim_to_first_poll_samples: u64,
    pub claim_to_first_poll_ms: u64,
    pub claim_to_first_poll_max_ms: u64,
    pub transport_polls: u64,
    pub payload_digest_checks: u64,
    pub payload_digest_ns: u64,
    pub dynamic_checks: u64,
    pub dynamic_check_ns: u64,
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
    let mut stats = OutboxDispatchStats::default();
    dispatch_pass(
        store, transport, authorizer, config, cancel, now_ms, &mut stats,
    )
    .await?;
    Ok(stats)
}

async fn dispatch_pass<
    T: MatrixOutboundTransport + ?Sized,
    A: MatrixOutboundAuthorizer + ?Sized,
>(
    store: &MatrixDurableStore,
    transport: &T,
    authorizer: &A,
    config: &OutboxDispatchConfig,
    cancel: &CancellationToken,
    now_ms: u64,
    stats: &mut OutboxDispatchStats,
) -> Result<(), OutboxDispatchError> {
    if !config.is_valid() {
        return Err(OutboxDispatchError::Invalid);
    }
    let clock = DispatchClock::new(now_ms);
    for _ in 0..config.claim_limit {
        if cancel.is_cancelled() {
            stats.cancelled = true;
            break;
        }
        // Acquire immediately before preparation. Later messages keep no lease
        // while an earlier message waits on SQLite, the broker or transport.
        let claims = store
            .claim_outbox_fenced(clock.now_ms()?, config.lease_ms, /*limit*/ 1)
            .await
            .map_err(store_error)?;
        let Some(claim) = claims.first() else {
            break;
        };
        stats.claimed += 1;
        match admit_claim(store, transport, authorizer, claim, &clock, cancel, stats).await {
            Ok(Admission::AlreadyTerminal) => {}
            Ok(Admission::Entered(entered)) => {
                // No pre-entry cleanup is reachable from this arm. In
                // particular, a failed timestamp or outcome write leaves the
                // exact entered claim fenced for recovery, not released.
                if let Err(error) = settle_entered(store, &entered, config, &clock, stats).await {
                    stats.post_entry_failures += 1;
                    return Err(error);
                }
            }
            Err(error) => {
                stats.pre_entry_failures += 1;
                release_pre_entry_claims(
                    store,
                    &claims,
                    &clock,
                    error == OutboxDispatchError::Authority,
                )
                .await?;
                if error == OutboxDispatchError::Canceled {
                    stats.cancelled = true;
                    break;
                }
                return Err(error);
            }
        }
    }
    stats.cancelled |= cancel.is_cancelled();
    Ok(())
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
    let mut telemetry = TelemetryWindow::new();
    loop {
        if cancel.is_cancelled() {
            telemetry.observe(
                &OutboxDispatchStats {
                    cancelled: true,
                    ..OutboxDispatchStats::default()
                },
                /*error*/ None,
            );
            return Ok(());
        }
        let mut stats = OutboxDispatchStats::default();
        let result = dispatch_pass(
            store,
            transport,
            authorizer,
            config,
            cancel,
            system_time_ms()?,
            &mut stats,
        )
        .await;
        // Also retain partial counters when a pass fails after entry.
        telemetry.observe(&stats, result.as_ref().err().copied());
        result?;
        if stats.cancelled {
            return Ok(());
        }
        if stats.claimed == 0 {
            tokio::select! {
                _ = cancel.cancelled() => {
                    telemetry.flush(/*error*/ None);
                    return Ok(());
                }
                _ = tokio::time::sleep(config.idle_poll) => {}
            }
        }
    }
}
