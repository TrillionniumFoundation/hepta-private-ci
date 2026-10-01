//! FD-checked Root policy and role-owned private material for real services.
use crate::ConsumerPortError;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::path::Path;
use zeroize::Zeroizing;
const MAX_FRAME_BYTES: usize = 32 * 1024;
pub(crate) fn read_root_configuration<T: serde::de::DeserializeOwned>(
    path: &Path,
) -> Result<T, ConsumerPortError> {
    use std::io::Read;
    if !path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                std::path::Component::ParentDir | std::path::Component::CurDir
            )
        })
    {
        return Err(ConsumerPortError::Invalid);
    }
    for ancestor in path.parent().ok_or(ConsumerPortError::Invalid)?.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor).map_err(unavailable)?;
        if !metadata.is_dir()
            || metadata.file_type().is_symlink()
            || metadata.uid() != 0
            || metadata.mode() & 0o022 != 0
        {
            return Err(ConsumerPortError::Invalid);
        }
    }
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags((rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32)
        .open(path)
        .map_err(unavailable)?;
    let metadata = file.metadata().map_err(unavailable)?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != 0
        || metadata.mode() & 0o027 != 0
        || metadata.len() > MAX_FRAME_BYTES as u64
    {
        return Err(ConsumerPortError::Invalid);
    }
    let mut bytes = Vec::new();
    Read::take(&mut file, MAX_FRAME_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() > MAX_FRAME_BYTES {
        return Err(ConsumerPortError::Invalid);
    }
    serde_json::from_slice(&bytes).map_err(unavailable)
}
pub(crate) fn read_private(
    path: &Path,
    maximum: usize,
) -> Result<Zeroizing<Vec<u8>>, ConsumerPortError> {
    use std::io::Read;
    let mut file = std::fs::OpenOptions::new()
        .read(true)
        .custom_flags((rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32)
        .open(path)
        .map_err(unavailable)?;
    let metadata = file.metadata().map_err(unavailable)?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
        || metadata.mode() & 0o077 != 0
        || metadata.len() > maximum as u64
    {
        return Err(ConsumerPortError::Invalid);
    }
    let mut bytes = Zeroizing::new(Vec::new());
    Read::take(&mut file, maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(unavailable)?;
    if bytes.len() > maximum {
        return Err(ConsumerPortError::Invalid);
    }
    Ok(bytes)
}

fn unavailable(_error: impl std::fmt::Display) -> ConsumerPortError {
    ConsumerPortError::Unavailable
}
