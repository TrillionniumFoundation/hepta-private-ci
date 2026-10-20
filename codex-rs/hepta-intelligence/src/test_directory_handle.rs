//! Portable, test-only directory handles for durability and fsync regressions.
//! Windows requires FILE_FLAG_BACKUP_SEMANTICS when opening a directory.
//! This flag does not bypass the operating system's access checks.

use std::fs::File;
use std::io;
use std::path::Path;

pub(crate) fn open_directory(path: &Path) -> io::Result<File> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        std::fs::OpenOptions::new()
            .read(true)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
            .open(path)
    }

    #[cfg(not(windows))]
    {
        File::open(path)
    }
}
