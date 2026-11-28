use std::fs::File;
use std::io;
use std::path::Path;

pub(crate) fn open_durable_directory(path: &Path) -> io::Result<File> {
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;

        // Match the original learning-ledger Windows fixture: retain an actual
        // writable directory handle so production sync_all still reaches the OS.
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
            .open(path)
    }
    #[cfg(not(windows))]
    File::open(path)
}
