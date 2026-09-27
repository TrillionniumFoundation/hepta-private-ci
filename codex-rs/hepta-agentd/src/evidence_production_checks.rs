impl EvidenceProductionConfigV1 {
    fn validate(&self, identity: &AgentdIdentity) -> Result<(), AgentdError> {
        if self.schema_version != PRODUCTION_CONFIG_SCHEMA_VERSION || self.mode != "production"
            || self.agent_id != identity.agent_id.as_str() || self.minimum_frontier_generation == 0
            || self.frontier_max_age_ms == 0 || self.frontier_max_age_ms > MAX_FRONTIER_AGE_MS
        {
            return Err(recovery_required("production evidence descriptor schema, owner, generation or freshness policy is invalid"));
        }
        StableId::new(self.store_id.clone()).map_err(|error| recovery_required(&format!("invalid recovery store id: {error}")))?;
        validate_digest(&self.backend_identity_sha256, "backend identity")?;
        for path in [&self.external_backend_root, &self.exact_source_receipt_file,
            &self.merge_candidate_receipt_file, &self.backup_publication_receipt_file]
        {
            if !path.is_absolute() { return Err(recovery_required("production evidence paths must be absolute")); }
        }
        Ok(())
    }
}

fn validate_qualification_receipts(exact_source_bytes: &[u8], merge_candidate_bytes: &[u8]) -> Result<QualifiedSourceIdentity, AgentdError> {
    let exact: Value = serde_json::from_slice(exact_source_bytes)?;
    let exact_workflow = validate_status_common(&exact, "kernel_evidence_exact_source", "exactSourceQualified")?;
    let candidate = exact.get("candidate").and_then(Value::as_object)
        .ok_or_else(|| recovery_required("exact-source receipt has no candidate object"))?;
    let source_commit = required_string(candidate.get("asOfCommit"), "exact-source commit")?;
    let source_tree = required_string(candidate.get("asOfTree"), "exact-source tree")?;
    let exact_source_commit = required_string(candidate.get("sourceCommit"), "exact-source source commit")?;
    let exact_tested_commit = required_string(candidate.get("testedCommit"), "exact-source tested commit")?;
    let exact_base_commit = required_string(candidate.get("baseCommit"), "exact-source base commit")?;
    let exact_lane = required_string(candidate.get("lane"), "exact-source lane")?;
    validate_git_identity(&source_commit, "exact-source commit")?;
    validate_git_identity(&source_tree, "exact-source tree")?;
    validate_git_identity(&exact_base_commit, "exact-source base commit")?;
    if exact_source_commit != source_commit || exact_tested_commit != source_commit || exact_lane != "source-head" {
        return Err(recovery_required("exact-source receipt candidate identity is internally inconsistent"));
    }
    let merge: Value = serde_json::from_slice(merge_candidate_bytes)?;
    let merge_workflow = validate_status_common(&merge, "kernel_evidence_synthetic_merge", "mergeCandidateQualified")?;
    if merge_workflow != exact_workflow {
        return Err(recovery_required("exact-source and deterministic-merge receipts are not from the same workflow run"));
    }
    let merge_candidate = merge.get("candidate").and_then(Value::as_object)
        .ok_or_else(|| recovery_required("merge receipt has no candidate object"))?;
    let merge_commit = required_string(merge_candidate.get("asOfCommit"), "merge commit")?;
    let merge_tree = required_string(merge_candidate.get("asOfTree"), "merge tree")?;
    let merge_tested_commit = required_string(merge_candidate.get("testedCommit"), "merge tested commit")?;
    let merge_source_commit = required_string(merge_candidate.get("sourceCommit"), "merge receipt source commit")?;
    let merge_base_commit = required_string(merge_candidate.get("baseCommit"), "merge receipt base commit")?;
    let merge_lane = required_string(merge_candidate.get("lane"), "merge lane")?;
    validate_git_identity(&merge_commit, "merge commit")?;
    validate_git_identity(&merge_tree, "merge tree")?;
    validate_git_identity(&merge_source_commit, "merge source commit")?;
    validate_git_identity(&merge_base_commit, "merge base commit")?;
    if merge_tested_commit != merge_commit || merge_source_commit != source_commit
        || merge_base_commit != exact_base_commit || merge_lane != "base-merge"
    {
        return Err(recovery_required("merge receipt is not bound to the exact-source candidate and base"));
    }
    let parents = merge_candidate.get("parents").and_then(Value::as_array)
        .ok_or_else(|| recovery_required("merge receipt has no parent vector"))?;
    if parents.len() != 2 || parents[0].as_str() != Some(merge_base_commit.as_str())
        || parents[1].as_str() != Some(source_commit.as_str())
    {
        return Err(recovery_required("merge receipt does not have the expected base/source parent order"));
    }
    Ok(QualifiedSourceIdentity { source_commit, source_tree })
}

