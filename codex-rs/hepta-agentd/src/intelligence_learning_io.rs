//! A bounded blocking-I/O boundary for the existing learning host.
//! A timed-out or dropped caller cannot release the actual worker's permit.
//! Dispatch uncertainty is left in kernel.operations for exact reconciliation.
//! If an uncancellable worker survives both the caller budget and a bounded
//! grace, the shared independent watchdog terminates this fenced Agentd
//! generation so Supervisor recovery can adopt and reconcile the operation.

use super::*;
use codex_hepta_operations::AuthorizedDispatch;

const IO_BUDGET: Duration = Duration::from_secs(30);
const IO_HARD_TIMEOUT_GRACE: Duration = Duration::from_secs(30);
const HARD_TIMEOUT_EXIT_CODE: i32 = 70;

fn spawn_learning_io_watchdog_v1<T, F>(
    permit: tokio::sync::OwnedSemaphorePermit,
    budget: Duration,
    grace: Duration,
    work: F,
) -> std::io::Result<
    tokio::task::JoinHandle<Result<T, AgentdIntelligenceLearningErrorV1>>,
>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, AgentdIntelligenceLearningErrorV1> + Send + 'static,
{
    crate::AgentdIntelligenceProductRunnerV1::spawn_unobserved_blocking(
        permit, budget, grace, work,
    )
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
    let mut worker = spawn_learning_io_watchdog_v1(permit, budget, grace, work).map_err(|error| {
        AgentdIntelligenceLearningErrorV1::Io(format!(
            "learning I/O watchdog failed to start: {error}"
        ))
    })?;

    match tokio::time::timeout(budget, &mut worker).await {
        Ok(Ok(result)) => result,
        Ok(Err(_)) | Err(_) => Err(AgentdIntelligenceLearningErrorV1::IoIndeterminate),
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
    use std::time::Instant;

    const HARD_TIMEOUT_CHILD_ENV: &str = "HEPTA_INTELLIGENCE_LEARNING_IO_HARD_TIMEOUT_CHILD";

    #[tokio::test]
    async fn learning_io_completion_disarms_and_joins_watchdog() {
        let result = run_bounded_learning_io_v1(
            Arc::new(tokio::sync::Semaphore::new(1)),
            Duration::from_secs(1),
            Duration::from_secs(1),
            || Ok::<u64, AgentdIntelligenceLearningErrorV1>(7),
        )
        .await
        .expect("bounded learning I/O");
        assert_eq!(result, 7);
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
                Duration::from_millis(20),
                Duration::from_millis(20),
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
            std::thread::sleep(Duration::from_secs(10));
            panic!("learning I/O hard timeout did not terminate child");
        }

        let executable = std::env::current_exe().expect("test binary");
        let test_name = format!(
            "{}::learning_io_hard_timeout_terminates_a_real_child_process",
            module_path!().split_once("::").expect("crate prefix").1,
        );
        let mut child = Command::new(executable)
            .args(["--exact", &test_name, "--nocapture"])
            .env(HARD_TIMEOUT_CHILD_ENV, "1")
            .spawn()
            .expect("spawn hard-timeout child");
        let deadline = Instant::now() + Duration::from_secs(15);
        let status = loop {
            if let Some(status) = child.try_wait().expect("observe child") {
                break status;
            }
            if Instant::now() >= deadline {
                let _ = child.kill();
                let _ = child.wait();
                panic!("learning I/O child watchdog deadline exceeded");
            }
            std::thread::sleep(Duration::from_millis(5));
        };
        assert_eq!(status.code(), Some(HARD_TIMEOUT_EXIT_CODE));
    }
}
