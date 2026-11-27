//! A distinct key domain for newly created TaskFlow effects.

use super::ProviderEffectBindingError;
use super::ProviderEffectKey;
use super::digest_parts;
use super::validate_non_empty;
use crate::AgentId;

impl ProviderEffectKey {
    /// Derives the key for a new TaskFlow logical effect from four separate
    /// length-delimited fields. The owner is the existing durable store owner,
    /// not a caller-selected subject. Owner-local run IDs cannot alias another
    /// agent, and colons inside identifiers cannot move a field boundary.
    ///
    /// The local attempt and payload are deliberately excluded. Once an owner
    /// has persisted an effect key, every later attempt and status lookup must
    /// keep that exact key, including keys created by older derivations. This
    /// constructor neither migrates an existing effect nor authorizes a retry.
    /// The outer key encoding stays compatible with the provider wire contract.
    pub fn for_taskflow_v2(
        provider_scope: &str,
        owner_agent_id: &AgentId,
        run_id: &str,
        step_id: &str,
    ) -> Result<Self, ProviderEffectBindingError> {
        validate_non_empty("provider scope", provider_scope)?;
        validate_non_empty("run id", run_id)?;
        validate_non_empty("step id", step_id)?;
        Ok(Self(format!(
            "provider-effect:v1:{}",
            digest_parts([
                "provider-effect:taskflow:v2",
                provider_scope,
                owner_agent_id.as_str(),
                run_id,
                step_id,
            ])
        )))
    }
}

#[cfg(test)]
#[path = "provider_effect_taskflow_key_v2_tests.rs"]
mod tests;
