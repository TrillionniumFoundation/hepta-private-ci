//! Short observation fence for the original artifact writer and its readers.
use super::*;

const LOCK_MAGIC: &[u8] = b"HEPTA-ARTIFACT-CURRENT-OBSERVATION-V1\n";

fn path(root: &Path) -> PathBuf {
    root.join("writer/current-observation.lock")
}

pub(super) fn create_for_writer(root: &Path) -> Result<File, ArtifactOwnerHostError> {
    // Only the original writer, already holding its lifetime writer fence,
    // may initialize this file. Readers never create or repair a missing lock.
    write_create_only_or_exact(&path(root), LOCK_MAGIC)?;
    open_existing(root)
}

pub(super) fn open_existing(root: &Path) -> Result<File, ArtifactOwnerHostError> {
    let path = path(root);
    let mut file = open_regular_existing(&path, LOCK_MAGIC.len())?;
    let mut bytes = Vec::new();
    (&mut file)
        .take(LOCK_MAGIC.len() as u64 + 1)
        .read_to_end(&mut bytes)?;
    if bytes != LOCK_MAGIC {
        return Err(ArtifactOwnerHostError::CurrentObservationFence);
    }
    Ok(file)
}

pub(super) fn open_regular_existing(
    path: &Path,
    maximum: usize,
) -> Result<File, ArtifactOwnerHostError> {
    let before = fs::symlink_metadata(path)?;
    if !before.is_file()
        || before.file_type().is_symlink()
        || before.len() > maximum as u64
        || path.canonicalize()? != path
    {
        return Err(ArtifactOwnerHostError::CurrentObservationFence);
    }
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(target_os = "linux")]
    options.custom_flags(0x20000 | 0x800); // O_NOFOLLOW | O_NONBLOCK
    #[cfg(target_os = "macos")]
    options.custom_flags(0x100 | 0x4); // O_NOFOLLOW | O_NONBLOCK
    let file = options.open(path)?;
    let opened = file.metadata()?;
    let after = fs::symlink_metadata(path)?;
    if !opened.is_file()
        || opened.len() > maximum as u64
        || after.file_type().is_symlink()
        || path.canonicalize()? != path
    {
        return Err(ArtifactOwnerHostError::CurrentObservationFence);
    }
    #[cfg(unix)]
    if !same_file(&before, &opened) || !same_file(&opened, &after) {
        return Err(ArtifactOwnerHostError::CurrentObservationFence);
    }
    Ok(file)
}

pub(super) fn validate_pinned(root: &Path, pinned: &File) -> Result<(), ArtifactOwnerHostError> {
    let file_path = path(root);
    let current = fs::symlink_metadata(&file_path)?;
    if current.file_type().is_symlink()
        || !current.is_file()
        || !pinned.metadata()?.is_file()
        || file_path.canonicalize()? != file_path
    {
        return Err(ArtifactOwnerHostError::CurrentObservationFence);
    }
    #[cfg(unix)]
    if !same_file(&current, &pinned.metadata()?) {
        return Err(ArtifactOwnerHostError::CurrentObservationFence);
    }
    Ok(())
}

pub(super) fn acquire_exclusive(
    root: &Path,
    pinned: &File,
) -> Result<File, ArtifactOwnerHostError> {
    validate_pinned(root, pinned)?;
    let guard = open_existing(root)?;
    #[cfg(unix)]
    if !same_file(&guard.metadata()?, &pinned.metadata()?) {
        return Err(ArtifactOwnerHostError::CurrentObservationFence);
    }
    match guard.try_lock() {
        Ok(()) => {}
        Err(TryLockError::WouldBlock) => {
            return Err(ArtifactOwnerHostError::CurrentObservationBusy);
        }
        Err(TryLockError::Error(error)) => return Err(error.into()),
    }
    validate_pinned(root, &guard)?;
    Ok(guard)
}

#[cfg(unix)]
fn same_file(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    (left.dev(), left.ino()) == (right.dev(), right.ino())
}
