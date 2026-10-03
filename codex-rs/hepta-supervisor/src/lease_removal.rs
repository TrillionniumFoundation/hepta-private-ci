//! An in-memory witness for retrying one owned, observed-exit lease removal.
//! It is not reconstructible from an absent file and grants no process authority.
//! Failed-publication absence requires a separate, same-owner launch witness.

use std::path::Path;
use std::path::PathBuf;

use crate::SupervisorError;

use super::ProcessLease;
use super::lease_path;
use super::read_lease;
use super::sync_directory;

/// Kept by the existing per-Agent slot until exit finalization completes.
/// Normal cleanup requires this object's successful unlink before an absent retry.
/// A failed-publication witness separately accounts for an initially absent lease.
pub(crate) struct ProcessLeaseRemoval {
    run_root: PathBuf,
    expected: ProcessLease,
    unlinked: bool,
    unpublished_launch: bool,
}

impl ProcessLeaseRemoval {
    pub(crate) fn new(run_root: &Path, expected: &ProcessLease) -> Self {
        Self {
            run_root: run_root.to_path_buf(),
            expected: expected.clone(),
            unlinked: false,
            unpublished_launch: false,
        }
    }

    /// Only the owner of a freshly spawned handle may create this witness,
    /// immediately after its own lease publication reports failure. Absence is
    /// then a possible publication outcome, not evidence of a normal exit.
    pub(crate) fn for_failed_publication(run_root: &Path, expected: &ProcessLease) -> Self {
        Self {
            unpublished_launch: true,
            ..Self::new(run_root, expected)
        }
    }

    pub(crate) fn is_unpublished_launch(&self) -> bool {
        self.unpublished_launch
    }

    pub(crate) fn finish(
        &mut self,
        run_root: &Path,
        expected: &ProcessLease,
    ) -> Result<(), SupervisorError> {
        self.finish_with(run_root, expected, |path| {
            sync_directory(path, "process_lease")
        })
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
        } else if actual.is_none() && self.unpublished_launch {
            // This owner retained the child across failed publication and has
            // now observed its exit. Remember even an absent-path sync attempt
            // so a restored/reappearing lease cannot be deleted on a retry.
            self.unlinked = true;
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

#[cfg(test)]
#[path = "unpublished_lease_tests.rs"]
mod unpublished_tests;
