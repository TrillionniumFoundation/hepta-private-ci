//! Bounded deadline enforcement for work already isolated in a managed child.
//!
//! This is the hard-deadline counterpart to the control-plane's in-process
//! `BudgetedReadOnlyOrganV1`. A synchronous Rust handler cannot be safely
//! preempted; code that can hang or block must first live behind a
//! `ManagedProcess` boundary. The supervisor can then remain authoritative and
//! request an OS/process kill when the wall deadline expires.

use std::cmp::min;
use std::fmt;
use std::thread;
use std::time::Duration;
use std::time::Instant;

use crate::ManagedProcess;
use crate::ProcessDriverError;
use crate::ProcessState;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ProcessDeadlinePolicyV1 {
    max_wall_time: Duration,
    poll_interval: Duration,
    max_logs_per_poll: usize,
}

impl ProcessDeadlinePolicyV1 {
    pub fn new(
        max_wall_time: Duration,
        poll_interval: Duration,
        max_logs_per_poll: usize,
    ) -> Result<Self, ProcessDeadlinePolicyErrorV1> {
        if max_wall_time.is_zero() {
            return Err(ProcessDeadlinePolicyErrorV1::ZeroWallTime);
        }
        if poll_interval.is_zero() || poll_interval > max_wall_time {
            return Err(ProcessDeadlinePolicyErrorV1::InvalidPollInterval);
        }
        if max_logs_per_poll == 0 {
            return Err(ProcessDeadlinePolicyErrorV1::ZeroLogBudget);
        }
        Ok(Self {
            max_wall_time,
            poll_interval,
            max_logs_per_poll,
        })
    }

    #[must_use]
    pub const fn max_wall_time(self) -> Duration {
        self.max_wall_time
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProcessDeadlinePolicyErrorV1 {
    ZeroWallTime,
    InvalidPollInterval,
    ZeroLogBudget,
}

impl fmt::Display for ProcessDeadlinePolicyErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for ProcessDeadlinePolicyErrorV1 {}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProcessDeadlineOutcomeV1 {
    Exited,
    KillRequestedAtDeadline,
}

/// Observe an already isolated process until it exits or its deadline expires.
///
/// `ManagedProcess` requires `poll` and `kill` to return promptly. This function
/// does not make an in-process callback preemptible and must never be used to
/// justify running untrusted or potentially blocking code on the supervisor
/// thread itself.
pub fn enforce_process_deadline_v1<P: ManagedProcess>(
    process: &mut P,
    policy: ProcessDeadlinePolicyV1,
) -> Result<ProcessDeadlineOutcomeV1, ProcessDriverError> {
    let started = Instant::now();
    loop {
        if matches!(
            process.poll(policy.max_logs_per_poll)?.state,
            ProcessState::Exited(_)
        ) {
            return Ok(ProcessDeadlineOutcomeV1::Exited);
        }

        let elapsed = started.elapsed();
        if elapsed >= policy.max_wall_time {
            process.kill()?;
            return Ok(ProcessDeadlineOutcomeV1::KillRequestedAtDeadline);
        }
        let remaining = policy.max_wall_time.saturating_sub(elapsed);
        thread::sleep(min(policy.poll_interval, remaining));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ProcessObservation;

    struct HangingChild {
        killed: bool,
        kill_calls: usize,
    }

    impl ManagedProcess for HangingChild {
        fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
            Ok(ProcessObservation {
                state: ProcessState::Running {
                    healthy: true,
                    drained: false,
                },
                logs: Vec::new(),
            })
        }

        fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }

        fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
            Ok(())
        }

        fn kill(&mut self) -> Result<(), ProcessDriverError> {
            self.killed = true;
            self.kill_calls += 1;
            Ok(())
        }
    }

    #[test]
    fn non_terminating_child_is_killed_at_deadline() {
        let mut child = HangingChild {
            killed: false,
            kill_calls: 0,
        };
        let policy =
            ProcessDeadlinePolicyV1::new(Duration::from_millis(3), Duration::from_millis(1), 8)
                .expect("policy");

        let outcome = enforce_process_deadline_v1(&mut child, policy).expect("deadline outcome");
        assert_eq!(outcome, ProcessDeadlineOutcomeV1::KillRequestedAtDeadline);
        assert!(child.killed);
        assert_eq!(child.kill_calls, 1);
    }

    #[test]
    fn invalid_deadline_policy_is_rejected() {
        assert_eq!(
            ProcessDeadlinePolicyV1::new(Duration::ZERO, Duration::from_millis(1), 1),
            Err(ProcessDeadlinePolicyErrorV1::ZeroWallTime)
        );
        assert_eq!(
            ProcessDeadlinePolicyV1::new(Duration::from_millis(1), Duration::from_millis(2), 1,),
            Err(ProcessDeadlinePolicyErrorV1::InvalidPollInterval)
        );
    }
}
