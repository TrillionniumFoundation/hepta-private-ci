use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static REQUESTS: AtomicU64 = AtomicU64::new(0);
static SELECTED_ITEMS: AtomicU64 = AtomicU64::new(0);
static MISSING_IDS: AtomicU64 = AtomicU64::new(0);
static PAYLOAD_BYTES: AtomicU64 = AtomicU64::new(0);
static TOTAL_BYTES: AtomicU64 = AtomicU64::new(0);
static BUDGET_REJECTIONS: AtomicU64 = AtomicU64::new(0);
static REVALIDATION_FAILURES: AtomicU64 = AtomicU64::new(0);
static STALE_CUT_REJECTIONS: AtomicU64 = AtomicU64::new(0);
static LATENCY_MICROS: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) struct CognitiveContextMetricsSnapshot {
    pub requests: u64,
    pub selected_items: u64,
    pub missing_ids: u64,
    pub payload_bytes: u64,
    pub total_bytes: u64,
    pub budget_rejections: u64,
    pub revalidation_failures: u64,
    pub stale_cut_rejections: u64,
    pub latency_micros: u64,
}

pub(crate) fn record_request() {
    REQUESTS.fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn record_read(payload_bytes: usize, total_bytes: usize, missing_ids: usize) {
    PAYLOAD_BYTES.fetch_add(payload_bytes as u64, Ordering::Relaxed);
    TOTAL_BYTES.fetch_add(total_bytes as u64, Ordering::Relaxed);
    MISSING_IDS.fetch_add(missing_ids as u64, Ordering::Relaxed);
}

pub(crate) fn record_selected(count: usize) {
    SELECTED_ITEMS.fetch_add(count as u64, Ordering::Relaxed);
}

pub(crate) fn record_budget_rejection() {
    BUDGET_REJECTIONS.fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn record_revalidation_failure(reason: &'static str) {
    REVALIDATION_FAILURES.fetch_add(1, Ordering::Relaxed);
    tracing::warn!(
        target: "hepta.cognitive_read",
        event = "cognitive_context_revalidation_failure",
        reason,
        "cognitive context candidate failed final-use revalidation"
    );
}

pub(crate) fn record_stale_cut_rejection() {
    STALE_CUT_REJECTIONS.fetch_add(1, Ordering::Relaxed);
    tracing::warn!(
        target: "hepta.cognitive_read",
        event = "cognitive_context_stale_cut",
        "cognitive context source cut changed before publication"
    );
}

pub(crate) fn record_latency(micros: u128) {
    LATENCY_MICROS.fetch_add(u64::try_from(micros).unwrap_or(u64::MAX), Ordering::Relaxed);
}

#[cfg(test)]
pub(crate) fn snapshot() -> CognitiveContextMetricsSnapshot {
    CognitiveContextMetricsSnapshot {
        requests: REQUESTS.load(Ordering::Relaxed),
        selected_items: SELECTED_ITEMS.load(Ordering::Relaxed),
        missing_ids: MISSING_IDS.load(Ordering::Relaxed),
        payload_bytes: PAYLOAD_BYTES.load(Ordering::Relaxed),
        total_bytes: TOTAL_BYTES.load(Ordering::Relaxed),
        budget_rejections: BUDGET_REJECTIONS.load(Ordering::Relaxed),
        revalidation_failures: REVALIDATION_FAILURES.load(Ordering::Relaxed),
        stale_cut_rejections: STALE_CUT_REJECTIONS.load(Ordering::Relaxed),
        latency_micros: LATENCY_MICROS.load(Ordering::Relaxed),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counters_are_monotone_and_low_cardinality() {
        let before = snapshot();
        record_request();
        record_read(11, 43, 2);
        record_selected(3);
        record_budget_rejection();
        record_revalidation_failure("candidate_not_current");
        record_stale_cut_rejection();
        record_latency(7);
        let after = snapshot();

        assert!(after.requests >= before.requests + 1);
        assert!(after.payload_bytes >= before.payload_bytes + 11);
        assert!(after.total_bytes >= before.total_bytes + 43);
        assert!(after.missing_ids >= before.missing_ids + 2);
        assert!(after.selected_items >= before.selected_items + 3);
        assert!(after.budget_rejections >= before.budget_rejections + 1);
        assert!(after.revalidation_failures >= before.revalidation_failures + 1);
        assert!(after.stale_cut_rejections >= before.stale_cut_rejections + 1);
        assert!(after.latency_micros >= before.latency_micros + 7);
    }
}
