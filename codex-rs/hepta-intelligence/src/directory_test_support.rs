//! Host-side test handles used by actual durable ledger operations.

use std::fs::File;
use std::path::Path;

pub(crate) fn directory(root: &Path) -> std::io::Result<File> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;

        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
        // Retain the current no-reparse handle contract. The actual production
        // directory verification and sync_all still execute and propagate failure.
        File::options()
            .read(true)
            .write(true)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
            .open(root)
    }
    #[cfg(not(windows))]
    File::open(root)
}
