//! Offload synchronous lifecycle work without detaching its owner or capacity.
//! Mutation serialization is intentionally retained until per-Agent transaction
//! ownership is independently qualified. Read observations do not enter this lane.

use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use tokio::runtime::Handle;
use tokio::sync::OwnedSemaphorePermit;
use tokio::sync::Semaphore;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use super::DaemonState;
use super::SupervisordMethod;
use super::SupervisordPayload;
use super::error_payload;
use super::mutex::micros;
use super::read_view::ReadView;
use super::read_view::unavailable;
use crate::UnixProcessDriver;

const LATENCY_BUCKETS: usize = 64;

struct LatencyHistogram {
    count: AtomicU64,
    buckets: [AtomicU64; LATENCY_BUCKETS],
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
struct LatencySummary {
    count: u64,
    p50_us: u64,
    p95_us: u64,
    p99_us: u64,
}

impl Default for LatencyHistogram {
    fn default() -> Self {
        Self {
            count: AtomicU64::new(0),
            buckets: std::array::from_fn(|_| AtomicU64::new(0)),
        }
    }
}

impl LatencyHistogram {
    fn record(&self, duration: Duration) {
        let value = micros(duration);
        let bucket = latency_bucket(value);
        self.buckets[bucket].fetch_add(1, Ordering::Relaxed);
        self.count.fetch_add(1, Ordering::Release);
    }

    fn snapshot(&self) -> LatencySummary {
        let count = self.count.load(Ordering::Acquire);
        if count == 0 {
            return LatencySummary::default();
        }
        LatencySummary {
            count,
            p50_us: self.percentile(count, 50),
            p95_us: self.percentile(count, 95),
            p99_us: self.percentile(count, 99),
        }
    }

    fn percentile(&self, count: u64, percentile: u64) -> u64 {
        let target = count
            .saturating_mul(percentile)
            .saturating_add(99)
            .saturating_div(100)
            .max(1);
        let mut observed = 0_u64;
        for (index, bucket) in self.buckets.iter().enumerate() {
            observed = observed.saturating_add(bucket.load(Ordering::Relaxed));
            if observed >= target {
                return latency_bucket_upper_bound(index);
            }
        }
        u64::MAX
    }
}

fn latency_bucket(value_us: u64) -> usize {
    if value_us <= 1 {
        return 0;
    }
    usize::try_from(u64::BITS - value_us.leading_zeros())
        .unwrap_or(LATENCY_BUCKETS - 1)
        .min(LATENCY_BUCKETS - 1)
}

fn latency_bucket_upper_bound(index: usize) -> u64 {
    if index == 0 {
        return 1;
    }
    1_u64
        .checked_shl(u32::try_from(index).unwrap_or(u32::MAX))
        .unwrap_or(u64::MAX)
}

pub(super) struct Execution {
    pub(super) view: ReadView,
    slots: Arc<Semaphore>,
    poisoned: AtomicBool,
    cancellation: CancellationToken,
    rejected: AtomicU64,
    completed: AtomicU64,
    tick_delay_max_us: AtomicU64,
    owner_wait: LatencyHistogram,
    owner_total: LatencyHistogram,
    read_total: LatencyHistogram,
    started: Instant,
    last_log_second: AtomicU64,
}

impl Execution {
    pub(super) fn new(cancellation: CancellationToken) -> Self {
        Self {
            view: ReadView::default(),
            // One existing lifecycle writer, not a new parallel writer authority.
            slots: Arc::new(Semaphore::new(1)),
            poisoned: AtomicBool::new(false),
            cancellation,
            rejected: AtomicU64::new(0),
            completed: AtomicU64::new(0),
            tick_delay_max_us: AtomicU64::new(0),
            owner_wait: LatencyHistogram::default(),
            owner_total: LatencyHistogram::default(),
            read_total: LatencyHistogram::default(),
            started: Instant::now(),
            last_log_second: AtomicU64::new(0),
        }
    }

    pub(super) fn failed(&self) -> bool {
        self.poisoned.load(Ordering::Acquire)
    }

    fn stopped(&self) -> bool {
        self.poisoned.load(Ordering::Acquire) || self.cancellation.is_cancelled()
    }

