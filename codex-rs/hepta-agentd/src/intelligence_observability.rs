//! Profile-owned observability for canonical intelligence.
//!
//! Metrics are attached to one explicit product provider profile. There is no
//! process-global registry, hidden authority, unbounded label set or caller-
//! supplied metric identity. Every counter is monotonic and every stage label
//! belongs to the closed seven-owner canonical pipeline.

use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_intelligence::CanonicalPortFailureClassV1;
use codex_hepta_intelligence::CanonicalStageV1;

use crate::IntelligenceLearningStateV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct IntelligenceStageMetricsSnapshotV1 {
    pub stage: CanonicalStageV1,
    pub calls: u64,
    pub succeeded: u64,
    pub rejected: u64,
    pub unavailable: u64,
    pub timed_out: u64,
    pub quarantined: u64,
    pub indeterminate: u64,
    pub total_latency_micros: u64,
    pub maximum_latency_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceRuntimeMetricsSnapshotV1 {
    pub stages: Vec<IntelligenceStageMetricsSnapshotV1>,
    pub worker_busy_rejections: u64,
    pub cognition_timeouts: u64,
    pub worker_crashes: u64,
    pub currentness_rejections: u64,
    pub candidate_set_rejections: u64,
    pub late_workers_active: u64,
    pub late_workers_completed: u64,
    pub decision_acknowledged: u64,
    pub decision_rejected: u64,
    pub decision_revoked: u64,
    pub decision_indeterminate: u64,
    pub last_authority_epoch: u64,
}

#[derive(Default)]
struct StageCountersV1 {
    calls: AtomicU64,
    succeeded: AtomicU64,
    rejected: AtomicU64,
    unavailable: AtomicU64,
    timed_out: AtomicU64,
    quarantined: AtomicU64,
    indeterminate: AtomicU64,
    total_latency_micros: AtomicU64,
    maximum_latency_micros: AtomicU64,
}

impl StageCountersV1 {
    fn observe(
        &self,
        latency: Duration,
        failure: Option<CanonicalPortFailureClassV1>,
    ) {
        self.calls.fetch_add(1, Ordering::Relaxed);
        let micros = u64::try_from(latency.as_micros()).unwrap_or(u64::MAX);
        self.total_latency_micros
            .fetch_add(micros, Ordering::Relaxed);
        update_max(&self.maximum_latency_micros, micros);
        match failure {
            None => {
                self.succeeded.fetch_add(1, Ordering::Relaxed);
            }
            Some(CanonicalPortFailureClassV1::Rejected) => {
                self.rejected.fetch_add(1, Ordering::Relaxed);
            }
            Some(CanonicalPortFailureClassV1::Unavailable) => {
                self.unavailable.fetch_add(1, Ordering::Relaxed);
            }
            Some(CanonicalPortFailureClassV1::TimedOut) => {
                self.timed_out.fetch_add(1, Ordering::Relaxed);
            }
            Some(CanonicalPortFailureClassV1::Quarantined) => {
                self.quarantined.fetch_add(1, Ordering::Relaxed);
            }
            Some(CanonicalPortFailureClassV1::Indeterminate) => {
                self.indeterminate.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    fn snapshot(&self, stage: CanonicalStageV1) -> IntelligenceStageMetricsSnapshotV1 {
        IntelligenceStageMetricsSnapshotV1 {
            stage,
            calls: self.calls.load(Ordering::Relaxed),
            succeeded: self.succeeded.load(Ordering::Relaxed),
            rejected: self.rejected.load(Ordering::Relaxed),
            unavailable: self.unavailable.load(Ordering::Relaxed),
            timed_out: self.timed_out.load(Ordering::Relaxed),
            quarantined: self.quarantined.load(Ordering::Relaxed),
            indeterminate: self.indeterminate.load(Ordering::Relaxed),
            total_latency_micros: self.total_latency_micros.load(Ordering::Relaxed),
            maximum_latency_micros: self.maximum_latency_micros.load(Ordering::Relaxed),
        }
    }
}

/// Bounded counters owned by one canonical intelligence product profile.
#[derive(Default)]
pub struct AgentdIntelligenceRuntimeMetricsV1 {
    objective: StageCountersV1,
    utility: StageCountersV1,
    neural: StageCountersV1,
    prompt: StageCountersV1,
    intuition: StageCountersV1,
    context: StageCountersV1,
    evaluation: StageCountersV1,
    worker_busy_rejections: AtomicU64,
    cognition_timeouts: AtomicU64,
    worker_crashes: AtomicU64,
    currentness_rejections: AtomicU64,
    candidate_set_rejections: AtomicU64,
    late_workers_active: AtomicU64,
    late_workers_completed: AtomicU64,
    decision_acknowledged: AtomicU64,
    decision_rejected: AtomicU64,
    decision_revoked: AtomicU64,
    decision_indeterminate: AtomicU64,
    last_authority_epoch: AtomicU64,
}

impl AgentdIntelligenceRuntimeMetricsV1 {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub(crate) fn observe_stage(
        &self,
        stage: CanonicalStageV1,
        latency: Duration,
        failure: Option<CanonicalPortFailureClassV1>,
    ) {
        self.stage(stage).observe(latency, failure);
    }

    pub(crate) fn observe_authority_epoch(&self, authority_epoch: u64) {
        update_max(&self.last_authority_epoch, authority_epoch);
    }

    pub(crate) fn record_worker_busy(&self) {
        self.worker_busy_rejections.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_cognition_timeout(&self) {
        self.cognition_timeouts.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_worker_crash(&self) {
        self.worker_crashes.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_candidate_set_rejection(&self) {
        self.candidate_set_rejections
            .fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_late_worker_started(&self) {
        self.late_workers_active.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_late_worker_completed(&self) {
        decrement_saturating(&self.late_workers_active);
        self.late_workers_completed.fetch_add(1, Ordering::Relaxed);
    }

    pub(crate) fn record_canonical_error(&self, error: &CanonicalIntelligenceError) {
        if matches!(
            error,
            CanonicalIntelligenceError::FreshnessUnavailable(_)
                | CanonicalIntelligenceError::StaleOwner(_)
                | CanonicalIntelligenceError::KeyDrift(_)
                | CanonicalIntelligenceError::AuthorityEpochDrift(_)
                | CanonicalIntelligenceError::RevocationFrontierDrift(_)
        ) {
            self.currentness_rejections
                .fetch_add(1, Ordering::Relaxed);
        }
    }

    pub(crate) fn record_learning_state(&self, state: &IntelligenceLearningStateV1) {
        match state {
            IntelligenceLearningStateV1::Pending => {}
            IntelligenceLearningStateV1::Acknowledged { .. } => {
                self.decision_acknowledged.fetch_add(1, Ordering::Relaxed);
            }
            IntelligenceLearningStateV1::Rejected { .. } => {
                self.decision_rejected.fetch_add(1, Ordering::Relaxed);
            }
            IntelligenceLearningStateV1::Revoked { .. } => {
                self.decision_revoked.fetch_add(1, Ordering::Relaxed);
            }
            IntelligenceLearningStateV1::Indeterminate { .. } => {
                self.decision_indeterminate
                    .fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    #[must_use]
    pub fn snapshot(&self) -> AgentdIntelligenceRuntimeMetricsSnapshotV1 {
        AgentdIntelligenceRuntimeMetricsSnapshotV1 {
            stages: vec![
                self.objective
                    .snapshot(CanonicalStageV1::ObjectiveValidated),
                self.utility
                    .snapshot(CanonicalStageV1::UtilityEvaluated),
                self.neural
                    .snapshot(CanonicalStageV1::NeuralSignalCollected),
                self.prompt
                    .snapshot(CanonicalStageV1::PromptPortfolioBuilt),
                self.intuition
                    .snapshot(CanonicalStageV1::IntuitionDecided),
                self.context
                    .snapshot(CanonicalStageV1::ContextCompiled),
                self.evaluation
                    .snapshot(CanonicalStageV1::EvaluationAdmitted),
            ],
            worker_busy_rejections: self.worker_busy_rejections.load(Ordering::Relaxed),
            cognition_timeouts: self.cognition_timeouts.load(Ordering::Relaxed),
            worker_crashes: self.worker_crashes.load(Ordering::Relaxed),
            currentness_rejections: self.currentness_rejections.load(Ordering::Relaxed),
            candidate_set_rejections: self.candidate_set_rejections.load(Ordering::Relaxed),
            late_workers_active: self.late_workers_active.load(Ordering::Relaxed),
            late_workers_completed: self.late_workers_completed.load(Ordering::Relaxed),
            decision_acknowledged: self.decision_acknowledged.load(Ordering::Relaxed),
            decision_rejected: self.decision_rejected.load(Ordering::Relaxed),
            decision_revoked: self.decision_revoked.load(Ordering::Relaxed),
            decision_indeterminate: self.decision_indeterminate.load(Ordering::Relaxed),
            last_authority_epoch: self.last_authority_epoch.load(Ordering::Relaxed),
        }
    }

    fn stage(&self, stage: CanonicalStageV1) -> &StageCountersV1 {
        match stage {
            CanonicalStageV1::ObjectiveValidated => &self.objective,
            CanonicalStageV1::UtilityEvaluated => &self.utility,
            CanonicalStageV1::NeuralSignalCollected => &self.neural,
            CanonicalStageV1::PromptPortfolioBuilt => &self.prompt,
            CanonicalStageV1::IntuitionDecided => &self.intuition,
            CanonicalStageV1::ContextCompiled => &self.context,
            CanonicalStageV1::EvaluationAdmitted => &self.evaluation,
        }
    }
}

fn update_max(target: &AtomicU64, value: u64) {
    let mut current = target.load(Ordering::Relaxed);
    while value > current {
        match target.compare_exchange_weak(
            current,
            value,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => break,
            Err(observed) => current = observed,
        }
    }
}

fn decrement_saturating(target: &AtomicU64) {
    let mut current = target.load(Ordering::Relaxed);
    while current > 0 {
        match target.compare_exchange_weak(
            current,
            current - 1,
            Ordering::Relaxed,
            Ordering::Relaxed,
        ) {
            Ok(_) => break,
            Err(observed) => current = observed,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn closed_stage_metrics_preserve_failure_class_and_latency() {
        let metrics = AgentdIntelligenceRuntimeMetricsV1::new();
        metrics.observe_stage(
            CanonicalStageV1::ContextCompiled,
            Duration::from_micros(17),
            Some(CanonicalPortFailureClassV1::TimedOut),
        );
        metrics.record_late_worker_started();
        metrics.record_late_worker_completed();
        let snapshot = metrics.snapshot();
        let context = snapshot
            .stages
            .iter()
            .find(|value| value.stage == CanonicalStageV1::ContextCompiled)
            .expect("context metrics");
        assert_eq!(context.calls, 1);
        assert_eq!(context.timed_out, 1);
        assert_eq!(context.total_latency_micros, 17);
        assert_eq!(context.maximum_latency_micros, 17);
        assert_eq!(snapshot.late_workers_active, 0);
        assert_eq!(snapshot.late_workers_completed, 1);
    }
}
