//! Bounded in-process observability for the hosted App Server profile.
//!
//! These counters are operational signals, not durable execution truth. Exact
//! request state remains in `DurableInferenceControl`; operators must reconcile
//! snapshots with the journal after restart.

use std::collections::btree_map::Entry;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct NativeMetricsSnapshot {
    pub indeterminate_total: u64,
    pub indeterminate_current: usize,
    pub oldest_indeterminate_age_ms: Option<u64>,
    pub held_reservations: usize,
    pub reconciliation_attempts: u64,
    pub reconciliation_successes: u64,
    pub reconciliation_failures: u64,
    pub missing_usage_total: u64,
    pub missing_usage_current: usize,
    pub authority_denials: u64,
    pub cancellation_to_interrupt_last_micros: Option<u64>,
    pub journal_capacity_rejections: u64,
    pub provider_receipt_resolutions: u64,
}

#[derive(Default)]
struct LiveState {
    indeterminate_since_ms: BTreeMap<String, u64>,
    missing_usage_requests: BTreeSet<String>,
}

#[derive(Default)]
struct NativeMetrics {
    indeterminate_total: AtomicU64,
    reconciliation_attempts: AtomicU64,
    reconciliation_successes: AtomicU64,
    reconciliation_failures: AtomicU64,
    missing_usage_total: AtomicU64,
    authority_denials: AtomicU64,
    cancellation_to_interrupt_last_micros: AtomicU64,
    journal_capacity_rejections: AtomicU64,
    provider_receipt_resolutions: AtomicU64,
    live: Mutex<LiveState>,
}

static METRICS: OnceLock<NativeMetrics> = OnceLock::new();

fn metrics() -> &'static NativeMetrics {
    METRICS.get_or_init(NativeMetrics::default)
}

pub fn native_metrics_snapshot() -> NativeMetricsSnapshot {
    let now_ms = wall_clock_ms();
    let live = metrics()
        .live
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let oldest_indeterminate_age_ms = live
        .indeterminate_since_ms
        .values()
        .min()
        .map(|first_seen| now_ms.saturating_sub(*first_seen));
    let interrupt = metrics()
        .cancellation_to_interrupt_last_micros
        .load(Ordering::Relaxed);
    NativeMetricsSnapshot {
        indeterminate_total: metrics().indeterminate_total.load(Ordering::Relaxed),
        indeterminate_current: live.indeterminate_since_ms.len(),
        oldest_indeterminate_age_ms,
        held_reservations: live.indeterminate_since_ms.len(),
        reconciliation_attempts: metrics().reconciliation_attempts.load(Ordering::Relaxed),
        reconciliation_successes: metrics().reconciliation_successes.load(Ordering::Relaxed),
        reconciliation_failures: metrics().reconciliation_failures.load(Ordering::Relaxed),
        missing_usage_total: metrics().missing_usage_total.load(Ordering::Relaxed),
        missing_usage_current: live.missing_usage_requests.len(),
        authority_denials: metrics().authority_denials.load(Ordering::Relaxed),
        cancellation_to_interrupt_last_micros: (interrupt != 0).then_some(interrupt),
        journal_capacity_rejections: metrics()
            .journal_capacity_rejections
            .load(Ordering::Relaxed),
        provider_receipt_resolutions: metrics()
            .provider_receipt_resolutions
            .load(Ordering::Relaxed),
    }
}

pub(crate) fn record_indeterminate(request_id: &str) {
    let mut live = metrics()
        .live
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if let Entry::Vacant(entry) = live.indeterminate_since_ms.entry(request_id.to_string()) {
        entry.insert(wall_clock_ms());
        metrics()
            .indeterminate_total
            .fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn record_terminal(request_id: &str, usage_known: bool) {
    let mut live = metrics()
        .live
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    live.indeterminate_since_ms.remove(request_id);
    if usage_known {
        live.missing_usage_requests.remove(request_id);
    } else if live.missing_usage_requests.insert(request_id.to_string()) {
        metrics()
            .missing_usage_total
            .fetch_add(1, Ordering::Relaxed);
    }
}

pub(crate) fn record_reconciliation_attempt() {
    metrics()
        .reconciliation_attempts
        .fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn record_reconciliation_success() {
    metrics()
        .reconciliation_successes
        .fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn record_reconciliation_failure() {
    metrics()
        .reconciliation_failures
        .fetch_add(1, Ordering::Relaxed);
}

pub(crate) fn record_provider_receipt_resolution() {
    metrics()
        .provider_receipt_resolutions
        .fetch_add(1, Ordering::Relaxed);
}

/// Record an explicit denial returned by the independently operated final-use
/// authority endpoint.
pub fn record_authority_denial() {
    metrics().authority_denials.fetch_add(1, Ordering::Relaxed);
}

/// Record observed delay from cancellation intent to the interrupt RPC entry.
pub fn record_cancellation_to_interrupt_latency(micros: u64) {
    metrics()
        .cancellation_to_interrupt_last_micros
        .store(micros.max(1), Ordering::Relaxed);
}

/// Record a control-journal capacity refusal. The refusal itself remains the
/// authoritative result returned by the journal owner.
pub fn record_journal_capacity_rejection() {
    metrics()
        .journal_capacity_rejections
        .fetch_add(1, Ordering::Relaxed);
}

fn wall_clock_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_distinguishes_held_unknown_from_terminal_missing_usage() {
        let request = format!("metrics-test-{}", wall_clock_ms());
        let before = native_metrics_snapshot();
        record_indeterminate(&request);
        let unknown = native_metrics_snapshot();
        assert_eq!(unknown.indeterminate_current, before.indeterminate_current + 1);
        record_terminal(&request, false);
        let terminal = native_metrics_snapshot();
        assert_eq!(terminal.indeterminate_current, before.indeterminate_current);
        assert!(terminal.missing_usage_current >= before.missing_usage_current + 1);
        record_terminal(&request, true);
    }
}
