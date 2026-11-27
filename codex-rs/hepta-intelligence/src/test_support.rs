use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;

/// Open this test's owned directory for the real ledger durability barrier.
pub(crate) fn open_fixture_directory(path: &Path) -> File {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;

        const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
        const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
        // Match the qualified learning-ledger fixture: FlushFileBuffers needs
        // write access and directory opens need FILE_FLAG_BACKUP_SEMANTICS.
        // Keep the final reparse point visible so it can be rejected below.
        options
            .write(true)
            .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT);
    }
    let directory = options.open(path).expect("open owned fixture directory");
    let metadata = directory.metadata().expect("inspect fixture directory");
    assert!(metadata.is_dir());
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;

        assert_eq!(metadata.file_attributes() & 0x0400, 0);
    }
    directory
}
