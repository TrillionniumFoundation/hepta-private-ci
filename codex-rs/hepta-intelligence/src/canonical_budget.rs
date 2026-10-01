//! Monotonic admission budgets for every canonical composition adapter.
//!
//! These checks discard overrunning synchronous results. Process containment
//! remains the host's responsibility; an elapsed check cannot stop an owner call.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::CanonicalIntelligenceError;
use crate::CanonicalPortFailureClassV1;
use crate::CanonicalPortInputV1;
use crate::CanonicalStageV1;

pub(super) struct CanonicalBudgetClock {
    started: Instant,
    total: Duration,
    run_digest: Digest32,
}

impl CanonicalBudgetClock {
    pub(super) fn start(total_micros: u64, run_id: &str) -> Self {
        Self {
            started: Instant::now(),
            total: Duration::from_micros(total_micros),
            run_digest: Digest32::of_bytes(run_id.as_bytes()),
        }
    }

    pub(super) fn check_total(
        &self,
        stage: CanonicalStageV1,
    ) -> Result<(), CanonicalIntelligenceError> {
        let elapsed = self.started.elapsed();
        if elapsed > self.total {
            return Err(self.timeout(stage, b"total", self.total, elapsed));
        }
        Ok(())
    }

    pub(super) fn check_stage(
        &self,
        input: &CanonicalPortInputV1,
        started: Instant,
    ) -> Result<(), CanonicalIntelligenceError> {
        let elapsed = started.elapsed();
        let budget = Duration::from_micros(input.budget_micros);
        if elapsed > budget {
            return Err(self.timeout(input.stage, b"stage", budget, elapsed));
        }
        self.check_total(input.stage)
    }

    fn timeout(
        &self,
        stage: CanonicalStageV1,
        scope: &[u8],
        budget: Duration,
        elapsed: Duration,
    ) -> CanonicalIntelligenceError {
        let mut bytes = b"hepta.intelligence.canonical-budget-timeout.v1\0".to_vec();
        bytes.extend_from_slice(self.run_digest.as_array());
        bytes.extend_from_slice(scope);
        bytes.extend_from_slice(format!("{stage:?}").as_bytes());
        bytes.extend_from_slice(&budget.as_nanos().to_be_bytes());
        bytes.extend_from_slice(&elapsed.as_nanos().to_be_bytes());
        CanonicalIntelligenceError::PortFailure {
            stage,
            class: CanonicalPortFailureClassV1::TimedOut,
            evidence_digest: Digest32::of_bytes(&bytes),
        }
    }
}
