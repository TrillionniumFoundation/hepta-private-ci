//! Bounded descriptor reads of private provider configuration and revocations.

use std::fs;
use std::fs::File;
use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io::Read;
use std::path::Path;
use std::path::PathBuf;

use crate::AgentdError;
#[cfg(unix)]
use crate::operator_namespace::OperatorNamespace;

pub(super) fn read_protected_file(
    path: &Path,
    max_bytes: u64,
    label: &str,
) -> Result<Vec<u8>, AgentdError> {
    ProtectedEffectFile::open(path, max_bytes, label)?.read(max_bytes, label)
}

struct ProtectedEffectFile {
    path: PathBuf,
    metadata: Metadata,
    #[cfg(unix)]
    namespace: OperatorNamespace,
    file: File,
}

struct EffectFilePreflight {
    path: PathBuf,
    metadata: Metadata,
    #[cfg(unix)]
    namespace: OperatorNamespace,
}

impl EffectFilePreflight {
    fn inspect(path: &Path, max_bytes: u64, label: &str) -> Result<Self, AgentdError> {
        if !path.is_absolute() {
            return Err(AgentdError::Invalid(format!("{label} must be absolute")));
        }
        let canonical = path.canonicalize()?;
        if canonical != path {
            return Err(AgentdError::Invalid(format!(
                "{label} must be canonical and symlink-free"
            )));
        }
        let metadata = fs::symlink_metadata(path)?;
        validate_file_metadata(&metadata, max_bytes, label)?;
        #[cfg(unix)]
        let namespace = OperatorNamespace::capture(&canonical, &metadata)?;
        Ok(Self {
            path: canonical,
            metadata,
            #[cfg(unix)]
            namespace,
        })
    }

    fn open(self, max_bytes: u64, label: &str) -> Result<ProtectedEffectFile, AgentdError> {
        let mut options = OpenOptions::new();
        options.read(true);
        #[cfg(unix)]
        crate::operator_namespace::configure_protected_open(&mut options);
        let file = options.open(&self.path)?;
        let opened = file.metadata()?;
        validate_file_metadata(&opened, max_bytes, label)?;
        if !same_file_version(&self.metadata, &opened) {
            return Err(AgentdError::Invalid(format!(
                "{label} changed while opening"
            )));
        }
        Ok(ProtectedEffectFile {
            path: self.path,
            metadata: self.metadata,
            #[cfg(unix)]
            namespace: self.namespace,
            file,
        })
    }
}

impl ProtectedEffectFile {
    fn open(path: &Path, max_bytes: u64, label: &str) -> Result<Self, AgentdError> {
        EffectFilePreflight::inspect(path, max_bytes, label)?.open(max_bytes, label)
    }

    fn read(self, max_bytes: u64, label: &str) -> Result<Vec<u8>, AgentdError> {
        let read_limit = max_bytes
            .checked_add(1)
            .ok_or_else(|| AgentdError::Invalid(format!("{label} byte bound overflows")))?;
        let capacity = usize::try_from(read_limit)
            .map_err(|_| AgentdError::Invalid(format!("{label} byte bound is too large")))?;
        let mut bytes = Vec::with_capacity(capacity);
        (&self.file).take(read_limit).read_to_end(&mut bytes)?;
        if bytes.is_empty() || bytes.len() as u64 > max_bytes {
            return Err(AgentdError::Invalid(format!(
                "{label} is empty or too large"
            )));
        }
        let path_after = fs::symlink_metadata(&self.path)?;
        let opened_after = self.file.metadata()?;
        validate_file_metadata(&path_after, max_bytes, label)?;
        validate_file_metadata(&opened_after, max_bytes, label)?;
        #[cfg(unix)]
        self.namespace.verify(&self.path, &path_after)?;
        if self.path.canonicalize()? != self.path
            || !same_file_version(&self.metadata, &path_after)
            || !same_file_version(&self.metadata, &opened_after)
            || bytes.len() as u64 != self.metadata.len()
        {
            return Err(AgentdError::Invalid(format!(
                "{label} changed while reading"
            )));
        }
        Ok(bytes)
    }
}

fn validate_file_metadata(
    metadata: &Metadata,
    max_bytes: u64,
    label: &str,
) -> Result<(), AgentdError> {
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(AgentdError::Invalid(format!(
            "{label} must be a regular non-symlink file"
        )));
    }
    if metadata.len() == 0 || metadata.len() > max_bytes {
        return Err(AgentdError::Invalid(format!(
            "{label} is empty or too large"
        )));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;

        if metadata.mode() & 0o077 != 0 {
            return Err(AgentdError::Invalid(format!(
                "{label} must not be group/world accessible"
            )));
        }
    }
    Ok(())
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

#[cfg(test)]
#[path = "automation_effect_file_tests.rs"]
mod tests;
