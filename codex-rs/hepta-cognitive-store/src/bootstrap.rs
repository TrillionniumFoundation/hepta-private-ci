//! Signed external bootstrap contracts for the cognitive production writer.
//!
//! These values carry no write authority by themselves. Agentd verifies their
//! signatures, external file identities, live revocation state and opaque-token
//! binding before it asks the physical owner to recover a writable generation.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveRecoveryAnchor;

pub const COGNITIVE_BOOTSTRAP_SCHEMA_VERSION: u32 = 1;
pub const COGNITIVE_BOOTSTRAP_NAMESPACE: &str = "hepta.cognitive.production-bootstrap.v1";
pub const COGNITIVE_AUTHORITY_STATE_NAMESPACE: &str =
    "hepta.cognitive.production-authority-state.v1";
pub const COGNITIVE_BOOTSTRAP_MAX_FUTURE_SKEW_MS: u64 = 5 * 60 * 1000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveBootstrapContractError(String);

impl CognitiveBootstrapContractError {
    fn invalid(message: impl Into<String>) -> Self {
        Self(message.into())
    }
}

impl fmt::Display for CognitiveBootstrapContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.0)
    }
}

impl StdError for CognitiveBootstrapContractError {}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CognitiveBootstrapTrustV1 {
    pub schema_version: u32,
    pub signer_principal_id: String,
    pub signer_key_epoch: u64,
    pub public_key_hex: String,
    pub revoked: bool,
}

