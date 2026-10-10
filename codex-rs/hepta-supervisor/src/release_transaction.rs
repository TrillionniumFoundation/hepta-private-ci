//! Durable release-transition journal.
//!
//! One create/replace journal exists per Agent run root. Every process boundary
//! is preceded by a synced phase write. The journal carries the exact source
//! and target release identities plus current immutable catalog bindings when
//! the release is registered. Qualification-only direct AgentRelease fixtures
//! keep those bindings absent and never acquire production authority.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::ReleaseBinding;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

pub const RELEASE_TRANSACTION_SCHEMA_VERSION: u32 = 3;
pub const RELEASE_TRANSACTION_FILE: &str = "supervisor-release-transaction.json";
const TRANSACTION_DOMAIN: &[u8] = b"hepta-supervisor:release-transaction:v3";
const COMPATIBILITY_DOMAIN: &[u8] = b"hepta-supervisor:release-compatibility-binding:v1";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReleaseTransactionKind {
    Upgrade,
    ExplicitRollback,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReleaseTransactionPhase {
    Prepared,
    Draining,
    TargetStarting,
    AutomaticRollbackStarting,
    Committed,
    RolledBack,
    Aborted,
    RecoveryRequired,
}

impl ReleaseTransactionPhase {
    pub fn terminal(self) -> bool {
        matches!(self, Self::Committed | Self::RolledBack | Self::Aborted)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DurableReleaseTransaction {
    pub schema_version: u32,
    pub agent_id: String,
    pub kind: ReleaseTransactionKind,
    pub source_release: String,
    pub target_release: String,
    pub rollback_predecessor: Option<String>,
    pub source_binding: Option<ReleaseBindingWire>,
    pub target_binding: Option<ReleaseBindingWire>,
    /// Deterministic witness that both current source/target bindings were
    /// admitted under the same release-policy frontier and supported schema.
    pub compatibility_binding_sha256: Option<Sha256Digest>,
    pub expected_release_state_generation: u64,
    pub expected_lifecycle_generation: u64,
    pub grant_sha256: Option<Sha256Digest>,
    pub authority_epoch: Option<u64>,
    pub phase: ReleaseTransactionPhase,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub recovery_decision_sha256: Option<Sha256Digest>,
    pub transaction_sha256: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseBindingWire {
    pub release_id: String,
    pub manifest_sha256: String,
    pub agentd_program_sha256: String,
    pub matrixd_program_sha256: Option<String>,
    pub admission_frontier_sha256: String,
}

impl From<ReleaseBinding> for ReleaseBindingWire {
    fn from(value: ReleaseBinding) -> Self {
        Self {
            release_id: value.release_id.to_string(),
            manifest_sha256: value.manifest_sha256,
            agentd_program_sha256: value.agentd_program_sha256,
            matrixd_program_sha256: value.matrixd_program_sha256,
            admission_frontier_sha256: value.admission_frontier_sha256,
        }
    }
}

#[derive(Debug, Error)]
pub enum ReleaseTransactionError {
    #[error("release transaction is invalid: {0}")]
    Invalid(String),
    #[error("release transaction digest mismatch")]
    DigestMismatch,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl DurableReleaseTransaction {
    #[expect(
        clippy::too_many_arguments,
        reason = "release transaction constructor keeps crash-recovery bindings explicit"
    )]
    pub fn new(
        agent_id: impl Into<String>,
        kind: ReleaseTransactionKind,
        source_release: impl Into<String>,
        target_release: impl Into<String>,
        rollback_predecessor: Option<String>,
        source_binding: Option<ReleaseBinding>,
        target_binding: Option<ReleaseBinding>,
        expected_release_state_generation: u64,
        expected_lifecycle_generation: u64,
    ) -> Result<Self, ReleaseTransactionError> {
        let source_binding = source_binding.map(Into::into);
        let target_binding = target_binding.map(Into::into);
        let compatibility_binding_sha256 =
            compatibility_binding_digest(source_binding.as_ref(), target_binding.as_ref())?;
        let mut value = Self {
            schema_version: RELEASE_TRANSACTION_SCHEMA_VERSION,
            agent_id: agent_id.into(),
            kind,
            source_release: source_release.into(),
            target_release: target_release.into(),
            rollback_predecessor,
            source_binding,
            target_binding,
            compatibility_binding_sha256,
            expected_release_state_generation,
            expected_lifecycle_generation,
            grant_sha256: None,
            authority_epoch: None,
            phase: ReleaseTransactionPhase::Prepared,
            recovery_decision_sha256: None,
            transaction_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        value.transaction_sha256 = value.compute_digest()?;
        value.validate()?;
        Ok(value)
    }

    pub fn with_phase(
        &self,
        phase: ReleaseTransactionPhase,
    ) -> Result<Self, ReleaseTransactionError> {
        let mut value = Self {
            phase,
            recovery_decision_sha256: if matches!(
                phase,
                ReleaseTransactionPhase::Committed | ReleaseTransactionPhase::RolledBack
            ) {
                self.recovery_decision_sha256.clone()
            } else {
                None
            },
            ..self.clone()
        };
        value.transaction_sha256 = value.compute_digest()?;
        value.validate()?;
        Ok(value)
    }

    pub fn with_recovery_resolution(
        &self,
        phase: ReleaseTransactionPhase,
        decision_sha256: Sha256Digest,
    ) -> Result<Self, ReleaseTransactionError> {
        if !matches!(
            phase,
            ReleaseTransactionPhase::Committed | ReleaseTransactionPhase::RolledBack
        ) {
            return Err(ReleaseTransactionError::Invalid(
                "recovery decision may only terminalize a release transaction".to_string(),
            ));
        }
        let mut value = Self {
            phase,
            recovery_decision_sha256: Some(decision_sha256),
            ..self.clone()
        };
        value.transaction_sha256 = value.compute_digest()?;
        value.validate()?;
        Ok(value)
    }

    pub fn with_authority(
        &self,
        grant_sha256: Sha256Digest,
        authority_epoch: u64,
    ) -> Result<Self, ReleaseTransactionError> {
        if authority_epoch == 0 {
            return Err(ReleaseTransactionError::Invalid(
                "authority epoch must be non-zero".to_string(),
            ));
        }
        let mut value = Self {
            grant_sha256: Some(grant_sha256),
            authority_epoch: Some(authority_epoch),
            ..self.clone()
        };
        value.transaction_sha256 = value.compute_digest()?;
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), ReleaseTransactionError> {
        if self.schema_version != RELEASE_TRANSACTION_SCHEMA_VERSION
            || self.agent_id.is_empty()
            || self.agent_id.len() > 256
            || self.source_release.is_empty()
            || self.target_release.is_empty()
            || self.source_release == self.target_release
            || self.expected_lifecycle_generation == 0
            || self.grant_sha256.is_some() != self.authority_epoch.is_some()
            || self.authority_epoch == Some(0)
        {
            return Err(ReleaseTransactionError::Invalid(
                "release transaction fields are outside their bounds".to_string(),
            ));
        }
        if let Some(digest) = self.recovery_decision_sha256.as_ref() {
            Sha256Digest::parse(digest.as_str().to_string()).map_err(|_| {
                ReleaseTransactionError::Invalid(
                    "release recovery decision digest is malformed".to_string(),
                )
            })?;
            if !matches!(
                self.phase,
                ReleaseTransactionPhase::Committed | ReleaseTransactionPhase::RolledBack
            ) {
                return Err(ReleaseTransactionError::Invalid(
                    "non-terminal release transaction cannot bind a recovery decision".to_string(),
                ));
            }
        }
        for binding in [self.source_binding.as_ref(), self.target_binding.as_ref()]
            .into_iter()
            .flatten()
        {
            if !valid_sha256(&binding.manifest_sha256)
                || !valid_sha256(&binding.agentd_program_sha256)
                || !valid_sha256(&binding.admission_frontier_sha256)
                || binding
                    .matrixd_program_sha256
                    .as_ref()
                    .is_some_and(|digest| !valid_sha256(digest))
            {
                return Err(ReleaseTransactionError::Invalid(
                    "release binding contains a malformed digest".to_string(),
                ));
            }
        }
        let expected_compatibility = compatibility_binding_digest(
            self.source_binding.as_ref(),
            self.target_binding.as_ref(),
        )?;
        if self.compatibility_binding_sha256 != expected_compatibility {
            return Err(ReleaseTransactionError::Invalid(
                "release compatibility binding digest mismatch".to_string(),
            ));
        }
        if self.transaction_sha256 != self.compute_digest()? {
            return Err(ReleaseTransactionError::DigestMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Result<Sha256Digest, ReleaseTransactionError> {
        let encoded = serde_json::to_vec(&(
            self.schema_version,
            &self.agent_id,
            self.kind,
            &self.source_release,
            &self.target_release,
            &self.rollback_predecessor,
            &self.source_binding,
            &self.target_binding,
            &self.compatibility_binding_sha256,
            self.expected_release_state_generation,
            self.expected_lifecycle_generation,
            &self.grant_sha256,
            self.authority_epoch,
            self.phase,
            &self.recovery_decision_sha256,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [TRANSACTION_DOMAIN, encoded.as_slice()].concat(),
        )))
    }
}

fn compatibility_binding_digest(
    source: Option<&ReleaseBindingWire>,
    target: Option<&ReleaseBindingWire>,
) -> Result<Option<Sha256Digest>, ReleaseTransactionError> {
    let (Some(source), Some(target)) = (source, target) else {
        return Ok(None);
    };
    if source.admission_frontier_sha256 != target.admission_frontier_sha256 {
        return Err(ReleaseTransactionError::Invalid(
            "source and target were not admitted under the same release frontier".to_string(),
        ));
    }
    let encoded = serde_json::to_vec(&(source, target))?;
    Ok(Some(Sha256Digest::from_sha256_output(Sha256::digest(
        [COMPATIBILITY_DOMAIN, encoded.as_slice()].concat(),
    ))))
}

pub fn read_release_transaction(
    run_root: &Path,
) -> Result<Option<DurableReleaseTransaction>, ReleaseTransactionError> {
    let bytes = match std::fs::read(run_root.join(RELEASE_TRANSACTION_FILE)) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let value: DurableReleaseTransaction = serde_json::from_slice(&bytes)?;
    value.validate()?;
    Ok(Some(value))
}

pub fn write_release_transaction(
    run_root: &Path,
    transaction: &DurableReleaseTransaction,
) -> Result<(), ReleaseTransactionError> {
    transaction.validate()?;
    std::fs::create_dir_all(run_root)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| {
            ReleaseTransactionError::Invalid("system clock before Unix epoch".to_string())
        })?
        .as_nanos();
    let temp = run_root.join(format!(
        ".{RELEASE_TRANSACTION_FILE}.{nanos}.{sequence}.tmp"
    ));
    let final_path = run_root.join(RELEASE_TRANSACTION_FILE);
    let bytes = serde_json::to_vec(transaction)?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    replace_same_directory(&temp, &final_path)?;
    sync_directory(run_root)?;
    Ok(())
}

fn replace_same_directory(temp: &Path, final_path: &Path) -> Result<(), std::io::Error> {
    #[cfg(unix)]
    {
        std::fs::rename(temp, final_path)
    }
    #[cfg(not(unix))]
    {
        if final_path.exists() {
            std::fs::remove_file(final_path)?;
        }
        std::fs::rename(temp, final_path)
    }
}

#[cfg(unix)]
fn sync_directory(path: &Path) -> Result<(), std::io::Error> {
    std::fs::File::open(path)?.sync_all()
}

#[cfg(not(unix))]
fn sync_directory(_path: &Path) -> Result<(), std::io::Error> {
    Ok(())
}

fn valid_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| matches!(byte, b'0'..=b'9' | b'a'..=b'f'))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn transaction_round_trips_across_phases() {
        let dir = tempfile::tempdir().expect("temp");
        let value = DurableReleaseTransaction::new(
            "agent",
            ReleaseTransactionKind::Upgrade,
            "v1",
            "v2",
            None,
            None,
            None,
            1,
            2,
        )
        .expect("transaction");
        write_release_transaction(dir.path(), &value).expect("prepared");
        let draining = value
            .with_phase(ReleaseTransactionPhase::Draining)
            .expect("phase");
        write_release_transaction(dir.path(), &draining).expect("draining");
        assert_eq!(
            read_release_transaction(dir.path()).expect("read"),
            Some(draining)
        );
    }
}
