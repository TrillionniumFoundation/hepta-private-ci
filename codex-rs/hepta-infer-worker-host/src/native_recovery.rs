//! Explicit recovery and observability boundary for hosted App Server runs.
//!
//! Provider terminality, usage and owner authority are deliberately separate.
//! A trusted provider verifier may settle terminal provider evidence for the
//! exact durable dispatch, but this module never upgrades that evidence to an
//! authorized successful effect on its own. Missing history remains quarantined
//! and is never converted into retry-safe or definitely-unsent state.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;

const MIN_RECONCILE_GRACE: Duration = Duration::from_millis(10);
const MAX_RECONCILE_GRACE: Duration = Duration::from_secs(30);
const MAX_REASON_BYTES: usize = 4096;
const MAX_OUTPUT_BYTES: usize = 1024 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NativeRecoveryPolicy {
    turn_start_reconcile_grace: Duration,
}

impl NativeRecoveryPolicy {
    pub fn new(turn_start_reconcile_grace: Duration) -> Result<Self, NativeRecoveryError> {
        if turn_start_reconcile_grace < MIN_RECONCILE_GRACE
            || turn_start_reconcile_grace > MAX_RECONCILE_GRACE
        {
            return Err(NativeRecoveryError::InvalidPolicy(
                "turn/start reconcile grace must be between 10 ms and 30 s",
            ));
        }
        Ok(Self {
            turn_start_reconcile_grace,
        })
    }

    pub fn turn_start_reconcile_grace(self) -> Duration {
        self.turn_start_reconcile_grace
    }
}

impl Default for NativeRecoveryPolicy {
    fn default() -> Self {
        Self {
            turn_start_reconcile_grace: Duration::from_secs(2),
        }
    }
}

#[derive(Debug, Default)]
pub struct NativeRecoveryCounters {
    reconcile_attempts: AtomicU64,
    reconcile_successes: AtomicU64,
    reconcile_misses: AtomicU64,
    reconcile_failures: AtomicU64,
    provider_receipt_successes: AtomicU64,
    provider_receipt_failures: AtomicU64,
    authority_denials: AtomicU64,
    interrupt_latency_samples: AtomicU64,
    interrupt_latency_micros: AtomicU64,
    maximum_interrupt_latency_micros: AtomicU64,
}

