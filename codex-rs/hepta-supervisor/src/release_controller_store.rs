//! Caller-owned, bounded journal storage. This is observation state, never
//! release authority. Sidecar locks survive atomic data-file replacement.
use crate::release_controller::MAX_PRODUCTION_RELEASE_JOURNAL_BYTES;
use crate::release_controller::ProductionReleaseControllerError as Error;
use crate::release_controller::ProductionReleaseJournalV1;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;

pub(crate) fn validate_operation_id(value: &str) -> Result<(), Error> {
    if value.is_empty()
        || value.len() > 128
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'-')
        })
    {
        return Err(Error::Invalid("operation id is malformed".to_string()));
    }
    Ok(())
}

pub(crate) fn validate_journal_path(path: &Path) -> Result<PathBuf, Error> {
    if !path.is_absolute() {
        return Err(Error::Invalid("journal path must be absolute".to_string()));
    }
    let name = path
        .file_name()
        .ok_or_else(|| Error::Invalid("journal must name a file".to_string()))?;
    let parent = path
        .parent()
        .ok_or_else(|| Error::Invalid("journal has no parent".to_string()))?
        .canonicalize()?;
    if !parent.is_dir() {
        return Err(Error::Invalid(
            "journal parent is not a directory".to_string(),
        ));
    }
    let canonical = parent.join(name);
    match std::fs::symlink_metadata(&canonical) {
        Ok(metadata) if !metadata.file_type().is_file() => {
            return Err(Error::Invalid(
                "journal must be a regular non-symlink file".to_string(),
            ));
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.into()),
    }
    Ok(canonical)
}

fn regular_options() -> OpenOptions {
    let mut options = OpenOptions::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC);
        options.mode(0o600);
    }
    options
}

pub(crate) fn read_bounded_regular_file(path: &Path, maximum_bytes: u64) -> Result<Vec<u8>, Error> {
    if !std::fs::symlink_metadata(path)?.file_type().is_file() {
        return Err(Error::Invalid(
            "input is not a regular non-symlink file".to_string(),
        ));
    }
    let file = regular_options().read(true).open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.len() > maximum_bytes {
        return Err(Error::Invalid(
            "input is not a bounded regular file".to_string(),
        ));
    }
    let mut bytes = Vec::new();
    file.take(maximum_bytes + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > maximum_bytes {
        return Err(Error::Invalid("input grew beyond its bound".to_string()));
    }
    Ok(bytes)
}

pub(crate) fn read_journal(path: &Path) -> Result<Option<ProductionReleaseJournalV1>, Error> {
    match std::fs::symlink_metadata(path) {
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
        Ok(_) => {}
    }
    let bytes = read_bounded_regular_file(path, MAX_PRODUCTION_RELEASE_JOURNAL_BYTES)?;
    let journal: ProductionReleaseJournalV1 = serde_json::from_slice(&bytes)?;
    if journal.journal_sha256 != journal.digest()? {
        return Err(Error::Conflict(
            "caller journal digest mismatch".to_string(),
        ));
    }
    Ok(Some(journal))
}

pub(crate) fn write_journal(
    path: &Path,
    journal: &mut ProductionReleaseJournalV1,
) -> Result<(), Error> {
    journal.journal_sha256 = journal.digest()?;
    let bytes = serde_json::to_vec(journal)?;
    if bytes.len() as u64 > MAX_PRODUCTION_RELEASE_JOURNAL_BYTES {
        return Err(Error::Invalid(
            "caller journal exceeds its bound".to_string(),
        ));
    }
    let parent = path
        .parent()
        .ok_or_else(|| Error::Invalid("journal has no parent".to_string()))?;
    let staging = parent.join(format!(".release-journal-{}.tmp", uuid::Uuid::new_v4()));
    let result = (|| {
        let mut file = regular_options()
            .create_new(true)
            .write(true)
            .open(&staging)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        crate::durable_publish::publish(&staging, path)?;
        Ok::<(), Error>(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&staging);
    }
    result
}

pub(crate) fn bounded_error(mut value: String) -> String {
    if value.len() > 1_024 {
        let mut end = 1_024;
        while !value.is_char_boundary(end) {
            end -= 1;
        }
        value.truncate(end);
    }
    value
}

pub(crate) struct JournalLock {
    _file: File,
}
impl JournalLock {
    pub(crate) fn acquire(journal_path: &Path) -> Result<Self, Error> {
        let name = journal_path
            .file_name()
            .and_then(|name| name.to_str())
            .ok_or_else(|| Error::Invalid("journal name is not UTF-8".to_string()))?;
        let path = journal_path.with_file_name(format!(".{name}.lock"));
        let file = regular_options()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(path)?;
        if !file.metadata()?.is_file() {
            return Err(Error::Invalid("lock is not a regular file".to_string()));
        }
        match file.try_lock() {
            Ok(()) => Ok(Self { _file: file }),
            Err(TryLockError::WouldBlock) => Err(Error::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}
