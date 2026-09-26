//! Allocation- and revocation-bound admission for the real Agent process start.
//!
//! The control request never selects an allocation. The existing supervisor
//! derives exactly one current active grant whose `principal_id` is the Agent
//! identity, restores the durable signed revocation frontier with independently
//! pinned trust roots, and verifies all grant/host/generation/digest fences
//! immediately before process spawn.

use codex_hepta_contracts::FinalUseRevocationConvergenceVerifier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationNodeTrust;
use codex_hepta_contracts::FinalUseTrustKey;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::DurableFleetOwner;
use codex_hepta_fleet::RevocationBoundGrantUseWitnessV1;
use codex_hepta_fleet::SystemFleetClock;
use codex_hepta_fleet::verify_final_use_with_revocation;
use serde::Deserialize;
use std::fmt;
use std::path::PathBuf;
use std::sync::Arc;
use thiserror::Error;

pub const FLEET_START_TRUST_PROFILE_SCHEMA_VERSION: u32 = 1;
const MAX_TRUST_PROFILE_BYTES: usize = 1_048_576;
const MAX_TRUST_KEYS: usize = 8;
const MAX_TRUSTED_NODES: usize = 256;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FleetStartTrustKeyV1 {
    pub key_id: String,
    pub verifying_key_hex: String,
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FleetStartNodeTrustV1 {
    pub node_id: String,
    pub keys: Vec<FleetStartTrustKeyV1>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct FleetStartTrustProfileV1 {
    pub schema_version: u32,
    pub local_node_id: String,
    pub distributor_id: String,
    pub distributor_keys: Vec<FleetStartTrustKeyV1>,
    pub nodes: Vec<FleetStartNodeTrustV1>,
}

impl FleetStartTrustProfileV1 {
    pub fn from_json_slice(bytes: &[u8]) -> Result<Self, FleetStartAdmissionError> {
        if bytes.is_empty() || bytes.len() > MAX_TRUST_PROFILE_BYTES {
            return Err(FleetStartAdmissionError::InvalidTrustProfile);
        }
        let profile: Self =
            serde_json::from_slice(bytes).map_err(|_| FleetStartAdmissionError::InvalidTrustProfile)?;
        profile.validate()?;
        Ok(profile)
    }

    pub fn validate(&self) -> Result<(), FleetStartAdmissionError> {
        if self.schema_version != FLEET_START_TRUST_PROFILE_SCHEMA_VERSION
            || !valid_identifier(&self.local_node_id)
            || !valid_identifier(&self.distributor_id)
            || self.distributor_keys.is_empty()
            || self.distributor_keys.len() > MAX_TRUST_KEYS
            || self.nodes.is_empty()
            || self.nodes.len() > MAX_TRUSTED_NODES
        {
            return Err(FleetStartAdmissionError::InvalidTrustProfile);
        }
        let mut local_matches = 0_usize;
        let mut node_ids = std::collections::BTreeSet::new();
        for node in &self.nodes {
            if !valid_identifier(&node.node_id)
                || node.keys.is_empty()
                || node.keys.len() > MAX_TRUST_KEYS
                || !node_ids.insert(node.node_id.as_str())
            {
                return Err(FleetStartAdmissionError::InvalidTrustProfile);
            }
            if node.node_id == self.local_node_id {
                local_matches += 1;
            }
            convert_keys(&node.keys)?;
        }
        if local_matches != 1 {
            return Err(FleetStartAdmissionError::InvalidTrustProfile);
        }
        convert_keys(&self.distributor_keys)?;
        Ok(())
    }
}

#[derive(Clone)]
pub struct FleetStartAdmission {
    supervisor_state_root: PathBuf,
    local_node_id: String,
    feed_verifier: FinalUseRevocationFeedVerifier,
    node_trust: Vec<FinalUseRevocationNodeTrust>,
}

impl fmt::Debug for FleetStartAdmission {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("FleetStartAdmission")
            .field("supervisor_state_root", &self.supervisor_state_root)
            .field("local_node_id", &self.local_node_id)
            .field("trusted_nodes", &self.node_trust.len())
            .finish_non_exhaustive()
    }
}

impl FleetStartAdmission {
    pub fn new(
        supervisor_state_root: impl Into<PathBuf>,
        profile: FleetStartTrustProfileV1,
    ) -> Result<Self, FleetStartAdmissionError> {
        profile.validate()?;
        let feed_verifier = FinalUseRevocationFeedVerifier::new_with_keys(
            profile.distributor_id,
            convert_keys(&profile.distributor_keys)?,
        )
        .map_err(|_| FleetStartAdmissionError::InvalidTrustProfile)?;
        let node_trust = profile
            .nodes
            .into_iter()
            .map(|node| {
                Ok(FinalUseRevocationNodeTrust {
                    node_id: node.node_id,
                    keys: convert_keys(&node.keys)?,
                })
            })
            .collect::<Result<Vec<_>, FleetStartAdmissionError>>()?;
        // Construct once at startup so malformed key rings cannot survive into
        // a request-time failure path. A fresh verifier is reconstructed for
        // every check because its constructor consumes the closed trust set.
        FinalUseRevocationConvergenceVerifier::new(node_trust.clone())
            .map_err(|_| FleetStartAdmissionError::InvalidTrustProfile)?;
        Ok(Self {
            supervisor_state_root: supervisor_state_root.into(),
            local_node_id: profile.local_node_id,
            feed_verifier,
            node_trust,
        })
    }

    pub fn local_node_id(&self) -> &str {
        &self.local_node_id
    }

    pub fn verify_agent_start(
        &self,
        agent_id: &AgentId,
    ) -> Result<RevocationBoundGrantUseWitnessV1, FleetStartAdmissionError> {
        let mut owner = DurableFleetOwner::open_supervisor_state_root(
            self.supervisor_state_root.clone(),
            Arc::new(SystemFleetClock),
        )
        .map_err(|error| FleetStartAdmissionError::Durable(error.to_string()))?;
        owner
            .metrics()
            .map_err(|error| FleetStartAdmissionError::Durable(error.to_string()))?;
        let principal_id = agent_id.to_string();
        let mut matching = owner
            .state()
            .fleet_grants
            .active_grants
            .values()
            .filter(|grant| grant.principal_id == principal_id && !grant.revoked);
        let grant = matching
            .next()
            .cloned()
            .ok_or_else(|| FleetStartAdmissionError::GrantMissing(principal_id.clone()))?;
        if matching.next().is_some() {
            return Err(FleetStartAdmissionError::GrantAmbiguous(principal_id));
        }
        let convergence_verifier =
            FinalUseRevocationConvergenceVerifier::new(self.node_trust.clone())
                .map_err(|_| FleetStartAdmissionError::InvalidTrustProfile)?;
        let witness = verify_final_use_with_revocation(
            &mut owner,
            self.feed_verifier.clone(),
            convergence_verifier,
            Arc::new(SystemAuthorityClock),
            &self.local_node_id,
            &grant.allocation_id,
            grant.lease_generation,
            &grant.host_id,
            grant.host_generation,
            &grant.semantic_digest,
        )
        .map_err(|error| FleetStartAdmissionError::Rejected(error.to_string()))?;
        if witness.grant.principal_id != agent_id.to_string() {
            return Err(FleetStartAdmissionError::PrincipalMismatch);
        }
        Ok(witness)
    }
}

fn convert_keys(
    keys: &[FleetStartTrustKeyV1],
) -> Result<Vec<FinalUseTrustKey>, FleetStartAdmissionError> {
    let mut ids = std::collections::BTreeSet::new();
    let mut public_keys = std::collections::BTreeSet::new();
    keys.iter()
        .map(|key| {
            let verifying_key = parse_key(&key.verifying_key_hex)?;
            if !valid_identifier(&key.key_id)
                || key.not_before_authority_epoch == 0
                || key.not_after_authority_epoch < key.not_before_authority_epoch
                || !ids.insert(key.key_id.as_str())
                || !public_keys.insert(verifying_key)
            {
                return Err(FleetStartAdmissionError::InvalidTrustProfile);
            }
            Ok(FinalUseTrustKey {
                key_id: key.key_id.clone(),
                verifying_key,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            })
        })
        .collect()
}

fn parse_key(value: &str) -> Result<[u8; 32], FleetStartAdmissionError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
    {
        return Err(FleetStartAdmissionError::InvalidTrustProfile);
    }
    let mut output = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        output[index] = (hex(pair[0])? << 4) | hex(pair[1])?;
    }
    Ok(output)
}

