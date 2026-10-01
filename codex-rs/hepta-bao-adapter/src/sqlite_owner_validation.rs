//! Existing durable owner rows implementation.

use super::*;

#[cfg(unix)]
pub(super) fn prepare_private_storage(path: &Path) -> Result<(), SqliteBaoOwnerErrorV1> {
    use std::os::unix::fs::DirBuilderExt;
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;

    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    if !parent.exists() {
        let mut builder = fs::DirBuilder::new();
        builder.mode(0o700).recursive(true);
        builder.create(parent).map_err(storage)?;
    }
    let parent_metadata = fs::symlink_metadata(parent).map_err(storage)?;
    if parent_metadata.file_type().is_symlink() || !parent_metadata.is_dir() {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "parent must be a real directory",
        ));
    }
    if parent_metadata.mode() & 0o077 != 0
        || parent_metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "parent must be owner-only and owner-owned",
        ));
    }
    // SQLite may read or write the WAL, shared-memory and hot rollback journal
    // during connection setup. Reject unsafe sidecars before that first access.
    for file_path in [
        path.to_path_buf(),
        sidecar_path(path, "-wal"),
        sidecar_path(path, "-shm"),
        sidecar_path(path, "-journal"),
    ] {
        match fs::symlink_metadata(&file_path) {
            Ok(_) => secure_database_file(&file_path)?,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(storage(error)),
        }
    }
    // Set the database mode before SQLite creates sidecars inheriting it.
    if !path.exists() {
        match fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32)
            .open(path)
        {
            Ok(file) => {
                file.sync_all().map_err(storage)?;
                fs::File::open(parent)
                    .map_err(storage)?
                    .sync_all()
                    .map_err(storage)?;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(storage(error)),
        }
    }
    secure_database_file(path)
}

#[cfg(not(unix))]
pub(super) fn prepare_private_storage(_path: &Path) -> Result<(), SqliteBaoOwnerErrorV1> {
    Err(SqliteBaoOwnerErrorV1::UnsupportedPlatform)
}

#[cfg(unix)]
pub(super) fn secure_database_file(path: &Path) -> Result<(), SqliteBaoOwnerErrorV1> {
    use std::os::unix::fs::MetadataExt;
    use std::os::unix::fs::OpenOptionsExt;
    use std::os::unix::fs::PermissionsExt;

    let metadata = fs::symlink_metadata(path).map_err(storage)?;
    if metadata.file_type().is_symlink()
        || !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
    {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "database identity changed while opening",
        ));
    }
    let file = fs::OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags((rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32)
        .open(path)
        .map_err(storage)?;
    let opened = file.metadata().map_err(storage)?;
    if opened.dev() != metadata.dev() || opened.ino() != metadata.ino() {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "database identity changed while securing storage",
        ));
    }
    file.set_permissions(fs::Permissions::from_mode(0o600))
        .map_err(storage)?;
    let secured = file.metadata().map_err(storage)?;
    if secured.mode() & 0o077 != 0 {
        return Err(SqliteBaoOwnerErrorV1::UnsafeStorage(
            "database permissions are not owner-only",
        ));
    }
    Ok(())
}

#[cfg(not(unix))]
pub(super) fn secure_database_file(_path: &Path) -> Result<(), SqliteBaoOwnerErrorV1> {
    Err(SqliteBaoOwnerErrorV1::UnsupportedPlatform)
}

pub(super) fn sidecar_path(path: &Path, suffix: &str) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(suffix);
    PathBuf::from(value)
}

pub(super) fn metadata_len(path: &Path) -> Result<u64, SqliteBaoOwnerErrorV1> {
    match fs::metadata(path) {
        Ok(metadata) => Ok(metadata.len()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(0),
        Err(error) => Err(storage(error)),
    }
}

pub(super) fn elapsed_micros(started: Instant) -> u64 {
    u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX)
}

