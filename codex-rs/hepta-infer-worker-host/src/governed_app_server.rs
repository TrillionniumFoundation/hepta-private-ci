//! Bounded operational policy around the hosted App Server worker.
//!
//! The inner `AppServerModelDriver` owns the only physical `turn/start` path.
//! Repeated calls made by this wrapper use the same durable request identity;
//! after a possible dispatch the inner driver is reconcile-only and never
//! creates another provider turn.

use std::error::Error as StdError;
use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use tokio::time::{Instant, sleep};
use tokio_util::sync::CancellationToken;

use crate::native_app_server::{
    AppServerModelDriver, NativeAdmission, NativeIntelligenceRunBinding, NativeRunOutput,
};

type Result<T> = std::result::Result<T, Box<dyn StdError + Send + Sync>>;

const MIN_RECONCILE_GRACE: Duration = Duration::from_millis(10);
const MAX_RECONCILE_GRACE: Duration = Duration::from_secs(30);
const MIN_RECONCILE_INTERVAL: Duration = Duration::from_millis(10);

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HostedReconcilePolicy {
    total_grace: Duration,
    retry_interval: Duration,
}

impl HostedReconcilePolicy {
    pub fn new(total_grace: Duration, retry_interval: Duration) -> Result<Self> {
        if !(MIN_RECONCILE_GRACE..=MAX_RECONCILE_GRACE).contains(&total_grace)
            || retry_interval < MIN_RECONCILE_INTERVAL
            || retry_interval > total_grace
        {
            return Err("invalid hosted reconciliation policy".into());
        }
        Ok(Self {
            total_grace,
            retry_interval,
        })
    }

    #[must_use]
    pub const fn total_grace(self) -> Duration {
        self.total_grace
    }

    #[must_use]
    pub const fn retry_interval(self) -> Duration {
        self.retry_interval
    }
}

impl Default for HostedReconcilePolicy {
    fn default() -> Self {
        Self {
            total_grace: Duration::from_secs(2),
            retry_interval: Duration::from_millis(250),
        }
    }
}

#[derive(Debug, Default)]
struct HostedMetricsInner {
    indeterminate_returns: AtomicU64,
    held_reservations: AtomicU64,
    reconcile_attempts: AtomicU64,
    reconcile_successes: AtomicU64,
    reconcile_failures: AtomicU64,
    missing_usage: AtomicU64,
    authority_denials: AtomicU64,
    journal_capacity_errors: AtomicU64,
    cancellation_returns: AtomicU64,
    cancellation_latency_micros: AtomicU64,
}

#[derive(Clone, Debug, Default)]
pub struct HostedWorkerMetrics {
    inner: Arc<HostedMetricsInner>,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct HostedWorkerMetricSnapshot {
    pub indeterminate_returns: u64,
    pub held_reservations: u64,
    pub reconcile_attempts: u64,
    pub reconcile_successes: u64,
    pub reconcile_failures: u64,
    pub missing_usage: u64,
    pub authority_denials: u64,
    pub journal_capacity_errors: u64,
    pub cancellation_returns: u64,
    pub cancellation_latency_micros: u64,
}

impl HostedWorkerMetrics {
    #[must_use]
    pub fn snapshot(&self) -> HostedWorkerMetricSnapshot {
        HostedWorkerMetricSnapshot {
            indeterminate_returns: self.inner.indeterminate_returns.load(Ordering::Relaxed),
            held_reservations: self.inner.held_reservations.load(Ordering::Relaxed),
            reconcile_attempts: self.inner.reconcile_attempts.load(Ordering::Relaxed),
            reconcile_successes: self.inner.reconcile_successes.load(Ordering::Relaxed),
            reconcile_failures: self.inner.reconcile_failures.load(Ordering::Relaxed),
            missing_usage: self.inner.missing_usage.load(Ordering::Relaxed),
            authority_denials: self.inner.authority_denials.load(Ordering::Relaxed),
            journal_capacity_errors: self.inner.journal_capacity_errors.load(Ordering::Relaxed),
            cancellation_returns: self.inner.cancellation_returns.load(Ordering::Relaxed),
            cancellation_latency_micros: self
                .inner
                .cancellation_latency_micros
                .load(Ordering::Relaxed),
        }
    }

    fn observe_output(&self, output: &NativeRunOutput) {
        if !output.terminal_observed {
            self.inner
                .indeterminate_returns
                .fetch_add(1, Ordering::Relaxed);
            self.inner
                .held_reservations
                .fetch_add(1, Ordering::Relaxed);
        }
        if output.observed_output_tokens.is_none() {
            self.inner.missing_usage.fetch_add(1, Ordering::Relaxed);
        }
    }

    fn observe_error(&self, error: &(dyn StdError + Send + Sync)) {
        let message = error.to_string().to_ascii_lowercase();
        if message.contains("authority") || message.contains("grant") {
            self.inner.authority_denials.fetch_add(1, Ordering::Relaxed);
        }
        if message.contains("capacity") || message.contains("journal") {
            self.inner
                .journal_capacity_errors
                .fetch_add(1, Ordering::Relaxed);
        }
    }
}

/// Production-candidate hosted profile. This wrapper changes operational
/// policy and observability only; it cannot activate the profile or manufacture
/// provider terminality/usage.
pub struct GovernedAppServerWorker {
    driver: AppServerModelDriver,
    policy: HostedReconcilePolicy,
    metrics: HostedWorkerMetrics,
}

impl GovernedAppServerWorker {
    #[must_use]
    pub fn new(driver: AppServerModelDriver, policy: HostedReconcilePolicy) -> Self {
        Self {
            driver,
            policy,
            metrics: HostedWorkerMetrics::default(),
        }
    }

