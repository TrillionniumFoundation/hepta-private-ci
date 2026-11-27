//! Install only a previously verified independent image into its registered
//! store. This Root-only integrity primitive grants no Current or writer lease.

use super::*;
use crate::cognitive_store::COGNITIVE_RECOVERED_DB_PREFIX;
use crate::cognitive_store::CognitiveStoreOpenGuard;
use crate::cognitive_store::publish_active_database;
use crate::cognitive_store::recovered_database_filename;
use crate::cognitive_store::valid_recovered_database_filename;
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
    /// Reconcile an already installed, unreleased Root generation against its
    /// independently retained image. This does not capture a witness, publish a
    /// pointer, install another generation or issue a writer. The original Root
    /// verifies the exact existing Current/live registration before this call.
    pub async fn reopen_root_checkpoint_installation(
        layout: &HeptaAgentLayout,
        image: CognitiveCheckpointImage,
        registered_uid: u32,
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
        validate_installation_directory(root, &directory)?;
        let path = resolve_active_database_path(root).map_err(unavailable)?;
        reopen_installation(
            root,
            path,
            image,
            InstallationOwner::Releasing(registered_uid),
            directory,
            guard,
        )
        .await
    }

    /// Called only after Root proves the old publisher retired, the old lease
    /// expired, the new original lease live, and holds the original writer lock.
    /// The registered cognitive directory must already be under Root0700
    /// custody. No live DB is opened, hashed, repaired or used as a witness.
    /// Old DB/WAL/journal generations remain untouched; the old pointer bytes
    /// are retained before the ORIGINAL atomic pointer publication. A complete
    /// Root-owned installation already selected by that pointer is reopened
    /// only against the same independently verified image, with no new writes
    /// or publication. Partial, ambiguous or changed installations are refused.
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
        validate_installation_directory(root, &directory)?;
        if private_file(&image.path, /*owner*/ 0)?.2 != image.bytes
            || digest_image(&image.file)? != (image.sha256.clone(), image.bytes)
        {
            return Err(invalid("independent material changed before installation"));
        }
        // An interrupted original install stays Root-owned until its Current
        // adoption and explicit release. Do not create a second generation or
        // republish its pointer. The original exclusive lock remains retained
        // across discovery, verification and the returned opaque installation.
        let active = match std::fs::symlink_metadata(root.join(".cognitive-active-v1")) {
            Ok(_) => Some(resolve_active_database_path(root).map_err(unavailable)?),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => return Err(unavailable(error)),
        };
        let mut retained = None;
        for entry in std::fs::read_dir(root).map_err(unavailable)? {
            let entry = entry.map_err(unavailable)?;
            let name = entry.file_name();
            if !name
                .as_encoded_bytes()
                .starts_with(COGNITIVE_RECOVERED_DB_PREFIX.as_bytes())
            {
                continue;
            }
            let metadata = entry.path().symlink_metadata().map_err(unavailable)?;
            if metadata.uid() != 0 {
                continue; // Suspect old owner bytes are never a recovery witness.
            }
            let name = name
                .to_str()
                .ok_or_else(|| invalid("invalid unreleased Root installation name"))?;
            if !valid_recovered_database_filename(name) || retained.is_some() {
                return Err(invalid("ambiguous unreleased Root installation"));
            }
            retained = Some(entry.path());
        }
        if let Some(path) = retained {
            if active.as_ref() != Some(&path) {
                return Err(invalid(
                    "unreleased Root installation has no exact active pointer",
                ));
            }
            return reopen_installation(
                root,
                path,
                image,
                InstallationOwner::Root,
                directory,
                guard,
            )
            .await;
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
        preserve_pointer(
            root,
            path.file_name()
                .and_then(|name| name.to_str())
                .ok_or_else(|| invalid("installed generation name missing"))?,
        )?;
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

#[derive(Clone, Copy)]
enum InstallationOwner {
    Root,
    Releasing(u32),
}

async fn reopen_installation(
    root: &Path,
    path: PathBuf,
    image: CognitiveCheckpointImage,
    owner: InstallationOwner,
    directory: File,
    guard: CognitiveStoreOpenGuard,
) -> Result<InstalledRootCheckpointImage, CognitiveRecoveryError> {
    let identity = installation_file(&path, owner)?;
    let database = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(&path)
        .map_err(unavailable)?;
    let held = database.metadata().map_err(unavailable)?;
    if (held.dev(), held.ino()) != (identity.0, identity.1)
        || digest_image(&database)? != (image.sha256.clone(), image.bytes)
        || digest_image(&image.file)? != (image.sha256.clone(), image.bytes)
    {
        return Err(invalid(
            "unreleased generation differs from independent pre-crash material",
        ));
    }
    validate_image(&path, &image.cut).await?;
    let pointer_path = root.join(".cognitive-active-v1");
    let pointer_identity = installation_file(&pointer_path, owner)?;
    let pointer = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
        .open(&pointer_path)
        .map_err(unavailable)?;
    let held = pointer.metadata().map_err(unavailable)?;
    if (held.dev(), held.ino()) != (pointer_identity.0, pointer_identity.1)
        || resolve_active_database_path(root).map_err(unavailable)? != path
        || installation_file(&path, owner)? != identity
    {
        return Err(invalid("unreleased generation identity changed"));
    }
    validate_installation_directory(root, &directory)?;
    database.sync_all().map_err(unavailable)?;
    pointer.sync_all().map_err(unavailable)?;
    directory.sync_all().map_err(unavailable)?;
    Ok(InstalledRootCheckpointImage {
        path,
        directory,
        database,
        pointer,
        root: root.to_path_buf(),
        _guard: guard,
    })
}

fn validate_installation_directory(
    root: &Path,
    directory: &File,
) -> Result<(), CognitiveRecoveryError> {
    let named = private_directory(root, /*owner*/ 0)?
        .metadata()
        .map_err(unavailable)?;
    let held = directory.metadata().map_err(unavailable)?;
    if (named.dev(), named.ino()) != (held.dev(), held.ino()) {
        return Err(invalid(
            "registered installation directory identity changed",
        ));
    }
    Ok(())
}

fn installation_file(
    path: &Path,
    allowed: InstallationOwner,
) -> Result<(u64, u64, u64, i64, i64), CognitiveRecoveryError> {
    let owner = path.symlink_metadata().map_err(unavailable)?.uid();
    match allowed {
        InstallationOwner::Root if owner != 0 => {
            return Err(invalid("unadopted installation must remain Root-owned"));
        }
        InstallationOwner::Releasing(registered_uid)
            if matches!(registered_uid, 0 | u32::MAX)
                || (owner != 0 && owner != registered_uid) =>
        {
            return Err(invalid(
                "unreleased installation owner is not the registered UID or Root",
            ));
        }
        InstallationOwner::Root | InstallationOwner::Releasing(_) => {}
    }
    private_file(path, owner)
}

fn preserve_pointer(root: &Path, generation: &str) -> Result<(), CognitiveRecoveryError> {
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
    let path = root.join(format!(".cognitive-active-v1.before-material-{generation}"));
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
