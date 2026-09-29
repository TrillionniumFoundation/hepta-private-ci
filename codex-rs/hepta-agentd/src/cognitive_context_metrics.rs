use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub(crate) const REVALIDATION_ALERT_THRESHOLD_PER_MINUTE: u64 = 3;
pub(crate) const REVALIDATION_ALERT_WINDOW_SECONDS: u64 = 60;

const ALERT_COUNT_MASK: u64 = 0xffff_ffff;
const REQUESTS_METRIC: &str = "codex.hepta.cognitive_read.requests";
const SELECTED_ITEMS_METRIC: &str = "codex.hepta.cognitive_read.selected_items";
const MISSING_IDS_METRIC: &str = "codex.hepta.cognitive_read.missing_ids";
const PAYLOAD_BYTES_METRIC: &str = "codex.hepta.cognitive_read.payload_bytes";
const TOTAL_BYTES_METRIC: &str = "codex.hepta.cognitive_read.total_bytes";
const BUDGET_REJECTIONS_METRIC: &str = "codex.hepta.cognitive_read.budget_rejections";
const REVALIDATION_FAILURES_METRIC: &str = "codex.hepta.cognitive_read.revalidation_failures";
const STALE_CUT_REJECTIONS_METRIC: &str = "codex.hepta.cognitive_read.stale_cut_rejections";
const REVALIDATION_ALERTS_METRIC: &str = "codex.hepta.cognitive_read.revalidation_alerts";
const LATENCY_MICROS_METRIC: &str = "codex.hepta.cognitive_read.latency_us";

static REQUESTS: AtomicU64 = AtomicU64::new(0);
static SELECTED_ITEMS: AtomicU64 = AtomicU64::new(0);
static MISSING_IDS: AtomicU64 = AtomicU64::new(0);
static PAYLOAD_BYTES: AtomicU64 = AtomicU64::new(0);
static TOTAL_BYTES: AtomicU64 = AtomicU64::new(0);
static BUDGET_REJECTIONS: AtomicU64 = AtomicU64::new(0);
static REVALIDATION_FAILURES: AtomicU64 = AtomicU64::new(0);
static STALE_CUT_REJECTIONS: AtomicU64 = AtomicU64::new(0);
static REVALIDATION_ALERTS: AtomicU64 = AtomicU64::new(0);
static REVALIDATION_WINDOW_STATE: AtomicU64 = AtomicU64::new(0);
static LATENCY_MICROS: AtomicU64 = AtomicU64::new(0);

#[cfg(test)]
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
    pub revalidation_alerts: u64,
    pub latency_micros: u64,
}

pub(crate) fn record_request() {
    saturating_add(&REQUESTS, 1);
    emit_counter(REQUESTS_METRIC, 1, &[]);
}

pub(crate) fn record_read(payload_bytes: usize, total_bytes: usize, missing_ids: usize) {
    let payload_bytes = saturating_u64(payload_bytes);
    let total_bytes = saturating_u64(total_bytes);
    let missing_ids = saturating_u64(missing_ids);
    saturating_add(&PAYLOAD_BYTES, payload_bytes);
    saturating_add(&TOTAL_BYTES, total_bytes);
    saturating_add(&MISSING_IDS, missing_ids);
    emit_histogram(PAYLOAD_BYTES_METRIC, payload_bytes, &[]);
    emit_histogram(TOTAL_BYTES_METRIC, total_bytes, &[]);
    emit_counter(MISSING_IDS_METRIC, missing_ids, &[]);
}

pub(crate) fn record_selected(count: usize) {
    let count = saturating_u64(count);
    saturating_add(&SELECTED_ITEMS, count);
    emit_counter(SELECTED_ITEMS_METRIC, count, &[]);
}

pub(crate) fn record_budget_rejection() {
    saturating_add(&BUDGET_REJECTIONS, 1);
    emit_counter(BUDGET_REJECTIONS_METRIC, 1, &[]);
}

pub(crate) fn record_revalidation_failure(reason: &'static str) {
    saturating_add(&REVALIDATION_FAILURES, 1);
    emit_counter(REVALIDATION_FAILURES_METRIC, 1, &[("reason", reason)]);
    tracing::warn!(
        target: "hepta.cognitive_read",
        event = "cognitive_context_revalidation_failure",
        reason,
        "cognitive context candidate failed final-use revalidation"
    );
    record_windowed_revalidation_alert(reason);
}

pub(crate) fn record_stale_cut_rejection() {
    saturating_add(&STALE_CUT_REJECTIONS, 1);
    emit_counter(STALE_CUT_REJECTIONS_METRIC, 1, &[]);
    tracing::warn!(
        target: "hepta.cognitive_read",
        event = "cognitive_context_stale_cut",
        "cognitive context source cut changed before publication"
    );
    record_windowed_revalidation_alert("stale_source_cut");
}

pub(crate) fn record_latency(micros: u128) {
    let micros = u64::try_from(micros).unwrap_or(u64::MAX);
    saturating_add(&LATENCY_MICROS, micros);
    emit_histogram(LATENCY_MICROS_METRIC, micros, &[]);
}

