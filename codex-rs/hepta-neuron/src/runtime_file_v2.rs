//! Descriptor-bound file checks and measured syncs. Parent directories remain
//! host-owned/trusted namespaces; a same-privilege adversary replacing every
//! ancestor is outside this local file-lock contract.
use std::cell::Cell;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::ops::Deref;
use std::ops::DerefMut;
use std::path::Path;
use std::path::PathBuf;
use std::time::Instant;

use serde::Serialize;

/// Process-local measurements, never protocol or activation evidence. Sync
/// timings are actual calls, including errors; bytes are observed file lengths.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct NeuronIoMetricsV2 {
    pub sync_calls: u64,
    pub sync_errors: u64,
    pub sync_micros: u64,
}

impl NeuronIoMetricsV2 {
    pub(crate) fn since(self, earlier: Self) -> Self {
        Self {
            sync_calls: self.sync_calls.saturating_sub(earlier.sync_calls),
            sync_errors: self.sync_errors.saturating_sub(earlier.sync_errors),
            sync_micros: self.sync_micros.saturating_sub(earlier.sync_micros),
        }
    }
}

pub(crate) struct MeasuredFileV2 {
    file: File,
    path: PathBuf,
    metrics: Cell<NeuronIoMetricsV2>,
}

impl MeasuredFileV2 {
    pub(crate) fn new(file: File, path: &Path) -> io::Result<Self> {
        let result = Self {
            file,
            path: path.to_owned(),
            metrics: Cell::default(),
        };
        result.verify_identity()?;
        Ok(result)
    }

    pub(crate) fn verify_identity(&self) -> io::Result<()> {
        let named = std::fs::symlink_metadata(&self.path)?;
        let opened = self.file.metadata()?;
        if !named.is_file() || named.file_type().is_symlink() || !opened.is_file() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "not a regular file",
            ));
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::MetadataExt;
            if named.dev() != opened.dev() || named.ino() != opened.ino() || opened.nlink() != 1 {
                return Err(io::Error::new(
                    io::ErrorKind::PermissionDenied,
                    "file identity changed",
                ));
            }
        }
        Ok(())
    }

    pub(crate) fn metrics(&self) -> NeuronIoMetricsV2 {
        self.metrics.get()
    }

    pub(crate) fn sync_data(&self) -> io::Result<()> {
        self.verify_identity()?;
        let started = Instant::now();
        let result = self.file.sync_data();
        self.record_sync(started, &result);
        result
    }

    pub(crate) fn sync_all(&self) -> io::Result<()> {
        self.verify_identity()?;
        let started = Instant::now();
        let result = self.file.sync_all();
        self.record_sync(started, &result);
        result
    }

    fn record_sync(&self, started: Instant, result: &io::Result<()>) {
        let mut metrics = self.metrics.get();
        metrics.sync_calls = metrics.sync_calls.saturating_add(1);
        metrics.sync_errors = metrics
            .sync_errors
            .saturating_add(u64::from(result.is_err()));
        metrics.sync_micros = metrics
            .sync_micros
            .saturating_add(u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX));
        self.metrics.set(metrics);
    }
}

impl Deref for MeasuredFileV2 {
    type Target = File;
    fn deref(&self) -> &File {
        &self.file
    }
}

impl DerefMut for MeasuredFileV2 {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.file
    }
}

pub(crate) fn open_regular(path: &Path) -> io::Result<File> {
    open_regular_after_metadata(path, || {})
}

fn open_regular_after_metadata(path: &Path, after_metadata: impl FnOnce()) -> io::Result<File> {
    let before = std::fs::symlink_metadata(path)?;
    if before.file_type().is_symlink() || !before.is_file() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "not a regular file",
        ));
    }
    after_metadata();
    let mut options = OpenOptions::new();
    options.read(true).write(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        // Non-blocking open also prevents a raced-in FIFO from hanging recovery.
        options.custom_flags(libc::O_NOFOLLOW | libc::O_NONBLOCK);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
        options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    }
    let file = options.open(path)?;
    let after = file.metadata()?;
    if !after.is_file() || after.file_type().is_symlink() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "not a regular file",
        ));
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::MetadataExt;
        if before.dev() != after.dev() || before.ino() != after.ino() || after.nlink() != 1 {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied,
                "file identity changed",
            ));
        }
    }
    Ok(file)
}

#[cfg(test)]
#[path = "runtime_file_v2_tests.rs"]
mod tests;
