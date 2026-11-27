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

pub(crate) fn ssh_keygen_command() -> std::process::Command {
    #[cfg(windows)]
    {
        use std::os::windows::ffi::OsStringExt;

        #[link(name = "kernel32")]
        unsafe extern "system" {
            fn GetSystemDirectoryW(buffer: *mut u16, size: u32) -> u32;
        }

        let mut buffer = [0_u16; 32768];
        // SAFETY: the writable buffer contains the advertised number of WCHARs.
        let length = unsafe { GetSystemDirectoryW(buffer.as_mut_ptr(), 32768) } as usize;
        assert!(
            length > 0 && length < buffer.len(),
            "read Windows system directory"
        );
        let system = std::path::PathBuf::from(std::ffi::OsString::from_wide(&buffer[..length]));
        std::process::Command::new(system.join("OpenSSH").join("ssh-keygen.exe"))
    }
    #[cfg(not(windows))]
    std::process::Command::new("/usr/bin/ssh-keygen")
}
