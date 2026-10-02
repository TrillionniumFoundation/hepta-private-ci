//! Bounded descriptor reads for the existing control-intent format.
//! This protects the final component, not a writable/replaced parent directory.

use std::fs::Metadata;
use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Read;
use std::path::Path;

use super::DurableControlIntentError;

pub(super) fn read(
    path: &Path,
    maximum: usize,
) -> Result<Option<Vec<u8>>, DurableControlIntentError> {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK | libc::O_CLOEXEC);
    }
    let mut file = match options.open(path) {
        Ok(file) => file,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let opened = file.metadata()?;
    validate(&opened, maximum)?;
    let named = std::fs::symlink_metadata(path)?;
    validate(&named, maximum)?;
    same_file(&opened, &named)?;
    let limit = u64::try_from(maximum)
        .ok()
        .and_then(|maximum| maximum.checked_add(1))
        .ok_or_else(|| invalid("control intent size limit overflows"))?;
    let mut bytes = Vec::new();
    (&mut file).take(limit).read_to_end(&mut bytes)?;
    if bytes.len() > maximum {
        return Err(invalid("control intent exceeds the bounded file size"));
    }
    let after = file.metadata()?;
    let named_after = std::fs::symlink_metadata(path)?;
    validate(&after, maximum)?;
    validate(&named_after, maximum)?;
    same_file(&opened, &after)?;
    same_file(&opened, &named_after)?;
    if bytes.len() as u64 != after.len() {
        return Err(invalid("control intent changed while being read"));
    }
    Ok(Some(bytes))
}

fn validate(metadata: &Metadata, maximum: usize) -> Result<(), DurableControlIntentError> {
    if !metadata.file_type().is_file()
        || metadata.file_type().is_symlink()
        || metadata.len() > maximum as u64
    {
        return Err(invalid("control intent is not a bounded regular file"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        // SAFETY: geteuid has no arguments and returns the current effective UID.
        let owner = unsafe { libc::geteuid() };
        if metadata.uid() != owner || metadata.nlink() != 1 || metadata.mode() & 0o022 != 0 {
            return Err(invalid(
                "control intent ownership, links or permissions are unsafe",
            ));
        }
    }
    Ok(())
}

fn same_file(before: &Metadata, after: &Metadata) -> Result<(), DurableControlIntentError> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.dev() != after.dev()
            || before.ino() != after.ino()
            || before.mtime() != after.mtime()
            || before.mtime_nsec() != after.mtime_nsec()
            || before.ctime() != after.ctime()
            || before.ctime_nsec() != after.ctime_nsec()
        {
            return Err(invalid("control intent identity changed during open/read"));
        }
    }
    if before.len() != after.len() || before.modified()? != after.modified()? {
        return Err(invalid("control intent changed during open/read"));
    }
    Ok(())
}

fn invalid(message: &str) -> DurableControlIntentError {
    DurableControlIntentError::Invalid(message.to_string())
}
