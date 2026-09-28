//! A bounded blocking-I/O boundary for the existing learning host.
//! A timed-out or dropped caller cannot release the actual worker's permit.
//! Dispatch uncertainty is left in kernel.operations for exact reconciliation.
//! If an uncancellable worker survives both the caller budget and a bounded
//! grace, an independent watchdog terminates this fenced Agentd generation so
//! Supervisor recovery can adopt and reconcile the durable operation.

use super::*;
use codex_hepta_operations::AuthorizedDispatch;
use std::sync::Condvar;

const IO_BUDGET: Duration = Duration::from_secs(30);
const IO_HARD_TIMEOUT_GRACE: Duration = Duration::from_secs(30);
const HARD_TIMEOUT_EXIT_CODE: i32 = 70;

#[derive(Default)]
struct LearningIoCompletionV1 {
    finished: std::sync::Mutex<bool>,
    changed: Condvar,
}

impl LearningIoCompletionV1 {
    fn finish(&self) {
        let mut finished = match self.finished.lock() {
            Ok(value) => value,
            Err(poisoned) => poisoned.into_inner(),
        };
        *finished = true;
        self.changed.notify_all();
    }

    fn wait_for(&self, duration: Duration) -> bool {
        let finished = match self.finished.lock() {
            Ok(value) => value,
            Err(poisoned) => poisoned.into_inner(),
        };
        if *finished {
            return true;
        }
        let (finished, _) = match self
            .changed
            .wait_timeout_while(finished, duration, |value| !*value)
        {
            Ok(value) => value,
            Err(poisoned) => poisoned.into_inner(),
        };
        *finished
    }
}

struct LearningIoCompletionGuardV1 {
    completion: Arc<LearningIoCompletionV1>,
}

impl Drop for LearningIoCompletionGuardV1 {
    fn drop(&mut self) {
        self.completion.finish();
    }
}

fn spawn_learning_io_watchdog_v1(
    completion: Arc<LearningIoCompletionV1>,
    budget: Duration,
    grace: Duration,
) -> Result<std::thread::JoinHandle<()>, AgentdIntelligenceLearningErrorV1> {
    if budget.is_zero() || grace.is_zero() {
        return Err(AgentdIntelligenceLearningErrorV1::Invalid(
            "learning I/O watchdog policy",
        ));
    }
    std::thread::Builder::new()
        .name("hepta-intelligence-learning-io-watchdog".to_string())
        .spawn(move || {
            if completion.wait_for(budget) || completion.wait_for(grace) {
                return;
            }
            // EX_SOFTWARE. The durable operation remains unsettled and can only
            // be adopted/reconciled by the successor fenced process generation.
            std::process::exit(HARD_TIMEOUT_EXIT_CODE);
        })
        .map_err(|error| {
            AgentdIntelligenceLearningErrorV1::Io(format!(
                "learning I/O watchdog failed to start: {error}"
            ))
        })
}

async fn run_bounded_learning_io_v1<T, F>(
    io_slots: Arc<tokio::sync::Semaphore>,
    budget: Duration,
    grace: Duration,
    work: F,
) -> Result<T, AgentdIntelligenceLearningErrorV1>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, AgentdIntelligenceLearningErrorV1> + Send + 'static,
{
    let permit = io_slots
        .try_acquire_owned()
        .map_err(|_| AgentdIntelligenceLearningErrorV1::IoBusy)?;
    let completion = Arc::new(LearningIoCompletionV1::default());
    let watchdog =
        spawn_learning_io_watchdog_v1(Arc::clone(&completion), budget, grace)?;
    let completion_guard = LearningIoCompletionGuardV1 { completion };
    let mut worker = tokio::task::spawn_blocking(move || {
        let _permit = permit;
        let _completion_guard = completion_guard;
        work()
    });

    match tokio::time::timeout(budget, &mut worker).await {
        Ok(Ok(result)) => {
            let _ = watchdog.join();
            result
        }
        Ok(Err(_)) => {
            let _ = watchdog.join();
            Err(AgentdIntelligenceLearningErrorV1::IoIndeterminate)
        }
        Err(_) => {
            // Dropping JoinHandle values does not cancel running spawn_blocking
            // work or the independent OS-thread watchdog.
            drop(watchdog);
            Err(AgentdIntelligenceLearningErrorV1::IoIndeterminate)
        }
    }
}

