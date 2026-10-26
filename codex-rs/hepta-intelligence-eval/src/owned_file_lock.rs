// An exclusive lock belongs to this guard, not to incidental duplicated or
// fork-inherited file descriptors. This type deliberately does not implement Clone.
use std::fs::File;
use std::fs::TryLockError;
use std::ops::Deref;
use std::ops::DerefMut;

pub(super) struct OwnedFileLock {
    file: File,
    owner_pid: u32,
}

impl OwnedFileLock {
    pub(super) fn acquire(file: File) -> Result<Self, TryLockError> {
        let owner_pid = std::process::id();
        file.try_lock()?;
        Ok(Self { file, owner_pid })
    }
}

impl Deref for OwnedFileLock {
    type Target = File;

    fn deref(&self) -> &Self::Target {
        &self.file
    }
}

impl DerefMut for OwnedFileLock {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.file
    }
}

impl Drop for OwnedFileLock {
    fn drop(&mut self) {
        // A forked child's copy must not unlock its still-live parent's lock.
        if std::process::id() == self.owner_pid {
            // Drop cannot acknowledge durability or report an unlock failure.
            // Closing our descriptor still follows; if another descriptor keeps
            // a failed unlock alive, a new owner continues to fail closed as Busy.
            let _ = self.file.unlock();
        }
    }
}
