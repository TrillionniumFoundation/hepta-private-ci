use std::fs::File;
use std::fs::OpenOptions;
use std::path::Path;

pub(crate) fn open_directory(path: &Path) -> File {
    let mut options = OpenOptions::new();
    options.read(true);
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        // Real writable directory handles are required by FlushFileBuffers.
        options.write(true).custom_flags(/*flags*/ 0x0200_0000);
    }
    options.open(path).expect("open durable fixture directory")
}
