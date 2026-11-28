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

pub(crate) fn ssh_keygen_path() -> std::path::PathBuf {
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
        let mut buffer = vec![0_u16; 32_768];
        // SAFETY: the initialized UTF-16 buffer spans the exact supplied size.
        // This reads the OS system directory; no environment search is used.
        let count = unsafe { GetSystemDirectoryW(buffer.as_mut_ptr(), buffer.len() as u32) };
        assert!(
            count != 0 && (count as usize) < buffer.len(),
            "read the Windows system directory: {}",
            std::io::Error::last_os_error()
        );
        std::path::PathBuf::from(OsString::from_wide(&buffer[..count as usize]))
            .join("OpenSSH")
            .join("ssh-keygen.exe")
    }
}
