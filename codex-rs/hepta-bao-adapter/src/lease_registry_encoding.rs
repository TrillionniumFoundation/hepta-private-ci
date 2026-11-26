//! lease registry encoding implementation.

use super::*;

pub(super) fn stamp_consumption_revisions(current: &StoredRegistryV1, next: &mut StoredRegistryV1) {
    for (operation_id, row) in &mut next.consumptions {
        let previous = current.consumptions.get(operation_id);
        let changed = previous.is_none_or(|value| value != row);
        if row.created_revision == 0 {
            row.created_revision = previous
                .map(|value| value.created_revision)
                .filter(|value| *value != 0)
                .unwrap_or(next.revision);
        }
        if changed || row.updated_revision == 0 {
            row.updated_revision = next.revision;
        }
    }
}

pub(super) fn future_reserve_bytes(
    state: &StoredRegistryV1,
) -> Result<(usize, usize), LeaseRegistryErrorV1> {
    let lease_reserve = state
        .operations
        .values()
        .filter(|operation| {
            matches!(
                operation.state,
                LeaseOperationStateV1::Prepared | LeaseOperationStateV1::Unknown
            )
        })
        .try_fold(0usize, |sum, operation| {
            let bytes = if operation.kind == LeaseOperationKindV1::Issue {
                3 * MAX_METADATA_BYTES
            } else {
                MAX_METADATA_BYTES + 2048
            };
            sum.checked_add(bytes)
                .ok_or(LeaseRegistryErrorV1::CapacityExceeded)
        })?;
    let consumption_reserve = state
        .consumptions
        .values()
        .filter(|row| row.state.requires_future_capacity())
        .count()
        .checked_mul(CONSUMPTION_FUTURE_RESERVE_BYTES)
        .ok_or(LeaseRegistryErrorV1::CapacityExceeded)?;
    Ok((lease_reserve, consumption_reserve))
}

pub(super) fn encode_state(
    state: &StoredRegistryV1,
    required_reserve: usize,
) -> Result<Vec<u8>, LeaseRegistryErrorV1> {
    let (lease_reserve, consumption_reserve) = future_reserve_bytes(state)?;
    let required_reserve = required_reserve.max(
        lease_reserve
            .checked_add(consumption_reserve)
            .ok_or(LeaseRegistryErrorV1::CapacityExceeded)?,
    );
    let bytes = serde_json::to_vec(state).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    if bytes
        .len()
        .checked_add(required_reserve)
        .is_none_or(|required| required > MAX_STORE_BYTES)
    {
        return Err(LeaseRegistryErrorV1::CapacityExceeded);
    }
    Ok(bytes)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum PersistFailure {
    NotApplied,
    Indeterminate,
}

pub(super) fn persist_bytes(
    path: &Path,
    bytes: &[u8],
    persistence: &dyn LeaseRegistryPersistenceV1,
) -> Result<(), PersistFailure> {
    let parent = parent_directory(path);
    let temp_path = sibling_with_suffix(path, ".next");
    remove_if_present(&temp_path).map_err(|_| PersistFailure::NotApplied)?;
    if persistence.write_and_sync_temp(&temp_path, bytes).is_err() {
        let _ = fs::remove_file(&temp_path);
        return Err(PersistFailure::NotApplied);
    }
    if persistence.rename(&temp_path, path).is_err() {
        return Err(PersistFailure::Indeterminate);
    }
    persistence
        .sync_parent(parent)
        .map_err(|_| PersistFailure::Indeterminate)
}

pub(super) fn private_file_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options
            .mode(0o600)
            .custom_flags(rustix::fs::OFlags::NOFOLLOW.bits() as i32);
    }
    options
}

pub(super) fn validate_private_file(file: &File) -> Result<(), LeaseRegistryErrorV1> {
    let metadata = file
        .metadata()
        .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    if !metadata.is_file() {
        return Err(LeaseRegistryErrorV1::Unavailable);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1
            || metadata.mode() & 0o077 != 0
            || metadata.uid() != rustix::process::geteuid().as_raw()
        {
            return Err(LeaseRegistryErrorV1::Unavailable);
        }
    }
    Ok(())
}

pub(super) fn prepare_parent(parent: &Path) -> Result<(), LeaseRegistryErrorV1> {
    if !parent.exists() {
        let mut builder = fs::DirBuilder::new();
        #[cfg(unix)]
        {
            use std::os::unix::fs::DirBuilderExt;
            builder.mode(0o700);
        }
        builder
            .recursive(true)
            .create(parent)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    }
    let metadata = fs::symlink_metadata(parent).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(LeaseRegistryErrorV1::Unavailable);
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.mode() & 0o077 != 0 || metadata.uid() != rustix::process::geteuid().as_raw() {
            return Err(LeaseRegistryErrorV1::Unavailable);
        }
    }
    Ok(())
}

pub(super) fn reject_existing_symlink(path: &Path) -> Result<(), LeaseRegistryErrorV1> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => Err(LeaseRegistryErrorV1::Unavailable),
        Ok(_) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(LeaseRegistryErrorV1::Unavailable),
    }
}

pub(super) fn remove_if_present(path: &Path) -> Result<(), LeaseRegistryErrorV1> {
    reject_existing_symlink(path)?;
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(LeaseRegistryErrorV1::Unavailable),
    }
}

pub(super) fn parent_directory(path: &Path) -> &Path {
    path.parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."))
}

pub(super) fn sibling_with_suffix(path: &Path, suffix: &str) -> PathBuf {
    let mut value = path.as_os_str().to_os_string();
    value.push(suffix);
    PathBuf::from(value)
}

pub(super) fn identifier(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 256
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"_-.:/".contains(&byte))
}
