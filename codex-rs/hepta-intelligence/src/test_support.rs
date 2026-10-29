use std::fs::File;
use std::path::Path;

/// Open the actual directory with the access required by the ledger's fsync.
pub(crate) fn directory(path: &Path) -> File {
    #[cfg(windows)]
    {
        use std::fs::OpenOptions;
        use std::os::windows::fs::OpenOptionsExt;

        OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
            .open(path)
            .expect("writable directory handle")
    }
    #[cfg(not(windows))]
    File::open(path).expect("directory handle")
}
