//! Bounded observability for canonical intelligence execution.
//!
//! Counters contain no prompt, objective or owner payload. They expose only
//! bounded lifecycle totals, admission/permit timing, stage latency aggregates,
//! authority-manifest timing and failure classes. The snapshot is suitable for
//! health/qualification surfaces without transferring another owner's facts.

use std::array;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence::CanonicalPortFailureClassV1;
use codex_hepta_intelligence::CanonicalStageV1;

use crate::RunPhase;
use crate::RunReceipt;

#[path = "intelligence_worker_state.rs"]
mod worker_state;
pub(crate) use worker_state::AgentdIntelligenceWorkerStateV1;

const STAGE_COUNT: usize = 7;
const RUN_PHASE_COUNT: usize = 8;
const MAX_TRACKED_RUN_DWELL: usize = 1_024;
const RATIO_SCALE_PPM: u64 = 1_000_000;

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
pub struct AgentdIntelligenceRunPhaseDurationV1 {
    pub phase: RunPhase,
    pub elapsed_ms: u64,
    pub current: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceRunDwellSnapshotV1 {
    pub run_id: String,
    pub observed_at_ms: u64,
    pub current_phase_entered_at_ms: u64,
    pub durations: Vec<AgentdIntelligenceRunPhaseDurationV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceTelemetrySnapshotV1 {
    pub provider_configured: bool,
    pub active_workers: u64,
    pub peak_active_workers: u64,
    pub timed_out_active_workers: u64,
    pub worker_slots: u64,
    pub busy_rejections: u64,
    pub request_timeouts: u64,
    pub late_worker_completions: u64,
    pub hard_timeout_trips: u64,
    pub worker_crashes: u64,
    pub queue_wait_observations: u64,
    pub queue_wait_total_micros: u64,
    pub queue_wait_max_micros: u64,
    pub permit_hold_observations: u64,
    pub permit_hold_total_micros: u64,
    pub permit_hold_max_micros: u64,
    pub run_identity_rejections: u64,
    pub currentness_rejections: u64,
    pub canonical_rejections: u64,
    pub ready_runs: u64,
    pub abstained_runs: u64,
    pub slow_path_runs: u64,
    pub ready_ratio_ppm: u32,
    pub abstained_ratio_ppm: u32,
    pub slow_path_ratio_ppm: u32,
    pub candidate_count_observations: u64,
    pub candidate_count_total: u64,
    pub candidate_count_max: u64,
    pub last_authority_epoch: u64,
    pub authority_manifest_reads: u64,
    pub authority_manifest_observed_at_ms: Option<u64>,
    pub authority_snapshot_age_ms: Option<u64>,
    pub manifest_verification_observations: u64,
    pub manifest_verification_total_micros: u64,
    pub manifest_verification_max_micros: u64,
    pub tracked_run_dwell: u64,
    pub run_dwell_evictions: u64,
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

#[derive(Clone, Debug)]
struct RunDwellRecord {
    phase: RunPhase,
    entered_at_ms: u64,
    accumulated_ms: [u64; RUN_PHASE_COUNT],
}

pub struct AgentdIntelligenceTelemetryV1 {
    provider_configured: AtomicBool,
    active_workers: AtomicU64,
    peak_active_workers: AtomicU64,
    timed_out_active_workers: AtomicU64,
    worker_slots: u64,
    busy_rejections: AtomicU64,
    request_timeouts: AtomicU64,
    late_worker_completions: AtomicU64,
    hard_timeout_trips: AtomicU64,
    worker_crashes: AtomicU64,
    queue_wait_observations: AtomicU64,
    queue_wait_total_micros: AtomicU64,
    queue_wait_max_micros: AtomicU64,
    permit_hold_observations: AtomicU64,
    permit_hold_total_micros: AtomicU64,
    permit_hold_max_micros: AtomicU64,
    run_identity_rejections: AtomicU64,
    currentness_rejections: AtomicU64,
    canonical_rejections: AtomicU64,
    ready_runs: AtomicU64,
    abstained_runs: AtomicU64,
    slow_path_runs: AtomicU64,
    candidate_count_observations: AtomicU64,
    candidate_count_total: AtomicU64,
    candidate_count_max: AtomicU64,
    last_authority_epoch: AtomicU64,
    authority_manifest_reads: AtomicU64,
    authority_manifest_observed_at_ms: AtomicU64,
    manifest_verification_observations: AtomicU64,
    manifest_verification_total_micros: AtomicU64,
    manifest_verification_max_micros: AtomicU64,
    run_dwell: Mutex<BTreeMap<String, RunDwellRecord>>,
    run_dwell_evictions: AtomicU64,
    stages: [StageCounters; STAGE_COUNT],
}

impl AgentdIntelligenceTelemetryV1 {
    #[must_use]
    pub fn new(worker_slots: usize) -> Self {
        Self {
            provider_configured: AtomicBool::new(false),
            active_workers: AtomicU64::new(0),
            peak_active_workers: AtomicU64::new(0),
            timed_out_active_workers: AtomicU64::new(0),
            worker_slots: u64::try_from(worker_slots).unwrap_or(u64::MAX),
            busy_rejections: AtomicU64::new(0),
            request_timeouts: AtomicU64::new(0),
            late_worker_completions: AtomicU64::new(0),
            hard_timeout_trips: AtomicU64::new(0),
            worker_crashes: AtomicU64::new(0),
            queue_wait_observations: AtomicU64::new(0),
            queue_wait_total_micros: AtomicU64::new(0),
            queue_wait_max_micros: AtomicU64::new(0),
            permit_hold_observations: AtomicU64::new(0),
            permit_hold_total_micros: AtomicU64::new(0),
            permit_hold_max_micros: AtomicU64::new(0),
            run_identity_rejections: AtomicU64::new(0),
            currentness_rejections: AtomicU64::new(0),
            canonical_rejections: AtomicU64::new(0),
            ready_runs: AtomicU64::new(0),
            abstained_runs: AtomicU64::new(0),
            slow_path_runs: AtomicU64::new(0),
            candidate_count_observations: AtomicU64::new(0),
            candidate_count_total: AtomicU64::new(0),
            candidate_count_max: AtomicU64::new(0),
            last_authority_epoch: AtomicU64::new(0),
            authority_manifest_reads: AtomicU64::new(0),
            authority_manifest_observed_at_ms: AtomicU64::new(0),
            manifest_verification_observations: AtomicU64::new(0),
            manifest_verification_total_micros: AtomicU64::new(0),
            manifest_verification_max_micros: AtomicU64::new(0),
            run_dwell: Mutex::new(BTreeMap::new()),
            run_dwell_evictions: AtomicU64::new(0),
            stages: array::from_fn(|_| StageCounters::default()),
        }
    }

    pub fn set_provider_configured(&self, configured: bool) {
        self.provider_configured
            .store(configured, Ordering::Release);
    }

    pub(crate) fn worker_started(self: &Arc<Self>) -> AgentdIntelligenceWorkerGuardV1 {
        let active = saturating_increment(&self.active_workers);
        self.peak_active_workers.fetch_max(active, Ordering::AcqRel);
        AgentdIntelligenceWorkerGuardV1 {
            state: Arc::new(AgentdIntelligenceWorkerStateV1::new(Arc::clone(self))),
        }
    }

    pub(crate) fn record_queue_wait(&self, elapsed_micros: u64) {
        record_duration(
            &self.queue_wait_observations,
            &self.queue_wait_total_micros,
            &self.queue_wait_max_micros,
            elapsed_micros,
        );
    }

    fn record_permit_hold(&self, elapsed_micros: u64) {
        record_duration(
            &self.permit_hold_observations,
            &self.permit_hold_total_micros,
            &self.permit_hold_max_micros,
            elapsed_micros,
        );
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

    pub(crate) fn record_candidate_count(&self, count: usize) {
        let count = u64::try_from(count).unwrap_or(u64::MAX);
        saturating_increment(&self.candidate_count_observations);
        saturating_add(&self.candidate_count_total, count);
        self.candidate_count_max.fetch_max(count, Ordering::AcqRel);
    }

    pub(crate) fn record_authority_manifest(
        &self,
        authority_epoch: u64,
        observed_at_ms: u64,
        verification_micros: u64,
    ) {
        self.last_authority_epoch
            .fetch_max(authority_epoch, Ordering::AcqRel);
        saturating_increment(&self.authority_manifest_reads);
        self.authority_manifest_observed_at_ms
            .store(observed_at_ms, Ordering::Release);
        record_duration(
            &self.manifest_verification_observations,
            &self.manifest_verification_total_micros,
            &self.manifest_verification_max_micros,
            verification_micros,
        );
    }

    pub(crate) fn record_stage_latency(&self, stage: CanonicalStageV1, elapsed_micros: u64) {
        let counters = &self.stages[stage_index(stage)];
        record_duration(
            &counters.latency_observations,
            &counters.latency_total_micros,
            &counters.latency_max_micros,
            elapsed_micros,
        );
    }

    pub(crate) fn record_stage_failure(
        &self,
        stage: CanonicalStageV1,
        class: CanonicalPortFailureClassV1,
    ) {
        let counters = &self.stages[stage_index(stage)];
        match class {
            CanonicalPortFailureClassV1::Rejected => saturating_increment(&counters.rejected),
            CanonicalPortFailureClassV1::Unavailable => saturating_increment(&counters.unavailable),
            CanonicalPortFailureClassV1::TimedOut => saturating_increment(&counters.timed_out),
            CanonicalPortFailureClassV1::Quarantined => saturating_increment(&counters.quarantined),
            CanonicalPortFailureClassV1::Indeterminate => {
                saturating_increment(&counters.indeterminate)
            }
        };
    }

    /// Observe an Agentd run receipt at one owner-supplied time. A same-phase
    /// replay is a no-op; a phase transition accumulates the preceding dwell.
    /// The map is bounded and deterministic. Eviction is telemetry loss only and
    /// cannot affect the authoritative run coordinator.
    pub fn observe_run_receipt(&self, receipt: &RunReceipt, observed_at_ms: u64) {
        let Ok(mut records) = self.run_dwell.lock() else {
            return;
        };
        if let Some(record) = records.get_mut(&receipt.run_id) {
            if observed_at_ms < record.entered_at_ms || receipt.phase == record.phase {
                return;
            }
            let elapsed = observed_at_ms.saturating_sub(record.entered_at_ms);
            let slot = &mut record.accumulated_ms[run_phase_index(record.phase)];
            *slot = slot.saturating_add(elapsed);
            record.phase = receipt.phase;
            record.entered_at_ms = observed_at_ms;
            return;
        }
        if records.len() >= MAX_TRACKED_RUN_DWELL {
            let oldest_key = records
                .iter()
                .min_by_key(|(_, value)| value.entered_at_ms)
                .map(|(key, _)| key.clone());
            if let Some(key) = oldest_key {
                records.remove(&key);
                saturating_increment(&self.run_dwell_evictions);
            }
        }
        records.insert(
            receipt.run_id.clone(),
            RunDwellRecord {
                phase: receipt.phase,
                entered_at_ms: observed_at_ms,
                accumulated_ms: [0; RUN_PHASE_COUNT],
            },
        );
    }

    #[must_use]
    pub fn tracks_run(&self, run_id: &str) -> bool {
        self.run_dwell
            .lock()
            .is_ok_and(|records| records.contains_key(run_id))
    }

    #[must_use]
    pub fn run_phase_dwell_snapshot(
        &self,
        run_id: &str,
        observed_at_ms: u64,
    ) -> Option<AgentdIntelligenceRunDwellSnapshotV1> {
        let records = self.run_dwell.lock().ok()?;
        let record = records.get(run_id)?;
        if observed_at_ms < record.entered_at_ms {
            return None;
        }
        let current_elapsed = observed_at_ms.saturating_sub(record.entered_at_ms);
        let durations = run_phase_order()
            .into_iter()
            .map(|phase| {
                let mut elapsed_ms = record.accumulated_ms[run_phase_index(phase)];
                let current = phase == record.phase;
                if current {
                    elapsed_ms = elapsed_ms.saturating_add(current_elapsed);
                }
                AgentdIntelligenceRunPhaseDurationV1 {
                    phase,
                    elapsed_ms,
                    current,
                }
            })
            .collect();
        Some(AgentdIntelligenceRunDwellSnapshotV1 {
            run_id: run_id.to_string(),
            observed_at_ms,
            current_phase_entered_at_ms: record.entered_at_ms,
            durations,
        })
    }

    #[must_use]
    pub fn snapshot(&self) -> AgentdIntelligenceTelemetrySnapshotV1 {
        self.snapshot_at(wall_clock_ms().unwrap_or(0))
    }

    #[must_use]
    pub fn snapshot_at(&self, observed_at_ms: u64) -> AgentdIntelligenceTelemetrySnapshotV1 {
        let tracked_run_dwell = self
            .run_dwell
            .lock()
            .ok()
            .and_then(|value| u64::try_from(value.len()).ok())
            .unwrap_or(u64::MAX);
        let ready_runs = self.ready_runs.load(Ordering::Acquire);
        let abstained_runs = self.abstained_runs.load(Ordering::Acquire);
        let slow_path_runs = self.slow_path_runs.load(Ordering::Acquire);
        let decision_observations = ready_runs
            .saturating_add(abstained_runs)
            .saturating_add(slow_path_runs);
        let authority_manifest_observed_at_ms = nonzero(
            self.authority_manifest_observed_at_ms
                .load(Ordering::Acquire),
        );
        AgentdIntelligenceTelemetrySnapshotV1 {
            provider_configured: self.provider_configured.load(Ordering::Acquire),
            active_workers: self.active_workers.load(Ordering::Acquire),
            peak_active_workers: self.peak_active_workers.load(Ordering::Acquire),
            timed_out_active_workers: self.timed_out_active_workers.load(Ordering::Acquire),
            worker_slots: self.worker_slots,
            busy_rejections: self.busy_rejections.load(Ordering::Acquire),
            request_timeouts: self.request_timeouts.load(Ordering::Acquire),
            late_worker_completions: self.late_worker_completions.load(Ordering::Acquire),
            hard_timeout_trips: self.hard_timeout_trips.load(Ordering::Acquire),
            worker_crashes: self.worker_crashes.load(Ordering::Acquire),
            queue_wait_observations: self.queue_wait_observations.load(Ordering::Acquire),
            queue_wait_total_micros: self.queue_wait_total_micros.load(Ordering::Acquire),
            queue_wait_max_micros: self.queue_wait_max_micros.load(Ordering::Acquire),
            permit_hold_observations: self.permit_hold_observations.load(Ordering::Acquire),
            permit_hold_total_micros: self.permit_hold_total_micros.load(Ordering::Acquire),
            permit_hold_max_micros: self.permit_hold_max_micros.load(Ordering::Acquire),
            run_identity_rejections: self.run_identity_rejections.load(Ordering::Acquire),
            currentness_rejections: self.currentness_rejections.load(Ordering::Acquire),
            canonical_rejections: self.canonical_rejections.load(Ordering::Acquire),
            ready_runs,
            abstained_runs,
            slow_path_runs,
            ready_ratio_ppm: ratio_ppm(ready_runs, decision_observations),
            abstained_ratio_ppm: ratio_ppm(abstained_runs, decision_observations),
            slow_path_ratio_ppm: ratio_ppm(slow_path_runs, decision_observations),
            candidate_count_observations: self.candidate_count_observations.load(Ordering::Acquire),
            candidate_count_total: self.candidate_count_total.load(Ordering::Acquire),
            candidate_count_max: self.candidate_count_max.load(Ordering::Acquire),
            last_authority_epoch: self.last_authority_epoch.load(Ordering::Acquire),
            authority_manifest_reads: self.authority_manifest_reads.load(Ordering::Acquire),
            authority_manifest_observed_at_ms,
            authority_snapshot_age_ms: authority_manifest_observed_at_ms
                .map(|value| observed_at_ms.saturating_sub(value)),
            manifest_verification_observations: self
                .manifest_verification_observations
                .load(Ordering::Acquire),
            manifest_verification_total_micros: self
                .manifest_verification_total_micros
                .load(Ordering::Acquire),
            manifest_verification_max_micros: self
                .manifest_verification_max_micros
                .load(Ordering::Acquire),
            tracked_run_dwell,
            run_dwell_evictions: self.run_dwell_evictions.load(Ordering::Acquire),
            stages: stage_order()
                .into_iter()
                .map(|stage| {
                    let counters = &self.stages[stage_index(stage)];
                    AgentdIntelligenceStageTelemetrySnapshotV1 {
                        stage,
                        latency_observations: counters.latency_observations.load(Ordering::Acquire),
                        latency_total_micros: counters.latency_total_micros.load(Ordering::Acquire),
                        latency_max_micros: counters.latency_max_micros.load(Ordering::Acquire),
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
    state: Arc<AgentdIntelligenceWorkerStateV1>,
}

impl AgentdIntelligenceWorkerGuardV1 {
    #[must_use]
    pub(crate) fn state(&self) -> Arc<AgentdIntelligenceWorkerStateV1> {
        Arc::clone(&self.state)
    }
}

impl Drop for AgentdIntelligenceWorkerGuardV1 {
    fn drop(&mut self) {
        self.state.finish();
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

fn run_phase_order() -> [RunPhase; RUN_PHASE_COUNT] {
    [
        RunPhase::Admitted,
        RunPhase::ContextAttached,
        RunPhase::Dispatched,
        RunPhase::Cancelling,
        RunPhase::Cancelled,
        RunPhase::Succeeded,
        RunPhase::Failed,
        RunPhase::Indeterminate,
    ]
}

const fn run_phase_index(phase: RunPhase) -> usize {
    match phase {
        RunPhase::Admitted => 0,
        RunPhase::ContextAttached => 1,
        RunPhase::Dispatched => 2,
        RunPhase::Cancelling => 3,
        RunPhase::Cancelled => 4,
        RunPhase::Succeeded => 5,
        RunPhase::Failed => 6,
        RunPhase::Indeterminate => 7,
    }
}

fn record_duration(
    observations: &AtomicU64,
    total: &AtomicU64,
    maximum: &AtomicU64,
    elapsed_micros: u64,
) {
    saturating_increment(observations);
    saturating_add(total, elapsed_micros);
    maximum.fetch_max(elapsed_micros, Ordering::AcqRel);
}

fn duration_micros(value: std::time::Duration) -> u64 {
    u64::try_from(value.as_micros()).unwrap_or(u64::MAX)
}

fn wall_clock_ms() -> Option<u64> {
    let value = SystemTime::now().duration_since(UNIX_EPOCH).ok()?;
    u64::try_from(value.as_millis()).ok()
}

const fn nonzero(value: u64) -> Option<u64> {
    if value == 0 { None } else { Some(value) }
}

fn ratio_ppm(value: u64, total: u64) -> u32 {
    if total == 0 {
        return 0;
    }
    let scaled = u128::from(value).saturating_mul(u128::from(RATIO_SCALE_PPM)) / u128::from(total);
    u32::try_from(scaled).unwrap_or(u32::MAX)
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
        match value.compare_exchange_weak(current, current - 1, Ordering::AcqRel, Ordering::Acquire)
        {
            Ok(_) => return,
            Err(observed) => current = observed,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn receipt(phase: RunPhase) -> RunReceipt {
        RunReceipt {
            run_id: "run.telemetry".to_string(),
            revision: 1,
            phase,
            context_digest: None,
            authority_epoch: 1,
            generation: 2,
            fence_digest: "1".repeat(64),
            deadline_ms: 10_000,
            cancel_reason: None,
            cancel_ack_deadline_ms: None,
            compilation_receipt_digest: None,
            terminal_observed: matches!(
                phase,
                RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed
            ),
            idempotent: false,
        }
    }

    #[test]
    fn worker_timeout_is_visible_while_active_and_after_late_completion() {
        let telemetry = Arc::new(AgentdIntelligenceTelemetryV1::new(4));
        let guard = telemetry.worker_started();
        assert!(guard.state().mark_timed_out());
        assert_eq!(telemetry.snapshot().timed_out_active_workers, 1);
        drop(guard);
        let snapshot = telemetry.snapshot();
        assert_eq!(snapshot.active_workers, 0);
        assert_eq!(snapshot.timed_out_active_workers, 0);
        assert_eq!(snapshot.peak_active_workers, 1);
        assert_eq!(snapshot.late_worker_completions, 1);
        assert_eq!(snapshot.permit_hold_observations, 1);
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

    #[test]
    fn ratios_candidate_counts_and_manifest_age_are_bounded() {
        let telemetry = AgentdIntelligenceTelemetryV1::new(4);
        telemetry.record_ready();
        telemetry.record_abstained();
        telemetry.record_slow_path();
        telemetry.record_candidate_count(3);
        telemetry.record_candidate_count(7);
        telemetry.record_authority_manifest(9, 100, 17);
        let snapshot = telemetry.snapshot_at(125);
        assert_eq!(snapshot.ready_ratio_ppm, 333_333);
        assert_eq!(snapshot.abstained_ratio_ppm, 333_333);
        assert_eq!(snapshot.slow_path_ratio_ppm, 333_333);
        assert_eq!(snapshot.candidate_count_observations, 2);
        assert_eq!(snapshot.candidate_count_total, 10);
        assert_eq!(snapshot.candidate_count_max, 7);
        assert_eq!(snapshot.authority_snapshot_age_ms, Some(25));
        assert_eq!(snapshot.manifest_verification_total_micros, 17);
    }

    #[test]
    fn run_phase_dwell_accumulates_exact_transitions() {
        let telemetry = AgentdIntelligenceTelemetryV1::new(4);
        telemetry.observe_run_receipt(&receipt(RunPhase::Admitted), 100);
        telemetry.observe_run_receipt(&receipt(RunPhase::ContextAttached), 130);
        telemetry.observe_run_receipt(&receipt(RunPhase::Dispatched), 180);
        let snapshot = telemetry
            .run_phase_dwell_snapshot("run.telemetry", 225)
            .expect("run dwell");
        assert_eq!(snapshot.durations[0].elapsed_ms, 30);
        assert_eq!(snapshot.durations[1].elapsed_ms, 50);
        assert_eq!(snapshot.durations[2].elapsed_ms, 45);
        assert!(snapshot.durations[2].current);
    }

    #[test]
    fn same_phase_idempotent_replay_does_not_reset_dwell() {
        let telemetry = AgentdIntelligenceTelemetryV1::new(4);
        telemetry.observe_run_receipt(&receipt(RunPhase::Admitted), 100);
        telemetry.observe_run_receipt(&receipt(RunPhase::Admitted), 120);
        let snapshot = telemetry
            .run_phase_dwell_snapshot("run.telemetry", 150)
            .expect("run dwell");
        assert_eq!(snapshot.current_phase_entered_at_ms, 100);
        assert_eq!(snapshot.durations[0].elapsed_ms, 50);
    }
}
