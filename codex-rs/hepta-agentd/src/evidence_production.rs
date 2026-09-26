//! Fail-closed production admission for kernel.evidence.
//!
//! The owner descriptor lives in the Agent home, while every mutable recovery
//! authority and receipt lives under a separately mounted external backend.
//! Startup succeeds only when the current executable, issuer trust, signer
//! policy, source/merge qualification receipts, durable backup publication and
//! local SQLite snapshot all match the latest signed external frontier.

use std::collections::BTreeSet;
#[cfg(unix)]
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_evidence::EvidenceAcceptedFrontierV1;
use codex_hepta_evidence::EvidenceFrontierBackend;
use codex_hepta_evidence::EvidenceRecoveryFrontierV2;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_evidence::LockedFileEvidenceFrontierBackend;
use codex_hepta_evidence::evidence_recovery_frontier_v2_sha256;
use codex_hepta_evidence::evidence_recovery_ledger_root_v2;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde_json::Value;
use sha2::Digest;
use sha2::Sha256;

use crate::AgentdError;
use crate::AgentdIdentity;
use crate::evidence_frontier_signers::EvidenceFrontierSignerTrustV2;
use crate::evidence_trust::EvidenceTrust;
use crate::evidence_trust::read_owner_file;

const PRODUCTION_CONFIG_SCHEMA_VERSION: u32 = 1;
const BACKUP_PUBLICATION_SCHEMA_VERSION: u32 = 1;
const MAX_EXTERNAL_CONTROL_FILE_BYTES: u64 = 2 * 1024 * 1024;
const MAX_EXECUTABLE_BYTES: u64 = 4 * 1024 * 1024 * 1024;
const MAX_FRONTIER_AGE_MS: u64 = 30 * 24 * 60 * 60 * 1000;
const MAX_FUTURE_CLOCK_SKEW_MS: u64 = 5 * 60 * 1000;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceProductionConfigV1 {
    schema_version: u32,
    mode: String,
    agent_id: String,
    store_id: String,
    external_backend_root: PathBuf,
    backend_identity_sha256: Sha256Digest,
    exact_source_receipt_file: PathBuf,
    merge_candidate_receipt_file: PathBuf,
    backup_publication_receipt_file: PathBuf,
    minimum_frontier_generation: u64,
    frontier_max_age_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceBackupPublicationReceiptV1 {
    schema_version: u32,
    store_id: String,
    frontier_generation: u64,
    snapshot_sha256: Sha256Digest,
    backend_identity_sha256: Sha256Digest,
    published_at_unix_ms: u64,
    durable_acknowledged: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct QualifiedSourceIdentity {
    source_commit: String,
    source_tree: String,
}

pub(crate) fn is_production_evidence_profile(
    identity: &AgentdIdentity,
    descriptor_or_frontier: &Path,
) -> bool {
    descriptor_or_frontier.parent() == Some(identity.home_root.as_path())
}

pub(crate) async fn verify_production_evidence_frontier(
    identity: &AgentdIdentity,
    store: &HeptaEvidenceStore,
    issuer_trust_file: &Path,
    production_config_file: &Path,
    signer_trust_file: &Path,
) -> Result<(), AgentdError> {
    let config_bytes = read_owner_file(production_config_file, identity)?;
    let config: EvidenceProductionConfigV1 = serde_json::from_slice(&config_bytes)?;
    config.validate(identity)?;

    let root = config.external_backend_root.canonicalize()?;
    if root != config.external_backend_root {
        return Err(recovery_required(
            "external frontier backend root must be canonical",
        ));
    }
    let external_files = [
        signer_trust_file,
        config.exact_source_receipt_file.as_path(),
        config.merge_candidate_receipt_file.as_path(),
        config.backup_publication_receipt_file.as_path(),
    ];
    let mut unique_files = BTreeSet::new();
    for path in external_files {
        if !unique_files.insert(path.to_path_buf()) {
            return Err(recovery_required(
                "production evidence control files must be role-distinct",
            ));
        }
    }

    let signer_trust_bytes = read_external_private_file(
        signer_trust_file,
        &root,
        identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let exact_source_bytes = read_external_private_file(
        &config.exact_source_receipt_file,
        &root,
        identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let merge_candidate_bytes = read_external_private_file(
        &config.merge_candidate_receipt_file,
        &root,
        identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;
    let backup_publication_bytes = read_external_private_file(
        &config.backup_publication_receipt_file,
        &root,
        identity,
        MAX_EXTERNAL_CONTROL_FILE_BYTES,
    )?;

    let signer_trust = EvidenceFrontierSignerTrustV2::parse(&signer_trust_bytes)?;
    let signer_trust_sha256 = Sha256Digest::for_bytes(&signer_trust_bytes);
    let (_, issuer_trust_sha256) = EvidenceTrust::load_with_digest(issuer_trust_file, identity)?;
    let qualified_source = validate_qualification_receipts(
        &exact_source_bytes,
        &merge_candidate_bytes,
    )?;
    let qualification_receipt_sha256 = qualification_receipt_set_sha256(
        &Sha256Digest::for_bytes(&exact_source_bytes),
        &Sha256Digest::for_bytes(&merge_candidate_bytes),
    );
    let backup_publication_sha256 = Sha256Digest::for_bytes(&backup_publication_bytes);
    let backup: EvidenceBackupPublicationReceiptV1 =
        serde_json::from_slice(&backup_publication_bytes)?;
    let build_artifact_sha256 = current_executable_sha256()?;

    let mut backend = LockedFileEvidenceFrontierBackend::open_external(
        &root,
        config.backend_identity_sha256.clone(),
        &identity.home_root,
    )
    .map_err(backend_error)?;
    backend.verify_backend_identity().map_err(backend_error)?;
    let frontier = backend
        .get_latest(&config.store_id)
        .map_err(backend_error)?
        .ok_or_else(|| recovery_required("external frontier backend has no published frontier"))?;
    frontier
        .validate_structure()
        .map_err(|error| recovery_required(&error.to_string()))?;

    let now = current_time_millis()?;
    if frontier.created_at_unix_ms > now.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS)
        || now.saturating_sub(frontier.created_at_unix_ms) > config.frontier_max_age_ms
    {
        return Err(recovery_required(
            "latest external frontier is outside the configured freshness window",
        ));
    }
    if frontier.frontier_generation < config.minimum_frontier_generation
        || frontier.store_id != config.store_id
        || frontier.source_commit != qualified_source.source_commit
        || frontier.source_tree != qualified_source.source_tree
        || frontier.issuer_trust_registry_sha256 != issuer_trust_sha256
        || frontier.frontier_signer_registry_sha256 != signer_trust_sha256
        || frontier.backend_identity_sha256 != config.backend_identity_sha256
        || frontier.build_artifact_sha256 != build_artifact_sha256
        || frontier.qualification_receipt_sha256 != qualification_receipt_sha256
        || frontier.backup_publication_sha256 != backup_publication_sha256
    {
        return Err(recovery_required(
            "latest external frontier does not match the production identity pins",
        ));
    }
    signer_trust.verify(&frontier)?;
    validate_backup_publication(&backup, &frontier, now, config.frontier_max_age_ms)?;

    let actual_snapshot = store.recovery_snapshot().await.map_err(evidence_error)?;
    if actual_snapshot != frontier.snapshot
        || evidence_recovery_ledger_root_v2(&actual_snapshot) != frontier.ledger_root_sha256
    {
        return Err(recovery_required(
            "local evidence database does not match the latest external ledger root",
        ));
    }
    let frontier_sha256 = evidence_recovery_frontier_v2_sha256(&frontier)
        .map_err(|error| recovery_required(&error.to_string()))?;
    store
        .accept_recovery_frontier(&EvidenceAcceptedFrontierV1 {
            store_id: frontier.store_id,
            frontier_generation: frontier.frontier_generation,
            frontier_sha256,
            backend_identity_sha256: frontier.backend_identity_sha256,
            accepted_at_unix_ms: now,
        })
        .await
        .map_err(evidence_error)?;
    Ok(())
}

impl EvidenceProductionConfigV1 {
    fn validate(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.schema_version != PRODUCTION_CONFIG_SCHEMA_VERSION
            || self.mode != "production"
            || self.agent_id != identity.agent_id.as_str()
            || self.minimum_frontier_generation == 0
            || self.frontier_max_age_ms == 0
            || self.frontier_max_age_ms > MAX_FRONTIER_AGE_MS
        {
            return Err(recovery_required(
                "production evidence descriptor schema, owner, generation or freshness policy is invalid",
            ));
        }
        StableId::new(self.store_id.clone())
            .map_err(|error| recovery_required(&format!("invalid recovery store id: {error}")))?;
        validate_digest(&self.backend_identity_sha256, "backend identity")?;
        for path in [
            &self.external_backend_root,
            &self.exact_source_receipt_file,
            &self.merge_candidate_receipt_file,
            &self.backup_publication_receipt_file,
        ] {
            if !path.is_absolute() {
                return Err(recovery_required(
                    "production evidence paths must be absolute",
                ));
            }
        }
        Ok(())
    }
}

fn validate_qualification_receipts(
    exact_source_bytes: &[u8],
    merge_candidate_bytes: &[u8],
) -> Result<QualifiedSourceIdentity, AgentdError> {
    let exact: Value = serde_json::from_slice(exact_source_bytes)?;
    validate_status_common(&exact, "kernel_evidence_exact_source", "exactSourceQualified")?;
    let candidate = exact
        .get("candidate")
        .and_then(Value::as_object)
        .ok_or_else(|| recovery_required("exact-source receipt has no candidate object"))?;
    let source_commit = required_string(candidate.get("asOfCommit"), "exact-source commit")?;
    let source_tree = required_string(candidate.get("asOfTree"), "exact-source tree")?;
    validate_git_identity(&source_commit, "exact-source commit")?;
    validate_git_identity(&source_tree, "exact-source tree")?;
    if required_string(candidate.get("sourceCommit"), "exact-source source commit")?
        != source_commit
    {
        return Err(recovery_required(
            "exact-source receipt candidate identity is internally inconsistent",
        ));
    }

    let merge: Value = serde_json::from_slice(merge_candidate_bytes)?;
    validate_status_common(
        &merge,
        "kernel_evidence_synthetic_merge",
        "mergeCandidateQualified",
    )?;
    let merge_candidate = merge
        .get("candidate")
        .and_then(Value::as_object)
        .ok_or_else(|| recovery_required("merge receipt has no candidate object"))?;
    if required_string(
        merge_candidate.get("sourceCommit"),
        "merge receipt source commit",
    )? != source_commit
    {
        return Err(recovery_required(
            "merge receipt is not bound to the exact-source candidate",
        ));
    }
    let parents = merge_candidate
        .get("parents")
        .and_then(Value::as_array)
        .ok_or_else(|| recovery_required("merge receipt has no parent vector"))?;
    if parents.len() != 2 || parents[1].as_str() != Some(source_commit.as_str()) {
        return Err(recovery_required(
            "merge receipt does not have the expected base/source parent order",
        ));
    }
    Ok(QualifiedSourceIdentity {
        source_commit,
        source_tree,
    })
}

fn validate_status_common(
    status: &Value,
    expected_kind: &str,
    qualification_flag: &str,
) -> Result<(), AgentdError> {
    if status.get("schemaVersion").and_then(Value::as_u64) != Some(1)
        || status.get("module").and_then(Value::as_str) != Some("kernel.evidence")
        || status.get("kind").and_then(Value::as_str) != Some(expected_kind)
        || status.get("qualified").and_then(Value::as_bool) != Some(true)
        || status.get(qualification_flag).and_then(Value::as_bool) != Some(true)
    {
        return Err(recovery_required(
            "qualification receipt schema, module, kind or disposition is invalid",
        ));
    }
    let candidate = status
        .get("candidate")
        .and_then(Value::as_object)
        .ok_or_else(|| recovery_required("qualification receipt has no candidate object"))?;
    if candidate.get("dirty").and_then(Value::as_bool) != Some(false)
        || candidate
            .get("identityErrors")
            .and_then(Value::as_array)
            .is_none_or(|errors| !errors.is_empty())
    {
        return Err(recovery_required(
            "qualification receipt candidate identity is dirty or rejected",
        ));
    }
    let checks = status
        .get("checks")
        .and_then(Value::as_object)
        .ok_or_else(|| recovery_required("qualification receipt has no check map"))?;
    if checks.is_empty()
        || checks
            .values()
            .any(|check| check.get("passed").and_then(Value::as_bool) != Some(true))
    {
        return Err(recovery_required(
            "qualification receipt contains a missing or failed command record",
        ));
    }
    let artifact = status
        .get("artifact")
        .and_then(Value::as_object)
        .ok_or_else(|| recovery_required("qualification receipt has no retained artifact"))?;
    let artifact_sha256 = required_string(artifact.get("sha256"), "artifact digest")?;
    Sha256Digest::parse(artifact_sha256)
        .map_err(|error| recovery_required(&format!("invalid artifact digest: {error}")))?;
    if artifact.get("id").and_then(Value::as_u64).unwrap_or(0) == 0
        || !artifact
            .get("url")
            .and_then(Value::as_str)
            .is_some_and(|url| url.starts_with("https://github.com/"))
    {
        return Err(recovery_required(
            "qualification receipt artifact identity is invalid",
        ));
    }
    if !status
        .get("workflow")
        .and_then(|workflow| workflow.get("workflowRunId"))
        .and_then(Value::as_str)
        .is_some_and(|run| !run.is_empty())
    {
        return Err(recovery_required(
            "qualification receipt is not bound to a workflow run",
        ));
    }
    Ok(())
}

fn validate_backup_publication(
    backup: &EvidenceBackupPublicationReceiptV1,
    frontier: &EvidenceRecoveryFrontierV2,
    now: u64,
    max_age_ms: u64,
) -> Result<(), AgentdError> {
    validate_digest(&backup.snapshot_sha256, "backup snapshot")?;
    validate_digest(&backup.backend_identity_sha256, "backup backend identity")?;
    let snapshot_bytes = serde_json::to_vec(&frontier.snapshot)?;
    if backup.schema_version != BACKUP_PUBLICATION_SCHEMA_VERSION
        || !backup.durable_acknowledged
        || backup.store_id != frontier.store_id
        || backup.frontier_generation != frontier.frontier_generation
        || backup.snapshot_sha256 != Sha256Digest::for_bytes(&snapshot_bytes)
        || backup.backend_identity_sha256 != frontier.backend_identity_sha256
        || backup.published_at_unix_ms > now.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS)
        || now.saturating_sub(backup.published_at_unix_ms) > max_age_ms
    {
        return Err(recovery_required(
            "backup publication receipt is not a current durable witness for the frontier",
        ));
    }
    Ok(())
}

fn qualification_receipt_set_sha256(
    exact_source: &Sha256Digest,
    merge_candidate: &Sha256Digest,
) -> Sha256Digest {
    let mut bytes = b"hepta.kernel.evidence.qualification-receipt-set.v1\0".to_vec();
    push_part(&mut bytes, exact_source.as_str().as_bytes());
    push_part(&mut bytes, merge_candidate.as_str().as_bytes());
    Sha256Digest::for_bytes(&bytes)
}

fn current_executable_sha256() -> Result<Sha256Digest, AgentdError> {
    let path = std::env::current_exe()?;
    let mut file = File::open(&path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() == 0 || metadata.len() > MAX_EXECUTABLE_BYTES {
        return Err(recovery_required(
            "current Agentd executable is not a bounded regular file",
        ));
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut observed = 0_u64;
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        observed = observed
            .checked_add(u64::try_from(count).unwrap_or(u64::MAX))
            .ok_or_else(|| recovery_required("current executable size overflow"))?;
        if observed > MAX_EXECUTABLE_BYTES {
            return Err(recovery_required(
                "current Agentd executable exceeds the bounded digest profile",
            ));
        }
        hasher.update(&buffer[..count]);
    }
    if observed != metadata.len() {
        return Err(recovery_required(
            "current Agentd executable changed while hashing",
        ));
    }
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}

#[cfg(unix)]
fn read_external_private_file(
    path: &Path,
    root: &Path,
    identity: &AgentdIdentity,
    maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;

    let home = identity.home_root.canonicalize()?;
    if !path.is_absolute()
        || path.parent() != Some(root)
        || root.starts_with(&home)
        || path.starts_with(&home)
        || path.canonicalize()? != path
    {
        return Err(recovery_required(
            "production evidence control files must be canonical direct children of the external backend",
        ));
    }
    let root_metadata = std::fs::metadata(root)?;
    let before = std::fs::symlink_metadata(path)?;
    if !root_metadata.is_dir()
        || root_metadata.mode() & 0o077 != 0
        || !before.is_file()
        || before.uid() != root_metadata.uid()
        || before.nlink() != 1
        || before.mode() & 0o077 != 0
        || before.len() == 0
        || before.len() > maximum_bytes
    {
        return Err(recovery_required(
            "production evidence control file is not private, owner-bound and bounded",
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
        return Err(recovery_required(
            "production evidence control file changed while opening",
        ));
    }
    let mut bytes = Vec::new();
    file.by_ref()
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || identity_tuple(&after) != identity_tuple(&before)
        || identity_tuple(&file.metadata()?) != identity_tuple(&before)
    {
        return Err(recovery_required(
            "production evidence control file changed while reading",
        ));
    }
    Ok(bytes)
}

#[cfg(not(unix))]
fn read_external_private_file(
    _path: &Path,
    _root: &Path,
    _identity: &AgentdIdentity,
    _maximum_bytes: u64,
) -> Result<Vec<u8>, AgentdError> {
    Err(recovery_required(
        "production evidence admission currently requires Unix file identity checks",
    ))
}

fn required_string(value: Option<&Value>, label: &str) -> Result<String, AgentdError> {
    value
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| recovery_required(&format!("{label} is missing")))
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), AgentdError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|error| recovery_required(&format!("invalid {label} digest: {error}")))
}

fn validate_git_identity(value: &str, label: &str) -> Result<(), AgentdError> {
    if !matches!(value.len(), 40 | 64)
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(recovery_required(&format!(
            "{label} must be a 40- or 64-character lowercase hexadecimal object id"
        )));
    }
    Ok(())
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

fn current_time_millis() -> Result<u64, AgentdError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| recovery_required(&format!("system clock is before Unix epoch: {error}")))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|error| recovery_required(&format!("system clock overflow: {error}")))
}

fn backend_error(error: codex_hepta_evidence::EvidenceFrontierBackendError) -> AgentdError {
    recovery_required(&error.to_string())
}

fn evidence_error(error: codex_hepta_evidence::EvidenceError) -> AgentdError {
    recovery_required(&error.to_string())
}

fn recovery_required(message: &str) -> AgentdError {
    AgentdError::Invalid(format!("kernel.evidence recovery_required: {message}"))
}

#[cfg(test)]
#[path = "evidence_production_tests.rs"]
mod tests;
