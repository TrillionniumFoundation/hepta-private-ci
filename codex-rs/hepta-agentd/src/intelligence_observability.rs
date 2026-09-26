//! Bounded observability for canonical intelligence execution.
//!
//! Counters contain no prompt, objective or owner payload. They expose only
//! bounded lifecycle totals, stage latency aggregates and failure classes. The
//! snapshot is suitable for health/qualification surfaces without transferring
//! another owner's facts.

use std::array;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_intelligence::CanonicalPortFailureClassV1;
use codex_hepta_intelligence::CanonicalStageV1;

const STAGE_COUNT: usize = 7;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceStageTelemetrySnapshotV1 {
    pub stage: CanonicalStageV1,
    pub latency_observations: u64,
    pub latency_total_micros: u64,
    pub latency_max_micros: u64,
    pub rejected: u64,
    pub unavailable: u64,
    pub timed_out: u64,
    pub quarantined: u64,
    pub indeterminate: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceTelemetrySnapshotV1 {
    pub provider_configured: bool,
    pub active_workers: u64,
    pub peak_active_workers: u64,
    pub worker_slots: u64,
    pub busy_rejections: u64,
    pub request_timeouts: u64,
    pub late_worker_completions: u64,
    pub hard_timeout_trips: u64,
    pub worker_crashes: u64,
    pub run_identity_rejections: u64,
    pub currentness_rejections: u64,
    pub canonical_rejections: u64,
    pub ready_runs: u64,
    pub abstained_runs: u64,
    pub slow_path_runs: u64,
    pub last_authority_epoch: u64,
    pub authority_manifest_reads: u64,
    pub stages: Vec<AgentdIntelligenceStageTelemetrySnapshotV1>,
}

#[derive(Default)]
struct StageCounters {
    latency_observations: AtomicU64,
    latency_total_micros: AtomicU64,
    latency_max_micros: AtomicU64,
    rejected: AtomicU64,
    unavailable: AtomicU64,
    timed_out: AtomicU64,
    quarantined: AtomicU64,
    indeterminate: AtomicU64,
}

pub struct AgentdIntelligenceTelemetryV1 {
    provider_configured: AtomicBool,
    active_workers: AtomicU64,
    peak_active_workers: AtomicU64,
    worker_slots: u64,
    busy_rejections: AtomicU64,
    request_timeouts: AtomicU64,
    late_worker_completions: AtomicU64,
    hard_timeout_trips: AtomicU64,
    worker_crashes: AtomicU64,
    run_identity_rejections: AtomicU64,
    currentness_rejections: AtomicU64,
    canonical_rejections: AtomicU64,
    ready_runs: AtomicU64,
    abstained_runs: AtomicU64,
    slow_path_runs: AtomicU64,
    last_authority_epoch: AtomicU64,
    authority_manifest_reads: AtomicU64,
    stages: [StageCounters; STAGE_COUNT],
}

impl AgentdIntelligenceTelemetryV1 {
    #[must_use]
    pub fn new(worker_slots: usize) -> Self {
        Self {
            provider_configured: AtomicBool::new(false),
            active_workers: AtomicU64::new(0),
            peak_active_workers: AtomicU64::new(0),
            worker_slots: u64::try_from(worker_slots).unwrap_or(u64::MAX),
            busy_rejections: AtomicU64::new(0),
            request_timeouts: AtomicU64::new(0),
            late_worker_completions: AtomicU64::new(0),
            hard_timeout_trips: AtomicU64::new(0),
            worker_crashes: AtomicU64::new(0),
            run_identity_rejections: AtomicU64::new(0),
            currentness_rejections: AtomicU64::new(0),
            canonical_rejections: AtomicU64::new(0),
            ready_runs: AtomicU64::new(0),
            abstained_runs: AtomicU64::new(0),
            slow_path_runs: AtomicU64::new(0),
            last_authority_epoch: AtomicU64::new(0),
            authority_manifest_reads: AtomicU64::new(0),
            stages: array::from_fn(|_| StageCounters::default()),
        }
    }

    pub fn set_provider_configured(&self, configured: bool) {
        self.provider_configured.store(configured, Ordering::Release);
    }

    pub(crate) fn worker_started(self: &Arc<Self>) -> AgentdIntelligenceWorkerGuardV1 {
        let active = saturating_increment(&self.active_workers);
        self.peak_active_workers.fetch_max(active, Ordering::AcqRel);
        AgentdIntelligenceWorkerGuardV1 {
            telemetry: Arc::clone(self),
            timed_out: Arc::new(AtomicBool::new(false)),
            finished: Arc::new(AtomicBool::new(false)),
        }
    }

    pub(crate) fn record_busy(&self) {
        saturating_increment(&self.busy_rejections);
    }

    pub(crate) fn record_request_timeout(&self) {
        saturating_increment(&self.request_timeouts);
    }

    pub(crate) fn record_hard_timeout_trip(&self) {
        saturating_increment(&self.hard_timeout_trips);
    }

    pub(crate) fn record_worker_crash(&self) {
        saturating_increment(&self.worker_crashes);
    }

    pub(crate) fn record_run_identity_rejection(&self) {
        saturating_increment(&self.run_identity_rejections);
    }

    pub(crate) fn record_currentness_rejection(&self) {
        saturating_increment(&self.currentness_rejections);
    }

    pub(crate) fn record_canonical_rejection(&self) {
        saturating_increment(&self.canonical_rejections);
    }

    pub(crate) fn record_ready(&self) {
        saturating_increment(&self.ready_runs);
    }

    pub(crate) fn record_abstained(&self) {
        saturating_increment(&self.abstained_runs);
    }

    pub(crate) fn record_slow_path(&self) {
        saturating_increment(&self.slow_path_runs);
    }

    pub(crate) fn record_authority_manifest(&self, authority_epoch: u64) {
        self.last_authority_epoch
            .fetch_max(authority_epoch, Ordering::AcqRel);
        saturating_increment(&self.authority_manifest_reads);
    }

    pub(crate) fn record_stage_latency(&self, stage: CanonicalStageV1, elapsed_micros: u64) {
        let counters = &self.stages[stage_index(stage)];
        saturating_increment(&counters.latency_observations);
        saturating_add(&counters.latency_total_micros, elapsed_micros);
        counters
            .latency_max_micros
            .fetch_max(elapsed_micros, Ordering::AcqRel);
    }

    pub(crate) fn record_stage_failure(
        &self,
        stage: CanonicalStageV1,
        class: CanonicalPortFailureClassV1,
    ) {
        let counters = &self.stages[stage_index(stage)];
        match class {
            CanonicalPortFailureClassV1::Rejected => saturating_increment(&counters.rejected),
            CanonicalPortFailureClassV1::Unavailable => {
                saturating_increment(&counters.unavailable)
            }
            CanonicalPortFailureClassV1::TimedOut => saturating_increment(&counters.timed_out),
            CanonicalPortFailureClassV1::Quarantined => {
                saturating_increment(&counters.quarantined)
            }
            CanonicalPortFailureClassV1::Indeterminate => {
                saturating_increment(&counters.indeterminate)
            }
        };
    }

    #[must_use]
    pub fn snapshot(&self) -> AgentdIntelligenceTelemetrySnapshotV1 {
        AgentdIntelligenceTelemetrySnapshotV1 {
            provider_configured: self.provider_configured.load(Ordering::Acquire),
            active_workers: self.active_workers.load(Ordering::Acquire),
            peak_active_workers: self.peak_active_workers.load(Ordering::Acquire),
            worker_slots: self.worker_slots,
            busy_rejections: self.busy_rejections.load(Ordering::Acquire),
            request_timeouts: self.request_timeouts.load(Ordering::Acquire),
            late_worker_completions: self.late_worker_completions.load(Ordering::Acquire),
            hard_timeout_trips: self.hard_timeout_trips.load(Ordering::Acquire),
            worker_crashes: self.worker_crashes.load(Ordering::Acquire),
            run_identity_rejections: self.run_identity_rejections.load(Ordering::Acquire),
            currentness_rejections: self.currentness_rejections.load(Ordering::Acquire),
            canonical_rejections: self.canonical_rejections.load(Ordering::Acquire),
            ready_runs: self.ready_runs.load(Ordering::Acquire),
            abstained_runs: self.abstained_runs.load(Ordering::Acquire),
            slow_path_runs: self.slow_path_runs.load(Ordering::Acquire),
            last_authority_epoch: self.last_authority_epoch.load(Ordering::Acquire),
            authority_manifest_reads: self.authority_manifest_reads.load(Ordering::Acquire),
            stages: stage_order()
                .into_iter()
                .map(|stage| {
                    let counters = &self.stages[stage_index(stage)];
                    AgentdIntelligenceStageTelemetrySnapshotV1 {
                        stage,
                        latency_observations: counters
                            .latency_observations
                            .load(Ordering::Acquire),
                        latency_total_micros: counters
                            .latency_total_micros
                            .load(Ordering::Acquire),
                        latency_max_micros: counters
                            .latency_max_micros
                            .load(Ordering::Acquire),
                        rejected: counters.rejected.load(Ordering::Acquire),
                        unavailable: counters.unavailable.load(Ordering::Acquire),
                        timed_out: counters.timed_out.load(Ordering::Acquire),
                        quarantined: counters.quarantined.load(Ordering::Acquire),
                        indeterminate: counters.indeterminate.load(Ordering::Acquire),
                    }
                })
                .collect(),
        }
    }
}

pub(crate) struct AgentdIntelligenceWorkerGuardV1 {
    telemetry: Arc<AgentdIntelligenceTelemetryV1>,
    timed_out: Arc<AtomicBool>,
    finished: Arc<AtomicBool>,
}

impl AgentdIntelligenceWorkerGuardV1 {
    #[must_use]
    pub(crate) fn timed_out_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.timed_out)
    }

    #[must_use]
    pub(crate) fn finished_flag(&self) -> Arc<AtomicBool> {
        Arc::clone(&self.finished)
    }
}

