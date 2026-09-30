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

// The authoritative lifecycle tick remains 25 ms. The immutable whole-fleet
// observation is only a bounded read projection, so coalesce tick-only rebuilds
// instead of reloading and re-projecting all 256 Agents after every tick.
const READ_VIEW_REFRESH_INTERVAL: Duration = Duration::from_millis(100);

pub(super) struct Execution {
    pub(super) view: ReadView,
    slots: Arc<Semaphore>,
    poisoned: AtomicBool,
    cancellation: CancellationToken,
    rejected: AtomicU64,
    completed: AtomicU64,
    tick_delay_max_us: AtomicU64,
    view_refreshes: AtomicU64,
    view_refresh_skips: AtomicU64,
    last_view_refresh_us: AtomicU64,
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
            view_refreshes: AtomicU64::new(0),
            view_refresh_skips: AtomicU64::new(0),
            last_view_refresh_us: AtomicU64::new(0),
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

    fn elapsed_us(&self, now: Instant) -> u64 {
        micros(now.saturating_duration_since(self.started))
    }

    fn view_refresh_due(&self, now: Instant) -> bool {
        self.elapsed_us(now).saturating_sub(
            self.last_view_refresh_us.load(Ordering::Relaxed),
        ) >= micros(READ_VIEW_REFRESH_INTERVAL)
    }

    fn note_view_refresh(&self, now: Instant) {
        self.last_view_refresh_us
            .store(self.elapsed_us(now), Ordering::Relaxed);
        self.view_refreshes.fetch_add(1, Ordering::Relaxed);
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
    if state.execution.stopped() {
        return unavailable();
    }
    if let Some(reply) = state.execution.view.respond(
        &method,
        Instant::now(),
        state.observed_faults.load(Ordering::Relaxed),
    ) {
        return reply;
    }
    // Wait on the FIFO semaphore, not in the blocking pool. Connection capacity
    // bounds the number of waiters; timeout drops only the unadmitted acquisition.
    // A bounded FIFO wait prevents a busy periodic ticker from starving mutations.
    let permit = tokio::select! {
        _ = state.execution.cancellation.cancelled() => return unavailable(),
        result = timeout(
            Duration::from_millis(250),
            Arc::clone(&state.execution.slots).acquire_owned(),
        ) => match result {
            Ok(Ok(permit)) => permit,
            _ => {
                state.execution.rejected.fetch_add(1, Ordering::Relaxed);
                return error_payload(
                    "control_state_unavailable",
                    "lifecycle owner is busy; no operation was admitted; refresh before retry",
                    /*actual*/ None,
                );
            }
        },
    };
    let runtime = Handle::current();
    match spawn_owned(state, permit, move |state| {
        let reply = runtime.block_on(super::handle_request(Arc::clone(state), method));
        let supervisor = state.supervisor.blocking_lock();
        // A live owner request may have changed state and therefore always
        // publishes a fresh projection before its result becomes observable.
        refresh(state, &supervisor);
        reply
    })
    .await
    {
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
        refresh_if_due(state, &supervisor, Instant::now());
        drop(supervisor);
        let second = execution.started.elapsed().as_secs();
        let previous = execution.last_log_second.load(Ordering::Relaxed);
        if second.saturating_sub(previous) >= 5
            && execution
                .last_log_second
                .compare_exchange(previous, second, Ordering::Relaxed, Ordering::Relaxed)
                .is_ok()
        {
            state.supervisor.log_snapshot();
            eprintln!(
                "hepta_supervisord_scheduler completed={} rejected_busy={} tick_delay_max_us={} view_refreshes={} view_refresh_skips={}",
                execution.completed.load(Ordering::Relaxed),
                execution.rejected.load(Ordering::Relaxed),
                execution.tick_delay_max_us.load(Ordering::Relaxed),
                execution.view_refreshes.load(Ordering::Relaxed),
                execution.view_refresh_skips.load(Ordering::Relaxed),
            );
        }
    })
    .await;
}

fn refresh_if_due(
    state: &DaemonState<UnixProcessDriver>,
    supervisor: &crate::Supervisor<UnixProcessDriver>,
    now: Instant,
) {
    if state.execution.view_refresh_due(now) {
        refresh_at(state, supervisor, now);
    } else {
        state
            .execution
            .view_refresh_skips
            .fetch_add(1, Ordering::Relaxed);
    }
}

pub(super) fn refresh(
    state: &DaemonState<UnixProcessDriver>,
    supervisor: &crate::Supervisor<UnixProcessDriver>,
) {
    refresh_at(state, supervisor, Instant::now());
}

fn refresh_at(
    state: &DaemonState<UnixProcessDriver>,
    supervisor: &crate::Supervisor<UnixProcessDriver>,
    now: Instant,
) {
    if state
        .execution
        .view
        .publish(&state.registry, supervisor, &state.supervisor_epoch)
        .is_err()
    {
        state.execution.view.invalidate();
        state.observed_faults.fetch_add(1, Ordering::Relaxed);
    } else {
        state.execution.note_view_refresh(now);
    }
}

#[cfg(test)]
#[path = "daemon_execution_tests.rs"]
mod tests;
