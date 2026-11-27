//! Publish a private pending directory before sealing its outer directory.
//!
//! The existing catalog resolver rejects every writable release root. This
//! permits a directory rename that requires write access to its source without
//! admitting the pending release or granting any per-agent allowance.

use std::fs;
use std::fs::File;
use std::fs::Metadata;
use std::fs::Permissions;
use std::io;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;

use crate::FleetRegistryError;
use crate::release_io::observe_io;

pub(super) fn create_staging(path: &Path) -> io::Result<()> {
    fs::DirBuilder::new().mode(0o700).create(path)
}

#[derive(Default)]
pub(super) struct Publication {
    renamed: bool,
}

impl Publication {
    pub(super) fn publish(
        &mut self,
        staging: &Path,
        final_root: &Path,
    ) -> Result<(), FleetRegistryError> {
        self.publish_with_seal(staging, final_root, |directory| {
            directory.set_permissions(Permissions::from_mode(/*mode*/ 0o555))
        })
    }

    fn publish_with_seal(
        &mut self,
        staging: &Path,
        final_root: &Path,
        seal: impl FnOnce(&File) -> io::Result<()>,
    ) -> Result<(), FleetRegistryError> {
        let staged = fs::symlink_metadata(staging)?;
        if !staged.file_type().is_dir() || staged.mode() & 0o777 != 0o700 {
            return Err(FleetRegistryError::Corrupt(
                "pending release is not a private writable directory".to_string(),
            ));
        }
        let identity = (staged.dev(), staged.ino());
        let rename_result = observe_io("install.rename", fs::rename(staging, final_root));
        #[cfg(test)]
        if let Err(error) = &rename_result {
            let _ = crate::release_io::observe_failed_rename(staging, final_root, error);
        }
        rename_result?;
        self.renamed = true;

        // Do not hold an open directory across rename. After rename, bind the
        // seal to the opened object and reject a symlink or a different inode.
        // These checks are not a namespace lease against another administrator.
        require_identity(&fs::symlink_metadata(final_root)?, identity)?;
        let directory = File::open(final_root)?;
        require_identity(&directory.metadata()?, identity)?;
        require_identity(&fs::symlink_metadata(final_root)?, identity)?;
        observe_io("install.seal_published", seal(&directory))?;
        let sealed = directory.metadata()?;
        require_identity(&sealed, identity)?;
        if sealed.mode() & 0o7777 != 0o555 {
            return Err(FleetRegistryError::Corrupt(
                "published release directory did not retain its sealed mode".to_string(),
            ));
        }
        observe_io("install.sync_sealed_directory", directory.sync_all())?;
        require_identity(&fs::symlink_metadata(final_root)?, identity)
    }

    pub(super) fn cleanup_staging(&self, staging: &Path) {
        // A post-rename error must not delete the public name, or the old
        // staging name if somebody has reused it. A writable pending final
        // directory remains rejected and requires explicit administrator repair.
        if !self.renamed {
            super::make_tree_removable(staging);
            let _ = fs::remove_dir_all(staging);
        }
    }
}

fn require_identity(metadata: &Metadata, expected: (u64, u64)) -> Result<(), FleetRegistryError> {
    if !metadata.file_type().is_dir() || (metadata.dev(), metadata.ino()) != expected {
        return Err(FleetRegistryError::Corrupt(
            "pending release directory identity changed".to_string(),
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "release_publication_macos_tests.rs"]
mod tests;
