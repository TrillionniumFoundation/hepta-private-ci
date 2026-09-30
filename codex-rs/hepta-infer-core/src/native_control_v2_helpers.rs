fn validate_native_request(request: &NativeRequest) -> Result<(), Error> {
    validate_identity(&request.request_id, "native request")?;
    validate_identity(&request.principal_id, "native principal")?;
    validate_digest(&request.payload_digest, "native payload")?;
    if request.worker_generation == 0 || request.model.is_empty() || request.model.len() > 256 {
        return Err(Error::InvalidIdentity("native worker/model"));
    }
    Ok(())
}

fn validate_execution_binding(
    record: &NativeRunRecord,
    binding: &NativeExecutionBinding,
) -> Result<(), Error> {
    if binding.authority_epoch == 0
        || binding.worker_generation != record.request.worker_generation
        || binding.model_id != record.request.model
        || binding.valid_until_unix_ms == 0
        || binding.maximum_input_tokens == 0
        || binding.maximum_output_tokens == 0
        || binding.maximum_cost_microunits == 0
    {
        return Err(Error::AssignmentMismatch);
    }
    for (value, field) in [
        (&binding.bundle_digest, "native authority bundle"),
        (&binding.manifest_digest, "native manifest"),
        (&binding.quota_lease_digest, "native quota lease"),
        (&binding.resource_lease_digest, "native resource lease"),
        (&binding.output_policy_digest, "native output policy"),
        (
            &binding.execution_binding_digest,
            "native execution binding",
        ),
        (&binding.model_digest, "native model"),
        (&binding.tokenizer_digest, "native tokenizer"),
        (&binding.template_digest, "native template"),
        (&binding.runtime_digest, "native runtime"),
        (&binding.adapter_digest, "native adapter"),
    ] {
        validate_digest(value, field)?;
    }
    for (value, field) in [
        (&binding.provider_id, "native provider"),
        (&binding.model_id, "native model id"),
        (&binding.model_revision, "native model revision"),
        (&binding.worker_id, "native worker"),
    ] {
        validate_identity(value, field)?;
    }
    Ok(())
}

fn validate_dispatch(dispatch: &NativeDispatch) -> Result<(), Error> {
    validate_identity(&dispatch.thread_id, "native thread")?;
    validate_identity(&dispatch.model_provider, "native provider")?;
    validate_digest(&dispatch.context_digest, "native context")?;
    if let Some(owner_context_digest) = &dispatch.owner_context_digest {
        validate_digest(owner_context_digest, "native owner context")?;
    }
    let codex_fields = [
        dispatch.codex_payload_digest.is_some(),
        dispatch.codex_request_digest.is_some(),
        dispatch.app_server_version.is_some(),
        dispatch.protocol_id.is_some(),
    ];
    if codex_fields.iter().any(|present| *present) && !codex_fields.iter().all(|present| *present) {
        return Err(Error::InvalidIdentity("native codex dispatch binding"));
    }
    let extended_codex_fields = [
        dispatch.codex_source_admission_digest.is_some(),
        dispatch.codex_home_digest.is_some(),
        dispatch.codex_connection_id.is_some(),
        dispatch.codex_session_id.is_some(),
        dispatch.codex_deadline_ms.is_some(),
        dispatch.codex_authority_witness_sha256.is_some(),
    ];
    if extended_codex_fields.iter().any(|present| *present)
        && (!codex_fields.iter().all(|present| *present)
            || !extended_codex_fields.iter().all(|present| *present))
    {
        return Err(Error::InvalidIdentity(
            "native codex extended dispatch binding",
        ));
    }
    let frontier_fields = [
        dispatch.codex_authority_epoch.is_some(),
        dispatch.codex_revocation_revision.is_some(),
        dispatch.codex_revocation_head_sha256.is_some(),
    ];
    if frontier_fields.iter().any(|present| *present)
        && (!extended_codex_fields.iter().all(|present| *present)
            || !frontier_fields.iter().all(|present| *present))
    {
        return Err(Error::InvalidIdentity(
            "native codex authority frontier binding",
        ));
    }
    if let Some(digest) = &dispatch.codex_payload_digest {
        validate_digest(digest, "native codex payload")?;
    }
    if let Some(digest) = &dispatch.codex_request_digest {
        validate_digest(digest, "native codex request")?;
    }
    if let Some(version) = &dispatch.app_server_version
        && (version.is_empty()
            || version.len() > 128
            || version.bytes().any(|byte| byte.is_ascii_control()))
    {
        return Err(Error::InvalidIdentity("native app server version"));
    }
    if let Some(protocol_id) = &dispatch.protocol_id {
        validate_identity(protocol_id, "native app server protocol")?;
    }
    if let Some(digest) = &dispatch.codex_source_admission_digest {
        validate_digest(digest, "native codex source admission")?;
    }
    if let Some(digest) = &dispatch.codex_home_digest {
        validate_digest(digest, "native codex home")?;
    }
    if dispatch.codex_connection_id == Some(0) {
        return Err(Error::InvalidIdentity("native codex connection"));
    }
    if let Some(session_id) = &dispatch.codex_session_id {
        validate_identity(session_id, "native codex session")?;
    }
    if dispatch.codex_deadline_ms == Some(0) {
        return Err(Error::InvalidIdentity("native codex deadline"));
    }
    if dispatch.codex_authority_epoch == Some(0) {
        return Err(Error::InvalidIdentity("native codex authority epoch"));
    }
    if dispatch.codex_revocation_revision == Some(0) {
        return Err(Error::InvalidIdentity("native codex revocation revision"));
    }
    if let Some(digest) = &dispatch.codex_revocation_head_sha256 {
        validate_digest(digest, "native codex revocation head")?;
    }
    if let Some(digest) = &dispatch.codex_authority_witness_sha256 {
        validate_digest(digest, "native codex authority witness")?;
    }
    Ok(())
}

