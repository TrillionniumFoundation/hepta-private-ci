//! Daemon-owned scheduling for the existing durable learning outbox.
//!
//! Recovery and first dispatch receive separate bounded shares. A poison prefix
//! cannot consume every iteration, and a batch of one alternates between them.
//! Generation fencing and exact destination reconciliation remain mandatory.

use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIntelligenceLearningErrorV1;
use crate::AgentdIntelligenceLearningHostV1;
use crate::AgentdState;

const MIN_RECONCILE_INTERVAL: Duration = Duration::from_millis(10);
const MAX_RECONCILE_INTERVAL: Duration = Duration::from_secs(60 * 60);
const MAX_RECONCILE_BATCH: u32 = 256;
const NOT_READY_POLL: Duration = Duration::from_millis(50);
const TRANSIENT_BACKOFF: Duration = Duration::from_secs(1);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceLearningRuntimeMetricsSnapshotV1 {
    pub reconcile_attempts: u64,
    pub reconcile_failures: u64,
    pub dispatch_attempts: u64,
    pub dispatch_failures: u64,
    pub unknown_committed_operations: u64,
    pub oldest_unsettled_append_age_ms: u64,
}

#[derive(Default)]
pub struct AgentdIntelligenceLearningRuntimeMetricsV1 {
    reconcile_attempts: AtomicU64,
    reconcile_failures: AtomicU64,
    dispatch_attempts: AtomicU64,
    dispatch_failures: AtomicU64,
}

impl AgentdIntelligenceLearningRuntimeMetricsV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub async fn snapshot(
        &self,
        host: &AgentdIntelligenceLearningHostV1,
    ) -> Result<AgentdIntelligenceLearningRuntimeMetricsSnapshotV1, AgentdIntelligenceLearningErrorV1>
    {
        let backlog = host.backlog_metrics().await?;
        Ok(AgentdIntelligenceLearningRuntimeMetricsSnapshotV1 {
            reconcile_attempts: self.reconcile_attempts.load(Ordering::Acquire),
            reconcile_failures: self.reconcile_failures.load(Ordering::Acquire),
            dispatch_attempts: self.dispatch_attempts.load(Ordering::Acquire),
            dispatch_failures: self.dispatch_failures.load(Ordering::Acquire),
            unknown_committed_operations: backlog.indeterminate_operations,
            oldest_unsettled_append_age_ms: backlog.oldest_active_outbox_age_ms,
        })
    }

    fn record_reconcile_attempt(&self) {
        saturating_increment(&self.reconcile_attempts);
    }

    fn record_reconcile_failure(&self) {
        saturating_increment(&self.reconcile_failures);
    }

    fn record_dispatch_attempt(&self) {
        saturating_increment(&self.dispatch_attempts);
    }

    fn record_dispatch_failure(&self) {
        saturating_increment(&self.dispatch_failures);
    }

    #[cfg(test)]
    fn counters(&self) -> (u64, u64, u64, u64) {
        (
            self.reconcile_attempts.load(Ordering::Acquire),
            self.reconcile_failures.load(Ordering::Acquire),
            self.dispatch_attempts.load(Ordering::Acquire),
            self.dispatch_failures.load(Ordering::Acquire),
        )
    }
}

pub struct AgentdIntelligenceLearningRuntimeConfigV1 {
    host: Arc<AgentdIntelligenceLearningHostV1>,
    interval: Duration,
    max_batch: u32,
    metrics: Arc<AgentdIntelligenceLearningRuntimeMetricsV1>,
}

impl AgentdIntelligenceLearningRuntimeConfigV1 {
    pub fn new(
        host: Arc<AgentdIntelligenceLearningHostV1>,
        interval: Duration,
        max_batch: u32,
    ) -> Result<Self, AgentdError> {
        validate_runtime_policy(interval, max_batch)?;
        Ok(Self {
            host,
            interval,
            max_batch,
            metrics: Arc::new(AgentdIntelligenceLearningRuntimeMetricsV1::new()),
        })
    }

    #[must_use]
    pub fn owner_generation(&self) -> u64 {
        self.host.owner_generation().get()
    }

    #[must_use]
    pub fn metrics(&self) -> Arc<AgentdIntelligenceLearningRuntimeMetricsV1> {
        Arc::clone(&self.metrics)
    }

    pub(crate) fn into_parts(
        self,
    ) -> (
        Arc<AgentdIntelligenceLearningHostV1>,
        Duration,
        u32,
        Arc<AgentdIntelligenceLearningRuntimeMetricsV1>,
    ) {
        (self.host, self.interval, self.max_batch, self.metrics)
    }
}

fn validate_runtime_policy(interval: Duration, max_batch: u32) -> Result<(), AgentdError> {
    if !(MIN_RECONCILE_INTERVAL..=MAX_RECONCILE_INTERVAL).contains(&interval) {
        return Err(AgentdError::Invalid(
            "intelligence learning reconciliation interval must be 10ms..=1h".to_string(),
        ));
    }
    if !(1..=MAX_RECONCILE_BATCH).contains(&max_batch) {
        return Err(AgentdError::Invalid(
            "intelligence learning reconciliation batch must be 1..=256".to_string(),
        ));
    }
    Ok(())
}

