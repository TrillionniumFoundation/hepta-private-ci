//! Durable snapshot and append-only WAL writes. Injection is a private test
//! parameter, never an environment variable or product API that can weaken
//! persistence.
use std::fs::File;
#[cfg(not(unix))]
use std::fs::OpenOptions;
use std::io::Read as _;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;

use atomic_write_file::AtomicWriteFile;

use crate::error::ShellError;
use crate::model::sha256_hex;
use crate::private_state::PrivateStateRoot;

const WAL_MAGIC: &[u8; 8] = b"HPTNWAL1";
const WAL_HEADER_BYTES: usize = 8 + 4 + 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Boundary {
    ParentVerified,
    Opened,
    Written,
    FileSynced,
    Replaced,
    DirectorySynced,
}

#[derive(Clone, Copy)]
pub(crate) enum FileAccess {
    Read,
    Write,
    Append,
    Lock,
    CreateNew,
}

#[derive(Debug)]
pub(crate) struct WalFrames {
    pub(crate) frames: Vec<Vec<u8>>,
    pub(crate) valid_bytes: u64,
    pub(crate) total_bytes: u64,
    pub(crate) partial_tail: bool,
}

pub(crate) fn previous_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(".previous");
    PathBuf::from(name)
}

pub(crate) fn wal_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(".wal");
    PathBuf::from(name)
}

pub(crate) fn write_private(
    root: &PrivateStateRoot,
    path: &Path,
    bytes: &[u8],
) -> Result<(), ShellError> {
    write_at_boundaries(root, path, bytes, |_| Ok(()))
}

fn write_at_boundaries(
    root: &PrivateStateRoot,
    path: &Path,
    bytes: &[u8],
    mut observe: impl FnMut(Boundary) -> Result<(), ShellError>,
) -> Result<(), ShellError> {
    root.verify()?;
    private_child_name(root, path)?;
    observe(Boundary::ParentVerified)?;
    #[cfg(any(target_os = "macos", windows))]
    verify_private_destination(root, path)?;
    let mut file = AtomicWriteFile::open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        let directory = file.directory().ok_or_else(|| {
            ShellError::Security("atomic native state write lacks its parent descriptor".to_owned())
        })?;
        let actual = rustix::fs::fstat(directory).map_err(std::io::Error::from)?;
        let expected = rustix::fs::fstat(root.directory_handle()).map_err(std::io::Error::from)?;
        if actual.st_dev != expected.st_dev || actual.st_ino != expected.st_ino {
            return Err(ShellError::Security(
                "atomic native state parent identity changed".to_owned(),
            ));
        }
        #[cfg(target_os = "macos")]
        codex_utils_private_state::verify_private_permissions(file.as_file())?;
        file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    }
    #[cfg(windows)]
    root.verify_mutable_file(file.as_file())?;
    observe(Boundary::Opened)?;
    #[cfg(any(target_os = "macos", windows))]
    {
        root.verify()?;
        #[cfg(target_os = "macos")]
        codex_utils_private_state::verify_private_permissions(file.as_file())?;
        #[cfg(windows)]
        root.verify_mutable_file(file.as_file())?;
        verify_private_destination(root, path)?;
    }
    file.write_all(bytes)?;
    observe(Boundary::Written)?;
    file.sync_all()?;
    observe(Boundary::FileSynced)?;
    #[cfg(any(target_os = "macos", windows))]
    {
        root.verify()?;
        #[cfg(target_os = "macos")]
        codex_utils_private_state::verify_private_permissions(file.as_file())?;
        #[cfg(windows)]
        root.verify_mutable_file(file.as_file())?;
        verify_private_destination(root, path)?;
    }
    file.commit()?;
    observe(Boundary::Replaced)?;
    sync_private_root(root)?;
    observe(Boundary::DirectorySynced)?;
    Ok(())
}

pub(crate) fn append_wal_frame(
    root: &PrivateStateRoot,
    snapshot_path: &Path,
    payload: &[u8],
    maximum_total: u64,
    maximum_frame: u64,
) -> Result<u64, ShellError> {
    if payload.is_empty() || payload.len() as u64 > maximum_frame {
        return Err(ShellError::State(
            "native journal WAL frame exceeds its byte budget".to_owned(),
        ));
    }
    let path = wal_path(snapshot_path);
    let existed = path.exists();
    let mut file = open_private_file_in(root, &path, FileAccess::Append, existed)?;
    let existing = file.metadata()?.len();
    let frame_bytes = WAL_HEADER_BYTES
        .checked_add(payload.len())
        .ok_or_else(|| ShellError::State("native journal WAL size overflow".to_owned()))?;
    let next = existing
        .checked_add(frame_bytes as u64)
        .ok_or_else(|| ShellError::State("native journal WAL size overflow".to_owned()))?;
    if next > maximum_total {
        return Err(ShellError::State(
            "native journal WAL reached its checkpoint budget".to_owned(),
        ));
    }
    file.write_all(WAL_MAGIC)?;
    file.write_all(&(payload.len() as u32).to_be_bytes())?;
    file.write_all(sha256_hex(payload).as_bytes())?;
    file.write_all(payload)?;
    file.sync_all()?;
    if !existed {
        sync_private_root(root)?;
    }
    root.verify()?;
    Ok(next)
}

