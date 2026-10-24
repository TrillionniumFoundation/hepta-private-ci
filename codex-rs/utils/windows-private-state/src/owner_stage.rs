//! Exact held staging-file publication under the original retained OS lock.

use super::OwnerLock;
use super::owner_file::LockedPrivateFile;
use super::owner_file::PrivateCreation;
use super::owner_file::PrivateFileAccess;
use crate::parent_anchor::Continuity;
use crate::security::ValidationError;
use std::cell::Cell;
use std::fmt;
use std::io;
use std::io::Write;

/// Distinguish a rejected native rename from uncertainty after publication.
#[derive(Debug)]
pub enum StageReplaceError {
    BeforePublication(ValidationError),
    Indeterminate(ValidationError),
}
impl fmt::Display for StageReplaceError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl std::error::Error for StageReplaceError {}

/// A bounded actual private stage with DELETE access on this file only.
/// Borrowing retains the real owner lock; no raw handle or clone is exposed.
pub struct LockedStateStage<'owner> {
    inner: LockedPrivateFile<'owner>,
    state: Cell<StageState>,
}

#[derive(Clone, Copy)]
enum StageState {
    Unpublished,
    Refused,
    Replaced,
}
impl OwnerLock {
    pub fn create_state_stage(
        &self,
        leaf: &str,
        maximum: usize,
    ) -> Result<LockedStateStage<'_>, ValidationError> {
        self.open_file(
            leaf,
            maximum,
            PrivateFileAccess::ReadWrite,
            Some(PrivateCreation::Stage),
        )
        .map(|inner| LockedStateStage {
            inner,
            state: Cell::new(StageState::Unpublished),
        })
    }
    /// Real directory flush, deliberately separate from stage rename so the
    /// original store retains its post-rename indeterminate/crash boundary.
    pub fn sync_all(&self) -> Result<(), ValidationError> {
        let mut held = self
            .context
            .lock()
            .map_err(|_| ValidationError::UnsafeObject)?;
        self.validate_locked(&mut held)?;
        held.continuity = Continuity::Refused;
        held.directory.file.sync_all()?;
        held.continuity = Continuity::Live;
        self.validate_locked(&mut held)
    }
}
impl LockedStateStage<'_> {
    fn ensure_unpublished(&self) -> io::Result<()> {
        match self.state.get() {
            StageState::Unpublished => Ok(()),
            StageState::Refused | StageState::Replaced => {
                Err(io::Error::other("stage already refused or published"))
            }
        }
    }
    pub fn set_len(&self, length: u64) -> io::Result<()> {
        self.ensure_unpublished()?;
        self.inner.set_len(length)
    }
    pub fn sync_all(&self) -> io::Result<()> {
        self.ensure_unpublished()?;
        self.inner.sync_all()
    }
    pub fn metadata(&self) -> io::Result<std::fs::Metadata> {
        self.inner.metadata()
    }

    /// Sync then atomically rename this exact stage handle into the held root.
    /// Success still requires OwnerLock::sync_all; failed post-rename validation
    /// is indeterminate. No path reopen, delete-sharing fallback or cleanup runs.
    pub fn replace_synced(&self, leaf: &str) -> Result<(), StageReplaceError> {
        let before = StageReplaceError::BeforePublication;
        self.ensure_unpublished()
            .map_err(|error| before(error.into()))?;
        self.state.set(StageState::Refused);
        let mut held = self
            .inner
            .owner
            .context
            .lock()
            .map_err(|_| before(ValidationError::UnsafeObject))?;
        self.inner
            .owner
            .validate_locked(&mut held)
            .map_err(before)?;
        held.continuity = Continuity::Refused;
        self.inner.inspect(&mut held).map_err(before)?;
        crate::stage::replace_synced_state_stage(&held.directory.file, &self.inner.file, leaf)
            .map_err(|error| before(error.into()))?;
        self.inner
            .inspect(&mut held)
            .map_err(StageReplaceError::Indeterminate)?;
        held.continuity = Continuity::Live;
        self.inner
            .owner
            .validate_locked(&mut held)
            .map_err(StageReplaceError::Indeterminate)?;
        self.state.set(StageState::Replaced);
        Ok(())
    }
}
impl Write for LockedStateStage<'_> {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        self.ensure_unpublished()?;
        self.inner.write(bytes)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.ensure_unpublished()?;
        self.inner.flush()
    }
}

#[cfg(test)]
#[path = "owner_stage_tests.rs"]
mod tests;
