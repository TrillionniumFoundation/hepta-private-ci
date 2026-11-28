use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;

const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;

fn open_directory_for_sync(path: &Path) -> std::io::Result<File> {
    use std::os::windows::fs::MetadataExt;

    // Directory handles require backup semantics. FlushFileBuffers also
    // requires write access; a read-only File::open handle cannot perform it.
    const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
    const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_dir() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidInput,
            "directory sync requires a directory without a reparse point",
        ));
    }
    Ok(file)
}

pub(super) fn sync_directory(path: &Path) -> std::io::Result<()> {
    open_directory_for_sync(path)?.sync_all()
}

#[cfg(test)]
#[path = "durable_windows_tests.rs"]
mod tests;