pub(crate) fn read_wal_frames(
    root: &PrivateStateRoot,
    snapshot_path: &Path,
    maximum_total: u64,
    maximum_frame: u64,
) -> Result<WalFrames, ShellError> {
    root.verify()?;
    let path = wal_path(snapshot_path);
    if std::fs::symlink_metadata(&path)
        .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound)
    {
        return Ok(WalFrames {
            frames: Vec::new(),
            valid_bytes: 0,
            total_bytes: 0,
            partial_tail: false,
        });
    }
    let file = open_private_file_in(root, &path, FileAccess::Read, /*preexisting*/ true)?;
    let metadata = file.metadata()?;
    if metadata.len() > maximum_total {
        return Err(ShellError::State(
            "native journal WAL exceeds its byte budget".to_owned(),
        ));
    }
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    file.take(maximum_total + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum_total {
        return Err(ShellError::State(
            "native journal WAL read exceeded its byte budget".to_owned(),
        ));
    }
    let mut frames = Vec::new();
    let mut offset = 0usize;
    let mut partial_tail = false;
    while offset < bytes.len() {
        if bytes.len() - offset < WAL_HEADER_BYTES {
            partial_tail = true;
            break;
        }
        if &bytes[offset..offset + WAL_MAGIC.len()] != WAL_MAGIC {
            return Err(ShellError::State(
                "native journal WAL framing magic mismatch".to_owned(),
            ));
        }
        let length_offset = offset + WAL_MAGIC.len();
        let length =
            u32::from_be_bytes(bytes[length_offset..length_offset + 4].try_into().map_err(
                |_| ShellError::State("native journal WAL length framing failed".to_owned()),
            )?) as usize;
        if length == 0 || length as u64 > maximum_frame {
            return Err(ShellError::State(
                "native journal WAL frame length is invalid".to_owned(),
            ));
        }
        let checksum_offset = length_offset + 4;
        let payload_offset = checksum_offset + 64;
        let Some(end) = payload_offset.checked_add(length) else {
            return Err(ShellError::State(
                "native journal WAL frame length overflow".to_owned(),
            ));
        };
        if end > bytes.len() {
            partial_tail = true;
            break;
        }
        let checksum =
            std::str::from_utf8(&bytes[checksum_offset..payload_offset]).map_err(|_| {
                ShellError::State("native journal WAL checksum is not UTF-8".to_owned())
            })?;
        let payload = &bytes[payload_offset..end];
        if checksum != sha256_hex(payload) {
            return Err(ShellError::State(
                "native journal WAL frame checksum mismatch".to_owned(),
            ));
        }
        frames.push(payload.to_vec());
        offset = end;
    }
    Ok(WalFrames {
        frames,
        valid_bytes: offset as u64,
        total_bytes: bytes.len() as u64,
        partial_tail,
    })
}

pub(crate) fn truncate_wal(
    root: &PrivateStateRoot,
    snapshot_path: &Path,
    length: u64,
) -> Result<(), ShellError> {
    root.verify()?;
    let path = wal_path(snapshot_path);
    if std::fs::symlink_metadata(&path)
        .is_err_and(|error| error.kind() == std::io::ErrorKind::NotFound)
    {
        if length == 0 {
            return Ok(());
        }
        return Err(ShellError::State(
            "native journal WAL disappeared before truncation".to_owned(),
        ));
    }
    let file = open_private_file_in(root, &path, FileAccess::Write, /*preexisting*/ true)?;
    file.set_len(length)?;
    file.sync_all()?;
    sync_private_root(root)
}

fn private_child_name<'a>(
    root: &PrivateStateRoot,
    path: &'a Path,
) -> Result<&'a std::ffi::OsStr, ShellError> {
    if path.parent() != Some(root.path()) {
        return Err(ShellError::Security(
            "native state file is outside its private root".to_owned(),
        ));
    }
    path.file_name()
        .ok_or_else(|| ShellError::Security("native state file has no name".to_owned()))
}