fn validate_status_common(status: &Value, expected_kind: &str, qualification_flag: &str) -> Result<QualificationWorkflowIdentity, AgentdError> {
    let other_qualification_flag = if qualification_flag == "exactSourceQualified" { "mergeCandidateQualified" } else { "exactSourceQualified" };
    if status.get("schemaVersion").and_then(Value::as_u64) != Some(1)
        || status.get("module").and_then(Value::as_str) != Some("kernel.evidence")
        || status.get("kind").and_then(Value::as_str) != Some(expected_kind)
        || status.get("qualified").and_then(Value::as_bool) != Some(true)
        || status.get(qualification_flag).and_then(Value::as_bool) != Some(true)
        || status.get(other_qualification_flag).and_then(Value::as_bool) != Some(false)
        || NON_RELEASE_QUALIFICATION_FLAGS.iter().any(|flag| status.get(*flag).and_then(Value::as_bool) != Some(false))
        || status.get("authority").and_then(|authority| authority.get("selfIssuedReleaseAuthority")).and_then(Value::as_bool) != Some(false)
    {
        return Err(recovery_required("qualification receipt schema, module, kind, disposition or authority boundary is invalid"));
    }
    let candidate = status.get("candidate").and_then(Value::as_object)
        .ok_or_else(|| recovery_required("qualification receipt has no candidate object"))?;
    if candidate.get("dirty").and_then(Value::as_bool) != Some(false)
        || candidate.get("identityErrors").and_then(Value::as_array).is_none_or(|errors| !errors.is_empty())
    {
        return Err(recovery_required("qualification receipt candidate identity is dirty or rejected"));
    }
    let checks = status.get("checks").and_then(Value::as_object)
        .ok_or_else(|| recovery_required("qualification receipt has no check map"))?;
    let observed_checks: BTreeSet<&str> = checks.keys().map(String::as_str).collect();
    let required_checks: BTreeSet<&str> = REQUIRED_QUALIFICATION_CHECKS.into_iter().collect();
    if observed_checks != required_checks {
        return Err(recovery_required("qualification receipt check inventory is incomplete or contains an unknown check"));
    }
    let mut log_paths = BTreeSet::new();
    for name in REQUIRED_QUALIFICATION_CHECKS {
        let check = checks.get(name).and_then(Value::as_object)
            .ok_or_else(|| recovery_required("qualification receipt check is not an object"))?;
        let expected_path = format!("{name}.json");
        let check_digest = required_string(check.get("sha256"), "check digest")?;
        Sha256Digest::parse(check_digest).map_err(|error| recovery_required(&format!("invalid check digest: {error}")))?;
        if check.get("path").and_then(Value::as_str) != Some(expected_path.as_str())
            || check.get("present").and_then(Value::as_bool) != Some(true)
            || check.get("status").and_then(Value::as_str) != Some("passed")
            || check.get("exitCode").and_then(Value::as_i64) != Some(0)
            || check.get("commandExitCode").and_then(Value::as_i64) != Some(0)
            || check.get("passed").and_then(Value::as_bool) != Some(true)
            || check.get("bytes").and_then(Value::as_u64).is_none_or(|bytes| bytes == 0)
            || check.get("error").is_none_or(|error| !error.is_null())
        {
            return Err(recovery_required("qualification receipt contains an incomplete or failed command record"));
        }
        let log = check.get("log").and_then(Value::as_object)
            .ok_or_else(|| recovery_required("qualification receipt check has no retained log"))?;
        let log_path = required_string(log.get("path"), "check log path")?;
        let log_digest = required_string(log.get("sha256"), "check log digest")?;
        Sha256Digest::parse(log_digest).map_err(|error| recovery_required(&format!("invalid check log digest: {error}")))?;
        if !log_paths.insert(log_path) || log.get("present").and_then(Value::as_bool) != Some(true)
            || log.get("bytes").and_then(Value::as_u64).is_none()
        {
            return Err(recovery_required("qualification receipt retained log identity is invalid or reused"));
        }
    }
    let workflow = status.get("workflow").and_then(Value::as_object)
        .ok_or_else(|| recovery_required("qualification receipt has no workflow identity"))?;
    let repository = required_string(workflow.get("repository"), "workflow repository")?;
    validate_repository_slug(&repository)?;
    let run_id = parse_positive_decimal(&required_string(workflow.get("workflowRunId"), "workflow run id")?, "workflow run id")?;
    let run_attempt = parse_positive_decimal(&required_string(workflow.get("workflowRunAttempt"), "workflow run attempt")?, "workflow run attempt")?;
    let expected_job = if expected_kind == "kernel_evidence_exact_source" { "source-head" } else { "merge-candidate" };
    if workflow.get("job").and_then(Value::as_str) != Some(expected_job)
        || workflow.get("event").and_then(Value::as_str) != Some("pull_request")
    {
        return Err(recovery_required("qualification receipt workflow job or event is not the governed PR lane"));
    }
    let artifact = status.get("artifact").and_then(Value::as_object)
        .ok_or_else(|| recovery_required("qualification receipt has no retained artifact"))?;
    let artifact_id = artifact.get("id").and_then(Value::as_u64).unwrap_or(0);
    let artifact_sha256 = required_string(artifact.get("sha256"), "artifact digest")?;
    Sha256Digest::parse(artifact_sha256).map_err(|error| recovery_required(&format!("invalid artifact digest: {error}")))?;
    let expected_artifact_url = format!("https://github.com/{repository}/actions/runs/{run_id}/artifacts/{artifact_id}");
    if artifact_id == 0 || artifact.get("url").and_then(Value::as_str) != Some(expected_artifact_url.as_str()) {
        return Err(recovery_required("qualification receipt artifact identity is invalid"));
    }
    Ok(QualificationWorkflowIdentity { repository, run_id, run_attempt })
}