pub(super) fn push_sample(samples: &mut VecDeque<u64>, value: u64) {
    if samples.len() == RUNTIME_SAMPLE_LIMIT {
        samples.pop_front();
    }
    samples.push_back(value);
}

pub(super) fn sorted_samples(samples: &VecDeque<u64>) -> Vec<u64> {
    let mut values = samples.iter().copied().collect::<Vec<_>>();
    values.sort_unstable();
    values
}

pub(super) fn percentile(samples: &[u64], percentile: usize) -> u64 {
    if samples.is_empty() {
        return 0;
    }
    let last = samples.len() - 1;
    let index = last
        .checked_mul(percentile)
        .and_then(|value| value.checked_add(99))
        .map(|value| value / 100)
        .unwrap_or(last)
        .min(last);
    samples[index]
}

pub(super) fn append_value(bytes: &mut Digest32Builder, value: &[u8]) {
    bytes.update(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.update(value);
}

pub(super) fn validate_consumption_input(
    row: &BaoConsumptionOperationV1,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    row.validate_for_persistence()
        .map_err(|_| SqliteBaoOwnerErrorV1::InvalidInput)
}

pub(super) fn validate_consumption_stored(
    row: &BaoConsumptionOperationV1,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    row.validate_for_persistence()
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("invalid persisted consumption row"))
}

