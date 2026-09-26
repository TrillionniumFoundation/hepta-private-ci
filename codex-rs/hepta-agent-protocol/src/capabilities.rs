//! Versioned capability negotiation for additive Agentd extensions.
//!
//! The request/response methods remain stable and strict. New optional
//! features are advertised through the dedicated capabilities endpoint instead
//! of forcing every client to understand every future method variant.

use std::collections::BTreeMap;

use serde::Deserialize;
use serde::Serialize;

pub const AGENTD_CAPABILITY_SCHEMA_VERSION: u32 = 1;
pub const AGENTD_CAPABILITY_AUTOMATION_CALENDAR_V2: &str = "automation.calendar_v2";
pub const AGENTD_CAPABILITY_AUTOMATION_EXTERNAL_EFFECT: &str = "automation.external_effect";
pub const AGENTD_CAPABILITY_AUTOMATION_EFFECT_PREPARATION: &str = "automation.effect_preparation";
pub const AGENTD_CAPABILITY_AUTOMATION_THRESHOLD_CIRCUIT: &str = "automation.threshold_circuit";
pub const AGENTD_CAPABILITY_CANONICAL_INTELLIGENCE_V1: &str = "intelligence.canonical_v1";
pub const MAX_AGENTD_CAPABILITIES: usize = 64;
pub const MAX_AGENTD_CAPABILITY_ID_BYTES: usize = 128;

#[derive(Clone, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdCapability {
    pub id: String,
    pub major: u16,
    pub minor: u16,
}

impl AgentdCapability {
    pub fn new(id: impl Into<String>, major: u16, minor: u16) -> Result<Self, String> {
        let capability = Self {
            id: id.into(),
            major,
            minor,
        };
        capability.validate()?;
        Ok(capability)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.id.is_empty() || self.id.len() > MAX_AGENTD_CAPABILITY_ID_BYTES {
            return Err("capability id is empty or too large".to_string());
        }
        if !self
            .id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'-' | b'_' | b':'))
        {
            return Err("capability id contains an invalid character".to_string());
        }
        if self.major == 0 {
            return Err("capability major version must be non-zero".to_string());
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdCapabilitySet {
    pub schema_version: u32,
    pub capabilities: Vec<AgentdCapability>,
}

impl AgentdCapabilitySet {
    pub fn empty() -> Self {
        Self {
            schema_version: AGENTD_CAPABILITY_SCHEMA_VERSION,
            capabilities: Vec::new(),
        }
    }

    pub fn new(mut capabilities: Vec<AgentdCapability>) -> Result<Self, String> {
        if capabilities.len() > MAX_AGENTD_CAPABILITIES {
            return Err("too many Agentd capabilities".to_string());
        }
        for capability in &capabilities {
            capability.validate()?;
        }
        capabilities.sort();
        if capabilities.windows(2).any(|pair| pair[0].id == pair[1].id) {
            return Err("duplicate Agentd capability id".to_string());
        }
        Ok(Self {
            schema_version: AGENTD_CAPABILITY_SCHEMA_VERSION,
            capabilities,
        })
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != AGENTD_CAPABILITY_SCHEMA_VERSION {
            return Err("unsupported Agentd capability schema".to_string());
        }
        Self::new(self.capabilities.clone()).map(|_| ())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NegotiatedAgentdCapabilities {
    pub schema_version: u32,
    pub capabilities: Vec<AgentdCapability>,
}

/// Return only capabilities supported by both peers. A major-version mismatch
/// is incompatible; the lower minor version is selected for compatible peers.
pub fn negotiate_capabilities(
    local: &AgentdCapabilitySet,
    remote: &AgentdCapabilitySet,
) -> Result<NegotiatedAgentdCapabilities, String> {
    local.validate()?;
    remote.validate()?;
    let local_by_id: BTreeMap<_, _> = local
        .capabilities
        .iter()
        .map(|capability| (&capability.id, capability))
        .collect();
    let mut capabilities = Vec::new();
    for remote_capability in &remote.capabilities {
        let Some(local_capability) = local_by_id.get(&remote_capability.id) else {
            continue;
        };
        if local_capability.major == remote_capability.major {
            capabilities.push(AgentdCapability {
                id: remote_capability.id.clone(),
                major: remote_capability.major,
                minor: local_capability.minor.min(remote_capability.minor),
            });
        }
    }
    Ok(NegotiatedAgentdCapabilities {
        schema_version: AGENTD_CAPABILITY_SCHEMA_VERSION,
        capabilities,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn capability(id: &str, major: u16, minor: u16) -> AgentdCapability {
        AgentdCapability::new(id, major, minor).expect("valid capability")
    }

    #[test]
    fn negotiation_is_intersection_with_minor_downgrade() {
        let local = AgentdCapabilitySet::new(vec![
            capability("memory.read", 1, 3),
            capability("future", 2, 1),
        ])
        .expect("local");
        let remote = AgentdCapabilitySet::new(vec![
            capability("memory.read", 1, 1),
            capability("future", 1, 9),
            capability("remote.only", 1, 1),
        ])
        .expect("remote");
        let negotiated = negotiate_capabilities(&local, &remote).expect("negotiated");
        assert_eq!(
            negotiated.capabilities,
            vec![capability("memory.read", 1, 1)]
        );
    }

    #[test]
    fn duplicate_and_invalid_ids_are_rejected() {
        assert!(
            AgentdCapabilitySet::new(vec![
                capability("memory.read", 1, 0),
                capability("memory.read", 1, 1),
            ])
            .is_err()
        );
        assert!(AgentdCapability::new("memory/read", 1, 0).is_err());
    }
}