fn apply_observation(
    record: &mut NativeRunRecord,
    mut output: NativeRunOutput,
    reconciliation: Option<&NativeReconciliationAudit>,
) -> Result<(), Error> {
    if reconciliation.is_some() {
        // Provider evidence proves terminality/usage, not Agentd readiness.
        output.owner_authority = record
            .observation
            .as_ref()
            .map_or(NativeOwnerAuthority::Unverified, |previous| {
                previous.owner_authority.clone()
            });
        if let Some(previous) = &record.observation
            && matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. })
        {
            output.boundary_status = NativeBoundaryStatus::Quarantined;
            output.stop_reason = previous.stop_reason.clone();
        }
    }
    let dispatch = record.dispatch.as_ref().ok_or(Error::AssignmentMismatch)?;
    if output.thread_id != dispatch.thread_id
        || output.model_provider != dispatch.model_provider
        || output.model != record.request.model
        || record
            .turn_id
            .as_ref()
            .is_some_and(|turn| turn != &output.turn_id)
    {
        return Err(Error::AssignmentMismatch);
    }
    if output.output.len() > 1024 * 1024
        || output
            .stop_reason
            .as_ref()
            .is_some_and(|reason| reason.len() > 4096)
    {
        return Err(Error::CapacityExceeded);
    }
    if let Some(digest) = &output.codex_terminal_correlation_digest {
        validate_digest(digest, "native codex terminal correlation")?;
    }
    let quota_exceeded = record.execution_binding.as_ref().is_some_and(|binding| {
        output
            .observed_output_tokens
            .is_some_and(|tokens| tokens > binding.maximum_output_tokens)
            || reconciliation
                .and_then(|audit| audit.usage_microunits)
                .is_some_and(|usage| usage > binding.maximum_cost_microunits)
    });
    if quota_exceeded {
        // Observed usage above the reservation is retained, never payment authority.
        output.boundary_status = NativeBoundaryStatus::Quarantined;
        if let Some(previous) = record
            .observation
            .as_ref()
            .filter(|previous| previous.terminal_observed)
        {
            output.stop_reason = previous.stop_reason.clone();
        }
        let reason = "observed usage exceeds signed quota; excess payment is not authorized";
        match &mut output.stop_reason {
            Some(previous)
                if !previous.contains(reason) && previous.len() + reason.len() + 2 <= 4096 =>
            {
                previous.push_str("; ");
                previous.push_str(reason);
            }
            Some(_) => {}
            None => output.stop_reason = Some(reason.to_string()),
        }
    }
    let complete_frontier = dispatch.codex_authority_epoch.is_some()
        && dispatch.codex_revocation_revision.is_some()
        && dispatch.codex_revocation_head_sha256.is_some();
    if output.terminal_observed
        && output.boundary_status == NativeBoundaryStatus::Succeeded
        && dispatch.codex_request_digest.is_some()
        && !complete_frontier
    {
        output.boundary_status = NativeBoundaryStatus::Quarantined;
        output.stop_reason = Some(
            "historical runtime.codex dispatch lacks claim-time authority frontier; terminal truth retained but success qualification denied"
                .to_string(),
        );
    }
    if output.terminal_observed
        && dispatch.codex_request_digest.is_some()
        && (output.codex_terminal_correlation_digest.is_none()
            || output.boundary_status == NativeBoundaryStatus::Indeterminate)
    {
        return Err(Error::TerminalObservationMissing);
    }
    if let NativeOwnerAuthority::Lost { reason } = &output.owner_authority
        && (reason.is_empty() || reason.len() > 4096)
    {
        return Err(Error::InvalidIdentity("owner authority loss reason"));
    }
    if output.terminal_observed == (output.status == NativeRunStatus::Indeterminate)
        || (output.turn_id.is_empty()
            && (output.terminal_observed
                || output.observed_output_tokens.is_some()
                || !output.output.is_empty()))
    {
        return Err(Error::TerminalObservationMissing);
    }
    if let Some(previous) = &record.observation {
        if (matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. })
            && previous.owner_authority != output.owner_authority)
            || (previous.terminal_observed
                && previous.owner_authority == NativeOwnerAuthority::Unverified
                && output.owner_authority == NativeOwnerAuthority::ObservedReady)
        {
            return Err(Error::Conflict);
        }
        if previous.terminal_observed
            && (previous.status != output.status
                || (previous.boundary_status != output.boundary_status && !quota_exceeded)
                || !output.terminal_observed
                || previous.output != output.output
                || (previous.stop_reason != output.stop_reason && !quota_exceeded)
                || (previous.codex_terminal_correlation_digest
                    != output.codex_terminal_correlation_digest
                    && reconciliation.is_none()))
        {
            return Err(Error::Conflict);
        }
        if previous.observed_output_tokens.is_some_and(|tokens| {
            output
                .observed_output_tokens
                .is_none_or(|next| next < tokens)
        }) {
            return Err(Error::Conflict);
        }
    }
    if !output.turn_id.is_empty() {
        validate_identity(&output.turn_id, "native turn")?;
        record.turn_id = Some(output.turn_id.clone());
    }
    record.state = if output.terminal_observed {
        NativeReservationState::Released
    } else {
        NativeReservationState::Indeterminate
    };
    record.observation = Some(output);
    Ok(())
}

