//! Descriptor-bound, bounded reads of owner-installed authority configuration.
//! Atomic replacement is allowed between reads, never within one observation.

#[cfg(unix)]
use std::fs;
#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::fs::Metadata;
#[cfg(unix)]
use std::io::Read;
use std::path::Path;

use crate::AgentdError;

#[cfg(unix)]
pub(super) fn read_protected_file(
    path: &Path,
    max_bytes: u64,
    label: &str,
) -> Result<Vec<u8>, AgentdError> {
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(invalid(
            label,
            "must be absolute, canonical and symlink-free",
        ));
    }
    let before = fs::symlink_metadata(path)?;
    let file: File = rustix::fs::open(
        path,
        rustix::fs::OFlags::RDONLY
            | rustix::fs::OFlags::NOFOLLOW
            | rustix::fs::OFlags::NONBLOCK
            | rustix::fs::OFlags::CLOEXEC,
        rustix::fs::Mode::empty(),
    )
    .map_err(|_| invalid(label, "cannot be opened safely"))?
    .into();
    read_opened_file(file, path, &before, max_bytes, label)
}

#[cfg(not(unix))]
pub(super) fn read_protected_file(
    _path: &Path,
    _max_bytes: u64,
    label: &str,
) -> Result<Vec<u8>, AgentdError> {
    Err(invalid(
        label,
        "requires the Unix descriptor identity and ownership profile",
    ))
}

// Keep the open/read cut explicit so replacement and growth can be exercised
// deterministically without weakening the production descriptor checks.
#[cfg(unix)]
fn read_opened_file(
    mut file: File,
    path: &Path,
    before: &Metadata,
    max_bytes: u64,
    label: &str,
) -> Result<Vec<u8>, AgentdError> {
    let limit = max_bytes
        .checked_add(1)
        .ok_or_else(|| invalid(label, "has an invalid read bound"))?;
    let opened = file.metadata()?;
    if !private_regular_file(&opened)
        || !same_observation(before, &opened)
        || opened.len() == 0
        || opened.len() > max_bytes
    {
        return Err(invalid(
            label,
            "must be bounded private owner-controlled regular state",
        ));
    }
    let mut bytes = Vec::new();
    file.by_ref().take(limit).read_to_end(&mut bytes)?;
    let after = fs::symlink_metadata(path)?;
    let retained = file.metadata()?;
    if u64::try_from(bytes.len()).ok() != Some(opened.len())
        || !same_observation(&opened, &retained)
        || !same_observation(&opened, &after)
        || !private_regular_file(&retained)
        || !private_regular_file(&after)
        || path.canonicalize()? != path
    {
        return Err(invalid(label, "changed while reading"));
    }
    Ok(bytes)
}

#[cfg(unix)]
fn private_regular_file(metadata: &Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    metadata.is_file()
        && metadata.mode() & 0o077 == 0
        && metadata.nlink() == 1
        && metadata.uid() == rustix::process::geteuid().as_raw()
}

#[cfg(unix)]
fn same_observation(left: &Metadata, right: &Metadata) -> bool {
    use std::os::unix::fs::MetadataExt;
    (
        left.dev(),
        left.ino(),
        left.len(),
        left.mode(),
        left.uid(),
        left.nlink(),
        left.mtime(),
        left.mtime_nsec(),
        left.ctime(),
        left.ctime_nsec(),
    ) == (
        right.dev(),
        right.ino(),
        right.len(),
        right.mode(),
        right.uid(),
        right.nlink(),
        right.mtime(),
        right.mtime_nsec(),
        right.ctime(),
        right.ctime_nsec(),
    )
}

fn invalid(label: &str, message: &str) -> AgentdError {
    AgentdError::Invalid(format!("{label} {message}"))
}

#[cfg(all(test, unix))]
#[path = "authority_protected_file_tests.rs"]
mod tests;
