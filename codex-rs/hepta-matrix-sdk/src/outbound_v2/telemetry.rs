use std::io::Write;

use tokio::time::Instant;

use super::OutboxDispatchError;
use super::OutboxDispatchStats;
use super::system_time_ms;

/// Bounded, process-local diagnostic windows. This is not a dispatch ledger.
/// Emitted only by the production sender, never from a transport poll. The
/// supervisor's normal stderr collection can forward these newline JSON events.
pub(super) struct TelemetryWindow {
    started: Instant,
    stats: OutboxDispatchStats,
}

impl TelemetryWindow {
    pub(super) fn new() -> Self {
        Self {
            started: Instant::now(),
            stats: OutboxDispatchStats::default(),
        }
    }

    pub(super) fn observe(
        &mut self,
        stats: &OutboxDispatchStats,
        error: Option<OutboxDispatchError>,
    ) {
        macro_rules! add {
            ($($field:ident),+ $(,)?) => {
                $(self.stats.$field = self.stats.$field.saturating_add(stats.$field);)+
            };
        }
        add!(
            claimed,
            sent,
            transport_accepted,
            indeterminate,
            observed_unqualified,
            retry_scheduled,
            permanent_failure,
            entered_attempts,
            pre_entry_failures,
            post_entry_failures,
            entered_proof_faults,
            entered_persistence_faults,
            entered_authority_faults,
            entered_identity_faults,
            entered_cancellation_faults,
            entered_deadline_faults,
            entered_clock_faults,
            entered_store_faults,
            entered_permit_faults,
            entered_invariant_faults,
            claim_to_first_poll_samples,
            claim_to_first_poll_ms,
            transport_polls,
            payload_digest_checks,
            payload_digest_ns,
            dynamic_checks,
            dynamic_check_ns,
        );
        self.stats.cancelled |= stats.cancelled;
        self.stats.claim_to_first_poll_max_ms = self
            .stats
            .claim_to_first_poll_max_ms
            .max(stats.claim_to_first_poll_max_ms);
        if error.is_some() || stats.cancelled || self.started.elapsed().as_secs() >= 10 {
            self.flush(error);
        }
    }

    pub(super) fn flush(&mut self, error: Option<OutboxDispatchError>) {
        let event = self.event(error);
        // Logging failure cannot authorize, retry or alter durable send truth.
        // No body, grant, raw capability or high-cardinality identifier exists
        // in this schema. Emission is once per 10s window or final task exit.
        let _ = writeln!(std::io::stderr().lock(), "{event}");
        self.stats = OutboxDispatchStats::default();
        self.started = Instant::now();
    }

    fn event(&self, error: Option<OutboxDispatchError>) -> serde_json::Value {
        let status = match error {
            None if self.stats.cancelled => "canceled",
            None => "running",
            Some(OutboxDispatchError::Invalid) => "invalid",
            Some(OutboxDispatchError::Store) => "store_unavailable",
            Some(OutboxDispatchError::Authority) => "authority_unavailable",
            Some(OutboxDispatchError::TransportIdentity) => "identity_unavailable",
            Some(OutboxDispatchError::LeaseExpired) => "lease_expired",
            Some(OutboxDispatchError::Canceled) => "canceled",
        };
        serde_json::json!({
            "schema": "hepta.channel-matrix-runtime-metrics.v1",
            "observed_at_ms": system_time_ms().ok(),
            "window_ms": u64::try_from(self.started.elapsed().as_millis()).unwrap_or(u64::MAX),
            "sender_status": status,
            "counters": self.stats,
        })
    }
}

#[cfg(test)]
#[path = "telemetry_tests.rs"]
mod tests;
