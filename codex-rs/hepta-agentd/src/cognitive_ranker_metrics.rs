//! Actionable read-path telemetry for the immutable cognitive ranker.

use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

#[derive(Default)]
pub(super) struct CognitiveRankerMetrics {
    exact_query_requests: AtomicU64,
    requested_items: AtomicU64,
    supported_items: AtomicU64,
    whole_batch_abstains: AtomicU64,
    ranking_applied: AtomicU64,
    registry_revalidation_count: AtomicU64,
    registry_revalidation_total_nanos: AtomicU64,
    registry_revalidation_max_nanos: AtomicU64,
    terminal_close_count: AtomicU64,
    revised_item_abstains: AtomicU64,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CognitiveRankerMetricsSnapshotV1 {
    pub exact_query_requests: u64,
    pub requested_items: u64,
    pub supported_items: u64,
    pub whole_batch_abstains: u64,
    pub ranking_applied: u64,
    pub registry_revalidation_count: u64,
    pub registry_revalidation_total_nanos: u64,
    pub registry_revalidation_max_nanos: u64,
    pub terminal_close_count: u64,
    pub revised_item_abstains: u64,
}

impl CognitiveRankerMetrics {
    pub(super) fn begin_rank(&self, items: usize) {
        self.exact_query_requests.fetch_add(1, Ordering::Relaxed);
        self.requested_items.fetch_add(
            u64::try_from(items).unwrap_or(u64::MAX),
            Ordering::Relaxed,
        );
    }

    pub(super) fn supported_item(&self) {
        self.supported_items.fetch_add(1, Ordering::Relaxed);
    }

    pub(super) fn abstained(&self, revised: bool) {
        self.whole_batch_abstains.fetch_add(1, Ordering::Relaxed);
        if revised {
            self.revised_item_abstains.fetch_add(1, Ordering::Relaxed);
        }
    }

    pub(super) fn applied(&self) {
        self.ranking_applied.fetch_add(1, Ordering::Relaxed);
    }

    pub(super) fn revalidated(&self, elapsed: Duration) {
        let nanos = u64::try_from(elapsed.as_nanos()).unwrap_or(u64::MAX);
        self.registry_revalidation_count
            .fetch_add(1, Ordering::Relaxed);
        self.registry_revalidation_total_nanos
            .fetch_add(nanos, Ordering::Relaxed);
        self.registry_revalidation_max_nanos
            .fetch_max(nanos, Ordering::Relaxed);
    }

    pub(super) fn terminal_close(&self) {
        self.terminal_close_count.fetch_add(1, Ordering::Relaxed);
    }

    pub(super) fn snapshot(&self) -> CognitiveRankerMetricsSnapshotV1 {
        CognitiveRankerMetricsSnapshotV1 {
            exact_query_requests: self.exact_query_requests.load(Ordering::Relaxed),
            requested_items: self.requested_items.load(Ordering::Relaxed),
            supported_items: self.supported_items.load(Ordering::Relaxed),
            whole_batch_abstains: self.whole_batch_abstains.load(Ordering::Relaxed),
            ranking_applied: self.ranking_applied.load(Ordering::Relaxed),
            registry_revalidation_count: self
                .registry_revalidation_count
                .load(Ordering::Relaxed),
            registry_revalidation_total_nanos: self
                .registry_revalidation_total_nanos
                .load(Ordering::Relaxed),
            registry_revalidation_max_nanos: self
                .registry_revalidation_max_nanos
                .load(Ordering::Relaxed),
            terminal_close_count: self.terminal_close_count.load(Ordering::Relaxed),
            revised_item_abstains: self.revised_item_abstains.load(Ordering::Relaxed),
        }
    }
}
