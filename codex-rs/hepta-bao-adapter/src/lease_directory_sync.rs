#[cfg(not(windows))]
use std::fs::File;
use std::io;
use std::path::Path;

pub(super) fn sync_parent(parent: &Path) -> io::Result<()> {
    #[cfg(windows)]
    let directory = {
        use std::os::windows::fs::OpenOptionsExt;

        // FlushFileBuffers requires a writable directory handle. Preserve the
        // real flush and its errors after the registry file is renamed.
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(0x0200_0000) // FILE_FLAG_BACKUP_SEMANTICS
            .open(parent)?
    };
    #[cfg(not(windows))]
    let directory = File::open(parent)?;
    directory.sync_all()
}
