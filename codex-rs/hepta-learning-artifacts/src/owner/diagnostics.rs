//! Bounded process-local observations, never an authority or durability receipt.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

/// Aggregate timings from actual owner calls, including unsuccessful calls.
/// These are not percentile estimates or target-host SLO qualification.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ArtifactPhaseTimingV1 {
    pub calls: u64,
    pub failures: u64,
    pub total_microseconds: u64,
    pub maximum_microseconds: u64,
}

impl ArtifactPhaseTimingV1 {
    fn record(&mut self, elapsed: Duration, failed: bool) {
        let micros = u64::try_from(elapsed.as_micros()).unwrap_or(u64::MAX);
        self.calls = self.calls.saturating_add(1);
        self.failures = self.failures.saturating_add(u64::from(failed));
        self.total_microseconds = self.total_microseconds.saturating_add(micros);
        self.maximum_microseconds = self.maximum_microseconds.max(micros);
    }
}

/// Measurements are bounded to this fixed set; caller-provided labels cannot
/// create unbounded metric cardinality. A phase includes its existing checkpoint
/// work where the owner API combines them; it is not a physical fsync timer.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum Phase {
    Open,
    Identity,
    Reconcile,
    Payload,
    Registry,
    Witness,
    Acknowledge,
    Withdrawal,
    Drain,
    Publish,
}

impl Phase {
    const fn index(self) -> usize {
        match self {
            Self::Open => 0,
            Self::Identity => 1,
            Self::Reconcile => 2,
            Self::Payload => 3,
            Self::Registry => 4,
            Self::Witness => 5,
            Self::Acknowledge => 6,
            Self::Withdrawal => 7,
            Self::Drain => 8,
            Self::Publish => 9,
        }
    }
}

/// Stable diagnostic snapshot. Missing measurements are unknown, not zero.
/// Durations refer to observation in this process and do not survive restart.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactOwnerDiagnosticsV1 {
    pub publication_calls: u64,
    pub publication_failures: u64,
    pub identity_conflicts: u64,
    pub withdrawal_conflicts: u64,
    pub withdrawal_blocked_publications: u64,
    pub recovery_reconciliation_failures: u64,
    pub recovery_required: bool,
    pub withdrawal_durability_unknown: bool,
    pub drain_durability_unknown: bool,
    pub draining: bool,
    pub observed_pending_microseconds: Option<u64>,
    pub observed_drain_microseconds: Option<u64>,
    pub observed_withdrawal_block_microseconds: Option<u64>,
    pub pending_predates_process: bool,
    pub drain_predates_process: bool,
    pub last_verified_request_digest: Option<Digest32>,
    pub pinned_bytes: Option<u64>,
    pub pending_physical_erasure_bytes: Option<u64>,
    pub open: ArtifactPhaseTimingV1,
    pub identity: ArtifactPhaseTimingV1,
    pub reconcile: ArtifactPhaseTimingV1,
    pub payload_and_checkpoint: ArtifactPhaseTimingV1,
    pub registry_and_checkpoint: ArtifactPhaseTimingV1,
    pub witness_and_checkpoint: ArtifactPhaseTimingV1,
    pub acknowledgement_checkpoint: ArtifactPhaseTimingV1,
    pub withdrawal_persistence: ArtifactPhaseTimingV1,
    pub drain_persistence: ArtifactPhaseTimingV1,
    pub publish: ArtifactPhaseTimingV1,
}

#[derive(Debug, Default)]
pub(super) struct Observations {
    timings: [ArtifactPhaseTimingV1; 10],
    pub(super) identity_conflicts: u64,
    pub(super) withdrawal_conflicts: u64,
    pub(super) withdrawal_blocked_publications: u64,
    pub(super) recovery_reconciliation_failures: u64,
    pub(super) last_verified_request_digest: Option<Digest32>,
    pending_since: Option<Instant>,
    drain_since: Option<Instant>,
    withdrawal_block_since: Option<Instant>,
    pending_predates_process: bool,
    drain_predates_process: bool,
}

impl Observations {
    pub(super) fn record<T, E>(
        &mut self,
        phase: Phase,
        started: Instant,
        outcome: &Result<T, E>,
    ) {
        self.timings[phase.index()].record(started.elapsed(), outcome.is_err());
        if phase == Phase::Reconcile && outcome.is_err() {
            self.recovery_reconciliation_failures =
                self.recovery_reconciliation_failures.saturating_add(1);
        }
    }

    pub(super) fn restore(&mut self, pending: bool, draining: bool) {
        self.pending_predates_process = pending;
        self.drain_predates_process = draining;
        self.observe_state(pending, draining, false);
    }

