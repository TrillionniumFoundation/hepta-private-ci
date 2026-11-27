use std::fs::File;
use std::path::Path;

pub(crate) fn open_directory(path: &Path) -> File {
    #[cfg(windows)]
    {
        use std::fs::OpenOptions;
        use std::os::windows::fs::OpenOptionsExt;

        // Ledger publication flushes this actual directory handle. Windows
        // requires both directory semantics and write access for that flush.
        OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
            .open(path)
            .expect("open writable ledger directory")
    }
    #[cfg(not(windows))]
    File::open(path).expect("open ledger directory")
}