impl NativeRecoveryCounters {
    pub(crate) fn record_reconcile_attempt(&self) {
        self.reconcile_attempts.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_reconcile_success(&self) {
        self.reconcile_successes.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_reconcile_miss(&self) {
        self.reconcile_misses.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_reconcile_failure(&self) {
        self.reconcile_failures.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_authority_denial(&self) {
        self.authority_denials.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_cancellation_to_interrupt_latency(&self, latency: Duration) {
        let micros = u64::try_from(latency.as_micros()).unwrap_or(u64::MAX);
        self.interrupt_latency_samples
            .fetch_add(1, Ordering::Relaxed);
        self.interrupt_latency_micros
            .fetch_add(micros, Ordering::Relaxed);
        let mut observed = self
            .maximum_interrupt_latency_micros
            .load(Ordering::Relaxed);
        while micros > observed {
            match self.maximum_interrupt_latency_micros.compare_exchange_weak(
                observed,
                micros,
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(current) => observed = current,
            }
        }
    }

    pub fn snapshot(&self) -> NativeRecoveryCounterSnapshot {
        NativeRecoveryCounterSnapshot {
            reconcile_attempts: self.reconcile_attempts.load(Ordering::Relaxed),
            reconcile_successes: self.reconcile_successes.load(Ordering::Relaxed),
            reconcile_misses: self.reconcile_misses.load(Ordering::Relaxed),
            reconcile_failures: self.reconcile_failures.load(Ordering::Relaxed),
            provider_receipt_successes: self
                .provider_receipt_successes
                .load(Ordering::Relaxed),
            provider_receipt_failures: self
                .provider_receipt_failures
                .load(Ordering::Relaxed),
            authority_denials: self.authority_denials.load(Ordering::Relaxed),
            interrupt_latency_samples: self
                .interrupt_latency_samples
                .load(Ordering::Relaxed),
            interrupt_latency_micros: self
                .interrupt_latency_micros
                .load(Ordering::Relaxed),
            maximum_interrupt_latency_micros: self
                .maximum_interrupt_latency_micros
                .load(Ordering::Relaxed),
        }
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct NativeRecoveryCounterSnapshot {
    pub reconcile_attempts: u64,
    pub reconcile_successes: u64,
    pub reconcile_misses: u64,
    pub reconcile_failures: u64,
    pub provider_receipt_successes: u64,
    pub provider_receipt_failures: u64,
    pub authority_denials: u64,
    pub interrupt_latency_samples: u64,
    pub interrupt_latency_micros: u64,
    pub maximum_interrupt_latency_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeRecoverySnapshot {
    pub total_records: usize,
    pub held_reservations: usize,
    pub indeterminate_count: usize,
    pub missing_usage_count: usize,
    pub terminal_without_usage_count: usize,
    pub native_maximum_in_flight: Option<usize>,
    pub journal_record_capacity: usize,
    pub journal_bytes: u64,
    pub oldest_indeterminate_age_ms: Option<u64>,
    pub age_evidence_complete: bool,
    pub counters: NativeRecoveryCounterSnapshot,
}

impl NativeRecoverySnapshot {
    /// New journal records carry the first durable indeterminate observation
    /// time. `first_indeterminate_ms` remains a compatibility projection for
    /// historical records that predate persisted age evidence.
    pub fn observe(
        control: &DurableInferenceControl,
        now_ms: u64,
        first_indeterminate_ms: &BTreeMap<String, u64>,
        counters: &NativeRecoveryCounters,
    ) -> Self {
        let mut total_records = 0_usize;
        let mut held_reservations = 0_usize;
        let mut indeterminate_count = 0_usize;
        let mut missing_usage_count = 0_usize;
        let mut terminal_without_usage_count = 0_usize;
        let mut oldest_indeterminate_age_ms = 0_u64;
        let mut age_evidence_complete = true;

        for record in control.native_records() {
            total_records += 1;
            if record.state != NativeReservationState::Released {
                held_reservations += 1;
            }
            let indeterminate = record.state == NativeReservationState::Indeterminate
                || record
                    .observation
                    .as_ref()
                    .is_some_and(|output| output.status == NativeRunStatus::Indeterminate);
            if indeterminate {
                indeterminate_count += 1;
                let first_seen = record.first_indeterminate_at_unix_ms.or_else(|| {
                    first_indeterminate_ms
                        .get(&record.request.request_id)
                        .copied()
                });
                match first_seen {
                    Some(first_seen) if first_seen <= now_ms => {
                        oldest_indeterminate_age_ms =
                            oldest_indeterminate_age_ms.max(now_ms - first_seen);
                    }
                    _ => age_evidence_complete = false,
                }
            }
            if let Some(output) = &record.observation {
                if output.observed_output_tokens.is_none() {
                    missing_usage_count += 1;
                    if output.terminal_observed {
                        terminal_without_usage_count += 1;
                    }
                }
            }
        }

        Self {
            total_records,
            held_reservations,
            indeterminate_count,
            missing_usage_count,
            terminal_without_usage_count,
            native_maximum_in_flight: control.native_maximum_in_flight(),
            journal_record_capacity: control.journal_record_capacity(),
            journal_bytes: control.native_journal_bytes(),
            oldest_indeterminate_age_ms: if indeterminate_count == 0 {
                Some(0)
            } else if age_evidence_complete {
                Some(oldest_indeterminate_age_ms)
            } else {
                None
            },
            age_evidence_complete,
            counters: counters.snapshot(),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderTerminalReceipt {
    pub request_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub model: String,
    pub model_provider: String,
    pub status: NativeRunStatus,
    pub output: String,
    /// `None` is unknown usage and is never normalized to zero.
    pub observed_output_tokens: Option<u64>,
    pub stop_reason: Option<String>,
    /// Domain-separated digest or signature witness produced by the trusted
    /// verifier for this exact terminal receipt and durable dispatch.
    pub verifier_witness_digest: String,
}

pub type ProviderReceiptVerificationFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<ProviderTerminalReceipt, NativeRecoveryError>>
            + Send
            + 'a,
    >,
>;

/// Trusted composition port. Implementations must authenticate the provider or
/// an independently operated reconciler and bind the complete durable record.
pub trait TrustedProviderTerminalReceiptVerifier: Send + Sync {
    fn verify<'a>(
        &'a self,
        record: &'a NativeRunRecord,
        proposed: ProviderTerminalReceipt,
    ) -> ProviderReceiptVerificationFuture<'a>;
}

pub async fn reconcile_provider_terminal<V: TrustedProviderTerminalReceiptVerifier>(
    control: &mut DurableInferenceControl,
    request_id: &str,
    proposed: ProviderTerminalReceipt,
    verifier: &V,
    counters: &NativeRecoveryCounters,
) -> Result<NativeRunRecord, NativeRecoveryError> {
    let record = control
        .native_record(request_id)
        .cloned()
        .ok_or(NativeRecoveryError::RequestNotFound)?;
    if record
        .observation
        .as_ref()
        .is_some_and(|output| output.terminal_observed)
    {
        return Err(NativeRecoveryError::AlreadyTerminal);
    }
    let receipt = match verifier.verify(&record, proposed).await {
        Ok(receipt) => receipt,
        Err(error) => {
            counters
                .provider_receipt_failures
                .fetch_add(1, Ordering::Relaxed);
            return Err(error);
        }
    };
    validate_provider_receipt(&record, &receipt)?;

    let boundary_status = match receipt.status {
        NativeRunStatus::Completed => NativeBoundaryStatus::Quarantined,
        NativeRunStatus::Failed => NativeBoundaryStatus::Failed,
        NativeRunStatus::Interrupted => NativeBoundaryStatus::Interrupted,
        NativeRunStatus::Indeterminate => {
            return Err(NativeRecoveryError::InvalidReceipt(
                "trusted terminal receipt cannot be indeterminate",
            ));
        }
    };
    let stop_reason = match receipt.status {
        NativeRunStatus::Completed => Some(
            "provider terminal receipt reconciled; owner authority was not atomically re-established"
                .to_string(),
        ),
        NativeRunStatus::Failed | NativeRunStatus::Interrupted => receipt.stop_reason,
        NativeRunStatus::Indeterminate => unreachable!(),
    };
    let output = NativeRunOutput {
        thread_id: receipt.thread_id,
        turn_id: receipt.turn_id,
        model: receipt.model,
        model_provider: receipt.model_provider,
        status: receipt.status,
        boundary_status,
        output: receipt.output,
        observed_output_tokens: receipt.observed_output_tokens,
        terminal_observed: true,
        stop_reason,
        owner_authority: NativeOwnerAuthority::Unverified,
        codex_terminal_correlation_digest: Some(receipt.verifier_witness_digest),
    };
    let settled = control
        .settle_native(request_id, output)
        .map_err(|error| NativeRecoveryError::Control(error.to_string()))?;
    counters
        .provider_receipt_successes
        .fetch_add(1, Ordering::Relaxed);
    Ok(settled)
}

pub fn quarantine_missing_history(
    control: &mut DurableInferenceControl,
    request_id: &str,
    reason: &str,
) -> Result<NativeRunRecord, NativeRecoveryError> {
    if reason.is_empty() || reason.len() > MAX_REASON_BYTES {
        return Err(NativeRecoveryError::InvalidReason);
    }
    let record = control
        .native_record(request_id)
        .cloned()
        .ok_or(NativeRecoveryError::RequestNotFound)?;
    if record
        .observation
        .as_ref()
        .is_some_and(|output| output.terminal_observed)
    {
        return Err(NativeRecoveryError::AlreadyTerminal);
    }
    let dispatch = record
        .dispatch
        .as_ref()
        .ok_or(NativeRecoveryError::MissingDispatch)?;
    let observed_output_tokens = record
        .observation
        .as_ref()
        .and_then(|output| output.observed_output_tokens);
    let output = NativeRunOutput {
        thread_id: dispatch.thread_id.clone(),
        turn_id: record.turn_id.clone().unwrap_or_default(),
        model: record.request.model.clone(),
        model_provider: dispatch.model_provider.clone(),
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Quarantined,
        output: String::new(),
        observed_output_tokens,
        terminal_observed: false,
        stop_reason: Some(reason.to_string()),
        owner_authority: NativeOwnerAuthority::Unverified,
        codex_terminal_correlation_digest: None,
    };
    control
        .settle_native(request_id, output)
        .map_err(|error| NativeRecoveryError::Control(error.to_string()))
}

fn validate_provider_receipt(
    record: &NativeRunRecord,
    receipt: &ProviderTerminalReceipt,
) -> Result<(), NativeRecoveryError> {
    let dispatch = record
        .dispatch
        .as_ref()
        .ok_or(NativeRecoveryError::MissingDispatch)?;
    if receipt.request_id != record.request.request_id
        || receipt.thread_id != dispatch.thread_id
        || receipt.model != record.request.model
        || receipt.model_provider != dispatch.model_provider
        || receipt.turn_id.is_empty()
        || receipt.turn_id.len() > 256
    {
        return Err(NativeRecoveryError::BindingMismatch);
    }
    if receipt.output.len() > MAX_OUTPUT_BYTES
        || receipt
            .stop_reason
            .as_ref()
            .is_some_and(|reason| reason.is_empty() || reason.len() > MAX_REASON_BYTES)
        || !is_digest(&receipt.verifier_witness_digest)
    {
        return Err(NativeRecoveryError::InvalidReceipt(
            "receipt bounds or verifier witness are invalid",
        ));
    }
    Ok(())
}

fn is_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeRecoveryError {
    InvalidPolicy(&'static str),
    RequestNotFound,
    MissingDispatch,
    AlreadyTerminal,
    BindingMismatch,
    InvalidReason,
    InvalidReceipt(&'static str),
    Verification(String),
    Control(String),
}

impl fmt::Display for NativeRecoveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NativeRecoveryError {}

#[cfg(test)]
#[path = "native_recovery_tests.rs"]
mod tests;
