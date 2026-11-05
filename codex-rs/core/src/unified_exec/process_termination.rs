use super::ProcessHandle;
use super::UnifiedExecError;
use super::UnifiedExecProcess;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::time::Instant;

const OBSERVATION_DEADLINE_EXPIRED: &str =
    "termination observation reached its caller-provided deadline";
const OBSERVATION_CANCELLED: &str =
    "termination observation was cancelled before native exit was observed";

struct TerminationObservation<'a> {
    process: &'a UnifiedExecProcess,
    requested: &'a AtomicBool,
    completed: bool,
}

impl Drop for TerminationObservation<'_> {
    fn drop(&mut self) {
        if self.requested.load(Ordering::Acquire)
            && !self.completed
            && !self.process.observe_current_exit()
        {
            self.process
                .signal_observation_failure(OBSERVATION_CANCELLED.to_string());
        }
    }
}

impl UnifiedExecProcess {
    /// Uses one caller-owned deadline for the original termination request and
    /// the original exit observer. An acknowledgement is never an exit fact.
    pub(in crate::unified_exec) async fn terminate_confirmed_until(
        &self,
        deadline: Instant,
    ) -> Result<(), UnifiedExecError> {
        if Instant::now() >= deadline {
            return Err(UnifiedExecError::process_failed(
                OBSERVATION_DEADLINE_EXPIRED.to_string(),
            ));
        }

        let requested = AtomicBool::new(false);
        let mut observation = TerminationObservation {
            process: self,
            requested: &requested,
            completed: false,
        };
        let mut state_rx = self.state_rx.clone();
        let request = async {
            if Instant::now() >= deadline {
                return Err(UnifiedExecError::process_failed(
                    OBSERVATION_DEADLINE_EXPIRED.to_string(),
                ));
            }
            requested.store(true, Ordering::Release);
            match &self.process_handle {
                ProcessHandle::Local(process) => process.terminate(),
                ProcessHandle::ExecServer(process) => {
                    process
                        .terminate()
                        .await
                        .map_err(|error| UnifiedExecError::process_failed(error.to_string()))?;
                }
            }
            Ok::<(), UnifiedExecError>(())
        };
        tokio::pin!(request);
        let deadline_elapsed = tokio::time::sleep_until(deadline);
        tokio::pin!(deadline_elapsed);
        let mut request_completed = false;
        let mut request_error: Option<UnifiedExecError> = None;

        loop {
            if Instant::now() >= deadline {
                if requested.load(Ordering::Acquire) {
                    self.signal_observation_failure(OBSERVATION_DEADLINE_EXPIRED.to_string());
                }
                return Err(UnifiedExecError::process_failed(
                    OBSERVATION_DEADLINE_EXPIRED.to_string(),
                ));
            }
            if self.observe_current_exit() {
                // A native result can arrive while the request is awaiting its
                // ACK. Keep that fact independently of the control future.
                if Instant::now() >= deadline {
                    return Err(UnifiedExecError::process_failed(
                        OBSERVATION_DEADLINE_EXPIRED.to_string(),
                    ));
                }
                observation.completed = true;
                self.finish_termination();
                return Ok(());
            }
            if let Some(message) = self.failure_message() {
                return Err(UnifiedExecError::process_failed(message));
            }
            if let Some(error) = request_error.take() {
                self.signal_observation_failure(error.to_string());
                return Err(error);
            }

            tokio::select! {
                biased;
                _ = &mut deadline_elapsed => {
                    if requested.load(Ordering::Acquire) {
                        self.signal_observation_failure(OBSERVATION_DEADLINE_EXPIRED.to_string());
                    }
                    return Err(UnifiedExecError::process_failed(
                        OBSERVATION_DEADLINE_EXPIRED.to_string(),
                    ));
                }
                result = &mut request, if !request_completed => {
                    request_completed = true;
                    request_error = result.err();
                }
                result = state_rx.changed() => {
                    if let Err(error) = result {
                        self.signal_observation_failure(error.to_string());
                        return Err(UnifiedExecError::process_failed(error.to_string()));
                    }
                }
            }
        }
    }
}
