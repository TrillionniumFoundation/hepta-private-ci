//! Durable snapshot writes. Injection is a private test parameter, never an
//! environment variable or a product API that can weaken persistence.
#[cfg(unix)]
use std::fs::File;
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;

use atomic_write_file::AtomicWriteFile;

use crate::error::ShellError;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Boundary {
    Opened,
    Written,
    FileSynced,
    Replaced,
    DirectorySynced,
}

pub(crate) fn previous_path(path: &Path) -> PathBuf {
    let mut name = path.as_os_str().to_os_string();
    name.push(".previous");
    PathBuf::from(name)
}

pub(crate) fn write(path: &Path, bytes: &[u8]) -> Result<(), ShellError> {
    write_at_boundaries(path, bytes, |_| Ok(()))
}

fn write_at_boundaries(
    path: &Path,
    bytes: &[u8],
    mut observe: impl FnMut(Boundary) -> Result<(), ShellError>,
) -> Result<(), ShellError> {
    let mut file = AtomicWriteFile::open(path)?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    }
    observe(Boundary::Opened)?;
    file.write_all(bytes)?;
    observe(Boundary::Written)?;
    file.sync_all()?;
    observe(Boundary::FileSynced)?;
    file.commit()?;
    observe(Boundary::Replaced)?;
    #[cfg(unix)]
    if let Some(parent) = path.parent() {
        File::open(parent)?.sync_all()?;
    }
    observe(Boundary::DirectorySynced)?;
    Ok(())
}

#[cfg(test)]
#[path = "journal_storage_tests.rs"]
mod tests;
