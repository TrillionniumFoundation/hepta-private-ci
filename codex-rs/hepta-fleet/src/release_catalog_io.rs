//! One-descriptor catalog observations. Bounds apply to the opened file and
//! its observed length, including when it grows after opening. These checks do
//! not claim atomic execution against arbitrary concurrent directory mutation.

use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use sha2::Digest;
use sha2::Sha256;

use crate::FleetRegistryError;

#[derive(Clone, Copy)]
pub(crate) enum FileRule {
    Regular,
    Immutable,
    Executable,
}

struct Snapshot {
    file: File,
    length: u64,
    rule: FileRule,
}

impl Snapshot {
    fn open(path: &Path, max_bytes: u64, rule: FileRule) -> Result<Self, FleetRegistryError> {
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
        }
        #[cfg(windows)]
        {
            use std::os::windows::fs::OpenOptionsExt;
            // FILE_FLAG_OPEN_REPARSE_POINT: inspect the opened link itself.
            options.custom_flags(0x0020_0000);
        }
        let file = match options.open(path) {
            Ok(file) => file,
            Err(error) => {
                #[cfg(unix)]
                if error.raw_os_error() == Some(libc::ELOOP) {
                    return corrupt("release file is not a physical regular file");
                }
                return Err(error.into());
            }
        };
        let metadata = file.metadata()?;
        validate(&metadata, rule)?;
        if metadata.len() > max_bytes {
            return corrupt("release file exceeds its byte bound");
        }
        Ok(Self {
            file,
            length: metadata.len(),
            rule,
        })
    }

    fn consume(
        &mut self,
        mut visit: impl FnMut(&[u8]) -> Result<(), FleetRegistryError>,
    ) -> Result<(), FleetRegistryError> {
        let mut remaining = self.length;
        let mut buffer = [0_u8; 64 * 1024];
        while remaining != 0 {
            let requested = remaining.min(buffer.len() as u64) as usize;
            let count = self.file.read(&mut buffer[..requested])?;
            if count == 0 {
                return corrupt("release file was truncated during its observation");
            }
            visit(&buffer[..count])?;
            remaining -= count as u64;
        }
        let mut extra = [0_u8; 1];
        if self.file.read(&mut extra)? != 0 {
            return corrupt("release file grew during its bounded observation");
        }
        let metadata = self.file.metadata()?;
        validate(&metadata, self.rule)?;
        if metadata.len() != self.length {
            return corrupt("release file length changed during its observation");
        }
        Ok(())
    }
}

fn validate(metadata: &std::fs::Metadata, rule: FileRule) -> Result<(), FleetRegistryError> {
    if !metadata.file_type().is_file() || metadata.file_type().is_symlink() {
        return corrupt("release file is not a physical regular file");
    }
    if !matches!(rule, FileRule::Regular) {
        if super::is_writable(metadata)
            || (matches!(rule, FileRule::Executable) && !super::is_executable(metadata))
        {
            return corrupt("immutable release file has unsafe mode");
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if metadata.nlink() != 1 {
                return corrupt("immutable release file has another filesystem link");
            }
        }
    }
    Ok(())
}

pub(crate) fn read(
    path: &Path,
    max_bytes: u64,
    rule: FileRule,
) -> Result<Vec<u8>, FleetRegistryError> {
    let mut snapshot = Snapshot::open(path, max_bytes, rule)?;
    let length = usize::try_from(snapshot.length)
        .map_err(|_| FleetRegistryError::Corrupt("release file length overflow".into()))?;
    let mut bytes = Vec::with_capacity(length);
    snapshot.consume(|chunk| {
        bytes.extend_from_slice(chunk);
        Ok(())
    })?;
    Ok(bytes)
}

pub(super) fn sha256(path: &Path, max_bytes: u64) -> Result<String, FleetRegistryError> {
    let mut snapshot = Snapshot::open(path, max_bytes, FileRule::Regular)?;
    hash(&mut snapshot)
}

pub(super) fn check_program(
    path: &Path,
    expected_size: u64,
    expected_sha256: &str,
) -> Result<(), FleetRegistryError> {
    let mut snapshot = Snapshot::open(path, expected_size, FileRule::Executable)?;
    if snapshot.length != expected_size || hash(&mut snapshot)? != expected_sha256 {
        return corrupt("release program differs from its authorized immutable metadata");
    }
    Ok(())
}

fn hash(snapshot: &mut Snapshot) -> Result<String, FleetRegistryError> {
    let mut hash = Sha256::new();
    snapshot.consume(|chunk| {
        hash.update(chunk);
        Ok(())
    })?;
    Ok(format!("{:x}", hash.finalize()))
}

pub(super) fn copy(source: &Path, output: &mut File) -> Result<(), FleetRegistryError> {
    let mut snapshot = Snapshot::open(source, u64::MAX, FileRule::Regular)?;
    snapshot.consume(|chunk| Ok(output.write_all(chunk)?))
}

fn corrupt<T>(message: &str) -> Result<T, FleetRegistryError> {
    Err(FleetRegistryError::Corrupt(message.to_owned()))
}

#[cfg(test)]
#[path = "release_catalog_io_tests.rs"]
mod tests;
