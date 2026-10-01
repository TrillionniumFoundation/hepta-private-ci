use std::fs::File;

/// Exclusive ownership of a native update transaction or helper runner.
///
/// Keep this guard until the protected transaction or orchestration completes.
/// Drop explicitly unlocks before closing its private handle, so normal release
/// does not wait for fork-inherited Unix descriptors to reach exec or exit.
/// The guard does not expose or duplicate the underlying handle.
#[must_use = "retain the update lock guard until the protected operation completes"]
pub struct UpdateLock {
    file: File,
}

impl UpdateLock {
    pub(crate) fn try_acquire(file: File) -> Result<Self, std::fs::TryLockError> {
        file.try_lock()?;
        Ok(Self { file })
    }
}

impl std::fmt::Debug for UpdateLock {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.debug_struct("UpdateLock").finish_non_exhaustive()
    }
}

impl Drop for UpdateLock {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

#[cfg(test)]
#[path = "update_lock_tests.rs"]
mod tests;
