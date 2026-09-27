//! An in-memory witness for retrying one owned, observed-exit lease removal.
//! It is not reconstructible from an absent file and grants no process authority.

use std::path::Path;
use std::path::PathBuf;

use crate::SupervisorError;

use super::ProcessLease;
use super::lease_path;
use super::read_lease;
use super::sync_directory;

/// Kept by the existing per-Agent slot until exit finalization completes.
/// Only this object's successful unlink can authorize a missing-file retry.
pub(crate) struct ProcessLeaseRemoval {
    run_root: PathBuf,
    expected: ProcessLease,
    unlinked: bool,
}

impl ProcessLeaseRemoval {
    pub(crate) fn new(run_root: &Path, expected: &ProcessLease) -> Self {
        Self {
            run_root: run_root.to_path_buf(),
            expected: expected.clone(),
            unlinked: false,
        }
    }

    pub(crate) fn finish(
        &mut self,
        run_root: &Path,
        expected: &ProcessLease,
    ) -> Result<(), SupervisorError> {
        self.finish_with(run_root, expected, sync_directory)
    }

    fn finish_with(
        &mut self,
        run_root: &Path,
        expected: &ProcessLease,
        sync: impl FnOnce(&Path) -> Result<(), SupervisorError>,
    ) -> Result<(), SupervisorError> {
        if run_root != self.run_root.as_path() || expected != &self.expected {
            return Err(SupervisorError::CorruptLease(
                "exit lease removal does not match the owned process and root".to_string(),
            ));
        }
        let actual = read_lease(run_root)?;
        if self.unlinked {
            // Even the same identity reappearing indicates restoration or a
            // competing writer, not permission to unlink that file again.
            if actual.is_some() {
                return Err(SupervisorError::CorruptLease(
                    "process lease reappeared during exit finalization".to_string(),
                ));
            }
        } else {
            let actual = actual.ok_or_else(|| {
                SupervisorError::CorruptLease("active process lease is missing".to_string())
            })?;
            if actual != self.expected {
                return Err(SupervisorError::CorruptLease(
                    "active process lease identity changed".to_string(),
                ));
            }
            std::fs::remove_file(lease_path(run_root))?;
            // Set before sync: a sync error cannot erase our successful unlink.
            self.unlinked = true;
        }
        // Re-sync on every retry, including after a later lifecycle CAS error.
        // Never report a failed durability boundary as acknowledged.
        sync(run_root)
    }
}

#[cfg(test)]
#[path = "lease_removal_tests.rs"]
mod tests;
