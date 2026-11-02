use std::fs::File;
use std::io;
use std::path::Path;

/// Opens a real directory handle for the durable ledger test fixtures.
pub(crate) fn open_directory(path: &Path) -> io::Result<File> {
    #[cfg(windows)]
    {
        use std::fs::OpenOptions;
        use std::os::windows::fs::OpenOptionsExt;

        // Match the learning-ledger fixtures: Windows needs a directory handle
        // with write access for sync_all. Production still performs that sync.
        OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(/*flags*/ 0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
            .open(path)
    }
    #[cfg(not(windows))]
    File::open(path)
}
