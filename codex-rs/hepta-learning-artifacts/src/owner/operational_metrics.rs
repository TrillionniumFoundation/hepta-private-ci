//! Bounded, non-authoritative operational observations for the artifact owner.
//!
//! These metrics explain why work is blocked and where time is spent. They do
//! not grant publication, activation, retention or erasure authority.

use std::collections::BTreeMap;
use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::StableId;

const MAX_STAGE_SAMPLES: usize = 256;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ArtifactOwnerStageV1 {
    StartupRecoveryScan,
    RequestIdentityAndPayloadHash,
    RecoveryReconciliation,
    PayloadWriteAndSync,
    RegistrySnapshotAndSync,
    CurrentSwitchAndSync,
    CheckpointPersist,
    PinnedAcquire,
}

impl ArtifactOwnerStageV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::StartupRecoveryScan => "startup_recovery_scan",
            Self::RequestIdentityAndPayloadHash => "request_identity_and_payload_hash",
            Self::RecoveryReconciliation => "recovery_reconciliation",
            Self::PayloadWriteAndSync => "payload_write_and_sync",
            Self::RegistrySnapshotAndSync => "registry_snapshot_and_sync",
            Self::CurrentSwitchAndSync => "current_switch_and_sync",
            Self::CheckpointPersist => "checkpoint_persist",
            Self::PinnedAcquire => "pinned_acquire",
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ArtifactOwnerBlockReasonV1 {
    IdentityConflict,
    StaleOwner,
    WithdrawalFrontierInsufficient,
    PersistenceUnknown,
    CapacityExceeded,
    RecoveryRequired,
    Draining,
    WriterBusy,
}

