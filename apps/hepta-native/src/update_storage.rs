use crate::error::ShellError;
use crate::private_state::PrivateStateRoot;
use atomic_write_file::AtomicWriteFile;
use serde::Serialize;
use sha2::Digest as _;
use sha2::Sha256;
use std::fs::File;
use std::io::Read as _;
use std::io::Write as _;
use std::path::Path;
pub(crate) const MAX_PACKAGE_BYTES: u64 = 512 * 1024 * 1024;

pub fn digest_file(path: &Path) -> Result<String, ShellError> {
    digest_open_file(crate::file_input::open_regular_file(path)?)
}

pub(crate) fn running_binary_digest() -> Result<String, ShellError> {
    #[cfg(target_os = "linux")]
    {
        // This kernel-owned link resolves the actual loaded executable inode,
        // not an unrelated replacement installed at the same pathname.
        digest_open_file(File::open("/proc/self/exe")?)
    }
    #[cfg(not(target_os = "linux"))]
    {
        digest_file(&std::env::current_exe()?)
    }
}

fn digest_open_file(mut file: File) -> Result<String, ShellError> {
    let mut hasher = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    let mut total = 0_u64;
    loop {
        let read = file.read(&mut buffer)?;
        if read == 0 {
            break;
        }
        total = total.saturating_add(read as u64);
        if total > MAX_PACKAGE_BYTES {
            return Err(ShellError::Update(format!(
                "file exceeds {MAX_PACKAGE_BYTES} bytes"
            )));
        }
        hasher.update(&buffer[..read]);
    }
    let digest = hasher.finalize();
    let mut out = String::with_capacity(64);
    for byte in digest {
        use std::fmt::Write as _;
        let _ = write!(&mut out, "{byte:02x}");
    }
    Ok(out)
}

pub(crate) fn copy_and_sync(source: &Path, destination: &Path) -> Result<(), ShellError> {
    if let Some(parent) = destination.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let source_file = crate::file_input::open_regular_file(source)?;
    let source_metadata = source_file.metadata()?;
    if source_metadata.len() > MAX_PACKAGE_BYTES {
        return Err(ShellError::Update(
            "copy source exceeds the package bound".into(),
        ));
    }
    let mut destination_file = AtomicWriteFile::open(destination)?;
    let copied = std::io::copy(
        &mut source_file.take(MAX_PACKAGE_BYTES + 1),
        &mut destination_file,
    )?;
    if copied > MAX_PACKAGE_BYTES {
        return Err(ShellError::Update(
            "copy source grew beyond the package bound".into(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        let mode = match std::fs::symlink_metadata(destination) {
            Ok(metadata) if metadata.is_file() => metadata.permissions().mode(),
            Ok(_) => {
                return Err(ShellError::Update(
                    "copy destination is not a regular file".into(),
                ));
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                source_metadata.permissions().mode()
            }
            Err(error) => return Err(error.into()),
        };
        // New backups retain executable bits. Existing installed binaries keep
        // their mode even when an operator downloads a non-executable package.
        destination_file.set_permissions(std::fs::Permissions::from_mode(mode & 0o777))?;
    }
    destination_file.flush()?;
    destination_file.sync_all()?;
    destination_file.commit()?;
    sync_parent_directory(destination)?;
    Ok(())
}

pub(crate) fn persist_json_atomic(path: &Path, value: &impl Serialize) -> Result<(), ShellError> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let bytes = serde_json::to_vec(value)?;
    let mut file = AtomicWriteFile::open(path)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    file.commit()?;
    sync_parent_directory(path)?;
    Ok(())
}

#[cfg(unix)]
pub(crate) fn sync_parent_directory(path: &Path) -> Result<(), ShellError> {
    if let Some(parent) = path.parent() {
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

#[cfg(not(unix))]
pub(crate) fn sync_parent_directory(_path: &Path) -> Result<(), ShellError> {
    Ok(())
}

// Shared by GUI transitions and the updater helper; never held across GUI life.
pub(crate) fn lock_update_root(root: &Path) -> Result<File, ShellError> {
    lock_named(root, "update-owner.lock")
}

pub(crate) fn lock_update_runner(root: &Path) -> Result<File, ShellError> {
    lock_named(root, "update-runner.lock")
}

fn lock_named(root: &Path, name: &str) -> Result<File, ShellError> {
    let _private_root = PrivateStateRoot::open_existing(root.to_path_buf())?;
    let path = root.join(name);
    match std::fs::symlink_metadata(&path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            return Err(ShellError::Security(
                "update owner lock is not a regular file".to_owned(),
            ));
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    let mut options = std::fs::OpenOptions::new();
    options.read(true).write(true).create(true).truncate(false);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.mode(0o600);
    }
    let file = options.open(path)?;
    file.try_lock().map_err(|_| {
        ShellError::Update("another native update transition is in progress".to_owned())
    })?;
    Ok(file)
}