fn iteration_budget(max_batch: u32, recovery_turn: bool) -> (u32, u32) {
    if max_batch == 1 {
        if recovery_turn { (1, 0) } else { (0, 1) }
    } else {
        let recovery = max_batch / 2;
        (recovery, max_batch - recovery)
    }
}

fn require_generation(state: &AgentdState, expected: u64) -> Result<(), AgentdError> {
    let current = state.current_generation()?;
    if current != expected {
        state.mark_fenced();
        return Err(AgentdError::GenerationFenced(format!(
            "intelligence learning generation {expected} does not match current {current}"
        )));
    }
    Ok(())
}

pub(crate) async fn run_intelligence_learning_runtime_v1(
    host: Arc<AgentdIntelligenceLearningHostV1>,
    state: Arc<AgentdState>,
    interval: Duration,
    max_batch: u32,
    metrics: Arc<AgentdIntelligenceLearningRuntimeMetricsV1>,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    validate_runtime_policy(interval, max_batch)?;
    let mut recovery_turn = true;
    loop {
        if cancellation.is_cancelled() {
            return Ok(());
        }
        if !state.automation_admission_ready()? {
            tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = tokio::time::sleep(std::cmp::min(interval, NOT_READY_POLL)) => {}
            }
            continue;
        }
        let owner_generation = host.owner_generation().get();
        require_generation(&state, owner_generation)?;
        let (recovery_budget, mut dispatch_budget) = iteration_budget(max_batch, recovery_turn);
        recovery_turn = !recovery_turn;
        let mut transient_failure = false;
        if recovery_budget > 0 {
            metrics.record_reconcile_attempt();
            match host.reconcile_unsettled(recovery_budget).await {
                Ok(receipts) => {
                    let visited = u32::try_from(receipts.len()).unwrap_or(recovery_budget);
                    dispatch_budget += recovery_budget.saturating_sub(visited);
                }
                Err(error) if error.is_transient() => {
                    metrics.record_reconcile_failure();
                    transient_failure = true;
                }
                Err(error) => {
                    metrics.record_reconcile_failure();
                    return Err(learning_error(error));
                }
            }
        }
        while dispatch_budget > 0 {
            if cancellation.is_cancelled() {
                return Ok(());
            }
            require_generation(&state, owner_generation)?;
            dispatch_budget -= 1;
            metrics.record_dispatch_attempt();
            match host.dispatch_next().await {
                Ok(Some(_)) => {}
                Ok(None) => break,
                Err(error) if error.is_transient() => {
                    // The operation retains its original identity. Only the
                    // owner's proved pre-dispatch deferral can requeue it.
                    metrics.record_dispatch_failure();
                    transient_failure = true;
                    break;
                }
                Err(error) => {
                    metrics.record_dispatch_failure();
                    return Err(learning_error(error));
                }
            }
        }
        require_generation(&state, owner_generation)?;
        let delay = if transient_failure {
            interval.max(TRANSIENT_BACKOFF)
        } else {
            interval
        };
        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            _ = tokio::time::sleep(delay) => {}
        }
    }
}

fn learning_error(error: AgentdIntelligenceLearningErrorV1) -> AgentdError {
    AgentdError::Protocol(format!(
        "intelligence learning reconciliation failed: {error}"
    ))
}

fn saturating_increment(value: &AtomicU64) {
    let mut current = value.load(Ordering::Acquire);
    loop {
        let next = current.saturating_add(1);
        match value.compare_exchange_weak(current, next, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn learning_runtime_policy_is_bounded() {
        assert!(validate_runtime_policy(Duration::from_millis(10), 1).is_ok());
        assert!(validate_runtime_policy(Duration::from_secs(3600), 256).is_ok());
        assert!(validate_runtime_policy(Duration::ZERO, 1).is_err());
        assert!(validate_runtime_policy(Duration::from_millis(9), 1).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(3601), 1).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(1), 0).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(1), 257).is_err());
    }

    #[test]
    fn recovery_and_dispatch_each_receive_a_bounded_share() {
        for total in 2..=256 {
            let (recovery, dispatch) = iteration_budget(total, true);
            assert!(recovery > 0);
            assert!(dispatch > 0);
            assert_eq!(recovery + dispatch, total);
        }
    }

    #[test]
    fn single_slot_alternates_instead_of_starving_new_work() {
        assert_eq!(iteration_budget(1, true), (1, 0));
        assert_eq!(iteration_budget(1, false), (0, 1));
        let mut dispatched = 0;
        let mut recovered = 0;
        for iteration in 0..10 {
            let (recovery, dispatch) = iteration_budget(1, iteration % 2 == 0);
            recovered += recovery;
            dispatched += dispatch;
        }
        assert_eq!((recovered, dispatched), (5, 5));
    }

    #[test]
    fn learning_runtime_metrics_keep_attempts_and_failures_separate() {
        let metrics = AgentdIntelligenceLearningRuntimeMetricsV1::new();
        metrics.record_reconcile_attempt();
        metrics.record_reconcile_attempt();
        metrics.record_reconcile_failure();
        metrics.record_dispatch_attempt();
        assert_eq!(metrics.counters(), (2, 1, 1, 0));
    }
}
