//! Daemon-owned scheduling for durable intelligence Decision/Outcome closure.
//!
//! The host and all final-use authority are supplied explicitly by the product
//! embedding. Agentd owns only bounded restart reconciliation and outbox drain
//! scheduling for the current Running generation. The default CLI installs no
//! host and therefore gains no learning-writer authority.

use std::sync::Arc;
use std::time::Duration;

use tokio_util::sync::CancellationToken;

use crate::AgentdError;
use crate::AgentdIntelligenceLearningErrorV1;
use crate::AgentdIntelligenceLearningHostV1;
use crate::AgentdState;

const MIN_RECONCILE_INTERVAL: Duration = Duration::from_millis(10);
const MAX_RECONCILE_INTERVAL: Duration = Duration::from_secs(60 * 60);
const MAX_RECONCILE_BATCH: u32 = 256;
const NOT_READY_POLL: Duration = Duration::from_millis(50);

/// Explicit product-owned scheduling profile for the durable learning outbox.
///
/// Construction does not mint a writer, grant provider, or authority. Those
/// objects are already sealed inside `AgentdIntelligenceLearningHostV1`.
pub struct AgentdIntelligenceLearningRuntimeConfigV1 {
    host: Arc<AgentdIntelligenceLearningHostV1>,
    interval: Duration,
    max_batch: u32,
}

impl AgentdIntelligenceLearningRuntimeConfigV1 {
    pub fn new(
        host: Arc<AgentdIntelligenceLearningHostV1>,
        interval: Duration,
        max_batch: u32,
    ) -> Result<Self, AgentdError> {
        validate_runtime_policy(interval, max_batch)?;
        Ok(Self {
            host,
            interval,
            max_batch,
        })
    }

    #[must_use]
    pub fn owner_generation(&self) -> u64 {
        self.host.owner_generation().get()
    }

    pub(crate) fn into_parts(self) -> (Arc<AgentdIntelligenceLearningHostV1>, Duration, u32) {
        (self.host, self.interval, self.max_batch)
    }
}

fn validate_runtime_policy(interval: Duration, max_batch: u32) -> Result<(), AgentdError> {
    if !(MIN_RECONCILE_INTERVAL..=MAX_RECONCILE_INTERVAL).contains(&interval) {
        return Err(AgentdError::Invalid(
            "intelligence learning reconciliation interval must be 10ms..=1h".to_string(),
        ));
    }
    if !(1..=MAX_RECONCILE_BATCH).contains(&max_batch) {
        return Err(AgentdError::Invalid(
            "intelligence learning reconciliation batch must be 1..=256".to_string(),
        ));
    }
    Ok(())
}

pub(crate) async fn run_intelligence_learning_runtime_v1(
    host: Arc<AgentdIntelligenceLearningHostV1>,
    state: Arc<AgentdState>,
    interval: Duration,
    max_batch: u32,
    cancellation: CancellationToken,
) -> Result<(), AgentdError> {
    validate_runtime_policy(interval, max_batch)?;
    loop {
        if !state.automation_admission_ready()? {
            tokio::select! {
                _ = cancellation.cancelled() => return Ok(()),
                _ = tokio::time::sleep(std::cmp::min(interval, NOT_READY_POLL)) => {}
            }
            continue;
        }

        let current_generation = state.current_generation()?;
        let owner_generation = host.owner_generation().get();
        if current_generation != owner_generation {
            state.mark_fenced();
            return Err(AgentdError::GenerationFenced(format!(
                "intelligence learning host generation {owner_generation} does not match current Running generation {current_generation}"
            )));
        }

        let reconciled = host
            .reconcile_unsettled(max_batch)
            .await
            .map_err(learning_error)?;
        let reconciled = u32::try_from(reconciled.len()).unwrap_or(max_batch);
        let mut remaining = max_batch.saturating_sub(reconciled);
        while remaining > 0 {
            match host.dispatch_next().await.map_err(learning_error)? {
                Some(_) => remaining -= 1,
                None => break,
            }
        }

        // A generation change during destination observation or append closes
        // the required service. The operation store retains any unsettled row
        // for adoption and exact replay by the successor generation.
        state.refresh_generation()?;
        if state.current_generation()? != owner_generation {
            state.mark_fenced();
            return Err(AgentdError::GenerationFenced(
                "intelligence learning generation changed during reconciliation".to_string(),
            ));
        }

        tokio::select! {
            _ = cancellation.cancelled() => return Ok(()),
            _ = tokio::time::sleep(interval) => {}
        }
    }
}

fn learning_error(error: AgentdIntelligenceLearningErrorV1) -> AgentdError {
    AgentdError::Protocol(format!(
        "intelligence learning reconciliation failed: {error}"
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn learning_runtime_policy_is_bounded() {
        assert!(validate_runtime_policy(Duration::from_millis(10), 1).is_ok());
        assert!(validate_runtime_policy(Duration::from_secs(3600), 256).is_ok());
        assert!(validate_runtime_policy(Duration::ZERO, 1).is_err());
        assert!(validate_runtime_policy(Duration::from_millis(9), 1).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(3601), 1).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(1), 0).is_err());
        assert!(validate_runtime_policy(Duration::from_secs(1), 257).is_err());
    }
}
