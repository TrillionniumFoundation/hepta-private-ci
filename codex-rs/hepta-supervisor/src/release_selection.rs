//! Durable authoritative release-selection record for production transitions.
//!
//! The record is supervisor-owned and binds the independently signed grant to
//! exact immutable release bytes, compatibility admission and the current
//! revocation frontier. It is not a deployment or user-task success receipt.

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

use crate::H7H89ProductionGrant;
use crate::ReleaseSelectionBinding;
use crate::SupervisorError;

pub(crate) const RELEASE_SELECTION_SCHEMA_VERSION: u32 = 1;
pub(crate) const RELEASE_SELECTION_FILE: &str = "supervisor-release-selection.json";
const SELECTION_DOMAIN: &[u8] = b"hepta-supervisor:release-selection:v1";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ReleaseSelectionStatus {
    Prepared,
    Queued,
    Committed,
    RolledBack,
    RecoveryRequired,
}

impl ReleaseSelectionStatus {
    pub(crate) const fn terminal(self) -> bool {
        matches!(self, Self::Committed | Self::RolledBack)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ReleaseSelectionRecord {
    pub schema_version: u32,
    pub agent_id: String,
    pub grant_sha256: Sha256Digest,
    pub source_release: String,
    pub target_release: String,
    pub binding: ReleaseSelectionBinding,
    pub control_revision: u64,
    pub lifecycle_generation: u64,
    pub status: ReleaseSelectionStatus,
    pub selection_sha256: Sha256Digest,
}

impl ReleaseSelectionRecord {
    pub(crate) fn prepared(
        grant: &H7H89ProductionGrant,
        control_revision: u64,
        lifecycle_generation: u64,
    ) -> Result<Self, SupervisorError> {
        let mut value = Self {
            schema_version: RELEASE_SELECTION_SCHEMA_VERSION,
            agent_id: grant.agent_id.clone(),
            grant_sha256: grant.grant_sha256.clone(),
            source_release: grant.source_release.clone(),
            target_release: grant.target_release.clone(),
            binding: grant.release_selection.clone(),
            control_revision,
            lifecycle_generation,
            status: ReleaseSelectionStatus::Prepared,
            selection_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        value.selection_sha256 = value.compute_digest()?;
        value.validate()?;
        Ok(value)
    }

    pub(crate) fn with_status(
        &self,
        status: ReleaseSelectionStatus,
    ) -> Result<Self, SupervisorError> {
        let mut value = Self {
            status,
            ..self.clone()
        };
        value.selection_sha256 = value.compute_digest()?;
        value.validate()?;
        Ok(value)
    }

    pub(crate) fn validate(&self) -> Result<(), SupervisorError> {
        if self.schema_version != RELEASE_SELECTION_SCHEMA_VERSION
            || self.agent_id.trim().is_empty()
            || self.agent_id.len() > 256
            || self.source_release.trim().is_empty()
            || self.target_release.trim().is_empty()
            || self.source_release == self.target_release
            || self.lifecycle_generation == 0
        {
            return Err(SupervisorError::Invalid(
                "release selection record fields are outside their bounds".to_string(),
            ));
        }
        self.binding
            .validate()
            .map_err(|error| SupervisorError::ProductionAuthority(error.to_string()))?;
        Sha256Digest::parse(self.grant_sha256.as_str().to_string())
            .map_err(|_| SupervisorError::Invalid("release selection grant digest is malformed".to_string()))?;
        Sha256Digest::parse(self.selection_sha256.as_str().to_string())
            .map_err(|_| SupervisorError::Invalid("release selection digest is malformed".to_string()))?;
        if self.selection_sha256 != self.compute_digest()? {
            return Err(SupervisorError::Invalid(
                "release selection digest mismatch".to_string(),
            ));
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, SupervisorError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.agent_id,
            &self.grant_sha256,
            &self.source_release,
            &self.target_release,
            &self.binding,
            self.control_revision,
            self.lifecycle_generation,
            self.status,
        ))
        .map_err(|error| SupervisorError::Invalid(format!("encode release selection: {error}")))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [SELECTION_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

pub(crate) fn read_release_selection(
    run_root: &Path,
) -> Result<Option<ReleaseSelectionRecord>, SupervisorError> {
    let path = run_root.join(RELEASE_SELECTION_FILE);
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    if bytes.len() > 32 * 1024 {
        return Err(SupervisorError::Invalid(
            "release selection record exceeds bounded size".to_string(),
        ));
    }
    let record: ReleaseSelectionRecord = serde_json::from_slice(&bytes)
        .map_err(|error| SupervisorError::Invalid(format!("decode release selection: {error}")))?;
    record.validate()?;
    Ok(Some(record))
}

pub(crate) fn write_release_selection(
    run_root: &Path,
    record: &ReleaseSelectionRecord,
) -> Result<(), SupervisorError> {
    record.validate()?;
    if let Some(existing) = read_release_selection(run_root)?
        && !existing.status.terminal()
        && existing.grant_sha256 != record.grant_sha256
    {
        return Err(SupervisorError::Invalid(
            "another release selection is unresolved".to_string(),
        ));
    }
    std::fs::create_dir_all(run_root)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| SupervisorError::Invalid("system clock before epoch".to_string()))?
        .as_nanos();
    let temp = run_root.join(format!(".{RELEASE_SELECTION_FILE}.{nanos}.{sequence}.tmp"));
    let final_path = run_root.join(RELEASE_SELECTION_FILE);
    let mut bytes = serde_json::to_vec(record)
        .map_err(|error| SupervisorError::Invalid(format!("encode release selection: {error}")))?;
    bytes.push(b'\n');
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    std::fs::rename(&temp, &final_path)?;
    sync_directory(run_root)
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), SupervisorError> {
    std::fs::File::open(path)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), SupervisorError> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::H7H89ProductionTransition;

    fn digest(seed: &[u8]) -> Sha256Digest {
        Sha256Digest::for_bytes(seed)
    }

    #[test]
    fn durable_selection_rejects_conflicting_unresolved_grants() {
        let temp = tempfile::tempdir().expect("temp");
        let binding = ReleaseSelectionBinding::new(
            digest(b"sm"),
            digest(b"sa"),
            None,
            digest(b"tm"),
            digest(b"ta"),
            None,
            7,
        )
        .expect("binding");
        let grant = H7H89ProductionGrant {
            schema_version: crate::SIGNED_AUTHORITY_SCHEMA_VERSION,
            namespace: crate::SIGNED_AUTHORITY_NAMESPACE.to_string(),
            agent_id: "agent".to_string(),
            source_release: "v1".to_string(),
            target_release: "v2".to_string(),
            transition: H7H89ProductionTransition::Upgrade,
            h7_envelope_sha256: digest(b"h7"),
            artifact_sha256: digest(b"artifact"),
            release_selection: binding,
            expected_control_revision: 0,
            expected_lifecycle_generation: 1,
            authority_epoch: 7,
            signer_id: "signer".to_string(),
            signer_epoch: 1,
            issued_at_unix_seconds: 1,
            expires_at_unix_seconds: 2,
            production_authority: true,
            external_effects: true,
            operator_acceptance: true,
            promotion: true,
            governance_bypass: false,
            signature_base64: "AA==".to_string(),
            grant_sha256: digest(b"grant"),
        };
        // The grant itself is not verified in this unit; the selection owner
        // only requires the already-verified digest/binding tuple.
        let record = ReleaseSelectionRecord::prepared(&grant, 1, 1).expect("record");
        write_release_selection(temp.path(), &record).expect("write");
        assert_eq!(
            read_release_selection(temp.path()).expect("read"),
            Some(record)
        );
    }
}
