//! Independent signed recovery-frontier admission for kernel.evidence.
//!
//! The frontier and signer trust files must be supplied from outside the Agent
//! home so restoring the evidence SQLite image cannot silently roll them back
//! as part of the same local state bundle.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE;
use codex_hepta_evidence::EvidenceRecoverySnapshotV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authbus_trust::hex_bytes;

const MAX_FRONTIER_FILE_BYTES: u64 = 64 * 1024;
const MAX_FRONTIER_TRUST_FILE_BYTES: u64 = 8 * 1024;
const MAX_FUTURE_CLOCK_SKEW_MS: u64 = 5 * 60 * 1000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRecoveryFrontierV1 {
    pub schema_version: u32,
    pub store_id: String,
    pub frontier_generation: u64,
    pub snapshot: EvidenceRecoverySnapshotV1,
    pub source_commit: String,
    pub source_tree: String,
    pub created_at_unix_ms: u64,
    pub signer_principal_id: String,
    pub signer_key_epoch: u64,
    pub signature_hex: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceRecoveryFrontierTrustV1 {
    schema_version: u32,
    signer_principal_id: String,
    signer_key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
}

impl EvidenceRecoveryFrontierV1 {
    fn validate(&self) -> Result<(), AgentdError> {
        if self.schema_version != 1
            || self.frontier_generation == 0
            || self.snapshot.schema_version != 1
            || self.snapshot.database_lineage != EVIDENCE_DATABASE_LINEAGE
        {
            return Err(invalid(
                "frontier schema, generation or database lineage is invalid",
            ));
        }
        StableId::new(self.store_id.clone())
            .map_err(|error| invalid(&format!("invalid recovery store id: {error}")))?;
        StableId::new(self.signer_principal_id.clone())
            .map_err(|error| invalid(&format!("invalid frontier signer principal: {error}")))?;
        Generation::new(self.signer_key_epoch)
            .map_err(|error| invalid(&format!("invalid frontier signer epoch: {error}")))?;
        validate_git_identity(&self.source_commit, "source commit")?;
        validate_git_identity(&self.source_tree, "source tree")?;
        let now = current_time_millis()?;
        if self.created_at_unix_ms > now.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS) {
            return Err(invalid("frontier creation time is too far in the future"));
        }
        let _: [u8; 64] = hex_bytes(&self.signature_hex)?;
        Ok(())
    }
}

pub fn evidence_recovery_frontier_signing_bytes(
    frontier: &EvidenceRecoveryFrontierV1,
) -> Result<Vec<u8>, AgentdError> {
    frontier.validate()?;
    let mut bytes = b"hepta.kernel.evidence.recovery-frontier.v1\0".to_vec();
    push_part(&mut bytes, frontier.store_id.as_bytes());
    bytes.extend_from_slice(&frontier.frontier_generation.to_be_bytes());
    push_part(&mut bytes, frontier.snapshot.database_lineage.as_bytes());
    push_part(
        &mut bytes,
        frontier.snapshot.migration_set_sha256.as_str().as_bytes(),
    );
    bytes.extend_from_slice(&frontier.snapshot.qualification_max_seq.to_be_bytes());
    push_part(
        &mut bytes,
        frontier
            .snapshot
            .qualification_frontier_sha256
            .as_str()
            .as_bytes(),
    );
    push_part(
        &mut bytes,
        frontier
            .snapshot
            .authbus_replay_frontier_sha256
            .as_str()
            .as_bytes(),
    );
    push_part(&mut bytes, frontier.source_commit.as_bytes());
    push_part(&mut bytes, frontier.source_tree.as_bytes());
    bytes.extend_from_slice(&frontier.created_at_unix_ms.to_be_bytes());
    push_part(&mut bytes, frontier.signer_principal_id.as_bytes());
    bytes.extend_from_slice(&frontier.signer_key_epoch.to_be_bytes());
    Ok(bytes)
}