impl AgentdIntelligenceLearningHostV1 {
    pub(super) async fn run_io<T, F>(&self, work: F) -> Result<T, AgentdIntelligenceLearningErrorV1>
    where
        T: Send + 'static,
        F: FnOnce() -> Result<T, AgentdIntelligenceLearningErrorV1> + Send + 'static,
    {
        run_bounded_learning_io_v1(
            Arc::clone(&self.io_slots),
            IO_BUDGET,
            IO_HARD_TIMEOUT_GRACE,
            work,
        )
        .await
    }

    pub(super) async fn execute_ledger_operation(
        &self,
        authorized: AuthorizedDispatch,
        payload: PersistedLearningEnvelopeV1,
    ) -> Result<ApplyObservation, AgentdIntelligenceLearningErrorV1> {
        let operations = self.operations.clone();
        let writer = Arc::clone(&self.writer);
        let runtime = tokio::runtime::Handle::current();
        self.run_io(move || {
            runtime.block_on(async move {
                operations
                    .execute_authorized(authorized, |_| {
                        let observed = match writer.lock() {
                            Ok(mut writer) => classify_apply(apply_payload(&mut writer, &payload)),
                            Err(_) => ApplyObservation::Indeterminate(Digest32::of_bytes(
                                b"hepta.agentd.intelligence-learning.writer-poisoned.v1",
                            )),
                        };
                        match &observed {
                            ApplyObservation::Acknowledged(receipt) => DispatchEffect::Dispatched {
                                value: observed.clone(),
                                dispatch_digest: receipt.chain_digest,
                                acknowledgement_digest: Some(receipt.chain_digest),
                            },
                            ApplyObservation::Rejected(reason)
                            | ApplyObservation::Revoked(reason)
                            | ApplyObservation::Indeterminate(reason) => {
                                DispatchEffect::Indeterminate {
                                    value: observed.clone(),
                                    reason_digest: *reason,
                                }
                            }
                        }
                    })
                    .await
                    .map_err(Into::into)
            })
        })
        .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command;

    const HARD_TIMEOUT_CHILD_ENV: &str = "HEPTA_INTELLIGENCE_LEARNING_IO_HARD_TIMEOUT_CHILD";

    #[test]
    fn learning_io_completion_disarms_and_joins_watchdog() {
        let completion = Arc::new(LearningIoCompletionV1::default());
        let watchdog = spawn_learning_io_watchdog_v1(
            Arc::clone(&completion),
            Duration::from_secs(1),
            Duration::from_secs(1),
        )
        .expect("watchdog");
        completion.finish();
        watchdog.join().expect("watchdog exits after completion");
    }

    #[test]
    fn learning_io_hard_timeout_terminates_a_real_child_process() {
        if std::env::var_os(HARD_TIMEOUT_CHILD_ENV).is_some() {
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_time()
                .build()
                .expect("runtime");
            let result = runtime.block_on(run_bounded_learning_io_v1::<(), _>(
                Arc::new(tokio::sync::Semaphore::new(1)),
                Duration::from_millis(100),
                Duration::from_millis(200),
                || -> Result<(), AgentdIntelligenceLearningErrorV1> {
                    loop {
                        std::thread::park();
                    }
                },
            ));
            assert!(matches!(
                result,
                Err(AgentdIntelligenceLearningErrorV1::IoIndeterminate)
            ));
            std::thread::sleep(Duration::from_secs(5));
            std::process::exit(99);
        }

        let status = Command::new(std::env::current_exe().expect("current test binary"))
            .arg("learning_io_hard_timeout_terminates_a_real_child_process")
            .arg("--nocapture")
            .env(HARD_TIMEOUT_CHILD_ENV, "1")
            .status()
            .expect("spawn hard-timeout child");
        assert_eq!(status.code(), Some(HARD_TIMEOUT_EXIT_CODE));
    }
}
