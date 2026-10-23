//! macOS requires an owner-writable directory at rename. Ordinary admission
//! still requires a sealed root; an interrupted publication can only be sealed
//! by an explicit retry with the same programs and arguments.

use super::*;

/// Directory sealing and persistence operations. Implementations must only
/// seal the supplied directory and sync it; identity/admission checks remain
/// in the publication owner, including after an operation reports failure.
pub(super) trait PublicationIo {
    fn seal(&self, path: &Path) -> Result<(), FleetRegistryError>;
    fn sync(&self, path: &Path) -> Result<(), FleetRegistryError>;
}

pub(super) struct NativePublicationIo;

impl PublicationIo for NativePublicationIo {
    fn seal(&self, path: &Path) -> Result<(), FleetRegistryError> {
        set_mode(path, /*mode*/ 0o555)
    }

    fn sync(&self, path: &Path) -> Result<(), FleetRegistryError> {
        sync_directory(path)
    }
}

pub(super) fn publish_prepared_directory(
    control: &ControlRoot,
    staging: &Path,
    destination: &Path,
    io: &impl PublicationIo,
) -> Result<(), FleetRegistryError> {
    let parent = destination
        .parent()
        .ok_or_else(|| FleetRegistryError::Invalid("release has no catalog parent".to_string()))?;
    let namespace = control.directory(parent)?;
    control.directory(staging)?.verify()?;
    let owned = std::fs::symlink_metadata(staging)?;
    // Do not seal before rename: Darwin rejects renaming a write-disabled dir.
    std::fs::rename(staging, destination)?;
    // Rename transfers publication ownership. Never delete the destination
    // on a later seal/fsync error: readers may already have admitted it, and
    // an unsealed complete directory is recoverable through exact retry.
    seal_owned_directory(control, destination, &owned, io)?;
    namespace.verify()
}

pub(super) fn recover_pending_install(
    registry: &FleetRegistry,
    release_id: &ReleaseId,
    source_agentd: &Path,
    agentd_args: &[String],
    source_matrixd: Option<&Path>,
    matrixd_args: &[String],
) -> Result<RegisteredRelease, FleetRegistryError> {
    let catalog = registry.layout().releases_root();
    let root = catalog.join(release_id.as_str());
    registry.control.directory(&root)?.verify()?;
    let owned = std::fs::symlink_metadata(&root)?;
    if !is_writable(&owned) {
        return Err(FleetRegistryError::Invalid(format!(
            "release {release_id} is already installed"
        )));
    }
    let candidate = resolve_catalog_release(
        &registry.control,
        catalog,
        release_id,
        ReleaseRootSeal::PendingInstall,
    )?;
    let matrix_matches = match (&candidate.matrixd, source_matrixd) {
        (None, None) => matrixd_args.is_empty(),
        (Some(program), Some(source)) => {
            program.args.as_slice() == matrixd_args
                && registry.control.sha256(&program.program)? == sha256_file(source)?
        }
        (None, Some(_)) | (Some(_), None) => false,
    };
    if candidate.args.as_slice() != agentd_args
        || registry.control.sha256(&candidate.program)? != sha256_file(source_agentd)?
        || !matrix_matches
    {
        return Err(FleetRegistryError::Invalid(format!(
            "pending release {release_id} differs from this install request"
        )));
    }
    seal_owned_directory(&registry.control, &root, &owned, &NativePublicationIo)?;
    resolve_catalog_release(
        &registry.control,
        catalog,
        release_id,
        ReleaseRootSeal::Required,
    )
}

fn seal_owned_directory(
    control: &ControlRoot,
    path: &Path,
    owned: &std::fs::Metadata,
    io: &impl PublicationIo,
) -> Result<(), FleetRegistryError> {
    control.directory(path)?.verify()?;
    let before = std::fs::symlink_metadata(path)?;
    if !same_owned_directory(owned, &before) {
        return Err(FleetRegistryError::Corrupt(
            "release publication changed its owned directory".to_string(),
        ));
    }
    io.seal(path)?;
    let after = std::fs::symlink_metadata(path)?;
    if !same_owned_directory(owned, &after) || is_writable(&after) {
        return Err(FleetRegistryError::Corrupt(
            "release directory did not retain its sealed identity".to_string(),
        ));
    }
    io.sync(path)?;
    io.sync(path.parent().ok_or_else(|| {
        FleetRegistryError::Invalid("release has no catalog parent".to_string())
    })?)?;
    control.directory(path)?.verify()
}

pub(super) fn cleanup_owned_tree(path: &Path, owned: &std::fs::Metadata) {
    if let Ok(current) = std::fs::symlink_metadata(path)
        && same_owned_directory(owned, &current)
    {
        make_tree_removable(path);
        let _ = std::fs::remove_dir_all(path);
    }
}

fn same_owned_directory(before: &std::fs::Metadata, after: &std::fs::Metadata) -> bool {
    if !before.is_dir() || !after.is_dir() || after.file_type().is_symlink() {
        return false;
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        (before.dev(), before.ino(), before.uid()) == (after.dev(), after.ino(), after.uid())
    }
    #[cfg(not(unix))]
    {
        matches!((before.created(), after.created()), (Ok(before), Ok(after)) if before == after)
    }
}

#[cfg(test)]
#[path = "release_publication_tests.rs"]
mod tests;