fn qualification_receipt_set_sha256(exact_source: &Sha256Digest, merge_candidate: &Sha256Digest) -> Sha256Digest {
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
        return Err(recovery_required("current Agentd executable is not a bounded regular file"));
    }
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut observed = 0_u64;
    loop {
        let count = file.read(&mut buffer)?;
        if count == 0 { break; }
        observed = observed.checked_add(u64::try_from(count).unwrap_or(u64::MAX))
            .ok_or_else(|| recovery_required("current executable size overflow"))?;
        if observed > MAX_EXECUTABLE_BYTES {
            return Err(recovery_required("current Agentd executable exceeds the bounded digest profile"));
        }
        hasher.update(&buffer[..count]);
    }
    if observed != metadata.len() { return Err(recovery_required("current Agentd executable changed while hashing")); }
    Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
}

fn read_external_private_file(path: &Path, root: &Path, identity: &AgentdIdentity, maximum_bytes: u64) -> Result<Vec<u8>, AgentdError> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    let home = identity.home_root.canonicalize()?;
    if !path.is_absolute() || path.parent() != Some(root) || root.starts_with(&home)
        || path.starts_with(&home) || path.canonicalize()? != path
    {
        return Err(recovery_required("production evidence control files must be canonical direct children of the external backend"));
    }
    let root_handle = OpenOptions::new().read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_DIRECTORY | libc::O_NOFOLLOW).open(root)?;
    let root_metadata = root_handle.metadata()?;
    let before = std::fs::symlink_metadata(path)?;
    if !root_metadata.is_dir() || root_metadata.mode() & 0o077 != 0 || !before.is_file()
        || before.uid() != root_metadata.uid() || before.nlink() != 1 || before.mode() & 0o077 != 0
        || before.len() == 0 || before.len() > maximum_bytes
    {
        return Err(recovery_required("production evidence control file is not private, owner-bound and bounded"));
    }
    let mut file = OpenOptions::new().read(true).custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW).open(path)?;
    let opened = file.metadata()?;
    let file_identity = |metadata: &std::fs::Metadata| {
        (metadata.dev(), metadata.ino(), metadata.len(), metadata.mtime(), metadata.mtime_nsec(), metadata.ctime(), metadata.ctime_nsec())
    };
    let directory_identity = |metadata: &std::fs::Metadata| {
        (metadata.dev(), metadata.ino(), metadata.uid(), metadata.mode())
    };
    if file_identity(&opened) != file_identity(&before) {
        return Err(recovery_required("production evidence control file changed while opening"));
    }
    let mut bytes = Vec::new();
    file.by_ref().take(maximum_bytes.saturating_add(1)).read_to_end(&mut bytes)?;
    let after = std::fs::symlink_metadata(path)?;
    let root_path_after = std::fs::symlink_metadata(root)?;
    if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > maximum_bytes
        || file_identity(&after) != file_identity(&before)
        || file_identity(&file.metadata()?) != file_identity(&before)
        || directory_identity(&root_path_after) != directory_identity(&root_metadata)
        || directory_identity(&root_handle.metadata()?) != directory_identity(&root_metadata)
    {
        return Err(recovery_required("production evidence control file or external root changed while reading"));
    }
    Ok(bytes)
}