    fn log_snapshot(&self) {
        let wait = self.owner_wait.snapshot();
        let total = self.owner_total.snapshot();
        let read = self.read_total.snapshot();
        eprintln!(
            "hepta_supervisord_latency owner_wait_count={} owner_wait_p50_us={} owner_wait_p95_us={} owner_wait_p99_us={} owner_total_count={} owner_total_p50_us={} owner_total_p95_us={} owner_total_p99_us={} read_count={} read_p50_us={} read_p95_us={} read_p99_us={}",
            wait.count,
            wait.p50_us,
            wait.p95_us,
            wait.p99_us,
            total.count,
            total.p50_us,
            total.p95_us,
            total.p99_us,
            read.count,
            read.p50_us,
            read.p95_us,
            read.p99_us,
        );
    }
}

struct OwnerWork {
    state: Arc<DaemonState<UnixProcessDriver>>,
    _permit: OwnedSemaphorePermit,
}

impl Drop for OwnerWork {
    fn drop(&mut self) {
        let execution = &self.state.execution;
        if std::thread::panicking() {
            // Publish the poison before releasing capacity to a waiting ticker.
            execution.poisoned.store(true, Ordering::Release);
            execution.view.invalidate();
            execution.cancellation.cancel();
        }
        execution.completed.fetch_add(1, Ordering::Relaxed);
    }
}

fn spawn_owned<R, F>(
    state: Arc<DaemonState<UnixProcessDriver>>,
    permit: OwnedSemaphorePermit,
    work: F,
) -> JoinHandle<Option<R>>
where
    R: Send + 'static,
    F: FnOnce(&Arc<DaemonState<UnixProcessDriver>>) -> R + Send + 'static,
{
    let owner = OwnerWork {
        state,
        _permit: permit,
    };
    tokio::task::spawn_blocking(move || {
        if owner.state.execution.stopped() {
            return None;
        }
        Some(work(&owner.state))
    })
}

pub(super) async fn handle(
    state: Arc<DaemonState<UnixProcessDriver>>,
    method: SupervisordMethod,
) -> SupervisordPayload {
    let request_started = Instant::now();
    if state.execution.stopped() {
        return unavailable();
    }
    if let Some(reply) = state.execution.view.respond(
        &method,
        Instant::now(),
        state.observed_faults.load(Ordering::Relaxed),
    ) {
        state.execution.read_total.record(request_started.elapsed());
        return reply;
    }

    // Wait on the FIFO semaphore, not in the blocking pool. Connection capacity
    // bounds the number of waiters; timeout drops only the unadmitted acquisition.
    // A bounded FIFO wait prevents a busy periodic ticker from starving mutations.
    let owner_wait_started = Instant::now();
    let permit = tokio::select! {
        _ = state.execution.cancellation.cancelled() => return unavailable(),
        result = timeout(
            Duration::from_millis(250),
            Arc::clone(&state.execution.slots).acquire_owned(),
        ) => match result {
            Ok(Ok(permit)) => permit,
            _ => {
                state.execution.owner_wait.record(owner_wait_started.elapsed());
                state.execution.owner_total.record(request_started.elapsed());
                state.execution.rejected.fetch_add(1, Ordering::Relaxed);
                return error_payload(
                    "control_state_unavailable",
                    "lifecycle owner is busy; no operation was admitted; refresh before retry",
                    /*actual*/ None,
                );
            }
        },
    };
    state
        .execution
        .owner_wait
        .record(owner_wait_started.elapsed());

    let runtime = Handle::current();
    let metrics_state = Arc::clone(&state);
    let outcome = spawn_owned(state, permit, move |state| {
        let reply = runtime.block_on(super::handle_request(Arc::clone(state), method));
        let supervisor = state.supervisor.blocking_lock();
        refresh(state, &supervisor);
        reply
    })
    .await;
    metrics_state
        .execution
        .owner_total
        .record(request_started.elapsed());
    match outcome {
        Ok(Some(reply)) => reply,
        Ok(None) => unavailable(),
        Err(_) => error_payload(
            "operation_indeterminate",
            "lifecycle worker failed; inspect durable state before retry",
            /*actual*/ None,
        ),
    }
}

pub(super) async fn tick(state: Arc<DaemonState<UnixProcessDriver>>, scheduled: Instant) {
    let permit = tokio::select! {
        _ = state.execution.cancellation.cancelled() => return,
        permit = Arc::clone(&state.execution.slots).acquire_owned() => match permit {
            Ok(permit) => permit,
            Err(_) => return,
        },
    };
    // Only one ticker waits. There is no unbounded blocking-pool submission queue.
    let _ = spawn_owned(state, permit, move |state| {
        let execution = &state.execution;
        execution.tick_delay_max_us.fetch_max(
            micros(Instant::now().saturating_duration_since(scheduled)),
            Ordering::Relaxed,
        );
        let mut supervisor = state.supervisor.blocking_lock();
        let faults = supervisor.tick(Instant::now()).faults;
        state
            .observed_faults
            .fetch_add(faults.len() as u64, Ordering::Relaxed);
        refresh(state, &supervisor);

        let second = execution.started.elapsed().as_secs();
        let previous = execution.last_log_second.load(Ordering::Relaxed);
        let log_now = second.saturating_sub(previous) >= 5
            && execution
                .last_log_second
                .compare_exchange(previous, second, Ordering::Relaxed, Ordering::Relaxed)
                .is_ok();
        let operational = log_now.then(|| supervisor.operational_summary()).transpose();
        drop(supervisor);

        if log_now {
            state.supervisor.log_snapshot();
            execution.log_snapshot();
            crate::control_latency::log_snapshot();
            match operational {
                Ok(Some(summary)) => eprintln!(
                    "hepta_supervisord_progress registered_agents={} blocked_agents={} target_identity_changed={} awaiting_process_exit={} restart_backoff={} restart_budget_exhausted={} release_transition_in_progress={} persistence_uncertain={} recovery_quarantined={} control_state_unavailable={} resource_enforcement_gaps={}",
                    summary.registered_agents,
                    summary.blocked_agents,
                    summary.target_identity_changed,
                    summary.awaiting_process_exit,
                    summary.restart_backoff,
                    summary.restart_budget_exhausted,
                    summary.release_transition_in_progress,
                    summary.persistence_uncertain,
                    summary.recovery_quarantined,
                    summary.control_state_unavailable,
                    summary.resource_enforcement_gaps,
                ),
                Ok(None) => {}
                Err(_) => {
                    state.observed_faults.fetch_add(1, Ordering::Relaxed);
                    eprintln!("hepta_supervisord_progress unavailable=1");
                }
            }
            eprintln!(
                "hepta_supervisord_scheduler completed={} rejected_busy={} tick_delay_max_us={}",
                execution.completed.load(Ordering::Relaxed),
                execution.rejected.load(Ordering::Relaxed),
                execution.tick_delay_max_us.load(Ordering::Relaxed),
            );
        }
    })
    .await;
}

pub(super) fn refresh(
    state: &DaemonState<UnixProcessDriver>,
    supervisor: &crate::Supervisor<UnixProcessDriver>,
) {
    if state
        .execution
        .view
        .publish(&state.registry, supervisor, &state.supervisor_epoch)
        .is_err()
    {
        state.execution.view.invalidate();
        state.observed_faults.fetch_add(1, Ordering::Relaxed);
    }
}

#[cfg(test)]
mod latency_tests {
    use super::*;

    #[test]
    fn histogram_reports_monotone_percentile_upper_bounds() {
        let histogram = LatencyHistogram::default();
        for value in [1_u64, 2, 4, 8, 16, 32, 64, 128, 256, 512] {
            histogram.record(Duration::from_micros(value));
        }
        let summary = histogram.snapshot();
        assert_eq!(summary.count, 10);
        assert!(summary.p50_us <= summary.p95_us);
        assert!(summary.p95_us <= summary.p99_us);
        assert!(summary.p99_us >= 512);
    }

    #[test]
    fn empty_histogram_is_explicitly_zero() {
        assert_eq!(
            LatencyHistogram::default().snapshot(),
            LatencySummary::default()
        );
    }
}

#[cfg(test)]
#[path = "daemon_execution_tests.rs"]
mod tests;
