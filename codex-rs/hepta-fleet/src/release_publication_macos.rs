//! Darwin publication keeps the new root writable until exclusive rename.
//! Readers reject that unsealed root as Corrupt. Failed slots are retained;
//! this is not protection against a hostile administrator racing the namespace.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::Metadata;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::path::PathBuf;

use rustix::fs::Mode;
use rustix::fs::OFlags;
use rustix::fs::RenameFlags;

use super::FleetRegistryError;
use super::ReleaseId;

#[derive(Debug, Eq, PartialEq)]
struct Identity {
    device: u64,
    inode: u64,
    uid: u32,
}

fn identity(metadata: &Metadata) -> Result<Identity, FleetRegistryError> {
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(corrupt("publication directory has unsafe type"));
    }
    Ok(Identity {
        device: metadata.dev(),
        inode: metadata.ino(),
        uid: metadata.uid(),
    })
}

fn corrupt(message: &str) -> FleetRegistryError {
    FleetRegistryError::Corrupt(message.to_string())
}

pub(super) struct Publication {
    catalog_path: PathBuf,
    staging_path: PathBuf,
    catalog: File,
    directory: File,
    catalog_identity: Identity,
    directory_identity: Identity,
}

impl Publication {
    pub(super) fn create(
        catalog_path: &Path,
        staging_path: &Path,
    ) -> Result<Self, FleetRegistryError> {
        if staging_path.parent() != Some(catalog_path) {
            return Err(corrupt("staging is outside publication catalog"));
        }
        let flags = OFlags::RDONLY | OFlags::DIRECTORY | OFlags::NOFOLLOW | OFlags::CLOEXEC;
        let catalog = File::from(
            rustix::fs::open(catalog_path, flags, Mode::empty()).map_err(std::io::Error::from)?,
        );
        let catalog_identity = identity(&catalog.metadata()?)?;
        if identity(&std::fs::symlink_metadata(catalog_path)?)? != catalog_identity {
            return Err(corrupt("publication catalog identity changed"));
        }
        let name = staging_path
            .file_name()
            .ok_or_else(|| corrupt("staging name missing"))?;
        rustix::fs::mkdirat(&catalog, name, Mode::RUSR | Mode::WUSR | Mode::XUSR)
            .map_err(std::io::Error::from)?;
        let directory = File::from(
            rustix::fs::openat(&catalog, name, flags, Mode::empty())
                .map_err(std::io::Error::from)?,
        );
        let directory_identity = identity(&directory.metadata()?)?;
        let publication = Self {
            catalog_path: catalog_path.to_path_buf(),
            staging_path: staging_path.to_path_buf(),
            catalog,
            directory,
            catalog_identity,
            directory_identity,
        };
        publication.verify_path(staging_path, /*expected_mode*/ 0o700)?;
        Ok(publication)
    }

    fn verify_path(&self, path: &Path, expected_mode: u32) -> Result<(), FleetRegistryError> {
        if path.parent() != Some(self.catalog_path.as_path())
            || identity(&self.catalog.metadata()?)? != self.catalog_identity
            || identity(&std::fs::symlink_metadata(&self.catalog_path)?)? != self.catalog_identity
            || identity(&self.directory.metadata()?)? != self.directory_identity
        {
            return Err(corrupt("publication directory binding changed"));
        }
        let metadata = std::fs::symlink_metadata(path)?;
        if identity(&metadata)? != self.directory_identity
            || metadata.mode() & 0o7777 != expected_mode
            || self.directory.metadata()?.mode() & 0o7777 != expected_mode
        {
            return Err(corrupt("publication path identity or mode changed"));
        }
        Ok(())
    }

    fn publish_unsealed(&self, final_root: &Path) -> Result<(), FleetRegistryError> {
        self.verify_path(&self.staging_path, /*expected_mode*/ 0o700)?;
        if final_root.parent() != Some(self.catalog_path.as_path()) {
            return Err(corrupt("release is outside publication catalog"));
        }
        let source = self
            .staging_path
            .file_name()
            .ok_or_else(|| corrupt("staging name missing"))?;
        let destination = final_root
            .file_name()
            .ok_or_else(|| corrupt("release name missing"))?;
        // NOREPLACE is RENAME_EXCL on Darwin. NOSYS/EACCES/EEXIST are errors,
        // never a reason to retry with a clobbering rename or change permissions.
        rustix::fs::renameat_with(
            &self.catalog,
            source,
            &self.catalog,
            destination,
            RenameFlags::NOREPLACE,
        )
        .map_err(std::io::Error::from)?;
        self.verify_path(final_root, /*expected_mode*/ 0o700)
    }

    fn seal(&self, final_root: &Path) -> Result<(), FleetRegistryError> {
        self.verify_path(final_root, /*expected_mode*/ 0o700)?;
        // Only this newly created, retained inode is chmodded. Never final_root.
        self.directory
            .set_permissions(std::fs::Permissions::from_mode(/*mode*/ 0o555))?;
        self.directory.sync_all()?;
        self.catalog.sync_all()?;
        self.verify_path(final_root, /*expected_mode*/ 0o555)
    }

    pub(super) fn publish(&self, final_root: &Path) -> Result<(), FleetRegistryError> {
        let release_id = ReleaseId::parse(
            final_root
                .file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| corrupt("release name is not UTF-8"))?,
        )?;
        verify_prepared(&self.staging_path, &release_id)?;
        self.publish_unsealed(final_root)?;
        verify_prepared(final_root, &release_id)?;
        self.seal(final_root)
    }
}

// New installations are schema V2. Public catalog readers remain unchanged and
// still reject the writable root; only this private preseal check omits that gate.
fn verify_prepared(root: &Path, release_id: &ReleaseId) -> Result<(), FleetRegistryError> {
    let bin = root.join("bin");
    super::validate_physical_directory(&bin, /*immutable*/ true)?;
    if super::directory_names(root)?
        != BTreeSet::from(["bin".to_string(), super::RELEASE_MANIFEST_FILE.to_string()])
    {
        return Err(corrupt("prepared release has unexpected root entries"));
    }
    let manifest = root.join(super::RELEASE_MANIFEST_FILE);
    super::validate_immutable_regular_file(&manifest, /*executable*/ false)?;
    let metadata: super::ReleaseMetadata =
        super::read_bounded_json(&manifest, super::MAX_RELEASE_MANIFEST_BYTES)?;
    super::validate_metadata(&metadata, release_id)?;
    let mut names = BTreeSet::from(["hepta-agentd".to_string()]);
    super::resolve_program(root, &metadata.agentd, release_id)?;
    if let Some(matrixd) = &metadata.matrixd {
        names.insert("hepta-matrixd".to_string());
        super::resolve_program(root, matrixd, release_id)?;
    }
    if super::directory_names(&bin)? != names {
        return Err(corrupt("prepared release has unexpected program entries"));
    }
    Ok(())
}

#[cfg(test)]
#[path = "release_publication_macos_tests.rs"]
mod tests;