pub(super) fn validate_lease_operation(
    operation: &LeaseOperationV1,
) -> Result<(), SqliteBaoOwnerErrorV1> {
    validate_identifier(&operation.operation_id)?;
    if operation.semantic_sha256 == [0; 32]
        || operation
            .lease_id
            .as_deref()
            .is_some_and(|value| validate_identifier(value).is_err())
        || operation.expected_generation == Some(0)
        || operation.resulting_generation == Some(0)
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    match operation.kind {
        crate::LeaseOperationKindV1::Issue => {
            if operation.expected_generation.is_some() {
                return Err(SqliteBaoOwnerErrorV1::InvalidInput);
            }
        }
        crate::LeaseOperationKindV1::Renew | crate::LeaseOperationKindV1::Revoke => {
            if operation.lease_id.is_none() || operation.expected_generation.is_none() {
                return Err(SqliteBaoOwnerErrorV1::InvalidInput);
            }
        }
    }
    let terminal = matches!(
        operation.state,
        LeaseOperationStateV1::Applied | LeaseOperationStateV1::Denied
    );
    if !operation.legacy_binding_incomplete
        && (terminal != operation.result_observation.is_some()
            || (!terminal
                && (operation.result_lease.is_some()
                    || operation.observed_at_unix_ms.is_some()
                    || operation.resulting_generation.is_some()))
            || (operation.state == LeaseOperationStateV1::Applied
                && operation.result_lease.is_none()))
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    if operation.state == LeaseOperationStateV1::Denied
        && (operation.result_lease.is_some() || operation.resulting_generation.is_some())
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    if let Some(snapshot) = operation.result_lease.as_ref() {
        validate_lease(snapshot)?;
        if operation.lease_id.as_deref() != Some(snapshot.lease_id.as_str())
            || operation.resulting_generation != Some(snapshot.generation)
        {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
    }
    if let (Some(expected), Some(resulting)) = (
        operation.expected_generation,
        operation.resulting_generation,
    ) && resulting <= expected
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    match operation.result_observation.as_ref() {
        Some(crate::ProviderLeaseObservationV1::Unknown) => {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        Some(
            crate::ProviderLeaseObservationV1::Denied
            | crate::ProviderLeaseObservationV1::NotApplied,
        ) if operation.state != LeaseOperationStateV1::Denied => {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        Some(
            crate::ProviderLeaseObservationV1::IssueApplied { .. }
            | crate::ProviderLeaseObservationV1::RenewApplied { .. }
            | crate::ProviderLeaseObservationV1::RevokeApplied { .. },
        ) if operation.state != LeaseOperationStateV1::Applied => {
            return Err(SqliteBaoOwnerErrorV1::InvalidInput);
        }
        Some(crate::ProviderLeaseObservationV1::IssueApplied { lease }) => {
            if operation.kind != crate::LeaseOperationKindV1::Issue
                || operation.result_lease.as_ref() != Some(lease)
                || lease.generation != 1
                || lease.state != SecretLeaseStateV1::Active
                || operation.observed_at_unix_ms.is_none_or(|value| value == 0)
            {
                return Err(SqliteBaoOwnerErrorV1::InvalidInput);
            }
        }
        Some(crate::ProviderLeaseObservationV1::RenewApplied {
            lease_id,
            observed_at_unix_ms,
            expires_at_unix_ms,
            renewable,
            provider_metadata_sha256,
        }) => {
            let lease = operation
                .result_lease
                .as_ref()
                .ok_or(SqliteBaoOwnerErrorV1::InvalidInput)?;
            if operation.kind != crate::LeaseOperationKindV1::Renew
                || lease.lease_id != *lease_id
                || *observed_at_unix_ms == 0
                || operation.observed_at_unix_ms != Some(*observed_at_unix_ms)
                || lease.expires_at_unix_ms != *expires_at_unix_ms
                || lease.expires_at_unix_ms <= *observed_at_unix_ms
                || lease.renewable != *renewable
                || lease.provider_metadata_sha256 != *provider_metadata_sha256
                || lease.state != SecretLeaseStateV1::Active
                || operation
                    .expected_generation
                    .and_then(|value| value.checked_add(1))
                    != operation.resulting_generation
            {
                return Err(SqliteBaoOwnerErrorV1::InvalidInput);
            }
        }
        Some(crate::ProviderLeaseObservationV1::RevokeApplied {
            lease_id,
            observed_at_unix_ms,
            provider_metadata_sha256,
        }) => {
            let lease = operation
                .result_lease
                .as_ref()
                .ok_or(SqliteBaoOwnerErrorV1::InvalidInput)?;
            if operation.kind != crate::LeaseOperationKindV1::Revoke
                || lease.lease_id != *lease_id
                || *observed_at_unix_ms == 0
                || operation.observed_at_unix_ms != Some(*observed_at_unix_ms)
                || lease.provider_metadata_sha256 != *provider_metadata_sha256
                || lease.state != SecretLeaseStateV1::Revoked
                || lease.renewable
                || operation
                    .expected_generation
                    .and_then(|value| value.checked_add(1))
                    != operation.resulting_generation
            {
                return Err(SqliteBaoOwnerErrorV1::InvalidInput);
            }
        }
        Some(
            crate::ProviderLeaseObservationV1::Denied
            | crate::ProviderLeaseObservationV1::NotApplied,
        )
        | None => {}
    }
    encode_row(operation).map(|_| ())
}

pub(super) fn validate_lease(lease: &SecretLeaseMetadataV1) -> Result<(), SqliteBaoOwnerErrorV1> {
    validate_identifier(&lease.lease_id)?;
    validate_identifier(&lease.secret_reference_id)?;
    validate_identifier(&lease.consumer_id)?;
    if lease.scope_sha256 == [0; 32]
        || lease.provider_metadata_sha256 == [0; 32]
        || lease.generation == 0
        || lease.expires_at_unix_ms <= lease.issued_at_unix_ms
    {
        return Err(SqliteBaoOwnerErrorV1::InvalidInput);
    }
    encode_row(lease).map(|_| ())
}

pub(super) fn same_lease_operation_claim_identity(
    current: &LeaseOperationV1,
    requested: &LeaseOperationV1,
) -> bool {
    if current.operation_id != requested.operation_id
        || current.kind != requested.kind
        || current.semantic_sha256 != requested.semantic_sha256
        || current.expected_generation != requested.expected_generation
    {
        return false;
    }
    match requested.kind {
        crate::LeaseOperationKindV1::Issue => requested.lease_id.is_none(),
        crate::LeaseOperationKindV1::Renew | crate::LeaseOperationKindV1::Revoke => {
            current.lease_id == requested.lease_id
        }
    }
}

pub(super) fn validate_identifier(value: &str) -> Result<(), SqliteBaoOwnerErrorV1> {
    if value.is_empty()
        || value.len() > 256
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
    {
        Err(SqliteBaoOwnerErrorV1::InvalidInput)
    } else {
        Ok(())
    }
}

pub(super) fn lease_operation_kind_text(kind: crate::LeaseOperationKindV1) -> &'static str {
    match kind {
        crate::LeaseOperationKindV1::Issue => "issue",
        crate::LeaseOperationKindV1::Renew => "renew",
        crate::LeaseOperationKindV1::Revoke => "revoke",
    }
}

pub(super) fn state_text(state: BaoConsumptionStateV1) -> &'static str {
    match state {
        BaoConsumptionStateV1::Claimed => "claimed",
        BaoConsumptionStateV1::Reserved => "reserved",
        BaoConsumptionStateV1::DispatchFenced => "dispatch_fenced",
        BaoConsumptionStateV1::DeliveryPrepared => "delivery_prepared",
        BaoConsumptionStateV1::ConsumerSucceeded => "consumer_succeeded",
        BaoConsumptionStateV1::ConsumerNotApplied => "consumer_not_applied",
        BaoConsumptionStateV1::ProviderFailed => "provider_failed",
        BaoConsumptionStateV1::Indeterminate => "indeterminate",
        BaoConsumptionStateV1::Succeeded => "succeeded",
        BaoConsumptionStateV1::Failed => "failed",
        BaoConsumptionStateV1::DispatchAttempted => "dispatch_attempted",
    }
}

pub(super) fn lease_operation_state_text(state: LeaseOperationStateV1) -> &'static str {
    match state {
        LeaseOperationStateV1::Prepared => "prepared",
        LeaseOperationStateV1::Unknown => "unknown",
        LeaseOperationStateV1::Applied => "applied",
        LeaseOperationStateV1::Denied => "denied",
    }
}

