//! Host-side test handles used by actual durable ledger operations.

use std::fs::File;
use std::path::Path;

pub(crate) fn directory(root: &Path) -> std::io::Result<File> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;

        // Match the existing learning-ledger fixture and native NTFS probe.
        // The actual production sync_all still executes and propagates failure.
        File::options()
            .read(true)
            .write(true)
            .custom_flags(0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
            .open(root)
    }
    #[cfg(not(windows))]
    File::open(root)
}
