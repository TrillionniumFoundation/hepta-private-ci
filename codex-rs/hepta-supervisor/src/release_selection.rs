//! Durable authoritative release-selection record for production transitions.
//!
//! This record is distinct from the signed intent journal: the intent proves
//! transaction progress, while this file retains the exact externally selected
//! artifact/release bytes and evidence digests that future runs are allowed to
//! load.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::H7H89ProductionGrant;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::publish_durable;

pub const RELEASE_SELECTION_SCHEMA_VERSION: u32 = 1;
pub const RELEASE_SELECTION_FILE: &str = "supervisor-release-selection.json";
const SELECTION_DOMAIN: &[u8] = b"hepta-supervisor:release-selection:v1";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseSelectionRecord {
    pub schema_version: u32,
    pub agent_id: String,
    pub grant_sha256: Sha256Digest,
    pub h7_envelope_sha256: Sha256Digest,
    pub artifact_sha256: Sha256Digest,
    pub source_release: String,
    pub target_release: String,
    pub source_release_manifest_sha256: Sha256Digest,
    pub target_release_manifest_sha256: Sha256Digest,
    pub target_agentd_sha256: Sha256Digest,
    pub target_matrixd_sha256: Option<Sha256Digest>,
    pub compatibility_sha256: Sha256Digest,
    pub revocation_frontier_sha256: Sha256Digest,
    pub selector_id: String,
    pub selector_epoch: u64,
    pub authority_epoch: u64,
    pub expected_control_revision: u64,
    pub expected_lifecycle_generation: u64,
    pub status: SignedIntentStatus,
    pub selection_sha256: Sha256Digest,
}

