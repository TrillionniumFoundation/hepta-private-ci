//! Same-owner Matrix exit cleanup. Missing files are not a recovery oracle.

use std::path::Path;
use std::path::PathBuf;

use crate::SupervisorError;
use crate::lease::MatrixProcessLease;
use crate::lease::read_matrix_lease;

pub(crate) struct MatrixProcessLeaseRemoval {
    path: PathBuf,
    expected: MatrixProcessLease,
    unlinked: bool,
    unpublished_launch: bool,
}

impl MatrixProcessLeaseRemoval {
    pub(crate) fn new(path: &Path, expected: &MatrixProcessLease) -> Self {
        Self {
            path: path.to_path_buf(),
            expected: expected.clone(),
            unlinked: false,
            unpublished_launch: false,
        }
    }

    /// Construct only while retaining the child whose publication just failed.
    pub(crate) fn for_failed_publication(path: &Path, expected: &MatrixProcessLease) -> Self {
        Self { unpublished_launch: true, ..Self::new(path, expected) }
    }

    pub(crate) fn finish(
        &mut self,
        path: &Path,
        expected: &MatrixProcessLease,
    ) -> Result<(), SupervisorError> {
        self.finish_with(path, expected, |parent| {
            #[cfg(unix)]
            std::fs::File::open(parent)?.sync_all()?;
            #[cfg(not(unix))]
            let _ = parent;
            Ok(())
        })
    }

    fn finish_with(
        &mut self,
        path: &Path,
        expected: &MatrixProcessLease,
        sync: impl FnOnce(&Path) -> Result<(), SupervisorError>,
    ) -> Result<(), SupervisorError> {
        if path != self.path.as_path() || expected != &self.expected {
            return Err(SupervisorError::CorruptLease(
                "Matrix exit cleanup changed process identity or path".to_string(),
            ));
        }
        let parent = path.parent().ok_or_else(|| {
            SupervisorError::CorruptLease("Matrix lease has no parent".to_string())
        })?;
        let actual = read_matrix_lease(path)?;
        if self.unlinked {
            if actual.is_some() {
                return Err(SupervisorError::CorruptLease(
                    "Matrix lease reappeared during exit cleanup".to_string(),
                ));
            }
        } else if actual.is_none() && self.unpublished_launch {
            self.unlinked = true;
        } else {
            if actual.as_ref() != Some(&self.expected) {
                return Err(SupervisorError::CorruptLease(
                    "Matrix exit cleanup requires the exact existing lease".to_string(),
                ));
            }
            std::fs::remove_file(path)?;
            self.unlinked = true;
        }
        // An acknowledged unlink or unpublished absence survives a failed sync.
        // This witness is local and is never reconstructed from file absence.
        sync(parent)
    }
}

#[cfg(test)]
#[path = "matrix_lease_removal_tests.rs"]
mod tests;