include!("native_control_v2_checkpoint.rs");

fn native_dispatch_digest(dispatch: &NativeDispatch) -> Result<String, Error> {
    let bytes = serde_json::to_vec(dispatch)
        .map_err(|_| Error::CorruptJournal("native dispatch digest encode"))?;
    Ok(sha256_hex(
        b"hepta.inference-control.native-dispatch.v1\0",
        &bytes,
    ))
}

fn sha256_hex(domain: &[u8], payload: &[u8]) -> String {
    let mut hash = Sha256::new();
    hash.update(domain);
    hash.update((payload.len() as u64).to_be_bytes());
    hash.update(payload);
    format!("{:x}", hash.finalize())
}

fn legacy_journal_lines(bytes: &[u8]) -> Result<Vec<u8>, Error> {
    let mut output = Vec::new();
    for line in bytes.split_inclusive(|byte| *byte == b'\n') {
        if !line.ends_with(b"\n") {
            return Err(Error::CorruptJournal("incomplete line"));
        }
        let content = &line[..line.len() - 1];
        if !content.starts_with(JOURNAL_PREFIX.as_bytes()) {
            output.extend_from_slice(line);
        }
    }
    Ok(output)
}

fn absolute_parent(path: &Path) -> Result<PathBuf, Error> {
    let parent = path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."));
    fs::canonicalize(parent).map_err(Error::from)
}

fn sibling_directory(path: &Path, suffix: &str) -> PathBuf {
    let name = path.file_name().unwrap_or(path.as_os_str());
    if name.as_encoded_bytes().len() + suffix.len() + 1 > 255 {
        let digest = sha256_hex(
            b"hepta.inference-control.journal-name.v1\0",
            name.as_encoded_bytes(),
        );
        return path.with_file_name(format!(".hepta-inference-{digest}.{suffix}"));
    }
    let mut value = OsString::from(path.as_os_str());
    value.push(format!(".{suffix}"));
    PathBuf::from(value)
}

fn temporary_generation_path(path: &Path, generation: u64, now_unix_ms: u64) -> PathBuf {
    let digest = sha256_hex(
        b"hepta.inference-control.journal-name.v1\0",
        path.file_name()
            .unwrap_or(path.as_os_str())
            .as_encoded_bytes(),
    );
    path.with_file_name(format!(
        ".hepta-inference-{digest}.compact.{generation}.{now_unix_ms}.{}",
        std::process::id()
    ))
}

fn write_content_addressed(path: &Path, bytes: &[u8]) -> Result<(), Error> {
    if path.exists() {
        // Reuse must retry durability even if an earlier write filled the page
        // cache before its fsync failed. Read and flush the same descriptor;
        // Windows FlushFileBuffers requires a handle opened for writing.
        let mut existing = OpenOptions::new().read(true).write(true).open(path)?;
        let mut existing_bytes = Vec::new();
        (&mut existing)
            .take((bytes.len() as u64).saturating_add(1))
            .read_to_end(&mut existing_bytes)?;
        if existing_bytes == bytes {
            existing.sync_all()?;
            return Ok(());
        }
        return Err(Error::CorruptJournal("content-address collision"));
    }
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path)?;
    file.write_all(bytes)?;
    file.flush()?;
    file.sync_all()?;
    Ok(())
}

fn read_bounded(path: &Path, maximum_bytes: u64) -> Result<Vec<u8>, Error> {
    let mut bytes = Vec::new();
    File::open(path)?
        .take(maximum_bytes.saturating_add(1))
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum_bytes {
        return Err(Error::CapacityExceeded);
    }
    Ok(bytes)
}

fn set_owner_only_directory(path: &Path) -> Result<(), Error> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(path, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

fn sync_directory(path: &Path) -> Result<(), Error> {
    #[cfg(unix)]
    {
        File::open(path)?.sync_all()?;
    }
    Ok(())
}

#[cfg(test)]
#[path = "native_control_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "native_storage_sync_tests.rs"]
mod storage_sync_tests;