#[derive(Debug, Error)]
pub enum ReleaseSelectionError {
    #[error("release selection is malformed: {0}")]
    Invalid(String),
    #[error("release selection digest mismatch")]
    DigestMismatch,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl ReleaseSelectionRecord {
    pub fn from_grant(
        grant: &H7H89ProductionGrant,
        status: SignedIntentStatus,
    ) -> Result<Self, ReleaseSelectionError> {
        let mut record = Self {
            schema_version: RELEASE_SELECTION_SCHEMA_VERSION,
            agent_id: grant.agent_id.clone(),
            grant_sha256: grant.grant_sha256.clone(),
            h7_envelope_sha256: grant.h7_envelope_sha256.clone(),
            artifact_sha256: grant.artifact_sha256.clone(),
            source_release: grant.source_release.clone(),
            target_release: grant.target_release.clone(),
            source_release_manifest_sha256: grant.source_release_manifest_sha256.clone(),
            target_release_manifest_sha256: grant.target_release_manifest_sha256.clone(),
            target_agentd_sha256: grant.target_agentd_sha256.clone(),
            target_matrixd_sha256: grant.target_matrixd_sha256.clone(),
            compatibility_sha256: grant.compatibility_sha256.clone(),
            revocation_frontier_sha256: grant.revocation_frontier_sha256.clone(),
            selector_id: grant.signer_id.clone(),
            selector_epoch: grant.signer_epoch,
            authority_epoch: grant.authority_epoch,
            expected_control_revision: grant.expected_control_revision,
            expected_lifecycle_generation: grant.expected_lifecycle_generation,
            status,
            selection_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        record.selection_sha256 = record.compute_digest()?;
        record.validate()?;
        Ok(record)
    }

    pub fn with_status(
        &self,
        status: SignedIntentStatus,
    ) -> Result<Self, ReleaseSelectionError> {
        let mut next = Self {
            status,
            ..self.clone()
        };
        next.selection_sha256 = next.compute_digest()?;
        next.validate()?;
        Ok(next)
    }

    pub fn validate(&self) -> Result<(), ReleaseSelectionError> {
        if self.schema_version != RELEASE_SELECTION_SCHEMA_VERSION
            || self.agent_id.trim().is_empty()
            || self.source_release.trim().is_empty()
            || self.target_release.trim().is_empty()
            || self.source_release == self.target_release
            || self.selector_id.trim().is_empty()
            || self.selector_epoch == 0
            || self.authority_epoch == 0
            || self.expected_lifecycle_generation == 0
        {
            return Err(ReleaseSelectionError::Invalid(
                "release-selection fields are outside their bounds".to_string(),
            ));
        }
        for digest in [
            &self.grant_sha256,
            &self.h7_envelope_sha256,
            &self.artifact_sha256,
            &self.source_release_manifest_sha256,
            &self.target_release_manifest_sha256,
            &self.target_agentd_sha256,
            &self.compatibility_sha256,
            &self.revocation_frontier_sha256,
            &self.selection_sha256,
        ] {
            Sha256Digest::parse(digest.as_str().to_string())
                .map_err(ReleaseSelectionError::Invalid)?;
        }
        if let Some(digest) = &self.target_matrixd_sha256 {
            Sha256Digest::parse(digest.as_str().to_string())
                .map_err(ReleaseSelectionError::Invalid)?;
        }
        if self.selection_sha256 != self.compute_digest()? {
            return Err(ReleaseSelectionError::DigestMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, ReleaseSelectionError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.agent_id,
            &self.grant_sha256,
            &self.h7_envelope_sha256,
            &self.artifact_sha256,
            &self.source_release,
            &self.target_release,
            &self.source_release_manifest_sha256,
            &self.target_release_manifest_sha256,
            &self.target_agentd_sha256,
            &self.target_matrixd_sha256,
            &self.compatibility_sha256,
            &self.revocation_frontier_sha256,
            &self.selector_id,
            self.selector_epoch,
            self.authority_epoch,
            self.expected_control_revision,
            self.expected_lifecycle_generation,
            self.status,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [SELECTION_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

pub fn read_selection(
    run_root: &Path,
) -> Result<Option<ReleaseSelectionRecord>, ReleaseSelectionError> {
    let path = run_root.join(RELEASE_SELECTION_FILE);
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let record: ReleaseSelectionRecord = serde_json::from_slice(&bytes)?;
    record.validate()?;
    Ok(Some(record))
}

pub fn write_selection(
    run_root: &Path,
    record: &ReleaseSelectionRecord,
) -> Result<(), ReleaseSelectionError> {
    record.validate()?;
    if let Some(existing) = read_selection(run_root)?
        && !existing.status.is_terminal()
        && existing.grant_sha256 != record.grant_sha256
    {
        return Err(ReleaseSelectionError::Invalid(
            "another release selection is unresolved".to_string(),
        ));
    }
    std::fs::create_dir_all(run_root)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| ReleaseSelectionError::Invalid("system clock before epoch".to_string()))?
        .as_nanos();
    let temp = run_root.join(format!(
        ".{RELEASE_SELECTION_FILE}.{nanos}.{sequence}.tmp"
    ));
    let final_path = run_root.join(RELEASE_SELECTION_FILE);
    let bytes = serde_json::to_vec(record)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    publish_durable(&temp, &final_path)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::H7H89ProductionTransition;

    #[test]
    fn selection_status_transition_preserves_exact_binding() {
        let grant = H7H89ProductionGrant {
            schema_version: crate::SIGNED_AUTHORITY_SCHEMA_VERSION,
            namespace: crate::SIGNED_AUTHORITY_NAMESPACE.to_string(),
            agent_id: "agent".to_string(),
            source_release: "v1".to_string(),
            target_release: "v2".to_string(),
            transition: H7H89ProductionTransition::Upgrade,
            h7_envelope_sha256: Sha256Digest::for_bytes(b"h7"),
            artifact_sha256: Sha256Digest::for_bytes(b"artifact"),
            source_release_manifest_sha256: Sha256Digest::for_bytes(b"source"),
            target_release_manifest_sha256: Sha256Digest::for_bytes(b"target"),
            target_agentd_sha256: Sha256Digest::for_bytes(b"agentd"),
            target_matrixd_sha256: None,
            compatibility_sha256: Sha256Digest::for_bytes(b"compat"),
            revocation_frontier_sha256: Sha256Digest::for_bytes(b"revoke"),
            expected_control_revision: 1,
            expected_lifecycle_generation: 2,
            authority_epoch: 3,
            signer_id: "selector".to_string(),
            signer_epoch: 4,
            issued_at_unix_seconds: 10,
            expires_at_unix_seconds: 20,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: true,
            governance_bypass: false,
            signature_base64: "fixture".to_string(),
            grant_sha256: Sha256Digest::for_bytes(b"grant"),
        };
        let prepared =
            ReleaseSelectionRecord::from_grant(&grant, SignedIntentStatus::Prepared).unwrap();
        let committed = prepared
            .with_status(SignedIntentStatus::Committed)
            .unwrap();
        assert_eq!(prepared.grant_sha256, committed.grant_sha256);
        assert_ne!(prepared.selection_sha256, committed.selection_sha256);
    }
}
