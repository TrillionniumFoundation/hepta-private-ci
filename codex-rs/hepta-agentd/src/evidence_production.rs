//! Fail-closed production admission for kernel.evidence.
//!
//! Development keeps the schema-v1 local signed-frontier profile. Production
//! requires schema v2 and binds the exact trust registry, running binary,
//! qualification status, migration set, ledger root, external backend identity,
//! and durable backup publication receipt.

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EVIDENCE_DATABASE_LINEAGE;
use codex_hepta_evidence::EvidenceFrontierBackendIdentityV1;
use codex_hepta_evidence::EvidenceRecoverySnapshotV1;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::authbus_trust::hex_bytes;
use crate::evidence_mode::EvidenceProductionAdmissionFiles;
use crate::evidence_trust::EvidenceTrust;

const MAX_PRODUCTION_ADMISSION_FILE_BYTES: u64 = 256 * 1024;
const MAX_PRODUCTION_SIGNERS: usize = 8;
const MAX_FUTURE_CLOCK_SKEW_MS: u64 = 5 * 60 * 1000;
const MAX_FRONTIER_AGE_MS: u64 = 30 * 24 * 60 * 60 * 1000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct EvidenceRecoveryFrontierV2 {
    pub schema_version: u32,
    pub store_id: String,
    pub frontier_generation: u64,
    pub snapshot: EvidenceRecoverySnapshotV1,
    pub ledger_root_sha256: Sha256Digest,
    pub evidence_trust_registry_sha256: Sha256Digest,
    pub recovery_signer_trust_sha256: Sha256Digest,
    pub build_identity_sha256: Sha256Digest,
    pub qualification_status_sha256: Sha256Digest,
    pub backend_identity_sha256: Sha256Digest,
    pub source_commit: String,
    pub source_tree: String,
    pub created_at_unix_ms: u64,
    pub signer_principal_id: String,
    pub signer_key_epoch: u64,
    pub signature_hex: String,
}