fn hex(value: u8) -> Result<u8, FleetStartAdmissionError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(FleetStartAdmissionError::InvalidTrustProfile),
    }
}

fn valid_identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
}

#[derive(Debug, Error)]
pub enum FleetStartAdmissionError {
    #[error("invalid runtime.fleet start trust profile")]
    InvalidTrustProfile,
    #[error("no active fleet allocation is bound to Agent principal {0}")]
    GrantMissing(String),
    #[error("multiple active fleet allocations are bound to Agent principal {0}")]
    GrantAmbiguous(String),
    #[error("fleet allocation principal changed during final-use verification")]
    PrincipalMismatch,
    #[error("durable fleet owner rejected start admission: {0}")]
    Durable(String),
    #[error("fleet final-use verification rejected start admission: {0}")]
    Rejected(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    fn key(byte: u8) -> String {
        format!("{byte:02x}").repeat(32)
    }

    fn profile() -> FleetStartTrustProfileV1 {
        FleetStartTrustProfileV1 {
            schema_version: FLEET_START_TRUST_PROFILE_SCHEMA_VERSION,
            local_node_id: "node-a".into(),
            distributor_id: "revocation-distributor".into(),
            distributor_keys: vec![FleetStartTrustKeyV1 {
                key_id: "distributor-v1".into(),
                verifying_key_hex: key(41),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: 99,
            }],
            nodes: vec![FleetStartNodeTrustV1 {
                node_id: "node-a".into(),
                keys: vec![FleetStartTrustKeyV1 {
                    key_id: "node-a-v1".into(),
                    verifying_key_hex: key(42),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 99,
                }],
            }],
        }
    }

    #[test]
    fn profile_requires_local_node_inside_closed_trust_set() {
        let mut profile = profile();
        profile.local_node_id = "node-b".into();
        assert!(matches!(
            profile.validate(),
            Err(FleetStartAdmissionError::InvalidTrustProfile)
        ));
    }

    #[test]
    fn profile_rejects_uppercase_or_duplicate_keys() {
        let mut profile = profile();
        profile.distributor_keys[0].verifying_key_hex = "AA".repeat(32);
        assert!(profile.validate().is_err());
        let mut profile = profile();
        profile.nodes[0].keys.push(profile.nodes[0].keys[0].clone());
        assert!(profile.validate().is_err());
    }
}
