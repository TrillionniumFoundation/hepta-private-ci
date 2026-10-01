use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::path::Path;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT: AtomicU64 = AtomicU64::new(0);

/// Minimal crate-local replacement used only by unit tests that need an
/// independently reopenable regular file. It intentionally exposes only the
/// operations required by the holdout compaction and checkpoint tests.
pub(crate) struct NamedTempFile {
    path: PathBuf,
}

impl NamedTempFile {
    pub(crate) fn new() -> io::Result<Self> {
        let path = std::env::temp_dir().join(format!(
            "hepta-learning-eval-unit-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, Ordering::Relaxed)
        ));
        OpenOptions::new()
            .create_new(true)
            .read(true)
            .write(true)
            .open(&path)?;
        Ok(Self { path })
    }

    pub(crate) fn reopen(&self) -> io::Result<File> {
        OpenOptions::new().read(true).write(true).open(&self.path)
    }

    pub(crate) fn path(&self) -> &Path {
        &self.path
    }
}

impl Drop for NamedTempFile {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.path);
    }
}
