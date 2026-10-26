//! Install only a previously verified independent image into its registered
//! store. This Root-only integrity primitive grants no Current or writer lease.

use super::*;
use crate::cognitive_store::CognitiveStoreOpenGuard;
use crate::cognitive_store::publish_active_database;
use crate::cognitive_store::recovered_database_filename;
use std::io::Write;

/// Retains the original exclusive store lock and Root custody until the trusted
/// launcher finishes its ORIGINAL Current adoption and releases its exact UID.
pub struct InstalledRootCheckpointImage {
    path: PathBuf,
    directory: File,
    database: File,
    pointer: File,
    root: PathBuf,
    _guard: CognitiveStoreOpenGuard,
}

impl InstalledRootCheckpointImage {
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Root supplies the same dedicated UID/GID it has actually registered.
    /// This releases filesystem custody only; it creates no owner or authority.
    pub fn release_to_registered_owner(
        self,
        uid: u32,
        gid: u32,
    ) -> Result<(), CognitiveRecoveryError> {
        require_root()?;
        if matches!(uid, 0 | u32::MAX) || matches!(gid, 0 | u32::MAX) {
            return Err(invalid("dedicated registered UID/GID required"));
        }
        let path = self.root.symlink_metadata().map_err(unavailable)?;
        let held = self.directory.metadata().map_err(unavailable)?;
        if (path.dev(), path.ino()) != (held.dev(), held.ino()) || path.uid() != 0 {
            return Err(invalid("registered install directory identity changed"));
        }
        for file in [&self.database, &self.pointer] {
            change_owner(file, uid, gid)?;
            file.sync_all().map_err(unavailable)?;
        }
        self.directory.sync_all().map_err(unavailable)?;
        change_owner(&self.directory, uid, gid)?;
        self.directory.sync_all().map_err(unavailable)?;
        Ok(())
    }
}

impl CognitiveStore {
    /// Called only after Root proves the old publisher retired, the old lease
    /// expired, the new original lease live, and holds the original writer lock.
    /// The registered cognitive directory must already be under Root0700
    /// custody. No live DB is opened, hashed, repaired or used as a witness.
    /// Old DB/WAL/journal generations remain untouched; the old pointer bytes
    /// are retained before the ORIGINAL atomic pointer publication.
    pub async fn install_root_checkpoint_image(
        layout: &HeptaAgentLayout,
        image: CognitiveCheckpointImage,
    ) -> Result<InstalledRootCheckpointImage, CognitiveRecoveryError> {
        require_root()?;
        super::super::validate_requirement(
            layout,
            CognitiveRecoveryRequirement::ExactCurrentCut(&image.cut),
        )?;
        let root = layout.cognitive_root();
        if root.canonicalize().map_err(unavailable)? != root || image.path.starts_with(root) {
            return Err(invalid(
                "original registered root and independent image required",
            ));
        }
        let directory = private_directory(root, /*owner*/ 0)?;
        let guard = CognitiveStoreOpenGuard::acquire_exclusive(root).map_err(unavailable)?;
        if private_file(&image.path, /*owner*/ 0)?.2 != image.bytes
            || digest_image(&image.file)? != (image.sha256.clone(), image.bytes)
        {
            return Err(invalid("independent material changed before installation"));
        }
        // This is a fresh original-format generation name. The image digest is
        // an integrity salt here, never a substitute writer fencing token.
        let path = root.join(recovered_database_filename(&image.cut, &image.sha256));
        let mut database = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .mode(0o600)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(&path)
            .map_err(unavailable)?;
        let mut offset = 0_u64;
        let mut buffer = [0_u8; 64 * 1024];
        while offset < image.bytes {
            let count = image
                .file
                .read_at(&mut buffer, offset)
                .map_err(unavailable)?;
            if count == 0 || offset + count as u64 > image.bytes {
                return Err(invalid(
                    "independent material length changed during installation",
                ));
            }
            database.write_all(&buffer[..count]).map_err(unavailable)?;
            offset += count as u64;
        }
        database.sync_all().map_err(unavailable)?;
        if digest_image(&database)? != (image.sha256.clone(), image.bytes)
            || digest_image(&image.file)? != (image.sha256.clone(), image.bytes)
        {
            return Err(invalid(
                "installed bytes differ from retained independent material",
            ));
        }
        validate_image(&path, &image.cut).await?;
        preserve_pointer(root, &image.sha256)?;
        directory.sync_all().map_err(unavailable)?;
        publish_active_database(root, &path).map_err(|error| {
            CognitiveRecoveryError::Indeterminate(format!(
                "material pointer publication uncertain: {error}"
            ))
        })?;
        let pointer = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open(root.join(".cognitive-active-v1"))
            .map_err(unavailable)?;
        let installed = InstalledRootCheckpointImage {
            path,
            directory,
            database,
            pointer,
            root: root.to_path_buf(),
            _guard: guard,
        };
        Ok(installed)
    }
}

fn preserve_pointer(root: &Path, digest: &Sha256Digest) -> Result<(), CognitiveRecoveryError> {
    let source = match OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(root.join(".cognitive-active-v1"))
    {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(()),
        Err(error) => return Err(unavailable(error)),
    };
    let metadata = source.metadata().map_err(unavailable)?;
    if !metadata.is_file()
        || metadata.nlink() != 1
        || metadata.mode() & 0o7777 != 0o600
        || metadata.len() > 256
    {
        return Err(invalid("prior pointer is not one bounded private file"));
    }
    let path = root.join(format!(
        ".cognitive-active-v1.before-material-{}",
        digest.as_str()
    ));
    let mut target = OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(path)
        .map_err(unavailable)?;
    let mut bytes = [0_u8; 257];
    let count = source
        .read_at(&mut bytes, /*offset*/ 0)
        .map_err(unavailable)?;
    if count as u64 != metadata.len() {
        return Err(invalid("prior pointer changed"));
    }
    target.write_all(&bytes[..count]).map_err(unavailable)?;
    target.sync_all().map_err(unavailable)
}

fn require_root() -> Result<(), CognitiveRecoveryError> {
    if !rustix::process::getuid().is_root() || !rustix::process::geteuid().is_root() {
        return Err(invalid("physical installation requires actual Root"));
    }
    Ok(())
}

fn change_owner(file: &File, uid: u32, gid: u32) -> Result<(), CognitiveRecoveryError> {
    rustix::fs::fchown(
        file,
        Some(rustix::fs::Uid::from_raw(uid)),
        Some(rustix::fs::Gid::from_raw(gid)),
    )
    .map_err(unavailable)
}
