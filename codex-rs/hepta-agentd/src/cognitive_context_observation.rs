//! Request-scoped telemetry. Dropping an unfinished future is observable, not
//! a success. No query, record, principal, receipt or content enters a label.

use std::time::Instant;

use crate::cognitive_context_metrics;

pub(super) enum Phase {
    Read,
    FinalUse,
}

pub(super) struct OperationObservation {
    phase: Phase,
    started: Instant,
    successful: bool,
}

impl OperationObservation {
    pub(super) fn start(phase: Phase) -> Self {
        if matches!(phase, Phase::Read) {
            cognitive_context_metrics::record_request();
        }
        Self {
            phase,
            started: Instant::now(),
            successful: false,
        }
    }

    pub(super) fn succeed(&mut self) {
        self.successful = true;
    }
}

impl Drop for OperationObservation {
    fn drop(&mut self) {
        let micros = self.started.elapsed().as_micros();
        let outcome = if self.successful {
            "success"
        } else {
            "rejected_or_cancelled"
        };
        let phase = match self.phase {
            Phase::Read => {
                // Includes Invalid, owner failure, ranker failure and cancelled
                // futures, not just contexts that reach publication.
                cognitive_context_metrics::record_latency(micros);
                "read"
            }
            Phase::FinalUse => {
                if !self.successful {
                    cognitive_context_metrics::record_revalidation_failure(
                        "final_use_rejected_or_cancelled",
                    );
                }
                "final_use"
            }
        };
        if let Some(metrics) = codex_otel::global() {
            let tags = [("phase", phase), ("outcome", outcome)];
            let _ = metrics.counter("codex.hepta.cognitive_read.operations", 1, &tags);
            let _ = metrics.histogram(
                "codex.hepta.cognitive_read.operation_latency_us",
                i64::try_from(micros).unwrap_or(i64::MAX),
                &tags,
            );
        }
    }
}

#[cfg(test)]
#[path = "cognitive_context_observation_tests.rs"]
mod tests;
