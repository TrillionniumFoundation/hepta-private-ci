use std::fs::File;
use std::io::Read;
use std::os::unix::fs::MetadataExt;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;

use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_matrix_sdk::MatrixAuthorityError;
use serde::de::DeserializeOwned;

use super::MatrixFinalUseBrokerError;

/// Secure, fail-closed reader for the independently published revocation feed.
///
/// Every refresh reopens and revalidates the exact private file identity. When
/// that identity is unchanged, the hot path avoids rereading and reparsing up
/// to `maximum` bytes. A changed file is cached only after the caller accepts
/// its monotonic authority semantics.
pub(super) struct RevocationFeed {
    path: PathBuf,
    maximum: usize,
    accepted_stamp: Mutex<PrivateFileStamp>,
}

impl RevocationFeed {
    pub(super) fn open(
        path: PathBuf,
        maximum: usize,
    ) -> Result<(Self, FinalUseRevocations), MatrixFinalUseBrokerError> {
        let snapshot = read_private_json_snapshot(&path, maximum)?;
        let feed = Self {
            path,
            maximum,
            accepted_stamp: Mutex::new(snapshot.stamp),
        };
        Ok((feed, snapshot.value))
    }

    pub(super) fn refresh(
        &self,
        apply: impl FnOnce(FinalUseRevocations) -> Result<(), MatrixAuthorityError>,
    ) -> Result<(), MatrixAuthorityError> {
        let mut accepted_stamp = self
            .accepted_stamp
            .lock()
            .map_err(|_| MatrixAuthorityError::Unavailable)?;
        let snapshot =
            read_private_json_if_changed(&self.path, self.maximum, Some(*accepted_stamp))
                .map_err(|_| MatrixAuthorityError::Unavailable)?;
        let Some(snapshot) = snapshot else {
            return Ok(());
        };

        apply(snapshot.value)?;
        *accepted_stamp = snapshot.stamp;
        Ok(())
    }
}

pub(super) fn read_private_json<T: DeserializeOwned>(
    path: &Path,
    maximum: usize,
) -> Result<T, MatrixFinalUseBrokerError> {
    read_private_json_snapshot(path, maximum).map(|snapshot| snapshot.value)
}

struct PrivateJsonSnapshot<T> {
    value: T,
    stamp: PrivateFileStamp,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct PrivateFileStamp {
    device: u64,
    inode: u64,
    length: u64,
    modified_seconds: i64,
    modified_nanoseconds: i64,
    changed_seconds: i64,
    changed_nanoseconds: i64,
}

impl PrivateFileStamp {
    fn from_metadata(metadata: &std::fs::Metadata) -> Self {
        Self {
            device: metadata.dev(),
            inode: metadata.ino(),
            length: metadata.len(),
            modified_seconds: metadata.mtime(),
            modified_nanoseconds: metadata.mtime_nsec(),
            changed_seconds: metadata.ctime(),
            changed_nanoseconds: metadata.ctime_nsec(),
        }
    }

    fn same_file(self, other: Self) -> bool {
        self.device == other.device && self.inode == other.inode
    }
}

fn read_private_json_snapshot<T: DeserializeOwned>(
    path: &Path,
    maximum: usize,
) -> Result<PrivateJsonSnapshot<T>, MatrixFinalUseBrokerError> {
    read_private_json_if_changed(path, maximum, None)?.ok_or(MatrixFinalUseBrokerError::UnsafePath)
}

fn read_private_json_if_changed<T: DeserializeOwned>(
    path: &Path,
    maximum: usize,
    accepted_stamp: Option<PrivateFileStamp>,
) -> Result<Option<PrivateJsonSnapshot<T>>, MatrixFinalUseBrokerError> {
    let (mut file, before) = open_private_file(path, maximum)?;
    if let Some(accepted_stamp) = accepted_stamp {
        if accepted_stamp == before {
            verify_private_file(path, &file, maximum, before)?;
            return Ok(None);
        }
        if accepted_stamp.same_file(before) {
            return Err(MatrixFinalUseBrokerError::UnsafePath);
        }
    }

    let mut bytes = Vec::new();
    file.by_ref()
        .take((maximum + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?;
    if bytes.len() > maximum {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    verify_private_file(path, &file, maximum, before)?;
    let value = serde_json::from_slice(&bytes)
        .map_err(|_| MatrixFinalUseBrokerError::InvalidConfiguration)?;
    Ok(Some(PrivateJsonSnapshot {
        value,
        stamp: before,
    }))
}

fn open_private_file(
    path: &Path,
    maximum: usize,
) -> Result<(File, PrivateFileStamp), MatrixFinalUseBrokerError> {
    let path_stamp = private_path_stamp(path, maximum)?;
    let file: File = rustix::fs::open(
        path,
        rustix::fs::OFlags::RDONLY | rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?
    .into();
    let file_stamp = private_file_stamp(&file, maximum)?;
    if file_stamp != path_stamp {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    Ok((file, file_stamp))
}

fn verify_private_file(
    path: &Path,
    file: &File,
    maximum: usize,
    expected: PrivateFileStamp,
) -> Result<(), MatrixFinalUseBrokerError> {
    if private_file_stamp(file, maximum)? != expected
        || private_path_stamp(path, maximum)? != expected
    {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    Ok(())
}

fn private_file_stamp(
    file: &File,
    maximum: usize,
) -> Result<PrivateFileStamp, MatrixFinalUseBrokerError> {
    let metadata = file
        .metadata()
        .map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?;
    validate_private_file_metadata(&metadata, maximum)
}

fn private_path_stamp(
    path: &Path,
    maximum: usize,
) -> Result<PrivateFileStamp, MatrixFinalUseBrokerError> {
    if !path.is_absolute()
        || std::fs::canonicalize(path).map_err(|_| MatrixFinalUseBrokerError::UnsafePath)? != path
    {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    let metadata =
        std::fs::symlink_metadata(path).map_err(|_| MatrixFinalUseBrokerError::UnsafePath)?;
    validate_private_file_metadata(&metadata, maximum)
}

fn validate_private_file_metadata(
    metadata: &std::fs::Metadata,
    maximum: usize,
) -> Result<PrivateFileStamp, MatrixFinalUseBrokerError> {
    if !metadata.is_file()
        || metadata.mode() & 0o077 != 0
        || metadata.nlink() != 1
        || metadata.uid() != rustix::process::geteuid().as_raw()
        || metadata.len() > maximum as u64
    {
        return Err(MatrixFinalUseBrokerError::UnsafePath);
    }
    Ok(PrivateFileStamp::from_metadata(metadata))
}

#[cfg(test)]
#[path = "revocation_file_tests.rs"]
mod tests;