pub(crate) async fn verify_evidence_recovery_frontier(
    identity: &AgentdIdentity,
    store: &HeptaEvidenceStore,
    frontier_file: &Path,
    signer_trust_file: &Path,
) -> Result<(), AgentdError> {
    let frontier_bytes = read_external_file(frontier_file, identity, MAX_FRONTIER_FILE_BYTES)?;
    let frontier: EvidenceRecoveryFrontierV1 = serde_json::from_slice(&frontier_bytes)?;
    frontier.validate()?;

    let trust_bytes =
        read_external_file(signer_trust_file, identity, MAX_FRONTIER_TRUST_FILE_BYTES)?;
    let trust: EvidenceRecoveryFrontierTrustV1 = serde_json::from_slice(&trust_bytes)?;
    if trust.schema_version != 1
        || trust.revoked
        || trust.signer_principal_id != frontier.signer_principal_id
        || trust.signer_key_epoch != frontier.signer_key_epoch
    {
        return Err(recovery_required(
            "frontier signer trust is missing, revoked or mismatched",
        ));
    }
    StableId::new(trust.signer_principal_id.clone())
        .map_err(|error| invalid(&format!("invalid trusted frontier signer: {error}")))?;
    Generation::new(trust.signer_key_epoch)
        .map_err(|error| invalid(&format!("invalid trusted frontier epoch: {error}")))?;
    let verifying_key = VerifyingKey::from_bytes(&hex_bytes(&trust.public_key_hex)?)
        .map_err(|_| invalid("invalid trusted frontier Ed25519 public key"))?;
    let signature = Signature::from_bytes(&hex_bytes(&frontier.signature_hex)?);
    verifying_key
        .verify_strict(
            &evidence_recovery_frontier_signing_bytes(&frontier)?,
            &signature,
        )
        .map_err(|_| recovery_required("frontier signature verification failed"))?;

    if let Some(existing_store_id) = store.recovery_store_id().await.map_err(evidence_error)?
        && existing_store_id != frontier.store_id
    {
        return Err(recovery_required(
            "frontier store id does not match the bound evidence database",
        ));
    }

    let actual = store.recovery_snapshot().await.map_err(evidence_error)?;
    if actual != frontier.snapshot {
        return Err(recovery_required(
            "local evidence/replay frontier does not match the signed checkpoint",
        ));
    }
    store
        .bind_recovery_store_id(&frontier.store_id)
        .await
        .map_err(evidence_error)?;
    Ok(())
}

#[cfg(unix)]
fn read_external_file(
    path: &Path,
    identity: &AgentdIdentity,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err(invalid("recovery frontier files must use absolute paths"));
    }
    let canonical = path.canonicalize()?;
    let home = identity.home_root.canonicalize()?;
    if canonical != path || canonical.starts_with(&home) {
        return Err(invalid(
            "recovery frontier files must be canonical and outside the Agent home rollback domain",
        ));
    }
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.nlink() != 1
        || before.mode() & 0o022 != 0
        || before.len() > maximum_bytes
    {
        return Err(invalid(
            "recovery frontier files must be bounded, regular and not writable by group/other",
        ));
    }
    let mut file = File::open(path)?;
    let opened = file.metadata()?;
    let identity_tuple = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    if identity_tuple(&opened) != identity_tuple(&before) {
        return Err(invalid("recovery frontier file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || !after.is_file()
        || identity_tuple(&after) != identity_tuple(&before)
        || identity_tuple(&file.metadata()?) != identity_tuple(&before)
    {
        return Err(invalid("recovery frontier file changed while reading"));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_external_file(
    _path: &Path,
    _identity: &AgentdIdentity,
    _maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        "the signed recovery-frontier profile currently requires Unix file identity checks",
    ))
}

fn validate_git_identity(value: &str, label: &str) -> Result<(), AgentdError> {
    if !matches!(value.len(), 40 | 64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(&format!(
            "{label} must be a 40- or 64-character lowercase hexadecimal object id"
        )));
    }
    Ok(())
}

fn current_time_millis() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| invalid(&format!("system clock is before Unix epoch: {error}")))?
        .as_millis();
    u64::try_from(millis).map_err(|error| invalid(&format!("system clock overflow: {error}")))
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

fn evidence_error(error: codex_hepta_evidence::EvidenceError) -> AgentdError {
    recovery_required(&error.to_string())
}

fn recovery_required(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence recovery_required: {message}"))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence recovery: {message}"))
}
