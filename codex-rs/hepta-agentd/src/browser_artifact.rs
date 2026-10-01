//! Bounded snapshots of operator-selected Browser artifacts.
//!
//! Unix trusts the selected file owner and root, including their namespace.
//! Canonical paths are returned for execution so a caller's stable directory
//! alias is not resolved again at spawn. This is a read-time fence, not proof of
//! the child process's loaded image or isolation from a malicious trusted owner.

use std::fs;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use sha2::Digest;
use sha2::Sha256;

use super::BrowserServoError;

pub(super) fn verify_file_digest(
    path: &Path,
    expected: [u8; 32],
    maximum: usize,
) -> Result<PathBuf, BrowserServoError> {
    ArtifactSnapshot::open(path, maximum)?.verify(expected, maximum)
}

struct ArtifactSnapshot {
    selected_path: PathBuf,
    physical_path: PathBuf,
    before: Metadata,
    file: File,
    #[cfg(unix)]
    namespace: crate::operator_namespace::OperatorNamespace,
}

struct ArtifactPreflight {
    selected_path: PathBuf,
    physical_path: PathBuf,
    before: Metadata,
    #[cfg(unix)]
    namespace: crate::operator_namespace::OperatorNamespace,
}

impl ArtifactPreflight {
    fn inspect(path: &Path, maximum: usize) -> Result<Self, BrowserServoError> {
        let before = fs::symlink_metadata(path).map_err(artifact_io_error)?;
        validate_file(&before, maximum)?;
        let physical_path = path.canonicalize().map_err(artifact_io_error)?;
        let physical_before = fs::symlink_metadata(&physical_path).map_err(artifact_io_error)?;
        validate_file(&physical_before, maximum)?;
        if !same_file_version(&before, &physical_before) {
            return Err(changed_artifact());
        }
        #[cfg(unix)]
        let namespace =
            crate::operator_namespace::OperatorNamespace::capture(&physical_path, &before)
                .map_err(artifact_io_error)?;
        Ok(Self {
            selected_path: path.to_path_buf(),
            physical_path,
            before,
            #[cfg(unix)]
            namespace,
        })
    }

    fn open(self, maximum: usize) -> Result<ArtifactSnapshot, BrowserServoError> {
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        crate::operator_namespace::configure_protected_open(&mut options);
        let file = options
            .open(&self.physical_path)
            .map_err(artifact_io_error)?;
        let opened = file.metadata().map_err(artifact_io_error)?;
        validate_file(&opened, maximum)?;
        if !same_file_version(&self.before, &opened) {
            return Err(changed_artifact());
        }
        Ok(ArtifactSnapshot {
            selected_path: self.selected_path,
            physical_path: self.physical_path,
            before: self.before,
            file,
            #[cfg(unix)]
            namespace: self.namespace,
        })
    }
}

impl ArtifactSnapshot {
    fn open(path: &Path, maximum: usize) -> Result<Self, BrowserServoError> {
        ArtifactPreflight::inspect(path, maximum)?.open(maximum)
    }

    fn verify(mut self, expected: [u8; 32], maximum: usize) -> Result<PathBuf, BrowserServoError> {
        let (digest, bytes_read) =
            bounded_digest(&mut self.file, maximum).map_err(artifact_io_error)?;
        if bytes_read == 0 || bytes_read > maximum as u64 || bytes_read != self.before.len() {
            return Err(changed_artifact());
        }
        let opened_after = self.file.metadata().map_err(artifact_io_error)?;
        let physical_after =
            fs::symlink_metadata(&self.physical_path).map_err(artifact_io_error)?;
        let selected_after =
            fs::symlink_metadata(&self.selected_path).map_err(artifact_io_error)?;
        validate_file(&opened_after, maximum)?;
        validate_file(&physical_after, maximum)?;
        validate_file(&selected_after, maximum)?;
        if !same_file_version(&self.before, &opened_after)
            || !same_file_version(&self.before, &physical_after)
            || !same_file_version(&self.before, &selected_after)
            || self
                .selected_path
                .canonicalize()
                .map_err(artifact_io_error)?
                != self.physical_path
        {
            return Err(changed_artifact());
        }
        #[cfg(unix)]
        self.namespace
            .verify(&self.physical_path, &opened_after)
            .map_err(artifact_io_error)?;
        if digest != expected {
            return Err(BrowserServoError::BindingMismatch(
                "Browser artifact digest does not match the selected artifact".into(),
            ));
        }
        Ok(self.physical_path)
    }
}

fn validate_file(metadata: &Metadata, maximum: usize) -> Result<(), BrowserServoError> {
    if !metadata.is_file() || metadata.file_type().is_symlink() {
        return Err(BrowserServoError::Invalid(
            "Browser artifact must be a regular non-symlink file".into(),
        ));
    }
    if metadata.len() == 0 || metadata.len() > maximum as u64 {
        return Err(BrowserServoError::Invalid(
            "Browser artifact exceeds its bounded file size".into(),
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if metadata.nlink() != 1 || metadata.mode() & 0o022 != 0 {
            return Err(BrowserServoError::Invalid(
                "Browser artifact permits untrusted writes or linked replacement".into(),
            ));
        }
    }
    Ok(())
}

fn same_file_version(before: &Metadata, after: &Metadata) -> bool {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        (
            before.dev(),
            before.ino(),
            before.uid(),
            before.mode(),
            before.nlink(),
            before.len(),
            before.mtime(),
            before.mtime_nsec(),
            before.ctime(),
            before.ctime_nsec(),
        ) == (
            after.dev(),
            after.ino(),
            after.uid(),
            after.mode(),
            after.nlink(),
            after.len(),
            after.mtime(),
            after.mtime_nsec(),
            after.ctime(),
            after.ctime_nsec(),
        )
    }
    #[cfg(not(unix))]
    {
        before.len() == after.len()
            && before.modified().ok() == after.modified().ok()
            && before.file_type() == after.file_type()
    }
}

fn bounded_digest(reader: &mut impl Read, maximum: usize) -> io::Result<([u8; 32], u64)> {
    let limit = u64::try_from(maximum)
        .ok()
        .and_then(|maximum| maximum.checked_add(1))
        .ok_or_else(|| io::Error::other("Browser artifact size bound overflow"))?;
    let mut bounded = reader.take(limit);
    let mut buffer = [0u8; 8 * 1024];
    let mut digest = Sha256::new();
    let mut bytes_read = 0;
    loop {
        let size = match bounded.read(&mut buffer) {
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            result => result?,
        };
        if size == 0 {
            break;
        }
        digest.update(&buffer[..size]);
        bytes_read += size as u64;
    }
    Ok((digest.finalize().into(), bytes_read))
}

fn artifact_io_error(error: io::Error) -> BrowserServoError {
    BrowserServoError::Invalid(format!("cannot verify Browser artifact: {error}"))
}

fn changed_artifact() -> BrowserServoError {
    BrowserServoError::Invalid("Browser artifact changed while verifying its snapshot".into())
}

#[cfg(test)]
#[path = "browser_artifact_tests.rs"]
mod tests;
