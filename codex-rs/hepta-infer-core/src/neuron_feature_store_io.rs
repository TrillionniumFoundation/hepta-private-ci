fn framed_bytes(payload_len: usize) -> Result<u64, NeuronFeatureStoreError> {
    4_u64
        .checked_add(u64::try_from(payload_len).map_err(|_| NeuronFeatureStoreError::Capacity)?)
        .and_then(|value| value.checked_add(CHECKSUM_BYTES as u64))
        .ok_or(NeuronFeatureStoreError::Capacity)
}

fn truncate_partial(
    file: &mut LockedFeatureFile,
    offset: u64,
) -> Result<(), NeuronFeatureStoreError> {
    file.set_len(offset)
        .map_err(|_| NeuronFeatureStoreError::Indeterminate)?;
    file.sync_all()
        .map_err(|_| NeuronFeatureStoreError::Indeterminate)
}

fn validate_parent(path: &Path) -> Result<(), NeuronFeatureStoreError> {
    let parent = path
        .parent()
        .ok_or(NeuronFeatureStoreError::Io(io::ErrorKind::InvalidInput))?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(NeuronFeatureStoreError::NotRegular);
    }
    Ok(())
}

#[cfg(unix)]
fn sync_parent_directory(path: &Path) -> Result<(), NeuronFeatureStoreError> {
    let parent = path
        .parent()
        .ok_or(NeuronFeatureStoreError::Io(io::ErrorKind::InvalidInput))?;
    File::open(parent)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent_directory(_path: &Path) -> Result<(), NeuronFeatureStoreError> {
    Ok(())
}
