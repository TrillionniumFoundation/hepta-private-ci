//! Confirmation-time file identity, not a claim of descriptor-bound OS dispatch.
//! The retained handle prevents identifier reuse while a final check is in
//! progress. Path-only launchers still have a final handoff race; see the
//! operational closure ledger before assigning a release qualification.
use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;

use crate::error::ShellError;
use crate::model::sha256_hex;

pub(crate) struct ResourceSnapshot {
    pub(crate) digest: String,
    _file: File,
}

pub(crate) fn snapshot(path: &Path) -> Result<ResourceSnapshot, ShellError> {
    snapshot_observed(path, || {})
}

fn snapshot_observed(
    path: &Path,
    after_open: impl FnOnce(),
) -> Result<ResourceSnapshot, ShellError> {
    if !path.is_absolute() {
        return Err(ShellError::InvalidInput(
            "resource path must be absolute".to_owned(),
        ));
    }
    let canonical = std::fs::canonicalize(path)?;
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt as _;
        options.custom_flags(
            (rustix::fs::OFlags::NOFOLLOW | rustix::fs::OFlags::NONBLOCK).bits() as i32,
        );
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt as _;
        // Open directories without following a final reparse point. Do not
        // share deletion while this snapshot is held at the effect boundary.
        options.custom_flags(0x0220_0000).share_mode(0x0000_0003);
    }
    let file = options.open(&canonical)?;
    after_open();
    let metadata = file.metadata()?;
    if !metadata.is_file() && !metadata.is_dir() {
        return Err(ShellError::Security(
            "resource must be a file or directory".to_owned(),
        ));
    }
    let object_identity = identity(&file)?;
    // The opened object and the original name must still describe one resource.
    // This rejects substitutions during resolution/open, not the residual race
    // inside a later path-only OS launcher.
    if std::fs::canonicalize(path)? != canonical
        || identity(&options.open(&canonical)?)? != object_identity
    {
        return Err(ShellError::Security(
            "resource changed during confirmation snapshot".to_owned(),
        ));
    }
    let digest = sha256_hex(serde_json::to_vec(&(
        "hepta.ui.native.resource-identity.v1",
        path.as_os_str().as_encoded_bytes(),
        canonical.as_os_str().as_encoded_bytes(),
        object_identity,
    ))?);
    Ok(ResourceSnapshot {
        digest,
        _file: file,
    })
}

#[cfg(unix)]
fn identity(file: &File) -> Result<Vec<u64>, ShellError> {
    use std::os::unix::fs::MetadataExt as _;
    let m = file.metadata()?;
    Ok(vec![
        m.dev(),
        m.ino(),
        u64::from(m.mode()),
        m.len(),
        m.mtime() as u64,
        m.mtime_nsec() as u64,
        m.ctime() as u64,
        m.ctime_nsec() as u64,
    ])
}

#[cfg(windows)]
fn identity(file: &File) -> Result<Vec<u64>, ShellError> {
    Ok(codex_hepta_private_state::opened_resource_identity(file)?.to_vec())
}

#[cfg(not(any(unix, windows)))]
fn identity(_file: &File) -> Result<Vec<u64>, ShellError> {
    Err(ShellError::Security(
        "resource identity is unsupported".to_owned(),
    ))
}

#[cfg(test)]
#[path = "resource_snapshot_tests.rs"]
mod tests;
