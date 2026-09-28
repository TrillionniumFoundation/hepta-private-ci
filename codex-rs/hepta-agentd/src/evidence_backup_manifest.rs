// Included in evidence_production.rs.  The signed frontier commits to the
// complete manifest bytes through `backup_publication_sha256`; production then
// verifies both the manifest semantics and the referenced backup object bytes.

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceBuildProvenanceV1 {
    schema_version: u32,
    repository: String,
    source_commit: String,
    source_tree: String,
    workflow_run_id: u64,
    workflow_run_attempt: u64,
    workflow_job: String,
    workflow_artifact_id: u64,
    workflow_artifact_url: String,
    workflow_artifact_sha256: Sha256Digest,
    builder_principal_id: String,
    toolchain_sha256: Sha256Digest,
    build_recipe_sha256: Sha256Digest,
    build_log_sha256: Sha256Digest,
    executable_sha256: Sha256Digest,
    executable_length: u64,
    built_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceBackupRestoreWitnessV1 {
    schema_version: u32,
    witness_principal_id: String,
    restored_object_sha256: Sha256Digest,
    restored_snapshot_sha256: Sha256Digest,
    sqlite_integrity_check_sha256: Sha256Digest,
    restored_at_unix_ms: u64,
    successful: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EvidenceBackupPublicationReceiptV1 {
    schema_version: u32,
    store_id: String,
    frontier_generation: u64,
    snapshot_sha256: Sha256Digest,
    backend_identity_sha256: Sha256Digest,
    backup_object_file_name: String,
    backup_object_id: String,
    backup_object_version: String,
    backup_object_length: u64,
    backup_object_sha256: Sha256Digest,
    storage_backend_identity_sha256: Sha256Digest,
    storage_acknowledgement_id: String,
    storage_acknowledgement_sha256: Sha256Digest,
    build_provenance: EvidenceBuildProvenanceV1,
    restore_witness: EvidenceBackupRestoreWitnessV1,
    published_at_unix_ms: u64,
    durable_acknowledged: bool,
}

fn validate_backup_publication(
    backup: &EvidenceBackupPublicationReceiptV1,
    frontier: &EvidenceRecoveryFrontierV2,
    observed_build_artifact_sha256: &Sha256Digest,
    now: u64,
    max_age_ms: u64,
) -> Result<(), AgentdError> {
    for (label, digest) in [
        ("backup snapshot", &backup.snapshot_sha256),
        ("backup frontier backend", &backup.backend_identity_sha256),
        ("backup object", &backup.backup_object_sha256),
        (
            "backup storage backend",
            &backup.storage_backend_identity_sha256,
        ),
        (
            "backup storage acknowledgement",
            &backup.storage_acknowledgement_sha256,
        ),
        (
            "build workflow artifact",
            &backup.build_provenance.workflow_artifact_sha256,
        ),
        ("build toolchain", &backup.build_provenance.toolchain_sha256),
        ("build recipe", &backup.build_provenance.build_recipe_sha256),
        ("build log", &backup.build_provenance.build_log_sha256),
        (
            "build executable",
            &backup.build_provenance.executable_sha256,
        ),
        (
            "restore object",
            &backup.restore_witness.restored_object_sha256,
        ),
        (
            "restore snapshot",
            &backup.restore_witness.restored_snapshot_sha256,
        ),
        (
            "restore integrity check",
            &backup.restore_witness.sqlite_integrity_check_sha256,
        ),
    ] {
        validate_digest(digest, label)?;
    }
    StableId::new(backup.store_id.clone())
        .map_err(|error| recovery_required(&format!("invalid backup store id: {error}")))?;
    StableId::new(backup.backup_object_id.clone())
        .map_err(|error| recovery_required(&format!("invalid backup object id: {error}")))?;
    StableId::new(backup.backup_object_version.clone())
        .map_err(|error| recovery_required(&format!("invalid backup object version: {error}")))?;
    StableId::new(backup.storage_acknowledgement_id.clone()).map_err(|error| {
        recovery_required(&format!(
            "invalid backup storage acknowledgement id: {error}"
        ))
    })?;
    StableId::new(backup.build_provenance.builder_principal_id.clone())
        .map_err(|error| recovery_required(&format!("invalid build principal id: {error}")))?;
    StableId::new(backup.restore_witness.witness_principal_id.clone()).map_err(|error| {
        recovery_required(&format!("invalid restore witness principal id: {error}"))
    })?;
    validate_repository_slug(&backup.build_provenance.repository)?;
    validate_git_identity(
        &backup.build_provenance.source_commit,
        "build source commit",
    )?;
    validate_git_identity(&backup.build_provenance.source_tree, "build source tree")?;
    validate_backup_object_name(&backup.backup_object_file_name)?;

    let snapshot_bytes = serde_json::to_vec(&frontier.snapshot)?;
    let expected_artifact_url = format!(
        "https://github.com/{}/actions/runs/{}/artifacts/{}",
        backup.build_provenance.repository,
        backup.build_provenance.workflow_run_id,
        backup.build_provenance.workflow_artifact_id
    );
    let build = &backup.build_provenance;
    let restore = &backup.restore_witness;
    if backup.schema_version != BACKUP_PUBLICATION_SCHEMA_VERSION
        || build.schema_version != BUILD_PROVENANCE_SCHEMA_VERSION
        || restore.schema_version != BACKUP_RESTORE_WITNESS_SCHEMA_VERSION
        || !backup.durable_acknowledged
        || !restore.successful
        || backup.store_id != frontier.store_id
        || backup.frontier_generation != frontier.frontier_generation
        || backup.snapshot_sha256 != Sha256Digest::for_bytes(&snapshot_bytes)
        || backup.backend_identity_sha256 != frontier.backend_identity_sha256
        || backup.backup_object_length == 0
        || backup.backup_object_length > MAX_BACKUP_OBJECT_BYTES
        || build.source_commit != frontier.source_commit
        || build.source_tree != frontier.source_tree
        || build.executable_sha256 != frontier.build_artifact_sha256
        || build.executable_sha256 != *observed_build_artifact_sha256
        || build.executable_length == 0
        || build.workflow_run_id == 0
        || build.workflow_run_attempt == 0
        || build.workflow_artifact_id == 0
        || build.workflow_job.is_empty()
        || build.workflow_job.len() > 128
        || build.workflow_artifact_url != expected_artifact_url
        || restore.restored_object_sha256 != backup.backup_object_sha256
        || restore.restored_snapshot_sha256 != backup.snapshot_sha256
        || build.built_at_unix_ms == 0
        || restore.restored_at_unix_ms == 0
        || build.built_at_unix_ms > backup.published_at_unix_ms
        || restore.restored_at_unix_ms > backup.published_at_unix_ms
        || backup.published_at_unix_ms > now.saturating_add(MAX_FUTURE_CLOCK_SKEW_MS)
        || now.saturating_sub(backup.published_at_unix_ms) > max_age_ms
        || now.saturating_sub(build.built_at_unix_ms) > max_age_ms
        || now.saturating_sub(restore.restored_at_unix_ms) > max_age_ms
    {
        return Err(recovery_required(
            "backup publication manifest is not a current durable object, governed build and witnessed restore for the frontier",
        ));
    }
    Ok(())
}

fn validate_backup_object_name(value: &str) -> Result<(), AgentdError> {
    let path = Path::new(value);
    if value.is_empty()
        || value.len() > 255
        || value == "."
        || value == ".."
        || value == "identity.json"
        || path.components().count() != 1
        || path.file_name() != Some(path.as_os_str())
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return Err(recovery_required(
            "backup object file name must be one bounded direct-child token",
        ));
    }
    Ok(())
}

#[cfg(unix)]
fn verify_backup_object(
    backup: &EvidenceBackupPublicationReceiptV1,
    root: &Path,
    identity: &AgentdIdentity,
    forbidden_paths: &[&Path],
) -> Result<(), AgentdError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    validate_backup_object_name(&backup.backup_object_file_name)?;
    let home = identity.home_root.canonicalize()?;
    let root = root.canonicalize()?;
    let path = root.join(&backup.backup_object_file_name);
    if root.starts_with(&home)
        || path.starts_with(&home)
        || path.parent() != Some(root.as_path())
        || forbidden_paths
            .iter()
            .any(|forbidden| *forbidden == path.as_path())
        || path.canonicalize()? != path
    {
        return Err(recovery_required(
            "backup object must be a distinct canonical direct child of the external backend",
        ));
    }

    let root_handle = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW)
        .open(&root)?;
    let root_before = root_handle.metadata()?;
    let before = std::fs::symlink_metadata(&path)?;
    if !root_before.is_dir()
        || root_before.mode() & 0o077 != 0
        || !before.is_file()
        || before.uid() != root_before.uid()
        || before.nlink() != 1
        || before.mode() & 0o077 != 0
        || before.len() != backup.backup_object_length
        || before.len() == 0
        || before.len() > MAX_BACKUP_OBJECT_BYTES
    {
        return Err(recovery_required(
            "backup object is not one private owner-bound bounded regular file",
        ));
    }

    let mut file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(&path)?;
    let opened = file.metadata()?;
    let file_identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.uid(),
            metadata.mode(),
            metadata.nlink(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    let directory_identity = |metadata: &std::fs::Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.uid(),
            metadata.mode(),
        )
    };
    if file_identity(&opened) != file_identity(&before) {
        return Err(recovery_required("backup object changed while opening"));
    }

    let mut hasher = Sha256::new();
    let mut observed = 0_u64;
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 {
            break;
        }
        observed = observed
            .checked_add(u64::try_from(count).unwrap_or(u64::MAX))
            .ok_or_else(|| recovery_required("backup object length overflow"))?;
        if observed > backup.backup_object_length || observed > MAX_BACKUP_OBJECT_BYTES {
            return Err(recovery_required(
                "backup object exceeds its signed bounded length",
            ));
        }
        hasher.update(&buffer[..count]);
    }

    let after = std::fs::symlink_metadata(&path)?;
    let root_after = std::fs::symlink_metadata(&root)?;
    let digest = Sha256Digest::from_sha256_output(hasher.finalize());
    if observed != backup.backup_object_length
        || digest != backup.backup_object_sha256
        || file_identity(&after) != file_identity(&before)
        || file_identity(&file.metadata()?) != file_identity(&before)
        || directory_identity(&root_after) != directory_identity(&root_before)
        || directory_identity(&root_handle.metadata()?) != directory_identity(&root_before)
    {
        return Err(recovery_required(
            "backup object bytes, identity or external root changed during verification",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
fn verify_backup_object(
    _backup: &EvidenceBackupPublicationReceiptV1,
    _root: &Path,
    _identity: &AgentdIdentity,
    _forbidden_paths: &[&Path],
) -> Result<(), AgentdError> {
    Err(recovery_required(
        "backup object verification currently requires Unix file identity checks",
    ))
}
