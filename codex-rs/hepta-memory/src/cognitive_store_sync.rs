//! Filesystem synchronization for the cognitive owner's publication boundary.

use std::path::Path;

use super::CognitiveStoreError;
use super::unavailable;

pub(super) fn sync_cognitive_directory(root: &Path) -> Result<(), CognitiveStoreError> {
    #[cfg(windows)]
    let directory = codex_utils_path::open_existing_private_state_directory_for_sync(root)
        .map_err(|error| {
            unavailable(format!(
                "open private cognitive directory for sync: {error}"
            ))
        })?;
    #[cfg(not(windows))]
    let directory = std::fs::File::open(root)
        .map_err(|error| unavailable(format!("open cognitive directory for sync: {error}")))?;

    // Opening the handle is not a durability acknowledgement. The real flush
    // remains mandatory, and publication uncertainty keeps its original owner.
    directory
        .sync_all()
        .map_err(|error| unavailable(format!("sync cognitive directory: {error}")))
}
