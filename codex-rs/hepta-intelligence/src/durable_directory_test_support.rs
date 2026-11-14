use std::fs::File;
use std::io;
use std::path::Path;

pub(crate) fn directory(path: &Path) -> io::Result<File> {
    #[cfg(windows)]
    {
        use std::fs::OpenOptions;
        use std::os::windows::fs::OpenOptionsExt;

        // Keep a real writable directory handle for the production ledger's
        // FlushFileBuffers call. Opening a directory also needs backup semantics.
        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS)
            .open(path)
    }
    #[cfg(not(windows))]
    File::open(path)
}
