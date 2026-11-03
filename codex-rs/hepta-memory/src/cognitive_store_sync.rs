//! Filesystem synchronization for the cognitive owner's publication boundary.

use std::path::Path;

use super::CognitiveStoreError;
use super::unavailable;

pub(super) fn sync_cognitive_directory(root: &Path) -> Result<(), CognitiveStoreError> {
    #[cfg(windows)]
    let directory = {
        use std::fs::OpenOptions;
        use std::os::windows::fs::MetadataExt;
        use std::os::windows::fs::OpenOptionsExt;

        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
        let directory = OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(root)
            .map_err(|error| unavailable(format!("open cognitive directory for sync: {error}")))?;
        let metadata = directory.metadata().map_err(|error| {
            unavailable(format!("inspect cognitive directory for sync: {error}"))
        })?;
        if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(unavailable(
                "cognitive synchronization handle is not an unredirected directory",
            ));
        }
        directory
    };
    #[cfg(not(windows))]
    let directory = std::fs::File::open(root)
        .map_err(|error| unavailable(format!("open cognitive directory for sync: {error}")))?;

    // Opening the handle is not a durability acknowledgement. The real flush
    // remains mandatory, and publication uncertainty keeps its original owner.
    directory
        .sync_all()
        .map_err(|error| unavailable(format!("sync cognitive directory: {error}")))
}
