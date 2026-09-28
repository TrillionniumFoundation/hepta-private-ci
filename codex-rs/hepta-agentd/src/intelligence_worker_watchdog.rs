//! Worker supervision independent of the request future and Tokio scheduler.
//!
//! A bounded worker owns this completion guard. Dropping the request merely
//! detaches its result; it cannot disarm the watchdog. Completion joins the
//! observer before the worker permit is released, so observers are bounded too.

use std::sync::Arc;
use std::sync::Condvar;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread::JoinHandle;
use std::time::Duration;
use std::time::Instant;

use super::super::AgentdIntelligenceProductRunnerV1;
use crate::AgentdIntelligenceTelemetryV1;

struct WorkerTimeoutObservationV1 {
    timed_out: Arc<AtomicBool>,
    telemetry: Arc<AgentdIntelligenceTelemetryV1>,
}

pub(super) struct WorkerCompletionV1 {
    completed: Arc<(Mutex<bool>, Condvar)>,
    observer: Option<JoinHandle<()>>,
}

impl WorkerCompletionV1 {
    pub(super) fn supervise(
        budget: Duration,
        hard_grace: Option<Duration>,
        timed_out: Arc<AtomicBool>,
        telemetry: Arc<AgentdIntelligenceTelemetryV1>,
    ) -> std::io::Result<Self> {
        Self::supervise_inner(
            budget,
            hard_grace,
            Some(WorkerTimeoutObservationV1 {
                timed_out,
                telemetry,
            }),
        )
    }

    fn supervise_unobserved(
        budget: Duration,
        hard_grace: Duration,
    ) -> std::io::Result<Self> {
        Self::supervise_inner(budget, Some(hard_grace), None)
    }

    fn supervise_inner(
        budget: Duration,
        hard_grace: Option<Duration>,
        observation: Option<WorkerTimeoutObservationV1>,
    ) -> std::io::Result<Self> {
        if budget.is_zero() || hard_grace.is_some_and(|grace| grace.is_zero()) {
            return Err(std::io::Error::new(
                std::io::ErrorKind::InvalidInput,
                "worker supervision budget and grace must be nonzero",
            ));
        }
        let deadline = Instant::now().checked_add(budget).ok_or_else(|| {
            std::io::Error::new(std::io::ErrorKind::InvalidInput, "worker deadline overflow")
        })?;
        let completed = Arc::new((Mutex::new(false), Condvar::new()));
        let observer_state = Arc::clone(&completed);
        let observer = std::thread::Builder::new()
            .name("hepta-intelligence-watchdog".to_string())
            .spawn(move || {
                if wait_until_complete(&observer_state, deadline) {
                    return;
                }
                if let Some(observation) = observation.as_ref()
                    && !observation.timed_out.swap(true, Ordering::AcqRel)
                {
                    observation.telemetry.record_request_timeout();
                }
                let Some(grace) = hard_grace else {
                    return;
                };
                let Some(exit_deadline) = deadline.checked_add(grace) else {
                    if let Some(observation) = observation.as_ref() {
                        observation.telemetry.record_hard_timeout_trip();
                    }
                    std::process::exit(70);
                };
                if !wait_until_complete(&observer_state, exit_deadline) {
                    if let Some(observation) = observation.as_ref() {
                        observation.telemetry.record_hard_timeout_trip();
                    }
                    // The supervisor must recover a new process generation and
                    // reconcile any durable unknown operation.
                    std::process::exit(70);
                }
            })?;
        Ok(Self {
            completed,
            observer: Some(observer),
        })
    }
}

impl Drop for WorkerCompletionV1 {
    fn drop(&mut self) {
        let (state, ready) = &*self.completed;
        let mut state = state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        *state = true;
        ready.notify_all();
        drop(state);
        if let Some(observer) = self.observer.take() {
            let _ = observer.join();
        }
    }
}

