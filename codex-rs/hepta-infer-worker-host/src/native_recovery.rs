//! Bounded reconcile-only recovery for durable App Server dispatches.
//!
//! No API in this module creates a new `turn/start`. Recovery either consumes
//! exact App Server history for the original durable operation or an
//! independently verified provider receipt bound to the same dispatch.

use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::native::NativeBoundaryStatus;
use codex_hepta_infer_core::durable_control::native::NativeOwnerAuthority;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use codex_hepta_infer_core::durable_control::native::NativeRunOutput;
use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tokio::time::sleep;
use tokio_util::sync::CancellationToken;

use crate::native_app_server::AppServerModelDriver;
use crate::native_observability::NativeWorkerMetrics;

const MAX_RECONCILE_ATTEMPTS: u32 = 64;
const MAX_RECONCILE_BACKOFF: Duration = Duration::from_secs(30);
const MAX_PROVIDER_OUTPUT_BYTES: usize = 1024 * 1024;
const MAX_RECEIPT_AUTHORITY_BYTES: usize = 64 * 1024;

pub type NativeReconcileFuture<'a> = Pin<
    Box<
        dyn Future<Output = Result<Option<NativeRunOutput>, Box<dyn std::error::Error + Send + Sync>>>
            + Send
            + 'a,
    >,
>;

/// Testable reconcile-only port. The production implementation delegates to
/// exact `thread/read` recovery and never issues `turn/start`.
pub trait NativeHistoryReconciler: Send + Sync {
    fn reconcile<'a>(
        &'a self,
        record: &'a NativeRunRecord,
        expected_prompt: &'a str,
    ) -> NativeReconcileFuture<'a>;
}

impl NativeHistoryReconciler for AppServerModelDriver {
    fn reconcile<'a>(
        &'a self,
        record: &'a NativeRunRecord,
        expected_prompt: &'a str,
    ) -> NativeReconcileFuture<'a> {
        Box::pin(async move { self.reconcile_existing(record, expected_prompt).await })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeReconciliationPolicy {
    pub maximum_attempts: u32,
    pub initial_backoff: Duration,
    pub maximum_backoff: Duration,
    /// Minimum retention contract expected from the selected App Server host.
    /// This is a deployment requirement, not a promise made by repository code.
    pub minimum_history_retention: Duration,
}

impl NativeReconciliationPolicy {
    pub fn new(
        maximum_attempts: u32,
        initial_backoff: Duration,
        maximum_backoff: Duration,
        minimum_history_retention: Duration,
    ) -> Result<Self, NativeRecoveryError> {
        if !(1..=MAX_RECONCILE_ATTEMPTS).contains(&maximum_attempts)
            || initial_backoff.is_zero()
            || maximum_backoff.is_zero()
            || initial_backoff > maximum_backoff
            || maximum_backoff > MAX_RECONCILE_BACKOFF
            || minimum_history_retention < maximum_backoff
        {
            return Err(NativeRecoveryError::InvalidPolicy);
        }
        Ok(Self {
            maximum_attempts,
            initial_backoff,
            maximum_backoff,
            minimum_history_retention,
        })
    }
}

