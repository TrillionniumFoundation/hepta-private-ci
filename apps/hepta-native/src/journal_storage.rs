//! Durable snapshot and append-only WAL writes. Injection is a private test
//! parameter, never an environment variable or product API that can weaken
//! persistence.
#[cfg(unix)]
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read as _;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;

use atomic_write_file::AtomicWriteFile;

use crate::error::ShellError;
use crate::model::sha256_hex;

const WAL_MAGIC: &[u8; 8] = b"HPTNWAL1";
const WAL_HEADER_BYTES: usize = 8 + 4 + 64;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Boundary {
    Opened,
    Written,
    FileSynced,
    Replaced,
    DirectorySynced,
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

pub(crate) fn write(path: &Path, bytes: &[u8]) -> Result<(), ShellError> {
    write_at_boundaries(path, bytes, |_| Ok(()))
}

pub(crate) fn append_wal_frame(
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
    let existing = if existed {
        std::fs::metadata(&path)?.len()
    } else {
        0
    };
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
    let mut options = OpenOptions::new();
    options.create(true).append(true).read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.mode(0o600);
    }
    let mut file = options.open(&path)?;
    ensure_private_file(&path, existed)?;
    file.write_all(WAL_MAGIC)?;
    file.write_all(&(payload.len() as u32).to_be_bytes())?;
    file.write_all(sha256_hex(payload).as_bytes())?;
    file.write_all(payload)?;
    file.sync_all()?;
    if !existed {
        sync_parent(&path)?;
    }
    Ok(next)
}

pub(crate) fn read_wal_frames(
    snapshot_path: &Path,
    maximum_total: u64,
    maximum_frame: u64,
) -> Result<WalFrames, ShellError> {
    let path = wal_path(snapshot_path);
    if !path.exists() {
        return Ok(WalFrames {
            frames: Vec::new(),
            valid_bytes: 0,
            total_bytes: 0,
            partial_tail: false,
        });
    }
    ensure_private_file(&path, true)?;
    let metadata = std::fs::metadata(&path)?;
    if metadata.len() > maximum_total {
        return Err(ShellError::State(
            "native journal WAL exceeds its byte budget".to_owned(),
        ));
    }
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    crate::file_input::open_regular_file(&path)?
        .take(maximum_total + 1)
        .read_to_end(&mut bytes)?;
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

pub(crate) fn truncate_wal(snapshot_path: &Path, length: u64) -> Result<(), ShellError> {
    let path = wal_path(snapshot_path);
    if !path.exists() {
        if length == 0 {
            return Ok(());
        }
        return Err(ShellError::State(
            "native journal WAL disappeared before truncation".to_owned(),
        ));
    }
    ensure_private_file(&path, true)?;
    let file = OpenOptions::new().write(true).open(&path)?;
    file.set_len(length)?;
    file.sync_all()?;
    sync_parent(&path)
}

fn write_at_boundaries(
    path: &Path,
    bytes: &[u8],
    mut observe: impl FnMut(Boundary) -> Result<(), ShellError>,
) -> Result<(), ShellError> {
    let mut file = AtomicWriteFile::open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    }
    observe(Boundary::Opened)?;
    file.write_all(bytes)?;
    observe(Boundary::Written)?;
    file.sync_all()?;
    observe(Boundary::FileSynced)?;
    file.commit()?;
    observe(Boundary::Replaced)?;
    sync_parent(path)?;
    observe(Boundary::DirectorySynced)?;
    Ok(())
}

fn ensure_private_file(path: &Path, preexisting: bool) -> Result<(), ShellError> {
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(ShellError::Security(format!(
            "native journal WAL is not a regular local file: {}",
            path.display()
        )));
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
        if mode != 0o600 {
            std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))?;
        }
    }
    Ok(())
}

#[cfg(unix)]
fn sync_parent(path: &Path) -> Result<(), ShellError> {
    if let Some(parent) = path.parent() {
        File::open(parent)?.sync_all()?;
    }
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent(_path: &Path) -> Result<(), ShellError> {
    Ok(())
}

#[cfg(test)]
#[path = "journal_storage_tests.rs"]
mod tests;
