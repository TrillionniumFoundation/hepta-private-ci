//! Filesystem synchronization for the cognitive owner's publication boundary.

use std::fs::File;
use std::path::Path;

use super::CognitiveStoreError;
use super::unavailable;

pub(super) fn open_cognitive_directory_for_sync(root: &Path) -> Result<File, CognitiveStoreError> {
    #[cfg(windows)]
    let directory = codex_utils_path::open_existing_private_state_directory_for_sync(root);
    #[cfg(not(windows))]
    let directory = File::open(root);
    directory.map_err(|error| unavailable(format!("open cognitive directory for sync: {error}")))
}

pub(super) fn sync_cognitive_directory(root: &Path) -> Result<(), CognitiveStoreError> {
    // Opening the handle is not a durability acknowledgement. The real flush
    // remains mandatory, and publication uncertainty keeps its original owner.
    open_cognitive_directory_for_sync(root)?
        .sync_all()
        .map_err(|error| unavailable(format!("sync cognitive directory: {error}")))
}