fn emit_counter(name: &str, value: u64, tags: &[(&str, &str)]) {
    if value == 0 {
        return;
    }
    if let Some(metrics) = codex_otel::global() {
        let _ = metrics.counter(name, saturating_i64(value), tags);
    }
}

fn emit_histogram(name: &str, value: u64, tags: &[(&str, &str)]) {
    if let Some(metrics) = codex_otel::global() {
        let _ = metrics.histogram(name, saturating_i64(value), tags);
    }
}

fn saturating_i64(value: u64) -> i64 {
    i64::try_from(value).unwrap_or(i64::MAX)
}

fn saturating_u64(value: usize) -> u64 {
    u64::try_from(value).unwrap_or(u64::MAX)
}

fn saturating_add(counter: &AtomicU64, value: u64) {
    let _ = counter.fetch_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
        Some(current.saturating_add(value))
    });
}

fn current_alert_window() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() / REVALIDATION_ALERT_WINDOW_SECONDS)
        .unwrap_or_default()
        .min(ALERT_COUNT_MASK)
}

fn increment_window_failure_count(window: u64) -> u64 {
    loop {
        let observed = REVALIDATION_WINDOW_STATE.load(Ordering::Acquire);
        let observed_window = observed >> 32;
        let observed_count = observed & ALERT_COUNT_MASK;
        let next_count = if observed_window == window {
            observed_count.saturating_add(1).min(ALERT_COUNT_MASK)
        } else {
            1
        };
        let next = (window << 32) | next_count;
        if REVALIDATION_WINDOW_STATE
            .compare_exchange_weak(observed, next, Ordering::AcqRel, Ordering::Acquire)
            .is_ok()
        {
            return next_count;
        }
    }
}

fn record_windowed_revalidation_alert(reason: &'static str) {
    let failures_in_window = increment_window_failure_count(current_alert_window());
    if failures_in_window >= REVALIDATION_ALERT_THRESHOLD_PER_MINUTE
        && failures_in_window % REVALIDATION_ALERT_THRESHOLD_PER_MINUTE == 0
    {
        saturating_add(&REVALIDATION_ALERTS, 1);
        emit_counter(REVALIDATION_ALERTS_METRIC, 1, &[("reason", reason)]);
        tracing::error!(
            target: "hepta.cognitive_read",
            event = "cognitive_context_revalidation_alert",
            reason,
            failures_in_window,
            alert_threshold = REVALIDATION_ALERT_THRESHOLD_PER_MINUTE,
            window_seconds = REVALIDATION_ALERT_WINDOW_SECONDS,
            "cognitive context final-use revalidation failures crossed the bounded alert threshold"
        );
    }
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
        revalidation_alerts: REVALIDATION_ALERTS.load(Ordering::Relaxed),
        latency_micros: LATENCY_MICROS.load(Ordering::Relaxed),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn counters_are_monotone_and_alerts_are_bounded() {
        let before = snapshot();
        record_request();
        record_read(11, 43, 2);
        record_selected(3);
        record_budget_rejection();
        for _ in 0..REVALIDATION_ALERT_THRESHOLD_PER_MINUTE {
            record_revalidation_failure("qualification_test");
        }
        record_stale_cut_rejection();
        record_latency(7);
        let after = snapshot();

        assert!(after.requests >= before.requests + 1);
        assert!(after.payload_bytes >= before.payload_bytes + 11);
        assert!(after.total_bytes >= before.total_bytes + 43);
        assert!(after.missing_ids >= before.missing_ids + 2);
        assert!(after.selected_items >= before.selected_items + 3);
        assert!(after.budget_rejections >= before.budget_rejections + 1);
        assert!(
            after.revalidation_failures
                >= before.revalidation_failures + REVALIDATION_ALERT_THRESHOLD_PER_MINUTE
        );
        assert!(after.stale_cut_rejections >= before.stale_cut_rejections + 1);
        assert!(after.revalidation_alerts >= before.revalidation_alerts + 1);
        assert!(after.latency_micros >= before.latency_micros + 7);
    }

    #[test]
    fn exported_metric_names_remain_low_cardinality_and_stable() {
        for name in [
            REQUESTS_METRIC,
            SELECTED_ITEMS_METRIC,
            MISSING_IDS_METRIC,
            PAYLOAD_BYTES_METRIC,
            TOTAL_BYTES_METRIC,
            BUDGET_REJECTIONS_METRIC,
            REVALIDATION_FAILURES_METRIC,
            STALE_CUT_REJECTIONS_METRIC,
            REVALIDATION_ALERTS_METRIC,
            LATENCY_MICROS_METRIC,
        ] {
            assert!(name.starts_with("codex.hepta.cognitive_read."));
            assert!(
                name.chars()
                    .all(|character| character.is_ascii_alphanumeric()
                        || matches!(character, '.' | '_' | '-'))
            );
        }
    }
}