pub(crate) fn open_private_file_in(
    root: &PrivateStateRoot,
    path: &Path,
    access: FileAccess,
    preexisting: bool,
) -> Result<File, ShellError> {
    root.verify()?;
    let name = private_child_name(root, path)?;
    #[cfg(unix)]
    let file: File = {
        let access = match access {
            FileAccess::Read => rustix::fs::OFlags::RDONLY,
            FileAccess::Write => rustix::fs::OFlags::WRONLY,
            FileAccess::Append => {
                rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE | rustix::fs::OFlags::APPEND
            }
            FileAccess::Lock => rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE,
            FileAccess::CreateNew => {
                rustix::fs::OFlags::RDWR | rustix::fs::OFlags::CREATE | rustix::fs::OFlags::EXCL
            }
        };
        rustix::fs::openat(
            root.directory_handle(),
            name,
            access
                | rustix::fs::OFlags::NOFOLLOW
                | rustix::fs::OFlags::NONBLOCK
                | rustix::fs::OFlags::CLOEXEC,
            rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        )
        .map_err(std::io::Error::from)?
        .into()
    };
    #[cfg(not(unix))]
    let file = {
        let _ = name;
        let mut options = OpenOptions::new();
        match access {
            FileAccess::Read => {
                options.read(true);
            }
            FileAccess::Write => {
                options.write(true);
            }
            FileAccess::Append => {
                options.read(true).append(true).create(true);
            }
            FileAccess::Lock => {
                options.read(true).write(true).create(true);
            }
            FileAccess::CreateNew => {
                options.read(true).write(true).create_new(true);
            }
        }
        open_private_file(path, &mut options, preexisting)?
    };
    let validation = (|| {
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt as _;

            if !matches!(access, FileAccess::Read) && file.metadata()?.nlink() != 1 {
                return Err(ShellError::Security(
                    "mutable native state file has multiple directory entries".to_owned(),
                ));
            }
        }
        validate_private_file(&file, path, preexisting)?;
        #[cfg(unix)]
        if !matches!(access, FileAccess::Read) {
            use std::os::unix::fs::PermissionsExt as _;

            if file.metadata()?.permissions().mode() & 0o777 != 0o600 {
                file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
            }
        }
        #[cfg(windows)]
        match access {
            FileAccess::Read => root.verify_file(&file)?,
            FileAccess::Write | FileAccess::Append | FileAccess::Lock | FileAccess::CreateNew => {
                root.verify_mutable_file(&file)?;
            }
        }
        root.verify()
    })();
    if let Err(error) = validation {
        drop(file);
        if matches!(access, FileAccess::CreateNew) {
            let _ = remove_private_file_in(root, path);
        }
        return Err(error);
    }
    Ok(file)
}

#[cfg(any(target_os = "macos", windows))]
pub(crate) fn verify_private_destination(
    root: &PrivateStateRoot,
    path: &Path,
) -> Result<(), ShellError> {
    match open_private_file_in(root, path, FileAccess::Read, /*preexisting*/ true) {
        Ok(file) => {
            #[cfg(windows)]
            root.verify_mutable_file(&file)?;
            #[cfg(not(windows))]
            let _ = file;
            Ok(())
        }
        Err(ShellError::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => root.verify(),
        Err(error) => Err(error),
    }
}

/// Unlink an exact temporary child from the original pinned directory. Unix
/// cleanup remains anchored even if the directory's public path was replaced.
pub(crate) fn remove_private_file_in(
    root: &PrivateStateRoot,
    path: &Path,
) -> Result<(), ShellError> {
    let name = private_child_name(root, path)?;
    #[cfg(unix)]
    rustix::fs::unlinkat(root.directory_handle(), name, rustix::fs::AtFlags::empty())
        .map_err(std::io::Error::from)?;
    #[cfg(not(unix))]
    {
        let _ = name;
        root.verify()?;
        std::fs::remove_file(path)?;
        root.verify()?;
    }
    Ok(())
}

fn sync_private_root(root: &PrivateStateRoot) -> Result<(), ShellError> {
    #[cfg(unix)]
    root.directory_handle().sync_all()?;
    root.verify()
}

/// Validate the same handle used for mutation. A path-only check followed by a
/// normal open can follow a replaced link or create a dangling link's target.
#[cfg(not(unix))]
fn open_private_file(
    path: &Path,
    options: &mut OpenOptions,
    preexisting: bool,
) -> Result<File, ShellError> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt as _;
        options.custom_flags(0x0020_0000); // FILE_FLAG_OPEN_REPARSE_POINT
    }
    let file = options.open(path)?;
    validate_private_file(&file, path, preexisting)?;
    Ok(file)
}

fn validate_private_file(file: &File, path: &Path, preexisting: bool) -> Result<(), ShellError> {
    #[cfg(not(unix))]
    let _ = preexisting;
    let metadata = file.metadata()?;
    if !metadata.is_file() {
        return Err(ShellError::Security(format!(
            "native journal state is not a regular local file: {}",
            path.display()
        )));
    }
    #[cfg(target_os = "macos")]
    codex_utils_private_state::verify_private_permissions(file)?;
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt as _;
        if metadata.file_attributes() & 0x400 != 0 {
            return Err(ShellError::Security(format!(
                "native journal state is a reparse point: {}",
                path.display()
            )));
        }
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        let mode = metadata.permissions().mode() & 0o777;
        if preexisting && mode & 0o077 != 0 {
            return Err(ShellError::Security(format!(
                "native journal WAL is group/world accessible: {}",
                path.display()
            )));
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "journal_storage_tests.rs"]
mod tests;

#[cfg(all(test, target_os = "macos"))]
#[path = "journal_macos_tests.rs"]
mod macos_tests;

#[cfg(all(test, windows))]
#[path = "journal_windows_tests.rs"]
mod windows_tests;
