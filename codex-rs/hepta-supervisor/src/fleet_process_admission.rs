use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseRevocationConvergenceVerifier;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationNodeTrust;
use codex_hepta_contracts::FinalUseTrustKey;
use codex_hepta_contracts::SystemAuthorityClock;
use codex_hepta_fleet::DurableFleetOwner;
use codex_hepta_fleet::LeaseLedger;
use codex_hepta_fleet::SystemFleetClock;
use codex_hepta_fleet::verify_final_use_with_revocation;
use serde::Deserialize;

use crate::AdoptSpec;
use crate::ProcessAdmission;
use crate::ProcessDriverError;
use crate::SpawnSpec;

pub const FLEET_PROCESS_ADMISSION_SCHEMA_VERSION: u32 = 1;
pub const MAX_FLEET_PROCESS_ADMISSION_PROFILE_BYTES: u64 = 1 << 20;
const MAX_ASSIGNMENTS: usize = 256;
const MAX_TRUST_KEYS: usize = 8;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FleetProcessAdmissionProfileV1 {
    schema_version: u32,
    node_id: String,
    distributor_id: String,
    distributor_keys: Vec<TrustKeyConfigV1>,
    node_trust: Vec<NodeTrustConfigV1>,
    assignments: Vec<FleetProcessAssignmentV1>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct TrustKeyConfigV1 {
    key_id: String,
    verifying_key_hex: String,
    not_before_authority_epoch: u64,
    not_after_authority_epoch: u64,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct NodeTrustConfigV1 {
    node_id: String,
    keys: Vec<TrustKeyConfigV1>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct FleetProcessAssignmentV1 {
    agent_id: AgentId,
    agent_generation: u64,
    allocation_id: String,
    lease_generation: u64,
    host_id: String,
    host_generation: u64,
    semantic_digest: String,
}

#[derive(Clone, Debug)]
struct ValidatedProfileV1 {
    node_id: String,
    distributor_id: String,
    distributor_keys: Vec<FinalUseTrustKey>,
    node_trust: Vec<FinalUseRevocationNodeTrust>,
    assignments: BTreeMap<AgentId, FleetProcessAssignmentV1>,
}

#[derive(Clone, Debug)]
pub struct FleetProcessAdmissionV1 {
    fleet_root: PathBuf,
    supervisor_state_root: PathBuf,
    profile: Option<ValidatedProfileV1>,
}

impl FleetProcessAdmissionV1 {
    pub fn from_optional_profile(
        fleet_root: impl Into<PathBuf>,
        supervisor_state_root: impl Into<PathBuf>,
        profile_path: Option<&Path>,
    ) -> Result<Self, ProcessDriverError> {
        let fleet_root = canonical_physical_directory(fleet_root.into(), "fleet root")?;
        let supervisor_state_root = canonical_physical_directory(
            supervisor_state_root.into(),
            "supervisor state root",
        )?;
        if !supervisor_state_root.starts_with(&fleet_root) {
            return Err(ProcessDriverError::new(
                "runtime.fleet state root is outside the configured fleet root",
            ));
        }
        let profile = profile_path.map(load_profile).transpose()?;
        Ok(Self {
            fleet_root,
            supervisor_state_root,
            profile,
        })
    }

    fn verify_agent(
        &self,
        agent_id: &AgentId,
        generation: u64,
        spawn_fleet_root: Option<&Path>,
    ) -> Result<(), ProcessDriverError> {
        if generation == 0 {
            return Err(ProcessDriverError::new(
                "runtime.fleet final-use admission rejects generation zero",
            ));
        }
        if let Some(root) = spawn_fleet_root {
            let canonical = root.canonicalize().map_err(ProcessDriverError::from)?;
            if canonical != self.fleet_root {
                return Err(ProcessDriverError::new(
                    "runtime.fleet final-use admission fleet-root mismatch",
                ));
            }
        }

        let owner = DurableFleetOwner::open_supervisor_state_root(
            &self.supervisor_state_root,
            Arc::new(SystemFleetClock),
        )
        .map_err(|error| {
            ProcessDriverError::new(format!(
                "open runtime.fleet final-use state: {error}"
            ))
        })?;
        let state = owner.state();
        if state.fleet_grants.active_grants.is_empty() && self.profile.is_none() {
            return Ok(());
        }
        let profile = self.profile.as_ref().ok_or_else(|| {
            ProcessDriverError::new(
                "active runtime.fleet grants require HEPTA_FLEET_FINAL_USE_PROFILE",
            )
        })?;
        let assignment = profile.assignments.get(agent_id).ok_or_else(|| {
            ProcessDriverError::new(format!(
                "no runtime.fleet final-use assignment for agent {agent_id}"
            ))
        })?;
        if assignment.agent_generation != generation {
            return Err(ProcessDriverError::new(format!(
                "runtime.fleet assignment generation {} does not match process generation {generation}",
                assignment.agent_generation
            )));
        }
        let grant = state
            .fleet_grants
            .active_grants
            .get(&assignment.allocation_id)
            .ok_or_else(|| {
                ProcessDriverError::new(format!(
                    "runtime.fleet allocation {} is not active",
                    assignment.allocation_id
                ))
            })?;
        if grant.principal_id != agent_id.to_string() {
            return Err(ProcessDriverError::new(
                "runtime.fleet allocation principal does not match the process agent",
            ));
        }

        let ledger = LeaseLedger::from_snapshot(
            Arc::new(SystemFleetClock),
            state.fleet_grants.clone(),
        )
        .map_err(|error| {
            ProcessDriverError::new(format!(
                "restore runtime.fleet lease ledger: {error}"
            ))
        })?;
        let snapshot = state.fleet_revocation_frontier.as_ref().ok_or_else(|| {
            ProcessDriverError::new(
                "runtime.fleet final-use admission has no durable revocation frontier",
            )
        })?;
        let feed = FinalUseRevocationFeedVerifier::new_with_keys(
            profile.distributor_id.clone(),
            profile.distributor_keys.clone(),
        )
        .map_err(|error| {
            ProcessDriverError::new(format!(
                "construct runtime.fleet revocation feed trust: {error}"
            ))
        })?;
        let convergence = FinalUseRevocationConvergenceVerifier::new(
            profile.node_trust.clone(),
        )
        .map_err(|error| {
            ProcessDriverError::new(format!(
                "construct runtime.fleet node trust: {error}"
            ))
        })?;
        let coordinator = snapshot
            .restore(feed, convergence, Arc::new(SystemAuthorityClock))
            .map_err(|error| {
                ProcessDriverError::new(format!(
                    "restore runtime.fleet revocation frontier: {error}"
                ))
            })?;
        verify_final_use_with_revocation(
            &ledger,
            &coordinator,
            &assignment.allocation_id,
            assignment.lease_generation,
            &assignment.host_id,
            assignment.host_generation,
            &assignment.semantic_digest,
            &profile.node_id,
        )
        .map_err(|error| {
            ProcessDriverError::new(format!(
                "runtime.fleet final-use admission rejected process effect: {error}"
            ))
        })?;
        Ok(())
    }
}

impl ProcessAdmission for FleetProcessAdmissionV1 {
    fn verify_spawn(&self, spec: &SpawnSpec) -> Result<(), ProcessDriverError> {
        self.verify_agent(&spec.agent_id, spec.generation, Some(&spec.fleet_root))
    }

    fn verify_adopt(&self, spec: &AdoptSpec) -> Result<(), ProcessDriverError> {
        self.verify_agent(&spec.agent_id, spec.registry_generation, None)
    }
}

fn load_profile(path: &Path) -> Result<ValidatedProfileV1, ProcessDriverError> {
    let path = path.canonicalize().map_err(ProcessDriverError::from)?;
    if !path.is_absolute() {
        return Err(ProcessDriverError::new(
            "runtime.fleet final-use profile path must be absolute",
        ));
    }
    let metadata = std::fs::symlink_metadata(&path).map_err(ProcessDriverError::from)?;
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > MAX_FLEET_PROCESS_ADMISSION_PROFILE_BYTES
    {
        return Err(ProcessDriverError::new(
            "runtime.fleet final-use profile must be a bounded regular file",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err(ProcessDriverError::new(
                "runtime.fleet final-use profile must not be group/world accessible",
            ));
        }
    }
    let profile: FleetProcessAdmissionProfileV1 =
        serde_json::from_slice(&std::fs::read(&path).map_err(ProcessDriverError::from)?)
            .map_err(|error| {
                ProcessDriverError::new(format!(
                    "decode runtime.fleet final-use profile: {error}"
                ))
            })?;
    validate_profile(profile)
}

fn validate_profile(
    profile: FleetProcessAdmissionProfileV1,
) -> Result<ValidatedProfileV1, ProcessDriverError> {
    if profile.schema_version != FLEET_PROCESS_ADMISSION_SCHEMA_VERSION
        || profile.assignments.is_empty()
        || profile.assignments.len() > MAX_ASSIGNMENTS
        || profile.distributor_keys.is_empty()
        || profile.distributor_keys.len() > MAX_TRUST_KEYS
        || profile.node_trust.is_empty()
    {
        return Err(ProcessDriverError::new(
            "invalid runtime.fleet final-use profile shape",
        ));
    }
    let distributor_keys = convert_keys(profile.distributor_keys)?;
    let mut node_trust = Vec::with_capacity(profile.node_trust.len());
    for node in profile.node_trust {
        if node.keys.is_empty() || node.keys.len() > MAX_TRUST_KEYS {
            return Err(ProcessDriverError::new(
                "invalid runtime.fleet node trust key count",
            ));
        }
        node_trust.push(FinalUseRevocationNodeTrust {
            node_id: node.node_id,
            keys: convert_keys(node.keys)?,
        });
    }
    // Constructor validation closes identifier, duplicate-node, key-id and
    // epoch-window semantics before any process effect can use the profile.
    FinalUseRevocationFeedVerifier::new_with_keys(
        profile.distributor_id.clone(),
        distributor_keys.clone(),
    )
    .map_err(|error| ProcessDriverError::new(format!("invalid distributor trust: {error}")))?;
    FinalUseRevocationConvergenceVerifier::new(node_trust.clone())
        .map_err(|error| ProcessDriverError::new(format!("invalid node trust: {error}")))?;

    let mut assignments = BTreeMap::new();
    for assignment in profile.assignments {
        if assignment.agent_generation == 0
            || assignment.lease_generation == 0
            || assignment.host_generation == 0
            || !valid_identity(&assignment.allocation_id)
            || !valid_identity(&assignment.host_id)
            || !valid_digest(&assignment.semantic_digest)
            || assignments
                .insert(assignment.agent_id.clone(), assignment)
                .is_some()
        {
            return Err(ProcessDriverError::new(
                "invalid or duplicate runtime.fleet process assignment",
            ));
        }
    }
    Ok(ValidatedProfileV1 {
        node_id: profile.node_id,
        distributor_id: profile.distributor_id,
        distributor_keys,
        node_trust,
        assignments,
    })
}

fn convert_keys(
    keys: Vec<TrustKeyConfigV1>,
) -> Result<Vec<FinalUseTrustKey>, ProcessDriverError> {
    keys.into_iter()
        .map(|key| {
            if key.not_before_authority_epoch == 0
                || key.not_after_authority_epoch < key.not_before_authority_epoch
            {
                return Err(ProcessDriverError::new(
                    "invalid runtime.fleet trust-key epoch window",
                ));
            }
            Ok(FinalUseTrustKey {
                key_id: key.key_id,
                verifying_key: decode_key(&key.verifying_key_hex)?,
                not_before_authority_epoch: key.not_before_authority_epoch,
                not_after_authority_epoch: key.not_after_authority_epoch,
            })
        })
        .collect()
}

fn decode_key(value: &str) -> Result<[u8; 32], ProcessDriverError> {
    if value.len() != 64 {
        return Err(ProcessDriverError::new(
            "runtime.fleet verifying key must be 64 lowercase hex digits",
        ));
    }
    let mut output = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        output[index] = (hex(pair[0])? << 4) | hex(pair[1])?;
    }
    Ok(output)
}

fn hex(value: u8) -> Result<u8, ProcessDriverError> {
    match value {
        b'0'..=b'9' => Ok(value - b'0'),
        b'a'..=b'f' => Ok(value - b'a' + 10),
        _ => Err(ProcessDriverError::new(
            "runtime.fleet verifying key must be lowercase hexadecimal",
        )),
    }
}

fn canonical_physical_directory(
    path: PathBuf,
    label: &str,
) -> Result<PathBuf, ProcessDriverError> {
    if !path.is_absolute() {
        return Err(ProcessDriverError::new(format!("{label} must be absolute")));
    }
    let canonical = path.canonicalize().map_err(ProcessDriverError::from)?;
    let metadata = std::fs::symlink_metadata(&canonical).map_err(ProcessDriverError::from)?;
    if !metadata.file_type().is_dir() || metadata.file_type().is_symlink() {
        return Err(ProcessDriverError::new(format!(
            "{label} must be a physical directory"
        )));
    }
    Ok(canonical)
}

fn valid_identity(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
}

fn valid_digest(value: &str) -> bool {
    value.len() == 64
        && !value.bytes().all(|byte| byte == b'0')
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn duplicate_agent_assignments_fail_closed() {
        let agent = AgentId::parse("00000000-0000-0000-0000-000000000001")
            .expect("agent id");
        let assignment = FleetProcessAssignmentV1 {
            agent_id: agent,
            agent_generation: 1,
            allocation_id: "allocation-one".into(),
            lease_generation: 1,
            host_id: "host-one".into(),
            host_generation: 1,
            semantic_digest: "1".repeat(64),
        };
        let profile = FleetProcessAdmissionProfileV1 {
            schema_version: FLEET_PROCESS_ADMISSION_SCHEMA_VERSION,
            node_id: "node-one".into(),
            distributor_id: "distributor-one".into(),
            distributor_keys: vec![TrustKeyConfigV1 {
                key_id: "distributor-key".into(),
                verifying_key_hex: "1".repeat(64),
                not_before_authority_epoch: 1,
                not_after_authority_epoch: 9,
            }],
            node_trust: vec![NodeTrustConfigV1 {
                node_id: "node-one".into(),
                keys: vec![TrustKeyConfigV1 {
                    key_id: "node-key".into(),
                    verifying_key_hex: "2".repeat(64),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 9,
                }],
            }],
            assignments: vec![assignment.clone(), assignment],
        };
        assert!(validate_profile(profile).is_err());
    }

    #[test]
    fn uppercase_or_zero_keys_are_not_silently_normalized() {
        assert!(decode_key(&"A".repeat(64)).is_err());
        assert_eq!(decode_key(&"0".repeat(64)).expect("shape-valid key"), [0; 32]);
    }
}
