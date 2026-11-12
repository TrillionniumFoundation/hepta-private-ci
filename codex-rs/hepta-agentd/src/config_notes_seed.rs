//! Pre-seed capability attenuation. This installs no Root, effect or tool owner.

use super::AgentdConfig;
use super::AgentdSocketInputs;
use super::CognitiveRetrievalMode;
use crate::AgentdError;

impl AgentdConfig {
    /// Select the finite v2 Core profile before creating an unused Notes thread.
    /// The original launcher still checks the effective profile and creates the
    /// original receipt. This selection grants no Notes execution authority.
    pub fn with_original_notes_seed_profile(mut self) -> Result<Self, AgentdError> {
        self.notes_thread_seed_profile = true;
        self.original_notes_seed_profile()?;
        Ok(self)
    }

    /// Recheck before runtime consumes any configured owner or socket input.
    pub(crate) fn original_notes_seed_profile(&self) -> Result<bool, AgentdError> {
        if !self.notes_thread_seed_profile {
            return Ok(false);
        }
        if !matches!(&self.sockets, AgentdSocketInputs::Bind)
            || self.authbus_trust_file.is_some()
            || self.authbus_checkpoint_file.is_some()
            || self.evidence_trust_file.is_some()
            || self.evidence_recovery_frontier_file.is_some()
            || self.evidence_recovery_frontier_trust_file.is_some()
            || self.automation_effect_host_file.is_some()
            || self.objective_profile_file.is_some()
            || self.cognitive_ranker.is_some()
            || self.production_operations.is_some()
            || self.production_writer_host.is_some()
            || self.notes_objective.is_some()
            || self.desktop_objective.is_some()
            || self.notes_ui.is_some()
            || self.notes_thread_tools.is_some()
            || self.desktop_thread_tools.is_some()
            || self.cognitive_retrieval_mode != CognitiveRetrievalMode::Compatibility
            || self.cognitive_retrieval_context.is_some()
            || self.cognitive_retrieval_learning.is_some()
            || self.plasticity_bootstrap.is_some()
            || self.learning_iteration_bootstrap.is_some()
            || self.terminal_learning_bootstrap.is_some()
            || self.neuron_generation_bootstrap.is_some()
            || self.circuit_task_bootstrap.is_some()
            || self.circuit_task_invocation.is_some()
            || self.intuition_policy_host.is_some()
            || self.intelligence_product_runner.is_some()
            || self.intelligence_invocation_provider.is_some()
        {
            return Err(AgentdError::Invalid(
                "original Notes seed profile cannot be combined with an execution or owner profile"
                    .into(),
            ));
        }
        crate::notes_thread_execution::inspect(&self.identity.home_root)?;
        Ok(true)
    }
}

#[cfg(test)]
#[path = "config_notes_seed_tests.rs"]
mod tests;