impl AgentdIntelligenceProductRunnerV1 {
    pub(crate) fn spawn_unobserved_blocking<F, T>(
        permit: tokio::sync::OwnedSemaphorePermit,
        budget: Duration,
        hard_grace: Duration,
        work: F,
    ) -> std::io::Result<tokio::task::JoinHandle<T>>
    where
        F: FnOnce() -> T + Send + 'static,
        T: Send + 'static,
    {
        let completion = WorkerCompletionV1::supervise_unobserved(budget, hard_grace)?;
        Ok(tokio::task::spawn_blocking(move || {
            // The actual worker owns supervision and capacity. Detaching the
            // request future releases neither one.
            let _permit = permit;
            let _completion = completion;
            work()
        }))
    }
}

fn wait_until_complete(completed: &(Mutex<bool>, Condvar), deadline: Instant) -> bool {
    let (state, ready) = completed;
    let mut state = state
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    loop {
        if *state {
            return true;
        }
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            return false;
        }
        let result = ready
            .wait_timeout(state, remaining)
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state = result.0;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn completion_disarms_and_joins_watchdog() {
        let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(1));
        let flag = Arc::new(AtomicBool::new(false));
        let completion = WorkerCompletionV1::supervise(
            Duration::from_secs(2),
            None,
            Arc::clone(&flag),
            Arc::clone(&telemetry),
        )
        .expect("watchdog");
        drop(completion);
        assert!(!flag.load(Ordering::Acquire));
        assert_eq!(telemetry.snapshot().request_timeouts, 0);
    }

    #[test]
    fn independent_watchdog_observes_detached_work() {
        let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(1));
        let flag = Arc::new(AtomicBool::new(false));
        let completion = WorkerCompletionV1::supervise(
            Duration::from_millis(10),
            None,
            Arc::clone(&flag),
            Arc::clone(&telemetry),
        )
        .expect("watchdog");
        let (release, wait) = std::sync::mpsc::channel();
        let worker = std::thread::spawn(move || {
            let _completion = completion;
            let _ = wait.recv_timeout(Duration::from_secs(5));
        });
        let deadline = Instant::now() + Duration::from_secs(2);
        while !flag.load(Ordering::Acquire) && Instant::now() < deadline {
            std::thread::sleep(Duration::from_millis(1));
        }
        let observed = flag.load(Ordering::Acquire);
        let _ = release.send(());
        worker.join().expect("worker exited");
        assert!(observed);
        assert_eq!(telemetry.snapshot().request_timeouts, 1);
    }

    #[test]
    fn explicit_hard_timeout_terminates_a_real_child_process() {
        const CHILD: &str = "HEPTA_INTELLIGENCE_WATCHDOG_TEST_CHILD";
        if std::env::var_os(CHILD).is_some() {
            let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(1));
            let completion = WorkerCompletionV1::supervise(
                Duration::from_millis(20),
                Some(Duration::from_millis(20)),
                Arc::new(AtomicBool::new(false)),
                telemetry,
            )
            .expect("watchdog");
            let _detached = std::thread::spawn(move || {
                let _completion = completion;
                loop {
                    std::thread::park();
                }
            });
            // No async runtime or live request future is needed to supervise.
            std::thread::sleep(Duration::from_secs(10));
            panic!("hard timeout did not terminate child");
        }
        let executable = std::env::current_exe().expect("test binary");
        let test_name = format!(
            "{}::explicit_hard_timeout_terminates_a_real_child_process",
            module_path!().split_once("::").expect("crate prefix").1,
        );
        let mut child = std::process::Command::new(executable)
            .args(["--exact", &test_name, "--nocapture"])
            .env(CHILD, "1")
            .spawn()
            .expect("child process");
        let deadline = Instant::now() + Duration::from_secs(15);
        let status = loop {
            if let Some(status) = child.try_wait().expect("observe child") {
                break status;
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("child watchdog deadline exceeded");
            }
            std::thread::sleep(Duration::from_millis(5));
        };
        assert_eq!(status.code(), Some(70));
    }
}
