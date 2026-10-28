//! Persistence boundaries for metadata-only lease lifecycle state.

use std::fs::File;
use std::io::Write;
use std::path::Path;

use super::LeaseOperationV1;
use super::LeaseRegistryErrorV1;
use super::MAX_METADATA_BYTES;
use super::MAX_RECORDS;
use super::SCHEMA_VERSION;
use super::SecretLeaseMetadataV1;
use super::SecretLeaseStateV1;
use super::StoredRegistryV1;

#[cfg(test)]
#[derive(Clone, Copy, Eq, PartialEq)]
pub(super) enum PersistFailure {
    BeforeRename,
    AfterRename,
}

pub(super) fn validate_state(state: &StoredRegistryV1) -> Result<(), LeaseRegistryErrorV1> {
    if state.schema_version != SCHEMA_VERSION
        || state.operations.len() > MAX_RECORDS
        || state.leases.len() > MAX_RECORDS
    {
        return Err(LeaseRegistryErrorV1::CorruptState);
    }
    for (id, operation) in &state.operations {
        if id != &operation.operation_id
            || !identifier(id)
            || operation.semantic_sha256 == [0; 32]
            || operation
                .lease_id
                .as_deref()
                .is_some_and(|value| !identifier(value))
        {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
    }
    for (id, lease) in &state.leases {
        if id != &lease.lease_id {
            return Err(LeaseRegistryErrorV1::CorruptState);
        }
        validate_lease(lease).map_err(|_| LeaseRegistryErrorV1::CorruptState)?;
    }
    Ok(())
}

pub(super) fn validate_lease(lease: &SecretLeaseMetadataV1) -> Result<(), LeaseRegistryErrorV1> {
    if !identifier(&lease.lease_id)
        || !identifier(&lease.secret_reference_id)
        || !identifier(&lease.consumer_id)
        || lease.scope_sha256 == [0; 32]
        || lease.provider_metadata_sha256 == [0; 32]
        || lease.generation == 0
        || lease.expires_at_unix_ms <= lease.issued_at_unix_ms
    {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    let encoded = serde_json::to_vec(lease).map_err(|_| LeaseRegistryErrorV1::InvalidInput)?;
    if encoded.len() > MAX_METADATA_BYTES {
        return Err(LeaseRegistryErrorV1::InvalidInput);
    }
    Ok(())
}

pub(super) fn persist(
    path: &Path,
    state: &StoredRegistryV1,
    #[cfg(test)] failure: Option<PersistFailure>,
) -> Result<(), LeaseRegistryErrorV1> {
    let parent = path.parent().ok_or(LeaseRegistryErrorV1::Unavailable)?;
    std::fs::create_dir_all(parent).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    let bytes = serde_json::to_vec(state).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or(LeaseRegistryErrorV1::Unavailable)?;
    let next = parent.join(format!("{file_name}.next"));
    let mut file = File::create(&next).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    #[cfg(test)]
    if failure == Some(PersistFailure::BeforeRename) {
        return Err(LeaseRegistryErrorV1::Unavailable);
    }
    std::fs::rename(&next, path).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    #[cfg(test)]
    if failure == Some(PersistFailure::AfterRename) {
        return Err(LeaseRegistryErrorV1::IndeterminateDurability);
    }
    #[cfg(windows)]
    let directory = {
        use std::os::windows::fs::OpenOptionsExt;

        // FlushFileBuffers requires write access on a directory handle.
        // Preserve the real durability barrier and every failure result.
        File::options()
            .read(true)
            .write(true)
            .custom_flags(0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
            .open(parent)
    };
    #[cfg(not(windows))]
    let directory = File::open(parent);
    directory
        .and_then(|directory| directory.sync_all())
        .map_err(|_| LeaseRegistryErrorV1::IndeterminateDurability)
}

pub(super) fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"_-.:/".contains(&b))
}

pub(super) fn restore_unknown_lease_state(
    state: &mut StoredRegistryV1,
    operation: &LeaseOperationV1,
) -> Result<(), LeaseRegistryErrorV1> {
    let Some(lease_id) = operation.lease_id.as_ref() else {
        return Ok(());
    };
    let lease = state
        .leases
        .get_mut(lease_id)
        .ok_or(LeaseRegistryErrorV1::LeaseNotFound)?;
    if matches!(
        lease.state,
        SecretLeaseStateV1::RenewUnknown | SecretLeaseStateV1::RevokeUnknown
    ) {
        lease.state = SecretLeaseStateV1::Active;
    }
    Ok(())
}
