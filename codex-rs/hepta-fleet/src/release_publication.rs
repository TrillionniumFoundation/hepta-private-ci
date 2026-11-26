//! Unix publication keeps Darwin's rename source writable until it is placed.
//! A catalog advisory lock serializes live installers; the durable per-release
//! fence is the admission barrier. Interrupted candidates stay fenced for review;
//! dropping this object, restarting, or retrying never clears that quarantine.

use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::fs::PermissionsExt;

use super::*;

struct PendingPublication<'a> {
    catalog: &'a Path,
    catalog_lock: File,
    release_id: &'a ReleaseId,
    staging: &'a Path,
    destination: PathBuf,
    directory: File,
    fence: File,
    fence_path: PathBuf,
}

pub(super) fn publish(
    catalog: &Path,
    staging: &Path,
    release_id: &ReleaseId,
    expected_manifest: &str,
) -> Result<RegisteredRelease, FleetRegistryError> {
    let publication = PendingPublication::begin(catalog, staging, release_id)?;
    publication.rename()?;
    let release = publication.seal_and_validate(expected_manifest)?;
    publication.commit(sync_directory)?;
    Ok(release)
}

impl<'a> PendingPublication<'a> {
    fn begin(
        catalog: &'a Path,
        staging: &'a Path,
        release_id: &'a ReleaseId,
    ) -> Result<Self, FleetRegistryError> {
        validate_physical_directory(catalog, /*immutable*/ false)?;
        let catalog_lock = File::open(catalog)?;
        catalog_lock.try_lock().map_err(std::io::Error::from)?;
        require_same_file(&catalog_lock, catalog)?;
        // The authoritative absence check and fence creation share this OS
        // lock through commit. A losing installer must never fence a winner
        // that committed after the loser's earlier public preflight check.
        let destination = catalog.join(release_id.as_str());
        require_absent_release(&destination, release_id)?;
        validate_physical_directory(staging, /*immutable*/ false)?;
        let directory = File::open(staging)?;
        require_same_file(&directory, staging)?;
        let fence_path = pending_install_path(catalog, release_id);
        let fence = OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&fence_path)?;
        fence.sync_all()?;
        sync_directory(catalog)?;
        Ok(Self {
            catalog,
            catalog_lock,
            release_id,
            staging,
            destination,
            directory,
            fence,
            fence_path,
        })
    }

    fn rename(&self) -> Result<(), FleetRegistryError> {
        require_same_file(&self.catalog_lock, self.catalog)?;
        require_same_file(&self.directory, self.staging)?;
        require_same_file(&self.fence, &self.fence_path)?;
        std::fs::rename(self.staging, &self.destination)?;
        Ok(())
    }

    fn seal_and_validate(
        &self,
        expected_manifest: &str,
    ) -> Result<RegisteredRelease, FleetRegistryError> {
        require_same_file(&self.directory, &self.destination)?;
        // Seal the retained object, never a path replacement. A same-owner
        // attacker with permission to rewrite the catalog is not sandboxed by
        // this protocol, but substitutions observed here must fail closed.
        self.directory
            .set_permissions(std::fs::Permissions::from_mode(/*mode*/ 0o555))?;
        let release = validate_catalog_release(self.catalog, self.release_id)?;
        let manifest = self.destination.join(RELEASE_MANIFEST_FILE);
        if sha256_file(&manifest)? != expected_manifest {
            return Err(FleetRegistryError::Corrupt(format!(
                "release {} manifest changed during publication",
                self.release_id
            )));
        }
        for (path, mode) in [
            (&self.destination, 0o555),
            (&self.destination.join("bin"), 0o555),
            (&manifest, 0o444),
            (&release.program, 0o555),
        ]
        .into_iter()
        .chain(
            release
                .matrixd
                .iter()
                .map(|program| (&program.program, 0o555)),
        ) {
            if std::fs::symlink_metadata(path)?.permissions().mode() & 0o7777 != mode {
                return Err(FleetRegistryError::Corrupt(format!(
                    "release publication mode changed: {}",
                    path.display()
                )));
            }
        }
        // Program contents and permissions were synced through their writing
        // handles. Persist the manifest's chmod and the root's final seal too.
        File::open(manifest)?.sync_all()?;
        self.directory.sync_all()?;
        require_same_file(&self.directory, &self.destination)?;
        Ok(release)
    }

    fn commit(
        self,
        sync_catalog: impl Fn(&Path) -> Result<(), FleetRegistryError>,
    ) -> Result<(), FleetRegistryError> {
        require_same_file(&self.catalog_lock, self.catalog)?;
        sync_catalog(self.catalog)?;
        require_same_file(&self.directory, &self.destination)?;
        require_same_file(&self.fence, &self.fence_path)?;
        // Admission commits at this unlink. A subsequent sync failure must
        // NOT restore a fence or mutate an already observable release.
        std::fs::remove_file(&self.fence_path)?;
        sync_catalog(self.catalog).map_err(|error| {
            FleetRegistryError::ReleasePublicationDurabilityUncertain {
                release_id: self.release_id.to_string(),
                source: match error {
                    FleetRegistryError::Io(error) => error,
                    error => std::io::Error::other(error),
                },
            }
        })
    }
}

fn require_same_file(handle: &File, path: &Path) -> Result<(), FleetRegistryError> {
    let expected = handle.metadata()?;
    let actual = std::fs::symlink_metadata(path)?;
    if actual.file_type().is_symlink()
        || (actual.dev(), actual.ino()) != (expected.dev(), expected.ino())
    {
        return Err(FleetRegistryError::Corrupt(format!(
            "release publication object was replaced: {}",
            path.display()
        )));
    }
    Ok(())
}

#[cfg(test)]
#[path = "release_publication_tests.rs"]
mod tests;
