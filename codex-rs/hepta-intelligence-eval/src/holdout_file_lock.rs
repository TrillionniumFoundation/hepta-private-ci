//! Private lock lifetime shared by the two cooperative file backends.
//!
//! Unix callers transfer lock management, not necessarily the only descriptor
//! reference. Unknown externally managed/prelocked aliases are not detectable.
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;

#[cfg(unix)]
#[path = "holdout_file_lock_unix.rs"]
mod unix;

pub(crate) struct AcquiredFile {
    file: File,
    #[cfg(unix)]
    lease: Option<unix::Lease>,
}

impl AcquiredFile {
    pub(crate) fn acquire(file: File) -> Result<Self, TryLockError> {
        #[cfg(unix)]
        {
            unix::acquire(file)
        }
        #[cfg(not(unix))]
        {
            // Preserve existing non-Unix close-only behavior. No FileID or
            // explicit-unlock guarantee is claimed on these platforms.
            file.try_lock()?;
            Ok(Self { file })
        }
    }

    pub(crate) fn check_process(&self) -> io::Result<()> {
        #[cfg(unix)]
        if let Some(lease) = self.lease {
            unix::check(lease)?;
        }
        Ok(())
    }
}

impl Drop for AcquiredFile {
    fn drop(&mut self) {
        #[cfg(unix)]
        if let Some(lease) = self.lease {
            unix::release(&self.file, lease);
        }
        // File closes only after explicit release; no implicit sync is added.
    }
}

// Private access only; the public stores never expose/clone their file. Their
// operational entry points check process ownership before external side effects.
impl Deref for AcquiredFile {
    type Target = File;
    fn deref(&self) -> &File {
        &self.file
    }
}
impl DerefMut for AcquiredFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.file
    }
}
impl Read for AcquiredFile {
    fn read(&mut self, buffer: &mut [u8]) -> io::Result<usize> {
        self.file.read(buffer)
    }
}
impl Write for AcquiredFile {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        self.file.write(buffer)
    }
    fn flush(&mut self) -> io::Result<()> {
        self.file.flush()
    }
}
impl Seek for AcquiredFile {
    fn seek(&mut self, position: SeekFrom) -> io::Result<u64> {
        self.file.seek(position)
    }
}

#[cfg(all(test, unix))]
#[path = "holdout_file_lock_tests.rs"]
mod tests;