impl Drop for AgentdIntelligenceWorkerGuardV1 {
    fn drop(&mut self) {
        self.finished.store(true, Ordering::Release);
        decrement_nonzero(&self.telemetry.active_workers);
        if self.timed_out.load(Ordering::Acquire) {
            saturating_increment(&self.telemetry.late_worker_completions);
        }
    }
}

fn stage_order() -> [CanonicalStageV1; STAGE_COUNT] {
    [
        CanonicalStageV1::ObjectiveValidated,
        CanonicalStageV1::UtilityEvaluated,
        CanonicalStageV1::NeuralSignalCollected,
        CanonicalStageV1::PromptPortfolioBuilt,
        CanonicalStageV1::IntuitionDecided,
        CanonicalStageV1::ContextCompiled,
        CanonicalStageV1::EvaluationAdmitted,
    ]
}

const fn stage_index(stage: CanonicalStageV1) -> usize {
    match stage {
        CanonicalStageV1::ObjectiveValidated => 0,
        CanonicalStageV1::UtilityEvaluated => 1,
        CanonicalStageV1::NeuralSignalCollected => 2,
        CanonicalStageV1::PromptPortfolioBuilt => 3,
        CanonicalStageV1::IntuitionDecided => 4,
        CanonicalStageV1::ContextCompiled => 5,
        CanonicalStageV1::EvaluationAdmitted => 6,
    }
}

