use std::fs::File;
use std::path::Path;

/// Open the actual containing directory used by the ledger's durability check.
/// This matches the learning-ledger owner fixture; no sync error is suppressed.
pub(crate) fn open_directory(path: &Path) -> std::io::Result<File> {
    #[cfg(windows)]
    {
        use std::fs::OpenOptions;
        use std::os::windows::fs::OpenOptionsExt;

        OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
            .open(path)
    }
    #[cfg(not(windows))]
    File::open(path)
}
