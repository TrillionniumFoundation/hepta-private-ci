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

pub const RELEASE_SELECTION_SCHEMA_VERSION: u32 = 1;
pub(crate) const RELEASE_SELECTION_FILE: &str = "supervisor-release-selection.json";
const SELECTION_DOMAIN: &[u8] = b"hepta-supervisor:release-selection:v1";
const RECOVERY_SELECTION_DOMAIN: &[u8] = b"hepta-supervisor:release-selection-recovery:v1";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReleaseSelectionStatus {
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
pub struct ReleaseSelectionSnapshot {
    pub schema_version: u32,
    pub agent_id: String,
    pub grant_sha256: Sha256Digest,
    pub h7_envelope_sha256: Sha256Digest,
    pub artifact_sha256: Sha256Digest,
    pub selector_id: String,
    pub selector_epoch: u64,
    pub operator_acceptance: bool,
    pub promotion: bool,
    pub source_release: String,
    pub target_release: String,
    pub binding: ReleaseSelectionBinding,
    pub control_revision: u64,
    pub lifecycle_generation: u64,
    pub status: ReleaseSelectionStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recovery_decision_sha256: Option<Sha256Digest>,
    pub selection_sha256: Sha256Digest,
}

impl ReleaseSelectionSnapshot {
    pub fn validate(&self) -> Result<(), SupervisorError> {
        ReleaseSelectionRecord {
            schema_version: self.schema_version,
            agent_id: self.agent_id.clone(),
            grant_sha256: self.grant_sha256.clone(),
            h7_envelope_sha256: self.h7_envelope_sha256.clone(),
            artifact_sha256: self.artifact_sha256.clone(),
            selector_id: self.selector_id.clone(),
            selector_epoch: self.selector_epoch,
            operator_acceptance: self.operator_acceptance,
            promotion: self.promotion,
            source_release: self.source_release.clone(),
            target_release: self.target_release.clone(),
            binding: self.binding.clone(),
            control_revision: self.control_revision,
            lifecycle_generation: self.lifecycle_generation,
            status: self.status,
            recovery_decision_sha256: self.recovery_decision_sha256.clone(),
            selection_sha256: self.selection_sha256.clone(),
        }
        .validate()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct ReleaseSelectionRecord {
    pub schema_version: u32,
    pub agent_id: String,
    pub grant_sha256: Sha256Digest,
    pub h7_envelope_sha256: Sha256Digest,
    pub artifact_sha256: Sha256Digest,
    pub selector_id: String,
    pub selector_epoch: u64,
    pub operator_acceptance: bool,
    pub promotion: bool,
    pub source_release: String,
    pub target_release: String,
    pub binding: ReleaseSelectionBinding,
    pub control_revision: u64,
    pub lifecycle_generation: u64,
    pub status: ReleaseSelectionStatus,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recovery_decision_sha256: Option<Sha256Digest>,
    pub selection_sha256: Sha256Digest,
}

impl ReleaseSelectionRecord {
    pub(crate) fn snapshot(&self) -> ReleaseSelectionSnapshot {
        ReleaseSelectionSnapshot {
            schema_version: self.schema_version,
            agent_id: self.agent_id.clone(),
            grant_sha256: self.grant_sha256.clone(),
            h7_envelope_sha256: self.h7_envelope_sha256.clone(),
            artifact_sha256: self.artifact_sha256.clone(),
            selector_id: self.selector_id.clone(),
            selector_epoch: self.selector_epoch,
            operator_acceptance: self.operator_acceptance,
            promotion: self.promotion,
            source_release: self.source_release.clone(),
            target_release: self.target_release.clone(),
            binding: self.binding.clone(),
            control_revision: self.control_revision,
            lifecycle_generation: self.lifecycle_generation,
            status: self.status,
            recovery_decision_sha256: self.recovery_decision_sha256.clone(),
            selection_sha256: self.selection_sha256.clone(),
        }
    }

    pub(crate) fn prepared(
        grant: &H7H89ProductionGrant,
        control_revision: u64,
        lifecycle_generation: u64,
    ) -> Result<Self, SupervisorError> {
        let mut value = Self {
            schema_version: RELEASE_SELECTION_SCHEMA_VERSION,
            agent_id: grant.agent_id.clone(),
            grant_sha256: grant.grant_sha256.clone(),
            h7_envelope_sha256: grant.h7_envelope_sha256.clone(),
            artifact_sha256: grant.artifact_sha256.clone(),
            selector_id: grant.signer_id.clone(),
            selector_epoch: grant.signer_epoch,
            operator_acceptance: grant.operator_acceptance,
            promotion: grant.promotion,
            source_release: grant.source_release.clone(),
            target_release: grant.target_release.clone(),
            binding: grant.release_selection.clone(),
            control_revision,
            lifecycle_generation,
            status: ReleaseSelectionStatus::Prepared,
            recovery_decision_sha256: None,
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

    pub(crate) fn with_recovery_status(
        &self,
        status: ReleaseSelectionStatus,
        recovery_decision_sha256: Sha256Digest,
    ) -> Result<Self, SupervisorError> {
        if !matches!(status, ReleaseSelectionStatus::Committed | ReleaseSelectionStatus::RolledBack) {
            return Err(SupervisorError::Invalid(
                "recovery decision may only terminalize a release selection".to_string(),
            ));
        }
        let mut value = Self {
            status,
            recovery_decision_sha256: Some(recovery_decision_sha256),
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
            || self.selector_id.trim().is_empty()
            || self.selector_id.len() > 256
            || self.selector_epoch == 0
            || !self.operator_acceptance
            || !self.promotion
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
        for (digest, label) in [
            (&self.grant_sha256, "grant"),
            (&self.h7_envelope_sha256, "H7 envelope"),
            (&self.artifact_sha256, "artifact"),
        ] {
            Sha256Digest::parse(digest.as_str().to_string()).map_err(|_| {
                SupervisorError::Invalid(format!("release selection {label} digest is malformed"))
            })?;
        }
        if let Some(digest) = self.recovery_decision_sha256.as_ref() {
            Sha256Digest::parse(digest.as_str().to_string()).map_err(|_| {
                SupervisorError::Invalid(
                    "release selection recovery decision digest is malformed".to_string(),
                )
            })?;
            if !self.status.terminal() {
                return Err(SupervisorError::Invalid(
                    "non-terminal release selection cannot bind a recovery decision".to_string(),
                ));
            }
        }
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
            &self.h7_envelope_sha256,
            &self.artifact_sha256,
            &self.selector_id,
            self.selector_epoch,
            self.operator_acceptance,
            self.promotion,
            &self.source_release,
            &self.target_release,
            &self.binding,
            self.control_revision,
            self.lifecycle_generation,
            self.status,
        ))
        .map_err(|error| SupervisorError::Invalid(format!("encode release selection: {error}")))?;
        let base = Sha256Digest::from_sha256_output(Sha256::digest(
            [SELECTION_DOMAIN, payload.as_slice()].concat(),
        ));
        let Some(recovery_decision_sha256) = self.recovery_decision_sha256.as_ref() else {
            return Ok(base);
        };
        Ok(Sha256Digest::from_sha256_output(Sha256::digest([
            RECOVERY_SELECTION_DOMAIN,
            base.as_str().as_bytes(),
            recovery_decision_sha256.as_str().as_bytes(),
        ]
        .concat())))
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

    fn grant(seed: &[u8], target: &str) -> H7H89ProductionGrant {
        let binding = ReleaseSelectionBinding::new(
            digest(b"sm"),
            digest(b"sa"),
            None,
            digest(target.as_bytes()),
            digest([target.as_bytes(), b"-agentd"].concat().as_slice()),
            None,
            digest(b"compatibility-receipt"),
            7,
        )
        .expect("binding");
        H7H89ProductionGrant {
            schema_version: crate::SIGNED_AUTHORITY_SCHEMA_VERSION,
            namespace: crate::SIGNED_AUTHORITY_NAMESPACE.to_string(),
            agent_id: "agent".to_string(),
            source_release: "v1".to_string(),
            target_release: target.to_string(),
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
            grant_sha256: digest(seed),
        }
    }

    #[test]
    fn durable_selection_rejects_conflicting_unresolved_grants() {
        let temp = tempfile::tempdir().expect("temp");
        let first =
            ReleaseSelectionRecord::prepared(&grant(b"grant-1", "v2"), 1, 1).expect("record");
        write_release_selection(temp.path(), &first).expect("write first");

        let second =
            ReleaseSelectionRecord::prepared(&grant(b"grant-2", "v3"), 2, 1).expect("record");
        let error = write_release_selection(temp.path(), &second)
            .expect_err("unresolved selection must reject a different grant");
        assert!(error.to_string().contains("another release selection is unresolved"));
        assert_eq!(
            read_release_selection(temp.path()).expect("read"),
            Some(first)
        );
    }

    #[test]
    fn terminal_selection_allows_next_independent_grant() {
        let temp = tempfile::tempdir().expect("temp");
        let first =
            ReleaseSelectionRecord::prepared(&grant(b"grant-1", "v2"), 1, 1).expect("record");
        let committed = first
            .with_status(ReleaseSelectionStatus::Committed)
            .expect("committed");
        write_release_selection(temp.path(), &committed).expect("write committed");

        let second =
            ReleaseSelectionRecord::prepared(&grant(b"grant-2", "v3"), 2, 2).expect("record");
        write_release_selection(temp.path(), &second).expect("write next");
        assert_eq!(
            read_release_selection(temp.path()).expect("read"),
            Some(second)
        );
    }

    #[test]
    fn durable_selection_rejects_tampered_bytes() {
        let temp = tempfile::tempdir().expect("temp");
        let record =
            ReleaseSelectionRecord::prepared(&grant(b"grant-1", "v2"), 1, 1).expect("record");
        write_release_selection(temp.path(), &record).expect("write");

        let path = temp.path().join(RELEASE_SELECTION_FILE);
        let mut value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&path).expect("read bytes")).expect("json");
        value["target_release"] = serde_json::Value::String("v9".to_string());
        std::fs::write(&path, serde_json::to_vec(&value).expect("encode")).expect("tamper");

        assert!(read_release_selection(temp.path()).is_err());
    }
}

