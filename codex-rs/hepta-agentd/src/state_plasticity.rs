use super::AgentdState;
use super::PlasticityFinalAdmissionGuardV1;
use super::poisoned_state;
use crate::AgentdError;
use codex_hepta_fleet::AgentLifecycle;

impl AgentdState {
    /// Refresh the fleet fence, then serialize the final admission decision with
    /// local draining and fencing. The caller must sample its clock before this
    /// call and retain the guard until synchronous append/anchor work returns;
    /// neither clock callbacks nor other state operations may run under it.
    pub(crate) fn plasticity_final_admission_guard(
        &self,
        expected_generation: u64,
    ) -> Result<PlasticityFinalAdmissionGuardV1<'_>, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        let owner_generation = self
            .identity
            .spawn_generation
            .checked_add(1)
            .ok_or_else(|| {
                AgentdError::GenerationFenced("plasticity owner generation overflow".to_string())
            })?;
        if expected_generation != owner_generation
            || runtime.current_generation != expected_generation
            || runtime.lifecycle != AgentLifecycle::Running
            || !runtime.app_server_ready
            || runtime.draining
            || runtime.fenced
        {
            return Err(AgentdError::GenerationFenced(
                "plasticity final admission requires the owner's exact live Running generation"
                    .to_string(),
            ));
        }
        Ok(PlasticityFinalAdmissionGuardV1 { _runtime: runtime })
    }
}

#[cfg(all(test, unix))]
#[path = "state_plasticity_tests.rs"]
mod tests;