impl CognitiveBootstrapTrustV1 {
    pub fn validate(&self) -> Result<(), CognitiveBootstrapContractError> {
        if self.schema_version != COGNITIVE_BOOTSTRAP_SCHEMA_VERSION
            || self.signer_key_epoch == 0
        {
            return Err(CognitiveBootstrapContractError::invalid(
                "invalid cognitive bootstrap trust schema or key epoch",
            ));
        }
        validate_stable_id(&self.signer_principal_id, "signer principal")?;
        validate_hex(&self.public_key_hex, 32, "signer public key")?;
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CognitiveAuthorityStateV1 {
    pub schema_version: u32,
    pub namespace: String,
    pub state_revision: u64,
    pub agent_id: AgentId,
    pub lease_id: String,
    pub writer_generation: u64,
    pub grant_digest: Sha256Digest,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub lease_expires_at_unix_seconds: u64,
    pub token_sha256: Sha256Digest,
    pub revoked: bool,
    pub predecessor_state_sha256: Option<Sha256Digest>,
    pub created_at_unix_ms: u64,
    pub signer_principal_id: String,
    pub signer_key_epoch: u64,
    pub signature_hex: String,
}

impl CognitiveAuthorityStateV1 {
    pub fn validate_structure(&self) -> Result<(), CognitiveBootstrapContractError> {
        if self.schema_version != COGNITIVE_BOOTSTRAP_SCHEMA_VERSION
            || self.namespace != COGNITIVE_AUTHORITY_STATE_NAMESPACE
            || self.state_revision == 0
            || self.writer_generation == 0
            || self.authority_epoch == 0
            || self.owner_epoch == 0
            || self.lease_expires_at_unix_seconds == 0
            || self.created_at_unix_ms == 0
            || self.signer_key_epoch == 0
        {
            return Err(CognitiveBootstrapContractError::invalid(
                "invalid cognitive authority state identity or monotone value",
            ));
        }
        validate_stable_id(&self.lease_id, "writer lease id")?;
        validate_stable_id(&self.signer_principal_id, "authority signer principal")?;
        if self.state_revision == 1 && self.predecessor_state_sha256.is_some() {
            return Err(CognitiveBootstrapContractError::invalid(
                "authority state revision one cannot name a predecessor",
            ));
        }
        if self.state_revision > 1 && self.predecessor_state_sha256.is_none() {
            return Err(CognitiveBootstrapContractError::invalid(
                "authority state successor requires a predecessor digest",
            ));
        }
        if !self.signature_hex.is_empty() {
            validate_hex(&self.signature_hex, 64, "authority state signature")?;
        }
        Ok(())
    }

    pub fn validate_at(&self, now_unix_ms: u64) -> Result<(), CognitiveBootstrapContractError> {
        self.validate_structure()?;
        if self.signature_hex.is_empty() {
            return Err(CognitiveBootstrapContractError::invalid(
                "authority state is unsigned",
            ));
        }
        if self.created_at_unix_ms
            > now_unix_ms.saturating_add(COGNITIVE_BOOTSTRAP_MAX_FUTURE_SKEW_MS)
        {
            return Err(CognitiveBootstrapContractError::invalid(
                "authority state creation time is too far in the future",
            ));
        }
        if self.lease_expires_at_unix_seconds <= now_unix_ms / 1000 {
            return Err(CognitiveBootstrapContractError::invalid(
                "authority state lease is expired",
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CognitiveProductionBootstrapV1 {
    pub schema_version: u32,
    pub namespace: String,
    pub agent_id: AgentId,
    pub recovery_anchor: CognitiveRecoveryAnchor,
    pub lease_id: String,
    pub writer_generation: u64,
    pub rollback_generation_floor: u64,
    pub authority_state_sha256: Sha256Digest,
    pub canary_id: String,
    pub source_commit: String,
    pub source_tree: String,
    pub created_at_unix_ms: u64,
    pub signer_principal_id: String,
    pub signer_key_epoch: u64,
    pub signature_hex: String,
}

impl CognitiveProductionBootstrapV1 {
    pub fn validate_structure(&self) -> Result<(), CognitiveBootstrapContractError> {
        if self.schema_version != COGNITIVE_BOOTSTRAP_SCHEMA_VERSION
            || self.namespace != COGNITIVE_BOOTSTRAP_NAMESPACE
            || self.writer_generation == 0
            || self.rollback_generation_floor <= self.writer_generation
            || self.created_at_unix_ms == 0
            || self.signer_key_epoch == 0
            || self.recovery_anchor.owner_agent_id != self.agent_id
        {
            return Err(CognitiveBootstrapContractError::invalid(
                "invalid cognitive bootstrap identity, generation or recovery owner",
            ));
        }
        validate_stable_id(&self.lease_id, "writer lease id")?;
        validate_stable_id(&self.canary_id, "canary id")?;
        validate_stable_id(&self.signer_principal_id, "bootstrap signer principal")?;
        validate_git_oid(&self.source_commit, "source commit")?;
        validate_git_oid(&self.source_tree, "source tree")?;
        if !self.signature_hex.is_empty() {
            validate_hex(&self.signature_hex, 64, "bootstrap signature")?;
        }
        Ok(())
    }

    pub fn validate_at(&self, now_unix_ms: u64) -> Result<(), CognitiveBootstrapContractError> {
        self.validate_structure()?;
        if self.signature_hex.is_empty() {
            return Err(CognitiveBootstrapContractError::invalid(
                "cognitive production bootstrap is unsigned",
            ));
        }
        if self.created_at_unix_ms
            > now_unix_ms.saturating_add(COGNITIVE_BOOTSTRAP_MAX_FUTURE_SKEW_MS)
        {
            return Err(CognitiveBootstrapContractError::invalid(
                "bootstrap creation time is too far in the future",
            ));
        }
        Ok(())
    }
}

pub fn cognitive_authority_state_signing_bytes(
    state: &CognitiveAuthorityStateV1,
) -> Result<Vec<u8>, CognitiveBootstrapContractError> {
    state.validate_structure()?;
    let mut bytes = b"hepta.cognitive.production-authority-state.v1\0".to_vec();
    bytes.extend_from_slice(&state.schema_version.to_be_bytes());
    push_part(&mut bytes, state.namespace.as_bytes());
    bytes.extend_from_slice(&state.state_revision.to_be_bytes());
    push_part(&mut bytes, state.agent_id.as_str().as_bytes());
    push_part(&mut bytes, state.lease_id.as_bytes());
    bytes.extend_from_slice(&state.writer_generation.to_be_bytes());
    push_digest(&mut bytes, &state.grant_digest);
    bytes.extend_from_slice(&state.authority_epoch.to_be_bytes());
    bytes.extend_from_slice(&state.owner_epoch.to_be_bytes());
    bytes.extend_from_slice(&state.lease_expires_at_unix_seconds.to_be_bytes());
    push_digest(&mut bytes, &state.token_sha256);
    bytes.push(u8::from(state.revoked));
    push_optional_digest(&mut bytes, state.predecessor_state_sha256.as_ref());
    bytes.extend_from_slice(&state.created_at_unix_ms.to_be_bytes());
    push_part(&mut bytes, state.signer_principal_id.as_bytes());
    bytes.extend_from_slice(&state.signer_key_epoch.to_be_bytes());
    Ok(bytes)
}

pub fn cognitive_authority_state_sha256(
    state: &CognitiveAuthorityStateV1,
) -> Result<Sha256Digest, CognitiveBootstrapContractError> {
    Ok(Sha256Digest::for_bytes(
        &cognitive_authority_state_signing_bytes(state)?,
    ))
}

pub fn cognitive_production_bootstrap_signing_bytes(
    bootstrap: &CognitiveProductionBootstrapV1,
) -> Result<Vec<u8>, CognitiveBootstrapContractError> {
    bootstrap.validate_structure()?;
    let mut bytes = b"hepta.cognitive.production-bootstrap.v1\0".to_vec();
    bytes.extend_from_slice(&bootstrap.schema_version.to_be_bytes());
    push_part(&mut bytes, bootstrap.namespace.as_bytes());
    push_part(&mut bytes, bootstrap.agent_id.as_str().as_bytes());
    push_part(&mut bytes, bootstrap.recovery_anchor.profile.as_bytes());
    push_part(
        &mut bytes,
        bootstrap.recovery_anchor.owner_agent_id.as_str().as_bytes(),
    );
    push_digest(&mut bytes, &bootstrap.recovery_anchor.schema_digest);
    push_digest(&mut bytes, &bootstrap.recovery_anchor.state_digest);
    push_part(&mut bytes, bootstrap.lease_id.as_bytes());
    bytes.extend_from_slice(&bootstrap.writer_generation.to_be_bytes());
    bytes.extend_from_slice(&bootstrap.rollback_generation_floor.to_be_bytes());
    push_digest(&mut bytes, &bootstrap.authority_state_sha256);
    push_part(&mut bytes, bootstrap.canary_id.as_bytes());
    push_part(&mut bytes, bootstrap.source_commit.as_bytes());
    push_part(&mut bytes, bootstrap.source_tree.as_bytes());
    bytes.extend_from_slice(&bootstrap.created_at_unix_ms.to_be_bytes());
    push_part(&mut bytes, bootstrap.signer_principal_id.as_bytes());
    bytes.extend_from_slice(&bootstrap.signer_key_epoch.to_be_bytes());
    Ok(bytes)
}

pub fn cognitive_production_bootstrap_sha256(
    bootstrap: &CognitiveProductionBootstrapV1,
) -> Result<Sha256Digest, CognitiveBootstrapContractError> {
    Ok(Sha256Digest::for_bytes(
        &cognitive_production_bootstrap_signing_bytes(bootstrap)?,
    ))
}

pub fn validate_cognitive_rollback_successor(
    current: &CognitiveAuthorityStateV1,
    successor: &CognitiveAuthorityStateV1,
    rollback_generation_floor: u64,
) -> Result<(), CognitiveBootstrapContractError> {
    current.validate_structure()?;
    successor.validate_structure()?;
    let current_digest = cognitive_authority_state_sha256(current)?;
    if successor.agent_id != current.agent_id
        || successor.lease_id != current.lease_id
        || successor.state_revision != current.state_revision.saturating_add(1)
        || successor.predecessor_state_sha256.as_ref() != Some(&current_digest)
        || successor.writer_generation <= current.writer_generation
        || successor.writer_generation < rollback_generation_floor
        || successor.owner_epoch <= current.owner_epoch
        || successor.authority_epoch < current.authority_epoch
        || successor.grant_digest == current.grant_digest
        || successor.token_sha256 == current.token_sha256
        || successor.revoked
    {
        return Err(CognitiveBootstrapContractError::invalid(
            "rollback successor must use the same owner/lease, exact predecessor, a fresh grant-bound token and strictly newer writer/owner generations",
        ));
    }
    Ok(())
}

fn validate_stable_id(value: &str, label: &str) -> Result<(), CognitiveBootstrapContractError> {
    StableId::new(value.to_string()).map_err(|error| {
        CognitiveBootstrapContractError::invalid(format!("invalid {label}: {error}"))
    })?;
    Ok(())
}

fn validate_git_oid(value: &str, label: &str) -> Result<(), CognitiveBootstrapContractError> {
    if !matches!(value.len(), 40 | 64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(CognitiveBootstrapContractError::invalid(format!(
            "{label} must be a 40- or 64-character lowercase hexadecimal object id"
        )));
    }
    Ok(())
}

fn validate_hex(
    value: &str,
    expected_bytes: usize,
    label: &str,
) -> Result<(), CognitiveBootstrapContractError> {
    if value.len() != expected_bytes.saturating_mul(2)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(CognitiveBootstrapContractError::invalid(format!(
            "{label} must be lowercase fixed-width hexadecimal"
        )));
    }
    Ok(())
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

fn push_digest(bytes: &mut Vec<u8>, digest: &Sha256Digest) {
    push_part(bytes, digest.as_str().as_bytes());
}

fn push_optional_digest(bytes: &mut Vec<u8>, digest: Option<&Sha256Digest>) {
    match digest {
        Some(digest) => {
            bytes.push(1);
            push_digest(bytes, digest);
        }
        None => bytes.push(0),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn agent() -> AgentId {
        AgentId::parse("00000000-0000-4000-8000-00000000cb01").expect("agent")
    }

    fn state(revision: u64, predecessor: Option<Sha256Digest>) -> CognitiveAuthorityStateV1 {
        CognitiveAuthorityStateV1 {
            schema_version: COGNITIVE_BOOTSTRAP_SCHEMA_VERSION,
            namespace: COGNITIVE_AUTHORITY_STATE_NAMESPACE.to_string(),
            state_revision: revision,
            agent_id: agent(),
            lease_id: "cognitive-production-writer".to_string(),
            writer_generation: revision,
            grant_digest: Sha256Digest::for_bytes(format!("grant-{revision}").as_bytes()),
            authority_epoch: revision,
            owner_epoch: revision,
            lease_expires_at_unix_seconds: 9_999_999_999,
            token_sha256: Sha256Digest::for_bytes(format!("token-{revision}").as_bytes()),
            revoked: false,
            predecessor_state_sha256: predecessor,
            created_at_unix_ms: 1,
            signer_principal_id: "cognitive-bootstrap-signer".to_string(),
            signer_key_epoch: 1,
            signature_hex: "00".repeat(64),
        }
    }

    #[test]
    fn rollback_requires_exact_predecessor_and_fresh_fence() {
        let current = state(1, None);
        let predecessor = cognitive_authority_state_sha256(&current).expect("digest");
        let mut successor = state(2, Some(predecessor));
        successor.authority_epoch = current.authority_epoch;
        validate_cognitive_rollback_successor(&current, &successor, 2)
            .expect("fresh rollback generation");

        successor.writer_generation = current.writer_generation;
        assert!(validate_cognitive_rollback_successor(&current, &successor, 2).is_err());
    }
}
