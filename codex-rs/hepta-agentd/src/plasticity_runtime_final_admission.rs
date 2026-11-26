//! Original lifecycle/Fleet guard and fresh CURRENT at synchronous append.
use super::*;

pub(super) struct FinalPlasticityAdmissionV1<'a> {
    pub(super) state: &'a AgentdState,
    pub(super) cancellation: &'a CancellationToken,
    pub(super) generation: u64,
    pub(super) guard: Option<crate::state::PlasticityFinalAdmissionGuardV1<'a>>,
    pub(super) unavailable: bool,
    pub(super) current_artifacts: Option<&'a PlasticityCurrentArtifactsV1>,
    pub(super) artifacts: &'a ArtifactRegistry,
    pub(super) baseline: codex_hepta_agent_components::types::StableId,
}

impl FinalPlasticityAdmissionV1<'_> {
    pub(super) fn observe(
        &mut self,
        clock: &mut dyn FnMut() -> Result<u64, AgentdError>,
        last_observed_unix_ms: &mut Option<u64>,
        guard_elapsed_ms: fn(&Instant) -> u128,
    ) -> Result<u64, AgentdError> {
        // Clock callbacks can expose fencing, draining or cancellation. Sample
        // before acquiring the runtime mutex, then retain the admission guard
        // through the synchronous registry append and external anchor update.
        let sampled_at = Instant::now();
        let now = observe_plasticity_clock_v1(clock, last_observed_unix_ms)?;
        if self.cancellation.is_cancelled() {
            self.unavailable = true;
            return Err(AgentdError::GenerationFenced(
                "plasticity owner cancelled before final admission".to_string(),
            ));
        }
        let guard = self
            .state
            .plasticity_final_admission_guard(self.generation)
            .inspect_err(|_| self.unavailable = true)?;
        // This is a sealed filesystem reader, never a producer callback. Read
        // CURRENT after the potentially blocking Fleet refresh and retain the
        // existing lifecycle guard through the original synchronous append.
        let window = self
            .current_artifacts
            .ok_or_else(|| AgentdError::Invalid("plasticity CURRENT not configured".to_string()))
            .and_then(|current| current.verify(self.artifacts, &self.baseline, now))
            .inspect_err(|_| self.unavailable = true)?;
        // Fleet refresh may block. Advance the sampled host time by the real
        // monotonic interval rather than reuse a now that was valid before I/O.
        // No clock callback or other state operation runs under the guard.
        let elapsed_ms = u64::try_from(guard_elapsed_ms(&sampled_at))
            .map_err(|_| AgentdError::Protocol("plasticity clock interval overflow".to_string()))?;
        let now = now.checked_add(elapsed_ms).ok_or_else(|| {
            AgentdError::Protocol("plasticity clock interval overflow".to_string())
        })?;
        *last_observed_unix_ms = Some(now);
        window.revalidate_at(now).map_err(|error| {
            self.unavailable = true;
            AgentdError::Invalid(error.to_string())
        })?;
        if self.cancellation.is_cancelled() {
            self.unavailable = true;
            return Err(AgentdError::GenerationFenced(
                "plasticity owner cancelled before final admission".to_string(),
            ));
        }
        // This is the admission linearization point. Later cancellation lets
        // this already admitted synchronous transaction finish; it cannot undo
        // durable work. Local lifecycle changes serialize on the retained lock.
        self.guard = Some(guard);
        Ok(now)
    }
}
