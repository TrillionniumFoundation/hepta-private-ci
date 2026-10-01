//! One linearization point for request timeouts, watchdogs and worker release.
//!
//! The worker, request and independent observer share this state. Lifecycle
//! counters change under the same lock as the phase: completion cannot decrement
//! a timeout gauge before its increment, and competing timeout observers count
//! the request exactly once. No user work or blocking I/O runs under this lock.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use super::AgentdIntelligenceTelemetryV1;
use super::decrement_nonzero;
use super::duration_micros;
use super::saturating_increment;

#[derive(Clone, Copy)]
enum WorkerPhaseV1 {
    Running,
    TimedOut,
    Finished,
    FinishedWithTimeout,
}

pub(crate) struct AgentdIntelligenceWorkerStateV1 {
    phase: Mutex<WorkerPhaseV1>,
    telemetry: Arc<AgentdIntelligenceTelemetryV1>,
    permit_started: Instant,
}

impl AgentdIntelligenceWorkerStateV1 {
    pub(super) fn new(telemetry: Arc<AgentdIntelligenceTelemetryV1>) -> Self {
        Self {
            phase: Mutex::new(WorkerPhaseV1::Running),
            telemetry,
            permit_started: Instant::now(),
        }
    }

    /// Record a timeout once, including when the request observes it after the
    /// actual worker has finished. Only an unfinished worker occupies the gauge.
    pub(crate) fn mark_timed_out(&self) -> bool {
        let mut phase = self
            .phase
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match *phase {
            WorkerPhaseV1::Running => {
                saturating_increment(&self.telemetry.timed_out_active_workers);
                *phase = WorkerPhaseV1::TimedOut;
            }
            WorkerPhaseV1::Finished => *phase = WorkerPhaseV1::FinishedWithTimeout,
            WorkerPhaseV1::TimedOut | WorkerPhaseV1::FinishedWithTimeout => return false,
        }
        self.telemetry.record_request_timeout();
        true
    }

    #[must_use]
    pub(crate) fn timed_out(&self) -> bool {
        let phase = self
            .phase
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        matches!(
            *phase,
            WorkerPhaseV1::TimedOut | WorkerPhaseV1::FinishedWithTimeout
        )
    }

    #[must_use]
    pub(crate) fn finished(&self) -> bool {
        let phase = self
            .phase
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        matches!(
            *phase,
            WorkerPhaseV1::Finished | WorkerPhaseV1::FinishedWithTimeout
        )
    }

    pub(super) fn finish(&self) {
        let mut phase = self
            .phase
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        match *phase {
            WorkerPhaseV1::Running => *phase = WorkerPhaseV1::Finished,
            WorkerPhaseV1::TimedOut => {
                decrement_nonzero(&self.telemetry.timed_out_active_workers);
                saturating_increment(&self.telemetry.late_worker_completions);
                *phase = WorkerPhaseV1::FinishedWithTimeout;
            }
            WorkerPhaseV1::Finished | WorkerPhaseV1::FinishedWithTimeout => return,
        }
        self.telemetry
            .record_permit_hold(duration_micros(self.permit_started.elapsed()));
        decrement_nonzero(&self.telemetry.active_workers);
    }
}

#[cfg(test)]
#[path = "intelligence_worker_state_tests.rs"]
mod tests;