impl EvidenceRecoveryFrontierV2 {
    fn validate(&self) -> Result<(), AgentdError> {
        if self.schema_version != 2
            || self.frontier_generation == 0
            || self.snapshot.schema_version != 1
            || self.snapshot.database_lineage != EVIDENCE_DATABASE_LINEAGE
        {
            return Err(invalid(
                "production frontier schema, generation, or database lineage is invalid",
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
            return Err(invalid("production frontier creation time is in the future"));
        }
        if now.saturating_sub(self.created_at_unix_ms) > MAX_FRONTIER_AGE_MS {
            return Err(recovery_required(
                "production frontier is older than the 30-day admission window",
            ));
        }
        let _: [u8; 64] = hex_bytes(&self.signature_hex)?;
        Ok(())
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RecoverySignerV2 {
    signer_principal_id: String,
    signer_key_epoch: u64,
    public_key_hex: String,
    revoked: bool,
    valid_from_frontier_generation: u64,
    valid_through_frontier_generation: Option<u64>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceRecoveryFrontierTrustV2 {
    schema_version: u32,
    signers: Vec<RecoverySignerV2>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceBuildIdentityV1 {
    schema_version: u32,
    source_commit: String,
    source_tree: String,
    binary_sha256: String,
    migration_set_sha256: String,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct EvidenceQualificationStatusV1 {
    schema_version: u32,
    module: String,
    as_of_commit: String,
    as_of_tree: String,
    workflow_run_id: String,
    exact_source_qualified: bool,
    merge_candidate_required: bool,
    merge_candidate_qualified: bool,
    all_required_qualification_lanes_passed: bool,
    artifacts: EvidenceQualificationArtifactsV1,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct EvidenceQualificationArtifactsV1 {
    exact_source_sha256: Option<String>,
    merge_candidate_sha256: Option<String>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceBackupPublicationV1 {
    schema_version: u32,
    store_id: String,
    backend_id: String,
    backend_key_epoch: u64,
    backend_audit_event_id: String,
    expected_generation: Option<u64>,
    committed_generation: u64,
    frontier_signing_sha256: String,
    snapshot_sha256: String,
    backend_identity_sha256: String,
    durable_acknowledgement_sha256: String,
    published_at_unix_ms: u64,
}

pub fn evidence_recovery_frontier_v2_signing_bytes(
    frontier: &EvidenceRecoveryFrontierV2,
) -> Result<Vec<u8>, AgentdError> {
    frontier.validate()?;
    let mut bytes = b"hepta.kernel.evidence.recovery-frontier.v2\0".to_vec();
    push_part(&mut bytes, frontier.store_id.as_bytes());
    bytes.extend_from_slice(&frontier.frontier_generation.to_be_bytes());
    push_snapshot(&mut bytes, &frontier.snapshot);
    for digest in [
        &frontier.ledger_root_sha256,
        &frontier.evidence_trust_registry_sha256,
        &frontier.recovery_signer_trust_sha256,
        &frontier.build_identity_sha256,
        &frontier.qualification_status_sha256,
        &frontier.backend_identity_sha256,
    ] {
        push_part(&mut bytes, digest.as_str().as_bytes());
    }
    push_part(&mut bytes, frontier.source_commit.as_bytes());
    push_part(&mut bytes, frontier.source_tree.as_bytes());
    bytes.extend_from_slice(&frontier.created_at_unix_ms.to_be_bytes());
    push_part(&mut bytes, frontier.signer_principal_id.as_bytes());
    bytes.extend_from_slice(&frontier.signer_key_epoch.to_be_bytes());
    Ok(bytes)
}

pub(crate) async fn verify_production_evidence_recovery_frontier(
    identity: &AgentdIdentity,
    store: &HeptaEvidenceStore,
    evidence_trust_file: &Path,
    frontier_file: &Path,
    signer_trust_file: &Path,
    production: &EvidenceProductionAdmissionFiles,
) -> Result<(), AgentdError> {
    let frontier_bytes = read_external_file(
        frontier_file,
        identity,
        MAX_PRODUCTION_ADMISSION_FILE_BYTES,
    )?;
    let frontier: EvidenceRecoveryFrontierV2 = serde_json::from_slice(&frontier_bytes)?;
    frontier.validate()?;

    let signer_trust_bytes = read_external_file(
        signer_trust_file,
        identity,
        MAX_PRODUCTION_ADMISSION_FILE_BYTES,
    )?;
    require_digest(
        &signer_trust_bytes,
        &frontier.recovery_signer_trust_sha256,
        "recovery signer trust",
    )?;
    let signer_trust: EvidenceRecoveryFrontierTrustV2 =
        serde_json::from_slice(&signer_trust_bytes)?;
    let verifying_key = active_signer_key(&signer_trust, &frontier)?;
    let signature = Signature::from_bytes(&hex_bytes(&frontier.signature_hex)?);
    let signing_bytes = evidence_recovery_frontier_v2_signing_bytes(&frontier)?;
    verifying_key
        .verify_strict(&signing_bytes, &signature)
        .map_err(|_| recovery_required("production frontier signature verification failed"))?;

    let evidence_trust = EvidenceTrust::load(evidence_trust_file, identity)?;
    if evidence_trust.registry_sha256()? != &frontier.evidence_trust_registry_sha256 {
        return Err(recovery_required(
            "active evidence trust registry is not bound by the production frontier",
        ));
    }

    let backend_identity_bytes = read_external_file(
        &production.backend_identity_file,
        identity,
        MAX_PRODUCTION_ADMISSION_FILE_BYTES,
    )?;
    require_digest(
        &backend_identity_bytes,
        &frontier.backend_identity_sha256,
        "frontier backend identity",
    )?;
    let backend_identity: EvidenceFrontierBackendIdentityV1 =
        serde_json::from_slice(&backend_identity_bytes)?;
    backend_identity
        .validate_for_production(&production.local_rollback_domain_id)
        .map_err(|error| recovery_required(&error.to_string()))?;

    let build_identity_bytes = read_external_file(
        &production.build_identity_file,
        identity,
        MAX_PRODUCTION_ADMISSION_FILE_BYTES,
    )?;
    require_digest(
        &build_identity_bytes,
        &frontier.build_identity_sha256,
        "build identity",
    )?;
    let build: EvidenceBuildIdentityV1 = serde_json::from_slice(&build_identity_bytes)?;
    verify_build_identity(&build, &frontier)?;

    let qualification_status_bytes = read_external_file(
        &production.qualification_status_file,
        identity,
        MAX_PRODUCTION_ADMISSION_FILE_BYTES,
    )?;
    require_digest(
        &qualification_status_bytes,
        &frontier.qualification_status_sha256,
        "qualification status",
    )?;
    let qualification: EvidenceQualificationStatusV1 =
        serde_json::from_slice(&qualification_status_bytes)?;
    verify_qualification_status(&qualification, &frontier)?;

    if let Some(existing_store_id) = store.recovery_store_id().await.map_err(evidence_error)?
        && existing_store_id != frontier.store_id
    {
        return Err(recovery_required(
            "production frontier store id does not match the bound evidence database",
        ));
    }
    let actual = store.recovery_snapshot().await.map_err(evidence_error)?;
    if actual != frontier.snapshot {
        return Err(recovery_required(
            "local evidence/replay frontier does not match the production checkpoint",
        ));
    }
    let actual_ledger_root = evidence_ledger_root(&frontier.store_id, &actual);
    if actual_ledger_root != frontier.ledger_root_sha256 {
        return Err(recovery_required(
            "production frontier ledger root does not match the local evidence ledger",
        ));
    }

    let backup_bytes = read_external_file(
        &production.backup_publication_file,
        identity,
        MAX_PRODUCTION_ADMISSION_FILE_BYTES,
    )?;
    let backup: EvidenceBackupPublicationV1 = serde_json::from_slice(&backup_bytes)?;
    verify_backup_publication(
        &backup,
        &frontier,
        &backend_identity,
        &signing_bytes,
    )?;

    store
        .bind_recovery_store_id(&frontier.store_id)
        .await
        .map_err(evidence_error)?;
    Ok(())
}

fn active_signer_key(
    trust: &EvidenceRecoveryFrontierTrustV2,
    frontier: &EvidenceRecoveryFrontierV2,
) -> Result<VerifyingKey, AgentdError> {
    if trust.schema_version != 2
        || trust.signers.is_empty()
        || trust.signers.len() > MAX_PRODUCTION_SIGNERS
    {
        return Err(recovery_required(
            "production signer trust schema or signer bounds are invalid",
        ));
    }
    let mut identities = std::collections::BTreeSet::new();
    for signer in &trust.signers {
        if !identities.insert((signer.signer_principal_id.clone(), signer.signer_key_epoch)) {
            return Err(recovery_required(
                "production signer trust contains duplicate principal epochs",
            ));
        }
        StableId::new(signer.signer_principal_id.clone())
            .map_err(|error| invalid(&format!("invalid trusted signer: {error}")))?;
        Generation::new(signer.signer_key_epoch)
            .map_err(|error| invalid(&format!("invalid trusted signer epoch: {error}")))?;
        if signer.valid_from_frontier_generation == 0
            || signer
                .valid_through_frontier_generation
                .is_some_and(|through| through < signer.valid_from_frontier_generation)
        {
            return Err(recovery_required(
                "production signer generation window is invalid",
            ));
        }
    }
    let signer = trust
        .signers
        .iter()
        .find(|candidate| {
            candidate.signer_principal_id == frontier.signer_principal_id
                && candidate.signer_key_epoch == frontier.signer_key_epoch
        })
        .ok_or_else(|| recovery_required("frontier signer is not trusted"))?;
    if signer.revoked
        || frontier.frontier_generation < signer.valid_from_frontier_generation
        || signer
            .valid_through_frontier_generation
            .is_some_and(|through| frontier.frontier_generation > through)
    {
        return Err(recovery_required(
            "frontier signer is revoked or outside its rotation window",
        ));
    }
    VerifyingKey::from_bytes(&hex_bytes(&signer.public_key_hex)?)
        .map_err(|_| invalid("invalid production frontier Ed25519 public key"))
}

fn verify_build_identity(
    build: &EvidenceBuildIdentityV1,
    frontier: &EvidenceRecoveryFrontierV2,
) -> Result<(), AgentdError> {
    validate_hex_digest(&build.binary_sha256, "build binary digest")?;
    validate_hex_digest(&build.migration_set_sha256, "build migration-set digest")?;
    if build.schema_version != 1
        || build.source_commit != frontier.source_commit
        || build.source_tree != frontier.source_tree
        || build.migration_set_sha256 != frontier.snapshot.migration_set_sha256.as_str()
    {
        return Err(recovery_required(
            "build identity is stale or mismatched with the production frontier",
        ));
    }
    let executable = std::env::current_exe()?;
    let actual_binary_sha256 = sha256_file(&executable)?;
    if actual_binary_sha256 != build.binary_sha256 {
        return Err(recovery_required(
            "running Agentd binary does not match the admitted build identity",
        ));
    }
    Ok(())
}

fn verify_qualification_status(
    status: &EvidenceQualificationStatusV1,
    frontier: &EvidenceRecoveryFrontierV2,
) -> Result<(), AgentdError> {
    if status.schema_version != 1
        || status.module != "kernel.evidence"
        || status.workflow_run_id.is_empty()
        || status.as_of_commit != frontier.source_commit
        || status.as_of_tree != frontier.source_tree
        || !status.exact_source_qualified
        || !status.all_required_qualification_lanes_passed
        || (status.merge_candidate_required && !status.merge_candidate_qualified)
    {
        return Err(recovery_required(
            "current candidate lacks a matching successful qualification status",
        ));
    }
    let exact = status
        .artifacts
        .exact_source_sha256
        .as_deref()
        .ok_or_else(|| recovery_required("qualification status lacks exact-source artifact"))?;
    validate_hex_digest(exact, "exact-source artifact digest")?;
    if status.merge_candidate_required {
        let merge = status
            .artifacts
            .merge_candidate_sha256
            .as_deref()
            .ok_or_else(|| {
                recovery_required("qualification status lacks merge-candidate artifact")
            })?;
        validate_hex_digest(merge, "merge-candidate artifact digest")?;
    }
    Ok(())
}

fn verify_backup_publication(
    backup: &EvidenceBackupPublicationV1,
    frontier: &EvidenceRecoveryFrontierV2,
    backend: &EvidenceFrontierBackendIdentityV1,
    signing_bytes: &[u8],
) -> Result<(), AgentdError> {
    StableId::new(backup.backend_audit_event_id.clone())
        .map_err(|error| invalid(&format!("invalid backend audit event id: {error}")))?;
    validate_hex_digest(
        &backup.frontier_signing_sha256,
        "backup frontier signing digest",
    )?;
    validate_hex_digest(&backup.snapshot_sha256, "backup snapshot digest")?;
    validate_hex_digest(
        &backup.backend_identity_sha256,
        "backup backend identity digest",
    )?;
    validate_hex_digest(
        &backup.durable_acknowledgement_sha256,
        "durable acknowledgement digest",
    )?;
    let expected_generation = frontier.frontier_generation.checked_sub(1);
    let snapshot_bytes = serde_json::to_vec(&frontier.snapshot)?;
    let now = current_time_millis()?;
    if backup.schema_version != 1
        || backup.store_id != frontier.store_id
        || backup.backend_id != backend.backend_id
        || backup.backend_key_epoch != backend.authentication_key_epoch
        || backup.expected_generation != expected_generation.filter(|value| *value != 0)
        || backup.committed_generation != frontier.frontier_generation
        || backup.frontier_signing_sha256
            != Sha256Digest::for_bytes(signing_bytes).as_str()
        || backup.snapshot_sha256 != Sha256Digest::for_bytes(&snapshot_bytes).as_str()
        || backup.backend_identity_sha256 != frontier.backend_identity_sha256.as_str()
        || backup.published_at_unix_ms < frontier.created_at_unix_ms
        || backup.published_at_unix_ms > now.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS)
    {
        return Err(recovery_required(
            "backup publication is not a durable CAS receipt for this frontier",
        ));
    }
    Ok(())
}

pub fn evidence_ledger_root(
    store_id: &str,
    snapshot: &EvidenceRecoverySnapshotV1,
) -> Sha256Digest {
    let mut bytes = b"hepta.kernel.evidence.ledger-root.v1\0".to_vec();
    push_part(&mut bytes, store_id.as_bytes());
    push_snapshot(&mut bytes, snapshot);
    Sha256Digest::for_bytes(&bytes)
}

fn push_snapshot(bytes: &mut Vec<u8>, snapshot: &EvidenceRecoverySnapshotV1) {
    bytes.extend_from_slice(&snapshot.schema_version.to_be_bytes());
    push_part(bytes, snapshot.database_lineage.as_bytes());
    push_part(bytes, snapshot.migration_set_sha256.as_str().as_bytes());
    bytes.extend_from_slice(&snapshot.qualification_max_seq.to_be_bytes());
    push_part(
        bytes,
        snapshot.qualification_frontier_sha256.as_str().as_bytes(),
    );
    push_part(
        bytes,
        snapshot.authbus_replay_frontier_sha256.as_str().as_bytes(),
    );
}

fn require_digest(
    bytes: &[u8],
    expected: &Sha256Digest,
    label: &str,
) -> Result<(), AgentdError> {
    if &Sha256Digest::for_bytes(bytes) != expected {
        return Err(recovery_required(&format!(
            "{label} digest does not match the signed frontier"
        )));
    }
    Ok(())
}

fn sha256_file(path: &Path) -> Result<String, AgentdError> {
    let metadata = std::fs::metadata(path)?;
    if !metadata.is_file() {
        return Err(invalid("running Agentd path is not a regular file"));
    }
    let mut file = File::open(path)?;
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        hasher.update(&buffer[..read]);
    }
    Ok(format!("{:x}", hasher.finalize()))
}

#[cfg(unix)]
fn read_external_file(
    path: &Path,
    identity: &AgentdIdentity,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    if !path.is_absolute() {
        return Err(invalid("production admission files must use absolute paths"));
    }
    let canonical = path.canonicalize()?;
    let home = identity.home_root.canonicalize()?;
    if canonical != path || canonical.starts_with(&home) {
        return Err(invalid(
            "production admission files must be canonical and outside the Agent home rollback domain",
        ));
    }
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.nlink() != 1
        || before.mode() & 0o022 != 0
        || before.len() > maximum_bytes
    {
        return Err(invalid(
            "production admission files must be bounded, regular, and not writable by group/other",
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
        return Err(invalid("production admission file changed while opening"));
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
        return Err(invalid("production admission file changed while reading"));
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
        "kernel.evidence production mode currently requires Unix file identity checks",
    ))
}

fn validate_git_identity(value: &str, label: &str) -> Result<(), AgentdError> {
    if !matches!(value.len(), 40 | 64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(&format!(
            "{label} must be a lowercase hexadecimal Git object id"
        )));
    }
    Ok(())
}

fn validate_hex_digest(value: &str, label: &str) -> Result<(), AgentdError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(invalid(&format!(
            "{label} must be a lowercase SHA-256 digest"
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
    AgentdError::Invalid(format!(
        "kernel.evidence production recovery_required: {message}"
    ))
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence production: {message}"))
}