fn required_string(value: Option<&Value>, label: &str) -> Result<String, AgentdError> {
    value.and_then(Value::as_str).filter(|value| !value.is_empty()).map(str::to_string)
        .ok_or_else(|| recovery_required(&format!("{label} is missing")))
}

fn parse_positive_decimal(value: &str, label: &str) -> Result<u64, AgentdError> {
    if !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return Err(recovery_required(&format!("{label} must be a positive decimal integer")));
    }
    let parsed = value.parse::<u64>().map_err(|error| recovery_required(&format!("invalid {label}: {error}")))?;
    if parsed == 0 { return Err(recovery_required(&format!("{label} must be positive"))); }
    Ok(parsed)
}

fn validate_repository_slug(value: &str) -> Result<(), AgentdError> {
    let mut parts = value.split('/');
    let owner = parts.next().unwrap_or_default();
    let repository = parts.next().unwrap_or_default();
    let valid_component = |component: &str| {
        !component.is_empty() && component.bytes().all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    };
    if !valid_component(owner) || !valid_component(repository) || parts.next().is_some() {
        return Err(recovery_required("workflow repository must be an owner/repository slug"));
    }
    Ok(())
}

fn validate_digest(digest: &Sha256Digest, label: &str) -> Result<(), AgentdError> {
    Sha256Digest::parse(digest.as_str().to_string()).map(|_| ())
        .map_err(|error| recovery_required(&format!("invalid {label} digest: {error}")))
}

fn validate_git_identity(value: &str, label: &str) -> Result<(), AgentdError> {
    if !matches!(value.len(), 40 | 64)
        || !value.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(recovery_required(&format!("{label} must be a 40- or 64-character lowercase hexadecimal object id")));
    }
    Ok(())
}

fn push_part(bytes: &mut Vec<u8>, part: &[u8]) {
    bytes.extend_from_slice(&u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(part);
}

fn current_time_millis() -> Result<u64, AgentdError> {
    let millis = SystemTime::now().duration_since(UNIX_EPOCH)
        .map_err(|error| recovery_required(&format!("system clock is before Unix epoch: {error}")))?.as_millis();
    u64::try_from(millis).map_err(|error| recovery_required(&format!("system clock overflow: {error}")))
}

fn backend_error(error: codex_hepta_evidence::EvidenceFrontierBackendError) -> AgentdError { recovery_required(&error.to_string()) }
fn evidence_error(error: codex_hepta_evidence::EvidenceError) -> AgentdError { recovery_required(&error.to_string()) }
fn recovery_required(message: &str) -> AgentdError { AgentdError::Invalid(format!("kernel.evidence recovery_required: {message}")) }
