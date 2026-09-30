//! Descriptor-bound opens and bounded reads for independently pinned bootstrap files.
//!
//! Native owner recovery still validates its supplied receipt, anchor and trust.
//! These checks protect file identity and the trusted operator namespace only.

use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use crate::AgentdError;
#[cfg(unix)]
use crate::operator_namespace::OperatorNamespace;

enum ExistingAccess {
    ReadOnly,
    ReadWrite,
}

struct ExistingBootstrapFile {
    path: PathBuf,
    canonical: PathBuf,
    metadata: Metadata,
    #[cfg(unix)]
    namespace: OperatorNamespace,
    file: File,
}

impl ExistingBootstrapFile {
    fn open(path: &Path, access: ExistingAccess, label: &str) -> Result<Self, AgentdError> {
        require_absolute_regular_file(path, label)?;
        let canonical = path.canonicalize()?;
        let metadata = std::fs::symlink_metadata(path)?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(invalid(label, "must be a regular non-symlink file"));
        }
        #[cfg(unix)]
        let namespace = OperatorNamespace::capture(&canonical, &metadata)?;
        let mut options = OpenOptions::new();
        options.read(true);
        match access {
            ExistingAccess::ReadOnly => {}
            ExistingAccess::ReadWrite => {
                options.write(true);
            }
        }
        let file = options.open(&canonical)?;
        let opened = file.metadata()?;
        if !opened.is_file() || !same_file_version(&metadata, &opened) {
            return Err(invalid(label, "changed while opening"));
        }
        Ok(Self {
            path: path.to_path_buf(),
            canonical,
            metadata,
            #[cfg(unix)]
            namespace,
            file,
        })
    }

    fn verify(&self, label: &str) -> Result<(), AgentdError> {
        let after = std::fs::symlink_metadata(&self.path)?;
        let opened_after = self.file.metadata()?;
        #[cfg(unix)]
        self.namespace.verify(&self.canonical, &after)?;
        if self.path.canonicalize()? != self.canonical
            || after.file_type().is_symlink()
            || !after.is_file()
            || !opened_after.is_file()
            || !same_file_version(&self.metadata, &after)
            || !same_file_version(&self.metadata, &opened_after)
        {
            return Err(invalid(label, "changed while reading"));
        }
        Ok(())
    }
}

pub(super) fn read_bounded(path: &Path, maximum: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
    let opened = ExistingBootstrapFile::open(path, ExistingAccess::ReadOnly, label)?;
    if opened.metadata.len() == 0 || opened.metadata.len() > maximum {
        return Err(invalid(label, "size is outside the allowed bound"));
    }
    let limit = maximum
        .checked_add(1)
        .ok_or_else(|| invalid(label, "byte bound overflows"))?;
    let capacity = usize::try_from(limit).map_err(|_| invalid(label, "byte bound is too large"))?;
    let mut bytes = Vec::with_capacity(capacity);
    (&opened.file).take(limit).read_to_end(&mut bytes)?;
    opened.verify(label)?;
    if bytes.len() as u64 != opened.metadata.len() || bytes.len() as u64 > maximum {
        return Err(invalid(label, "changed while reading"));
    }
    Ok(bytes)
}

pub(super) fn read_existing<T>(
    path: &Path,
    label: &str,
    read: impl FnOnce(File) -> Result<T, AgentdError>,
) -> Result<T, AgentdError> {
    let opened = ExistingBootstrapFile::open(path, ExistingAccess::ReadOnly, label)?;
    let value = read(opened.file.try_clone()?)?;
    opened.verify(label)?;
    Ok(value)
}

pub(super) fn require_absolute_regular_file(path: &Path, label: &str) -> Result<(), AgentdError> {
    if !path.is_absolute() {
        return Err(invalid(label, "path must be absolute"));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(invalid(label, "must be a regular non-symlink file"));
    }
    Ok(())
}

pub(super) fn open_existing_rw(path: &Path, label: &str) -> Result<File, AgentdError> {
    let opened = ExistingBootstrapFile::open(path, ExistingAccess::ReadWrite, label)?;
    opened.verify(label)?;
    Ok(opened.file)
}

pub(super) fn create_new_rw(path: &Path, label: &str) -> Result<File, AgentdError> {
    if !path.is_absolute() {
        return Err(invalid(label, "path must be absolute"));
    }
    let parent = path
        .parent()
        .ok_or_else(|| invalid(label, "has no parent"))?;
    if parent.canonicalize()? != parent {
        return Err(invalid(label, "parent must be canonical"));
    }
    if !std::fs::symlink_metadata(parent)?.is_dir() {
        return Err(invalid(label, "parent must be a regular directory"));
    }
    #[cfg(unix)]
    let parent_metadata = std::fs::symlink_metadata(parent)?;
    #[cfg(unix)]
    let namespace = OperatorNamespace::capture(path, &parent_metadata)?;
    let mut options = OpenOptions::new();
    options.read(true).write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let file = options.open(path)?;
    #[cfg(unix)]
    namespace.verify(path, &parent_metadata)?;
    Ok(file)
}

#[cfg(unix)]
fn same_file_version(before: &Metadata, after: &Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    let version = |metadata: &Metadata| {
        (
            metadata.dev(),
            metadata.ino(),
            metadata.uid(),
            metadata.mode(),
            metadata.len(),
            metadata.mtime(),
            metadata.mtime_nsec(),
            metadata.ctime(),
            metadata.ctime_nsec(),
        )
    };
    version(before) == version(after)
}

#[cfg(not(unix))]
fn same_file_version(before: &Metadata, after: &Metadata) -> bool {
    before.len() == after.len()
        && before.modified().ok() == after.modified().ok()
        && before.created().ok() == after.created().ok()
        && before.permissions().readonly() == after.permissions().readonly()
}

fn invalid(label: &str, message: &str) -> AgentdError {
    AgentdError::Invalid(format!("{label} {message}"))
}

#[cfg(all(test, unix))]
#[path = "plasticity_process_file_tests.rs"]
mod tests;