impl Default for NativeReconciliationPolicy {
    fn default() -> Self {
        Self {
            maximum_attempts: 6,
            initial_backoff: Duration::from_millis(100),
            maximum_backoff: Duration::from_secs(2),
            minimum_history_retention: Duration::from_secs(24 * 60 * 60),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeRecoveryOutcome {
    AlreadyTerminal(NativeRunOutput),
    Settled(NativeRunOutput),
    UsagePending {
        terminal: NativeRunOutput,
        reason: String,
    },
    Held {
        state: NativeReservationState,
        attempts: u32,
        reason: String,
    },
    Cancelled {
        state: NativeReservationState,
        attempts: u32,
    },
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NativeRecoveryError {
    InvalidPolicy,
    RequestNotFound,
    NotRecoverable(NativeReservationState),
    Reconcile(String),
    Control(String),
    InvalidReceipt(&'static str),
    Authority(String),
}

impl std::fmt::Display for NativeRecoveryError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for NativeRecoveryError {}

impl From<codex_hepta_infer_core::durable_control::Error> for NativeRecoveryError {
    fn from(value: codex_hepta_infer_core::durable_control::Error) -> Self {
        Self::Control(value.to_string())
    }
}

pub struct NativeRecoveryManager<R> {
    reconciler: Arc<R>,
    policy: NativeReconciliationPolicy,
    metrics: Arc<NativeWorkerMetrics>,
}

impl<R> NativeRecoveryManager<R>
where
    R: NativeHistoryReconciler,
{
    pub fn new(
        reconciler: Arc<R>,
        policy: NativeReconciliationPolicy,
        metrics: Arc<NativeWorkerMetrics>,
    ) -> Self {
        Self {
            reconciler,
            policy,
            metrics,
        }
    }

    pub async fn resolve_existing(
        &self,
        control: &mut DurableInferenceControl,
        request_id: &str,
        expected_prompt: &str,
        cancellation: &CancellationToken,
    ) -> Result<NativeRecoveryOutcome, NativeRecoveryError> {
        let record = control
            .native_record(request_id)
            .cloned()
            .ok_or(NativeRecoveryError::RequestNotFound)?;
        if let Some(output) = record
            .observation
            .as_ref()
            .filter(|output| output.terminal_observed)
        {
            return if output.observed_output_tokens.is_some() {
                Ok(NativeRecoveryOutcome::AlreadyTerminal(output.clone()))
            } else {
                self.metrics.record_missing_usage();
                Ok(NativeRecoveryOutcome::UsagePending {
                    terminal: output.clone(),
                    reason: "terminal history exists but trusted token usage is absent".to_string(),
                })
            };
        }
        if !matches!(
            record.state,
            NativeReservationState::Dispatching
                | NativeReservationState::Running
                | NativeReservationState::Cancelling
                | NativeReservationState::Indeterminate
        ) {
            return Err(NativeRecoveryError::NotRecoverable(record.state));
        }

        let mut backoff = self.policy.initial_backoff;
        for attempt in 1..=self.policy.maximum_attempts {
            if cancellation.is_cancelled() {
                return Ok(NativeRecoveryOutcome::Cancelled {
                    state: record.state,
                    attempts: attempt - 1,
                });
            }
            self.metrics.record_reconcile_attempt();
            match self
                .reconciler
                .reconcile(&record, expected_prompt)
                .await
            {
                Ok(Some(output)) if output.terminal_observed => {
                    self.metrics.record_reconcile_success();
                    if output.observed_output_tokens.is_none() {
                        self.metrics.record_missing_usage();
                        return Ok(NativeRecoveryOutcome::UsagePending {
                            terminal: output,
                            reason: "exact terminal history lacks trusted token usage; reservation remains held"
                                .to_string(),
                        });
                    }
                    let settled = control.settle_native(request_id, output)?;
                    let terminal = settled
                        .observation
                        .ok_or_else(|| NativeRecoveryError::Control(
                            "settlement omitted its terminal observation".to_string(),
                        ))?;
                    self.metrics.record_indeterminate_resolved();
                    return Ok(NativeRecoveryOutcome::Settled(terminal));
                }
                Ok(Some(_)) | Ok(None) => {
                    self.metrics.record_reconcile_failure();
                }
                Err(error) => {
                    self.metrics.record_reconcile_failure();
                    return Err(NativeRecoveryError::Reconcile(error.to_string()));
                }
            }
            if attempt < self.policy.maximum_attempts {
                tokio::select! {
                    () = sleep(backoff) => {}
                    () = cancellation.cancelled() => {
                        return Ok(NativeRecoveryOutcome::Cancelled {
                            state: record.state,
                            attempts: attempt,
                        });
                    }
                }
                backoff = backoff
                    .checked_mul(2)
                    .unwrap_or(self.policy.maximum_backoff)
                    .min(self.policy.maximum_backoff);
            }
        }
        Ok(NativeRecoveryOutcome::Held {
            state: record.state,
            attempts: self.policy.maximum_attempts,
            reason: format!(
                "no exact terminal history after {} bounded attempts; no replay; host must retain history for at least {:?}",
                self.policy.maximum_attempts, self.policy.minimum_history_retention
            ),
        })
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderTerminalReceipt {
    pub authority_id: StableId,
    pub request_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub model: String,
    pub model_provider: String,
    pub status: NativeRunStatus,
    pub boundary_status: NativeBoundaryStatus,
    pub output: String,
    pub observed_output_tokens: u64,
    pub terminal_correlation_digest: String,
    pub final_use_witness_digest: String,
    pub receipt_digest: String,
    /// Opaque signature/certificate material interpreted only by the configured
    /// independent authority implementation.
    pub authority_blob: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderReceiptVerification {
    pub authority_id: StableId,
    pub verification_witness_digest: Digest32,
    pub terminal_stream_bound: bool,
    pub usage_bound: bool,
    pub replay_protected: bool,
}

pub trait ProviderReceiptAuthority: Send + Sync {
    fn verify(
        &self,
        receipt: &ProviderTerminalReceipt,
        record: &NativeRunRecord,
        canonical_receipt_digest: Digest32,
    ) -> Result<ProviderReceiptVerification, NativeRecoveryError>;
}

pub struct ProviderReceiptVerifier<A> {
    authority: A,
}

impl<A> ProviderReceiptVerifier<A>
where
    A: ProviderReceiptAuthority,
{
    pub fn new(authority: A) -> Self {
        Self { authority }
    }

    pub fn verify(
        &self,
        receipt: ProviderTerminalReceipt,
        record: &NativeRunRecord,
    ) -> Result<VerifiedProviderReceipt, NativeRecoveryError> {
        let dispatch = record
            .dispatch
            .as_ref()
            .ok_or(NativeRecoveryError::InvalidReceipt("dispatch missing"))?;
        let expected_authority_witness = dispatch
            .codex_authority_witness_sha256
            .as_deref()
            .ok_or(NativeRecoveryError::InvalidReceipt(
                "final-use witness missing",
            ))?;
        if dispatch.codex_authority_epoch.is_none()
            || dispatch.codex_revocation_revision.is_none()
            || dispatch.codex_revocation_head_sha256.is_none()
        {
            return Err(NativeRecoveryError::InvalidReceipt(
                "authority frontier missing",
            ));
        }
        if receipt.request_id != record.request.request_id
            || receipt.thread_id != dispatch.thread_id
            || receipt.model != record.request.model
            || receipt.model_provider != dispatch.model_provider
            || receipt.final_use_witness_digest != expected_authority_witness
            || receipt.turn_id.is_empty()
            || receipt.output.len() > MAX_PROVIDER_OUTPUT_BYTES
            || receipt.authority_blob.is_empty()
            || receipt.authority_blob.len() > MAX_RECEIPT_AUTHORITY_BYTES
            || receipt.status == NativeRunStatus::Indeterminate
            || receipt.boundary_status == NativeBoundaryStatus::Indeterminate
        {
            return Err(NativeRecoveryError::InvalidReceipt(
                "receipt does not match durable dispatch",
            ));
        }
        let supplied_digest = parse_digest(&receipt.receipt_digest, "receipt digest")?;
        let canonical_digest = provider_receipt_digest(&receipt);
        if supplied_digest != canonical_digest {
            return Err(NativeRecoveryError::InvalidReceipt(
                "receipt digest mismatch",
            ));
        }
        parse_digest(
            &receipt.terminal_correlation_digest,
            "terminal correlation",
        )?;
        parse_digest(&receipt.final_use_witness_digest, "final-use witness")?;
        let verification = self.authority.verify(&receipt, record, canonical_digest)?;
        if verification.authority_id != receipt.authority_id
            || verification.verification_witness_digest.is_zero()
            || !verification.terminal_stream_bound
            || !verification.usage_bound
            || !verification.replay_protected
        {
            return Err(NativeRecoveryError::Authority(
                "provider authority did not bind terminality, usage and replay protection"
                    .to_string(),
            ));
        }
        Ok(VerifiedProviderReceipt {
            request_id: receipt.request_id,
            receipt_digest: canonical_digest,
            output: NativeRunOutput {
                thread_id: receipt.thread_id,
                turn_id: receipt.turn_id,
                model: receipt.model,
                model_provider: receipt.model_provider,
                status: receipt.status,
                boundary_status: receipt.boundary_status,
                output: receipt.output,
                observed_output_tokens: Some(receipt.observed_output_tokens),
                terminal_observed: true,
                stop_reason: None,
                owner_authority: NativeOwnerAuthority::ObservedReady,
                codex_terminal_correlation_digest: Some(
                    receipt.terminal_correlation_digest,
                ),
            },
        })
    }
}

#[derive(Debug)]
pub struct VerifiedProviderReceipt {
    request_id: String,
    receipt_digest: Digest32,
    output: NativeRunOutput,
}

impl VerifiedProviderReceipt {
    pub fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }
}

pub fn settle_verified_provider_receipt(
    control: &mut DurableInferenceControl,
    verified: VerifiedProviderReceipt,
    metrics: &NativeWorkerMetrics,
) -> Result<NativeRunOutput, NativeRecoveryError> {
    let settled = control.settle_native(&verified.request_id, verified.output)?;
    let output = settled
        .observation
        .ok_or_else(|| NativeRecoveryError::Control(
            "verified provider settlement omitted output".to_string(),
        ))?;
    metrics.record_reconcile_success();
    metrics.record_indeterminate_resolved();
    Ok(output)
}

#[must_use]
pub fn provider_receipt_digest(receipt: &ProviderTerminalReceipt) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.provider-terminal-receipt.v1");
    push_id(&mut bytes, &receipt.authority_id);
    push_string(&mut bytes, &receipt.request_id);
    push_string(&mut bytes, &receipt.thread_id);
    push_string(&mut bytes, &receipt.turn_id);
    push_string(&mut bytes, &receipt.model);
    push_string(&mut bytes, &receipt.model_provider);
    bytes.push(match receipt.status {
        NativeRunStatus::Completed => 0,
        NativeRunStatus::Failed => 1,
        NativeRunStatus::Interrupted => 2,
        NativeRunStatus::Indeterminate => 3,
    });
    bytes.push(match receipt.boundary_status {
        NativeBoundaryStatus::Succeeded => 0,
        NativeBoundaryStatus::Failed => 1,
        NativeBoundaryStatus::Interrupted => 2,
        NativeBoundaryStatus::Cancelled => 3,
        NativeBoundaryStatus::TimedOut => 4,
        NativeBoundaryStatus::Quarantined => 5,
        NativeBoundaryStatus::Indeterminate => 6,
    });
    push_string(&mut bytes, &receipt.output);
    bytes.extend_from_slice(&receipt.observed_output_tokens.to_be_bytes());
    push_string(&mut bytes, &receipt.terminal_correlation_digest);
    push_string(&mut bytes, &receipt.final_use_witness_digest);
    bytes.extend_from_slice(Digest32::of_bytes(&receipt.authority_blob).as_array());
    Digest32::of_bytes(&bytes)
}

fn parse_digest(value: &str, field: &'static str) -> Result<Digest32, NativeRecoveryError> {
    value
        .parse()
        .map_err(|_| NativeRecoveryError::InvalidReceipt(field))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    push_string(bytes, value.as_str());
}

fn push_string(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn policy_rejects_unbounded_or_incoherent_retry() {
        assert!(NativeReconciliationPolicy::new(
            0,
            Duration::from_millis(1),
            Duration::from_secs(1),
            Duration::from_secs(1),
        )
        .is_err());
        assert!(NativeReconciliationPolicy::new(
            1,
            Duration::from_secs(2),
            Duration::from_secs(1),
            Duration::from_secs(1),
        )
        .is_err());
        assert!(NativeReconciliationPolicy::new(
            2,
            Duration::from_millis(10),
            Duration::from_secs(1),
            Duration::from_secs(60),
        )
        .is_ok());
    }
}
