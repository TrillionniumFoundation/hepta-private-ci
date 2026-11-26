//! Bounded read projection of the Supervisor-owned serving topology.
//!
//! These observations do not select a candidate, hand off a writer, or grant
//! effects. The product binds them to its own compiled implementation at startup.
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

pub const SUPERVISORD_CONTROL_SCHEMA_VERSION: u32 = 2;
pub const MAX_SUPERVISORD_CONTROL_FRAME_BYTES: u64 = 65_536;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeModuleSelectionV1 {
    pub module_id: String,
    pub topology_digest: Sha256Digest,
    pub selected: Option<RuntimeModuleBindingV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeModuleBindingV1 {
    pub owner_id: String,
    pub generation: u64,
    pub implementation_digest: Sha256Digest,
    pub candidate_artifact_digest: Sha256Digest,
    pub state_class: String,
    pub dependencies: Vec<String>,
    pub authoritative_domains: Vec<String>,
    pub input_ports: Vec<String>,
    pub output_ports: Vec<String>,
    pub effect_scope: Vec<String>,
}

impl RuntimeModuleSelectionV1 {
    /// Validate the bounded observation, not its authority or currentness.
    pub fn validate(&self) -> Result<(), String> {
        validate_runtime_module_id(&self.module_id)?;
        if let Some(binding) = &self.selected {
            validate_runtime_module_id(&binding.owner_id)?;
            if !matches!(
                binding.state_class.as_str(),
                "stateless" | "stateful" | "stateful_external"
            ) {
                return Err("unknown selected module state class".to_string());
            }
            for values in [
                &binding.dependencies,
                &binding.authoritative_domains,
                &binding.input_ports,
                &binding.output_ports,
                &binding.effect_scope,
            ] {
                if values.len() > 64
                    || values
                        .iter()
                        .collect::<std::collections::BTreeSet<_>>()
                        .len()
                        != values.len()
                {
                    return Err("invalid selected module bounds".to_string());
                }
                for value in values {
                    validate_runtime_module_id(value)?;
                }
            }
            if binding.generation == 0
                || binding
                    .implementation_digest
                    .as_str()
                    .bytes()
                    .all(|byte| byte == b'0')
                || binding
                    .candidate_artifact_digest
                    .as_str()
                    .bytes()
                    .all(|byte| byte == b'0')
            {
                return Err("invalid selected runtime module binding".to_string());
            }
        }
        if self
            .topology_digest
            .as_str()
            .bytes()
            .all(|byte| byte == b'0')
        {
            return Err("missing runtime topology digest".to_string());
        }
        Ok(())
    }
}

pub fn validate_runtime_module_id(value: &str) -> Result<(), String> {
    if value.is_empty()
        || value.len() > 128
        || value
            .bytes()
            .any(|byte| !byte.is_ascii_alphanumeric() && !matches!(byte, b'.' | b'_' | b'-' | b':'))
    {
        return Err("invalid runtime module identity".to_string());
    }
    Ok(())
}

#[cfg(test)]
#[path = "module_selection_tests.rs"]
mod tests;