pub(super) fn lease_state_text(state: SecretLeaseStateV1) -> &'static str {
    match state {
        SecretLeaseStateV1::Active => "active",
        SecretLeaseStateV1::RenewUnknown => "renew_unknown",
        SecretLeaseStateV1::RevokeUnknown => "revoke_unknown",
        SecretLeaseStateV1::Revoked => "revoked",
        SecretLeaseStateV1::Expired => "expired",
    }
}

pub(super) fn encode_row(value: &impl Serialize) -> Result<Vec<u8>, SqliteBaoOwnerErrorV1> {
    let bytes = serde_json::to_vec(value).map_err(|_| SqliteBaoOwnerErrorV1::InvalidInput)?;
    if bytes.len() > MAX_ROW_BYTES {
        return Err(SqliteBaoOwnerErrorV1::CapacityExceeded);
    }
    Ok(bytes)
}

pub(super) fn decode_row<T: serde::de::DeserializeOwned>(
    bytes: &[u8],
) -> Result<T, SqliteBaoOwnerErrorV1> {
    if bytes.len() > MAX_ROW_BYTES {
        return Err(SqliteBaoOwnerErrorV1::CorruptState(
            "row exceeds encoded bound",
        ));
    }
    serde_json::from_slice(bytes)
        .map_err(|_| SqliteBaoOwnerErrorV1::CorruptState("row JSON is invalid"))
}

pub(super) fn fixed_u64(value: &[u8]) -> Result<u64, SqliteBaoOwnerErrorV1> {
    let value = fixed_u64_allow_zero(value)?;
    if value == 0 {
        Err(SqliteBaoOwnerErrorV1::CorruptState("zero monotonic value"))
    } else {
        Ok(value)
    }
}
