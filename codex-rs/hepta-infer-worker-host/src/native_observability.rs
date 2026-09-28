use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[derive(Debug, Default)]
pub struct NativeWorkerMetrics {
    indeterminate_count: AtomicU64,
    oldest_indeterminate_started_ms: AtomicU64,
    held_reservations: AtomicU64,
    reconcile_attempts: AtomicU64,
    reconcile_successes: AtomicU64,
    reconcile_failures: AtomicU64,
    missing_usage: AtomicU64,
    authority_denials: AtomicU64,
    cancellation_latency_total_micros: AtomicU64,
    cancellation_latency_count: AtomicU64,
    cancellation_latency_max_micros: AtomicU64,
    journal_capacity_rejections: AtomicU64,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct NativeWorkerMetricsSnapshot {
    pub indeterminate_count: u64,
    pub oldest_indeterminate_started_ms: Option<u64>,
    pub held_reservations: u64,
    pub reconcile_attempts: u64,
    pub reconcile_successes: u64,
    pub reconcile_failures: u64,
    pub missing_usage: u64,
    pub authority_denials: u64,
    pub cancellation_latency_count: u64,
    pub cancellation_latency_total_micros: u64,
    pub cancellation_latency_max_micros: u64,
    pub journal_capacity_rejections: u64,
}

impl NativeWorkerMetrics {
    pub fn record_indeterminate(&self, started_ms: u64) {
        self.indeterminate_count.fetch_add(1, Ordering::Relaxed);
        self.held_reservations.fetch_add(1, Ordering::Relaxed);
        let _ = self.oldest_indeterminate_started_ms.fetch_update(
            Ordering::Relaxed,
            Ordering::Relaxed,
            |current| {
                if current == 0 || started_ms < current {
                    Some(started_ms)
                } else {
                    None
                }
            },
        );
    }

    pub fn record_indeterminate_resolved(&self) {
        decrement_nonzero(&self.indeterminate_count);
        decrement_nonzero(&self.held_reservations);
        if self.indeterminate_count.load(Ordering::Relaxed) == 0 {
            self.oldest_indeterminate_started_ms
                .store(0, Ordering::Relaxed);
        }
    }

    pub fn record_reconcile_attempt(&self) {
        self.reconcile_attempts.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_reconcile_success(&self) {
        self.reconcile_successes.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_reconcile_failure(&self) {
        self.reconcile_failures.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_missing_usage(&self) {
        self.missing_usage.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_authority_denial(&self) {
        self.authority_denials.fetch_add(1, Ordering::Relaxed);
    }

    pub fn record_cancellation_latency(&self, latency_micros: u64) {
        self.cancellation_latency_total_micros
            .fetch_add(latency_micros, Ordering::Relaxed);
        self.cancellation_latency_count
            .fetch_add(1, Ordering::Relaxed);
        self.cancellation_latency_max_micros
            .fetch_max(latency_micros, Ordering::Relaxed);
    }

    pub fn record_journal_capacity_rejection(&self) {
        self.journal_capacity_rejections
            .fetch_add(1, Ordering::Relaxed);
    }

    pub fn snapshot(&self) -> NativeWorkerMetricsSnapshot {
        let oldest = self
            .oldest_indeterminate_started_ms
            .load(Ordering::Relaxed);
        NativeWorkerMetricsSnapshot {
            indeterminate_count: self.indeterminate_count.load(Ordering::Relaxed),
            oldest_indeterminate_started_ms: (oldest != 0).then_some(oldest),
            held_reservations: self.held_reservations.load(Ordering::Relaxed),
            reconcile_attempts: self.reconcile_attempts.load(Ordering::Relaxed),
            reconcile_successes: self.reconcile_successes.load(Ordering::Relaxed),
            reconcile_failures: self.reconcile_failures.load(Ordering::Relaxed),
            missing_usage: self.missing_usage.load(Ordering::Relaxed),
            authority_denials: self.authority_denials.load(Ordering::Relaxed),
            cancellation_latency_count: self
                .cancellation_latency_count
                .load(Ordering::Relaxed),
            cancellation_latency_total_micros: self
                .cancellation_latency_total_micros
                .load(Ordering::Relaxed),
            cancellation_latency_max_micros: self
                .cancellation_latency_max_micros
                .load(Ordering::Relaxed),
            journal_capacity_rejections: self
                .journal_capacity_rejections
                .load(Ordering::Relaxed),
        }
    }
}

fn decrement_nonzero(value: &AtomicU64) {
    let _ = value.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
        current.checked_sub(1)
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_tracks_actionable_recovery_state() {
        let metrics = NativeWorkerMetrics::default();
        metrics.record_indeterminate(200);
        metrics.record_indeterminate(100);
        metrics.record_reconcile_attempt();
        metrics.record_reconcile_success();
        metrics.record_missing_usage();
        metrics.record_authority_denial();
        metrics.record_cancellation_latency(7);
        metrics.record_cancellation_latency(11);
        metrics.record_journal_capacity_rejection();
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.indeterminate_count, 2);
        assert_eq!(snapshot.oldest_indeterminate_started_ms, Some(100));
        assert_eq!(snapshot.held_reservations, 2);
        assert_eq!(snapshot.reconcile_attempts, 1);
        assert_eq!(snapshot.reconcile_successes, 1);
        assert_eq!(snapshot.missing_usage, 1);
        assert_eq!(snapshot.authority_denials, 1);
        assert_eq!(snapshot.cancellation_latency_count, 2);
        assert_eq!(snapshot.cancellation_latency_total_micros, 18);
        assert_eq!(snapshot.cancellation_latency_max_micros, 11);
        assert_eq!(snapshot.journal_capacity_rejections, 1);
        metrics.record_indeterminate_resolved();
        metrics.record_indeterminate_resolved();
        assert_eq!(metrics.snapshot().oldest_indeterminate_started_ms, None);
    }
}
