//! Bounded private receipts and checksum-pinned Root source-file reads.
use super::AgentdError;
use super::RowState;
use super::invalid;
use super::private_parent;
use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

#[derive(Clone, Copy)]
pub(super) enum SourceOwnership {
    RootProtected,
    PrivateOwner,
}

pub(super) fn read_regular(
    path: &Path,
    maximum: u64,
    ownership: SourceOwnership,
) -> Result<Vec<u8>, AgentdError> {
    let root_source = matches!(ownership, SourceOwnership::RootProtected);
    if !path.is_absolute() || path.canonicalize()? != path {
        return Err(invalid("reference file canonical path"));
    }
    let before = std::fs::symlink_metadata(path)?;
    if !before.is_file() || before.file_type().is_symlink() || before.len() > maximum {
        return Err(invalid("reference file bounds"));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let owner = if root_source {
            0
        } else {
            rustix::process::geteuid().as_raw()
        };
        let mask = if root_source { 0o022 } else { 0o077 };
        if before.uid() != owner || before.nlink() != 1 || before.mode() & mask != 0 {
            return Err(invalid("reference file owner or permissions"));
        }
        if root_source {
            for parent in path
                .parent()
                .ok_or_else(|| invalid("reference source parent"))?
                .ancestors()
            {
                let metadata = std::fs::symlink_metadata(parent)?;
                if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
                    return Err(invalid("reference source directory must be Root protected"));
                }
            }
        }
    }
    #[cfg(not(unix))]
    if root_source {
        return Err(invalid(
            "Root-pinned reference batches require a Unix authority boundary",
        ));
    }
    let file = File::open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        let after = file.metadata()?;
        if before.dev() != after.dev() || before.ino() != after.ino() {
            return Err(invalid("reference input changed while opening"));
        }
    }
    let mut bytes = Vec::new();
    file.take(maximum + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != before.len() {
        return Err(invalid("reference input changed or exceeded bounds"));
    }
    Ok(bytes)
}
pub(super) fn write_private(path: &Path, value: &RowState) -> Result<(), AgentdError> {
    private_parent(path)?;
    let bytes = serde_json::to_vec(value).map_err(|error| invalid(error.to_string()))?;
    if bytes.len() > 8 * 1024 * 1024 {
        return Err(invalid("reference receipt byte budget"));
    }
    let temporary = path.with_extension(format!("{}.pending", std::process::id()));
    let mut options = std::fs::OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let result = (|| {
        let mut file = options.open(&temporary)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        std::fs::rename(&temporary, path)?;
        File::open(
            path.parent()
                .ok_or_else(|| invalid("reference receipt parent"))?,
        )?
        .sync_all()?;
        Ok(())
    })();
    if result.is_err() {
        let _ = std::fs::remove_file(&temporary);
    }
    result
}