impl ArtifactOwnerBlockReasonV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::IdentityConflict => "identity_conflict",
            Self::StaleOwner => "stale_owner",
            Self::WithdrawalFrontierInsufficient => "withdrawal_frontier_insufficient",
            Self::PersistenceUnknown => "persistence_unknown",
            Self::CapacityExceeded => "capacity_exceeded",
            Self::RecoveryRequired => "recovery_required",
            Self::Draining => "draining",
            Self::WriterBusy => "writer_busy",
        }
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactOwnerStageSummaryV1 {
    pub count: u64,
    pub total_micros: u128,
    pub last_micros: u64,
    pub max_micros: u64,
    pub p50_micros: u64,
    pub p95_micros: u64,
    pub p99_micros: u64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct ArtifactOwnerOperationalSnapshotV1 {
    pub recovery_operation_id: Option<StableId>,
    pub oldest_pending_attempt_age_ms: Option<u64>,
    pub withdrawal_blocked_count: u64,
    pub withdrawal_blocked_duration_ms: Option<u64>,
    pub drain_duration_ms: Option<u64>,
    pub recovery_reconciliation_failures: u64,
    pub pinned_bytes: u64,
    pub pending_physical_erase_bytes: u64,
    pub owner_epoch_conflicts: u64,
    pub withdrawal_epoch_conflicts: u64,
    pub block_counts: BTreeMap<ArtifactOwnerBlockReasonV1, u64>,
    pub stages: BTreeMap<ArtifactOwnerStageV1, ArtifactOwnerStageSummaryV1>,
}

#[derive(Debug, Default)]
struct StageAccumulator {
    count: u64,
    total_micros: u128,
    last_micros: u64,
    max_micros: u64,
    samples: VecDeque<u64>,
}

impl StageAccumulator {
    fn record(&mut self, micros: u64) {
        self.count = self.count.saturating_add(1);
        self.total_micros = self.total_micros.saturating_add(u128::from(micros));
        self.last_micros = micros;
        self.max_micros = self.max_micros.max(micros);
        if self.samples.len() == MAX_STAGE_SAMPLES {
            self.samples.pop_front();
        }
        self.samples.push_back(micros);
    }

    fn summary(&self) -> ArtifactOwnerStageSummaryV1 {
        let mut ordered = self.samples.iter().copied().collect::<Vec<_>>();
        ordered.sort_unstable();
        ArtifactOwnerStageSummaryV1 {
            count: self.count,
            total_micros: self.total_micros,
            last_micros: self.last_micros,
            max_micros: self.max_micros,
            p50_micros: percentile(&ordered, 50),
            p95_micros: percentile(&ordered, 95),
            p99_micros: percentile(&ordered, 99),
        }
    }
}

fn percentile(ordered: &[u64], percentile: usize) -> u64 {
    if ordered.is_empty() {
        return 0;
    }
    let index = (ordered.len() - 1).saturating_mul(percentile) / 100;
    ordered[index]
}

#[derive(Debug, Default)]
struct OperationalState {
    recovery_operation_id: Option<StableId>,
    recovery_observed_since: Option<Instant>,
    withdrawal_blocked_since: Option<Instant>,
    drain_started_at: Option<Instant>,
    withdrawal_blocked_count: u64,
    recovery_reconciliation_failures: u64,
    pinned_bytes: u64,
    pending_physical_erase_bytes: u64,
    owner_epoch_conflicts: u64,
    withdrawal_epoch_conflicts: u64,
    block_counts: BTreeMap<ArtifactOwnerBlockReasonV1, u64>,
    stages: BTreeMap<ArtifactOwnerStageV1, StageAccumulator>,
}

#[derive(Clone, Debug, Default)]
pub struct ArtifactOwnerOperationalMetricsV1 {
    state: Arc<Mutex<OperationalState>>,
}

impl ArtifactOwnerOperationalMetricsV1 {
    pub(crate) fn start_stage(&self, stage: ArtifactOwnerStageV1) -> ArtifactOwnerStageTimerV1 {
        ArtifactOwnerStageTimerV1 {
            metrics: self.clone(),
            stage,
            started: Instant::now(),
        }
    }

    pub(crate) fn record_stage_micros(&self, stage: ArtifactOwnerStageV1, micros: u64) {
        self.with_state(|state| state.stages.entry(stage).or_default().record(micros));
    }

    pub(crate) fn mark_recovery_required(&self, operation_id: StableId) {
        self.with_state(|state| {
            if state.recovery_operation_id.as_ref() != Some(&operation_id) {
                state.recovery_observed_since = Some(Instant::now());
            }
            state.recovery_operation_id = Some(operation_id);
            increment(&mut state.block_counts, ArtifactOwnerBlockReasonV1::RecoveryRequired);
        });
    }

    pub(crate) fn clear_recovery_required(&self) {
        self.with_state(|state| {
            state.recovery_operation_id = None;
            state.recovery_observed_since = None;
        });
    }

    pub(crate) fn record_recovery_failure(&self) {
        self.with_state(|state| {
            state.recovery_reconciliation_failures =
                state.recovery_reconciliation_failures.saturating_add(1);
        });
    }

    pub(crate) fn mark_withdrawal_block(&self) {
        self.with_state(|state| {
            state.withdrawal_blocked_count = state.withdrawal_blocked_count.saturating_add(1);
            state.withdrawal_blocked_since.get_or_insert_with(Instant::now);
        });
    }

    pub(crate) fn clear_withdrawal_block(&self) {
        self.with_state(|state| state.withdrawal_blocked_since = None);
    }

    pub(crate) fn begin_drain(&self) {
        self.with_state(|state| {
            state.drain_started_at.get_or_insert_with(Instant::now);
            increment(&mut state.block_counts, ArtifactOwnerBlockReasonV1::Draining);
        });
    }

    pub(crate) fn record_block(&self, reason: ArtifactOwnerBlockReasonV1) {
        self.with_state(|state| increment(&mut state.block_counts, reason));
    }

    pub(crate) fn record_owner_epoch_conflict(&self) {
        self.with_state(|state| {
            state.owner_epoch_conflicts = state.owner_epoch_conflicts.saturating_add(1);
        });
    }

    pub(crate) fn record_withdrawal_epoch_conflict(&self) {
        self.with_state(|state| {
            state.withdrawal_epoch_conflicts = state.withdrawal_epoch_conflicts.saturating_add(1);
        });
    }

    /// Observability only. The authoritative reader owner supplies this gauge.
    pub fn set_pinned_bytes(&self, bytes: u64) {
        self.with_state(|state| state.pinned_bytes = bytes);
    }

    /// Observability only. The authoritative erasure owner supplies this gauge.
    pub fn set_pending_physical_erase_bytes(&self, bytes: u64) {
        self.with_state(|state| state.pending_physical_erase_bytes = bytes);
    }

    #[must_use]
    pub fn snapshot(&self) -> ArtifactOwnerOperationalSnapshotV1 {
        self.with_state(|state| ArtifactOwnerOperationalSnapshotV1 {
            recovery_operation_id: state.recovery_operation_id.clone(),
            oldest_pending_attempt_age_ms: state.recovery_observed_since.map(elapsed_ms),
            withdrawal_blocked_count: state.withdrawal_blocked_count,
            withdrawal_blocked_duration_ms: state.withdrawal_blocked_since.map(elapsed_ms),
            drain_duration_ms: state.drain_started_at.map(elapsed_ms),
            recovery_reconciliation_failures: state.recovery_reconciliation_failures,
            pinned_bytes: state.pinned_bytes,
            pending_physical_erase_bytes: state.pending_physical_erase_bytes,
            owner_epoch_conflicts: state.owner_epoch_conflicts,
            withdrawal_epoch_conflicts: state.withdrawal_epoch_conflicts,
            block_counts: state.block_counts.clone(),
            stages: state
                .stages
                .iter()
                .map(|(stage, value)| (*stage, value.summary()))
                .collect(),
        })
    }

    fn with_state<T>(&self, action: impl FnOnce(&mut OperationalState) -> T) -> T {
        let mut guard = self.state.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
        action(&mut guard)
    }
}

fn increment<K: Ord>(counts: &mut BTreeMap<K, u64>, key: K) {
    counts
        .entry(key)
        .and_modify(|value| *value = value.saturating_add(1))
        .or_insert(1);
}

fn elapsed_ms(started: Instant) -> u64 {
    duration_ms(started.elapsed())
}

fn duration_ms(duration: Duration) -> u64 {
    u64::try_from(duration.as_millis()).unwrap_or(u64::MAX)
}

pub(crate) struct ArtifactOwnerStageTimerV1 {
    metrics: ArtifactOwnerOperationalMetricsV1,
    stage: ArtifactOwnerStageV1,
    started: Instant,
}

impl Drop for ArtifactOwnerStageTimerV1 {
    fn drop(&mut self) {
        let micros = u64::try_from(self.started.elapsed().as_micros()).unwrap_or(u64::MAX);
        self.metrics.record_stage_micros(self.stage, micros);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("valid fixture id")
    }

    #[test]
    fn stage_samples_are_bounded_while_lifetime_counts_remain_exact() {
        let metrics = ArtifactOwnerOperationalMetricsV1::default();
        for value in 1..=300 {
            metrics.record_stage_micros(ArtifactOwnerStageV1::PayloadWriteAndSync, value);
        }
        let summary = metrics.snapshot().stages[&ArtifactOwnerStageV1::PayloadWriteAndSync];
        assert_eq!(summary.count, 300);
        assert_eq!(summary.max_micros, 300);
        assert!(summary.p50_micros >= 45);
        assert!(summary.p99_micros <= 300);
    }

    #[test]
    fn blockers_and_resource_gauges_answer_actionable_questions() {
        let metrics = ArtifactOwnerOperationalMetricsV1::default();
        metrics.mark_recovery_required(id("operation"));
        metrics.mark_withdrawal_block();
        metrics.begin_drain();
        metrics.record_recovery_failure();
        metrics.record_owner_epoch_conflict();
        metrics.record_withdrawal_epoch_conflict();
        metrics.set_pinned_bytes(41);
        metrics.set_pending_physical_erase_bytes(17);
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.recovery_operation_id, Some(id("operation")));
        assert_eq!(snapshot.withdrawal_blocked_count, 1);
        assert_eq!(snapshot.recovery_reconciliation_failures, 1);
        assert_eq!(snapshot.pinned_bytes, 41);
        assert_eq!(snapshot.pending_physical_erase_bytes, 17);
        assert_eq!(snapshot.owner_epoch_conflicts, 1);
        assert_eq!(snapshot.withdrawal_epoch_conflicts, 1);
        metrics.clear_recovery_required();
        metrics.clear_withdrawal_block();
        assert!(metrics.snapshot().recovery_operation_id.is_none());
        assert!(metrics.snapshot().withdrawal_blocked_duration_ms.is_none());
    }
}
