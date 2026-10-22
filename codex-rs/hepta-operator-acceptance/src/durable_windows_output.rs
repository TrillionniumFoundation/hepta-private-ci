//! Create-only output custody under the private immediate parent.

use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::path::Path;

use codex_utils_path::create_private_recovery_copy;
use codex_utils_path::discard_private_recovery_copy;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_existing_private_state_directory_for_sync;
use codex_utils_path::private_state_snapshot;
use codex_utils_path::require_non_impersonating_thread;

use super::FILE_ATTRIBUTE_DIRECTORY;
use super::FILE_ATTRIBUTE_REPARSE_POINT;
use super::FileSnapshot;
use super::invalid;
use super::verify_unchanged;
use crate::AcceptanceError;
use crate::durable::secure_read;

#[derive(Debug, Eq, PartialEq)]
struct DirectoryIdentity {
    volume: u64,
    index: u64,
}

impl DirectoryIdentity {
    fn capture(file: &File) -> Result<Self, AcceptanceError> {
        require_non_impersonating_thread()?;
        if !private_state_snapshot(file)?.is_directory() {
            return Err(invalid("sidecar parent must be a private directory"));
        }
        let information = winapi_util::file::information(file)?;
        let attributes = information.file_attributes();
        if attributes & FILE_ATTRIBUTE_DIRECTORY == 0
            || attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        {
            return Err(invalid("sidecar parent must be an unredirected directory"));
        }
        Ok(Self {
            volume: information.volume_serial_number(),
            index: information.file_index(),
        })
    }
}

pub(in crate::durable) struct OutputParent {
    file: File,
    identity: DirectoryIdentity,
}

impl OutputParent {
    pub(in crate::durable) fn open(path: &Path) -> Result<Self, AcceptanceError> {
        require_non_impersonating_thread()?;
        let file = open_existing_private_state_directory_for_sync(path)?;
        let identity = DirectoryIdentity::capture(&file)?;
        Ok(Self { file, identity })
    }

    pub(in crate::durable) fn verify(&self, path: &Path) -> Result<(), AcceptanceError> {
        let retained = DirectoryIdentity::capture(&self.file)?;
        let current = open_existing_private_state_directory(path)?;
        let current = DirectoryIdentity::capture(&current)?;
        // Creating a child legitimately changes parent times and size. Compare
        // identity, not whole snapshots, and independently revalidate privacy.
        if retained != self.identity || current != self.identity {
            return Err(invalid("sidecar parent changed during durable write"));
        }
        require_non_impersonating_thread()?;
        Ok(())
    }

    pub(in crate::durable) fn sync(&self, path: &Path) -> Result<(), AcceptanceError> {
        self.verify(path)?;
        // A real flush of the retained write-capable directory handle. Failure
        // propagates; opening a directory alone is not durability evidence.
        self.file.sync_all()?;
        self.verify(path)
    }
}

pub(in crate::durable) fn verify_directory(path: &Path) -> Result<(), AcceptanceError> {
    require_non_impersonating_thread()?;
    let directory = open_existing_private_state_directory(path)?;
    DirectoryIdentity::capture(&directory)?;
    require_non_impersonating_thread()?;
    Ok(())
}

pub(in crate::durable) fn write_private_new(
    path: &Path,
    bytes: &[u8],
) -> Result<(), AcceptanceError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("sidecar artifact has no parent"))?;
    let name = path
        .file_name()
        .ok_or_else(|| invalid("sidecar artifact has no name"))?;
    let custody = OutputParent::open(parent)?;
    custody.verify(parent)?;
    // FILE_CREATE relative to the retained parent, with the creation-only
    // current-user protected DACL. Never reopen/repair an existing destination.
    let mut file = create_private_recovery_copy(&custody.file, name)?;
    let result = (|| {
        FileSnapshot::capture(&file, "new sidecar artifact")?;
        file.write_all(bytes)?;
        file.sync_all()?;
        let snapshot = FileSnapshot::capture(&file, "sidecar artifact")?;
        file.seek(SeekFrom::Start(0))?;
        let mut persisted = Vec::with_capacity(bytes.len());
        (&mut file)
            .take(bytes.len().saturating_add(1) as u64)
            .read_to_end(&mut persisted)?;
        if persisted != bytes || secure_read(path, bytes.len())? != bytes {
            return Err(invalid("sidecar artifact differs after durable write"));
        }
        verify_unchanged(&file, path, &snapshot, "sidecar artifact")?;
        #[cfg(test)]
        tests::before_sync(parent);
        custody.sync(parent)?;
        require_non_impersonating_thread()?;
        Ok(())
    })();
    if result.is_err() {
        // Delete only the exact file created above, through its DELETE handle.
        // A cleanup failure is also failure, never a persisted-success receipt.
        discard_private_recovery_copy(&file)?;
    }
    result
}

#[cfg(test)]
#[path = "durable_windows_output_tests.rs"]
mod tests;
