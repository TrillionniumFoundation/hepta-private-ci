#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use tempfile::TempDir;

pub(crate) fn private_tempdir(label: &str) -> TempDir {
    let temporary = tempfile::tempdir().unwrap_or_else(|error| panic!("{label}: {error}"));
    #[cfg(unix)]
    std::fs::set_permissions(temporary.path(), std::fs::Permissions::from_mode(0o700))
        .unwrap_or_else(|error| panic!("secure {label}: {error}"));
    temporary
}

// Use only an OS installation path. A PATH lookup would allow a fixture to
// execute a caller-supplied program rather than the interoperability oracle.
pub(crate) fn ssh_keygen() -> std::path::PathBuf {
    #[cfg(not(windows))]
    {
        std::path::PathBuf::from("/usr/bin/ssh-keygen")
    }
    #[cfg(windows)]
    {
        use std::ffi::OsString;
        use std::os::windows::ffi::OsStringExt;

        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn GetSystemDirectoryW(buffer: *mut u16, size: u32) -> u32;
        }
        let mut buffer = [0_u16; 32768];
        // SAFETY: buffer is writable for the supplied UTF-16 unit count.
        let length = unsafe { GetSystemDirectoryW(buffer.as_mut_ptr(), buffer.len() as u32) };
        assert!(
            length > 0 && (length as usize) < buffer.len(),
            "query trusted system directory: {}",
            std::io::Error::last_os_error()
        );
        std::path::PathBuf::from(OsString::from_wide(&buffer[..length as usize]))
            .join("OpenSSH")
            .join("ssh-keygen.exe")
    }
}