    pub(super) fn observe_state(&mut self, pending: bool, draining: bool, withdrawal_block: bool) {
        update_start(&mut self.pending_since, pending);
        update_start(&mut self.drain_since, draining);
        update_start(&mut self.withdrawal_block_since, withdrawal_block);
        if !pending {
            self.pending_predates_process = false;
        }
    }

    pub(super) fn snapshot(
        &self,
        recovery_required: bool,
        withdrawal_durability_unknown: bool,
        drain_durability_unknown: bool,
        draining: bool,
    ) -> ArtifactOwnerDiagnosticsV1 {
        ArtifactOwnerDiagnosticsV1 {
            publication_calls: self.timings[Phase::Publish.index()].calls,
            publication_failures: self.timings[Phase::Publish.index()].failures,
            identity_conflicts: self.identity_conflicts,
            withdrawal_conflicts: self.withdrawal_conflicts,
            withdrawal_blocked_publications: self.withdrawal_blocked_publications,
            recovery_reconciliation_failures: self.recovery_reconciliation_failures,
            recovery_required,
            withdrawal_durability_unknown,
            drain_durability_unknown,
            draining,
            observed_pending_microseconds: elapsed(self.pending_since),
            observed_drain_microseconds: elapsed(self.drain_since),
            observed_withdrawal_block_microseconds: elapsed(self.withdrawal_block_since),
            pending_predates_process: self.pending_predates_process,
            drain_predates_process: self.drain_predates_process,
            last_verified_request_digest: self.last_verified_request_digest,
            // The owner service has no authoritative pin/refcount or erasure
            // observer. Reporting zero would falsely claim measured absence.
            pinned_bytes: None,
            pending_physical_erasure_bytes: None,
            open: self.timings[Phase::Open.index()],
            identity: self.timings[Phase::Identity.index()],
            reconcile: self.timings[Phase::Reconcile.index()],
            payload_and_checkpoint: self.timings[Phase::Payload.index()],
            registry_and_checkpoint: self.timings[Phase::Registry.index()],
            witness_and_checkpoint: self.timings[Phase::Witness.index()],
            acknowledgement_checkpoint: self.timings[Phase::Acknowledge.index()],
            withdrawal_persistence: self.timings[Phase::Withdrawal.index()],
            drain_persistence: self.timings[Phase::Drain.index()],
            publish: self.timings[Phase::Publish.index()],
        }
    }
}

fn update_start(started: &mut Option<Instant>, active: bool) {
    if active {
        started.get_or_insert_with(Instant::now);
    } else {
        *started = None;
    }
}

fn elapsed(started: Option<Instant>) -> Option<u64> {
    started.map(|value| u64::try_from(value.elapsed().as_micros()).unwrap_or(u64::MAX))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn artifact_timing_counts_failures_and_saturates_without_wraparound() {
        let mut timing = ArtifactPhaseTimingV1::default();
        timing.record(Duration::from_micros(7), /*failed*/ false);
        timing.record(Duration::from_micros(11), /*failed*/ true);
        assert_eq!(timing, ArtifactPhaseTimingV1 {
            calls: 2, failures: 1, total_microseconds: 18, maximum_microseconds: 11,
        });
        timing.calls = u64::MAX;
        timing.total_microseconds = u64::MAX;
        timing.record(Duration::from_micros(1), /*failed*/ false);
        assert_eq!(timing.calls, u64::MAX);
        assert_eq!(timing.total_microseconds, u64::MAX);
    }

    #[test]
    fn artifact_observation_distinguishes_restart_age_from_process_observation() {
        let mut observations = Observations::default();
        observations.restore(/*pending*/ true, /*draining*/ true);
        let first = observations.snapshot(/*recovery_required*/ true,
            /*withdrawal_durability_unknown*/ false, /*drain_durability_unknown*/ false,
            /*draining*/ true);
        assert!(first.pending_predates_process);
        assert!(first.drain_predates_process);
        assert!(first.observed_pending_microseconds.is_some());
        assert_eq!(first.pinned_bytes, None);
        assert_eq!(first.pending_physical_erasure_bytes, None);
        observations.observe_state(/*pending*/ false, /*draining*/ true, /*withdrawal_block*/ false);
        let recovered = observations.snapshot(/*recovery_required*/ false,
            /*withdrawal_durability_unknown*/ false, /*drain_durability_unknown*/ false,
            /*draining*/ true);
        assert!(!recovered.pending_predates_process);
        assert_eq!(recovered.observed_pending_microseconds, None);
    }
}