fn saturating_increment(value: &AtomicU64) -> u64 {
    let mut current = value.load(Ordering::Acquire);
    loop {
        let next = current.saturating_add(1);
        match value.compare_exchange_weak(current, next, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return next,
            Err(observed) => current = observed,
        }
    }
}

fn saturating_add(value: &AtomicU64, amount: u64) {
    let mut current = value.load(Ordering::Acquire);
    loop {
        let next = current.saturating_add(amount);
        match value.compare_exchange_weak(current, next, Ordering::AcqRel, Ordering::Acquire) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}

fn decrement_nonzero(value: &AtomicU64) {
    let mut current = value.load(Ordering::Acquire);
    while current != 0 {
        match value.compare_exchange_weak(
            current,
            current - 1,
            Ordering::AcqRel,
            Ordering::Acquire,
        ) {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn worker_timeout_is_visible_after_late_completion() {
        let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(4));
        let guard = telemetry.worker_started();
        guard.timed_out_flag().store(true, Ordering::Release);
        drop(guard);
        let snapshot = telemetry.snapshot();
        assert_eq!(snapshot.active_workers, 0);
        assert_eq!(snapshot.peak_active_workers, 1);
        assert_eq!(snapshot.late_worker_completions, 1);
    }

    #[test]
    fn stage_failure_classes_remain_separate() {
        let telemetry = AgentdIntelligenceTelemetryV1::new(4);
        telemetry.record_stage_latency(CanonicalStageV1::UtilityEvaluated, 17);
        telemetry.record_stage_failure(
            CanonicalStageV1::UtilityEvaluated,
            CanonicalPortFailureClassV1::Quarantined,
        );
        let stage = &telemetry.snapshot().stages[1];
        assert_eq!(stage.latency_observations, 1);
        assert_eq!(stage.latency_total_micros, 17);
        assert_eq!(stage.quarantined, 1);
        assert_eq!(stage.rejected, 0);
    }
}