    #[must_use]
    pub fn metrics(&self) -> HostedWorkerMetrics {
        self.metrics.clone()
    }

    pub async fn run(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_internal(
            control,
            admission,
            prompt,
            context_query,
            None,
            cancellation,
        )
        .await
    }

    pub async fn run_intelligence(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        intelligence: NativeIntelligenceRunBinding,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        self.run_internal(
            control,
            admission,
            prompt,
            context_query,
            Some(intelligence),
            cancellation,
        )
        .await
    }

    async fn run_internal(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        intelligence: Option<NativeIntelligenceRunBinding>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        let request_id = admission.request_id.clone();
        let maximum_in_flight = admission.maximum_in_flight;
        let started = Instant::now();
        let first = self
            .invoke(
                control,
                NativeAdmission {
                    request_id: request_id.clone(),
                    maximum_in_flight,
                },
                prompt.clone(),
                context_query.clone(),
                intelligence.clone(),
                cancellation,
            )
            .await;
        let mut output = match first {
            Ok(output) => output,
            Err(error) => {
                self.metrics.observe_error(error.as_ref());
                return Err(error);
            }
        };
        if output.terminal_observed {
            self.metrics.observe_output(&output);
            return Ok(output);
        }

        let deadline = Instant::now() + self.policy.total_grace();
        while Instant::now() < deadline {
            self.metrics
                .inner
                .reconcile_attempts
                .fetch_add(1, Ordering::Relaxed);
            if cancellation.is_cancelled() {
                self.metrics
                    .inner
                    .cancellation_returns
                    .fetch_add(1, Ordering::Relaxed);
                self.metrics
                    .inner
                    .cancellation_latency_micros
                    .store(
                        u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
                        Ordering::Relaxed,
                    );
                break;
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                break;
            }
            sleep(self.policy.retry_interval().min(remaining)).await;
            match self
                .invoke(
                    control,
                    NativeAdmission {
                        request_id: request_id.clone(),
                        maximum_in_flight,
                    },
                    prompt.clone(),
                    context_query.clone(),
                    intelligence.clone(),
                    cancellation,
                )
                .await
            {
                Ok(candidate) => {
                    output = candidate;
                    if output.terminal_observed {
                        self.metrics
                            .inner
                            .reconcile_successes
                            .fetch_add(1, Ordering::Relaxed);
                        self.metrics.observe_output(&output);
                        return Ok(output);
                    }
                }
                Err(error) => {
                    self.metrics
                        .inner
                        .reconcile_failures
                        .fetch_add(1, Ordering::Relaxed);
                    self.metrics.observe_error(error.as_ref());
                    return Err(error);
                }
            }
        }
        self.metrics.observe_output(&output);
        Ok(output)
    }

    async fn invoke(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        context_query: Option<String>,
        intelligence: Option<NativeIntelligenceRunBinding>,
        cancellation: &CancellationToken,
    ) -> Result<NativeRunOutput> {
        match intelligence {
            Some(binding) => {
                self.driver
                    .run_intelligence(
                        control,
                        admission,
                        prompt,
                        context_query,
                        binding,
                        cancellation,
                    )
                    .await
            }
            None => {
                self.driver
                    .run(
                        control,
                        admission,
                        prompt,
                        context_query,
                        cancellation,
                    )
                    .await
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reconciliation_policy_is_bounded() {
        assert!(HostedReconcilePolicy::new(Duration::ZERO, Duration::ZERO).is_err());
        assert!(
            HostedReconcilePolicy::new(Duration::from_secs(31), Duration::from_millis(20))
                .is_err()
        );
        assert!(
            HostedReconcilePolicy::new(Duration::from_secs(2), Duration::from_secs(3)).is_err()
        );
        assert!(
            HostedReconcilePolicy::new(Duration::from_secs(2), Duration::from_millis(100)).is_ok()
        );
    }

    #[test]
    fn metric_snapshot_preserves_unknown_usage() {
        let metrics = HostedWorkerMetrics::default();
        metrics.observe_output(&NativeRunOutput {
            thread_id: "thread".to_string(),
            turn_id: String::new(),
            model: "model".to_string(),
            model_provider: "provider".to_string(),
            status: crate::native_app_server::NativeRunStatus::Indeterminate,
            boundary_status: crate::native_app_server::NativeBoundaryStatus::Indeterminate,
            output: String::new(),
            observed_output_tokens: None,
            terminal_observed: false,
            stop_reason: Some("unknown".to_string()),
            owner_authority: crate::native_app_server::NativeOwnerAuthority::Unverified,
            codex_terminal_correlation_digest: None,
        });
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.indeterminate_returns, 1);
        assert_eq!(snapshot.held_reservations, 1);
        assert_eq!(snapshot.missing_usage, 1);
    }
}
