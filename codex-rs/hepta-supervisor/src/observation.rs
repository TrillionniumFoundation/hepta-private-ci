//! Read-only collection from an existing owner-local Supervisor.
//!
//! Repeated equal reads are a stable bracket, NOT an atomic distributed
//! snapshot, proof of authorization, remote-host identity, or time attestation.
//! Consumers must retain those distinctions when an independent observer signs
//! its own judgement. This collector never issues a lifecycle mutation.

use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde::Serialize;
use tokio_util::sync::CancellationToken;

use crate::DurableReleaseTransaction;
use crate::ProductionMutationState;
use crate::SupervisorError;
use crate::SupervisordAgentStatus;
use crate::SupervisordClient;
use crate::SupervisordControlFence;
use crate::SupervisordHealth;

/// Untrusted-clock, unsigned measurements from eight correlated read-only RPCs.
/// This type is not accepted by any production authorization or model-selection
/// API. An unchanged bracket may still contain an unobserved intervening change.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SupervisordObservationV1 {
    pub schema: &'static str,
    pub health: SupervisordHealth,
    pub agent: SupervisordAgentStatus,
    pub release_selection: Option<DurableReleaseTransaction>,
    pub production_mutation: Option<ProductionMutationState>,
    pub started_unix_micros: u128,
    pub ended_unix_micros: u128,
    pub elapsed_monotonic_micros: u128,
    pub atomic_snapshot: bool,
    pub independently_attested: bool,
    pub production_accepted: bool,
}

impl SupervisordClient {
    /// Collect a bounded bracket for an externally expected exact control fence.
    /// The caller supplies a private owner-local socket and current expectation;
    /// neither a caller-provided fence nor this method proves external authority.
    /// Cancellation drops only read-only RPCs, never unjoined mutation effects.
    pub async fn observe_current(
        &self,
        expected: &SupervisordControlFence,
        stop: &CancellationToken,
    ) -> Result<SupervisordObservationV1, SupervisorError> {
        expected.validate().map_err(|_| {
            SupervisorError::Invalid("invalid observation expectation".to_string())
        })?;
        let started = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| {
            SupervisorError::Invalid("observation clock precedes epoch".to_string())
        })?;
        let monotonic = Instant::now();
        let read = async {
            let health = self.health().await?;
            let agent = self.snapshot(expected.agent_id.clone()).await?;
            let selection = self.release_selection(expected.agent_id.clone()).await?;
            let production = self.production_mutation_status(expected.agent_id.clone()).await?;
            let production_after = self.production_mutation_status(expected.agent_id.clone()).await?;
            let selection_after = self.release_selection(expected.agent_id.clone()).await?;
            let agent_after = self.snapshot(expected.agent_id.clone()).await?;
            let health_after = self.health().await?;
            if !health.ready
                || health.process_id == 0
                || health.supervisor_epoch != expected.supervisor_epoch
                || agent.agent_id != expected.agent_id
                || agent.control_fence != *expected
                || agent != agent_after
                || health != health_after
                || selection != selection_after
                || production != production_after
            {
                return Err(SupervisorError::Invalid(
                    "observation changed or differs from expected owner fence".to_string(),
                ));
            }
            let ended = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| {
                SupervisorError::Invalid("observation clock precedes epoch".to_string())
            })?;
            if ended < started {
                return Err(SupervisorError::Invalid("observation clock regressed".to_string()));
            }
            Ok(SupervisordObservationV1 {
                schema: "hepta.supervisord.read-observation.v1",
                health,
                agent,
                release_selection: selection,
                production_mutation: production,
                started_unix_micros: started.as_micros(),
                ended_unix_micros: ended.as_micros(),
                elapsed_monotonic_micros: monotonic.elapsed().as_micros(),
                atomic_snapshot: false,
                independently_attested: false,
                production_accepted: false,
            })
        };
        tokio::select! {
            biased;
            _ = stop.cancelled() => Err(SupervisorError::Invalid("observation cancelled".to_string())),
            _ = tokio::time::sleep(Duration::from_secs(10)) => Err(SupervisorError::Invalid("observation timed out".to_string())),
            result = read => result,
        }
    }
}

#[cfg(test)]
#[path = "observation_tests.rs"]
mod tests;
