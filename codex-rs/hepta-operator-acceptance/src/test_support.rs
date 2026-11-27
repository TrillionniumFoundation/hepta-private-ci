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
        let mut command = std::process::Command::new(system.join("OpenSSH").join("ssh-keygen.exe"));
        // Win32 OpenSSH reads ProgramData before initializing its diagnostics.
        // Bazel's test environment omits it; derive the real known-folder path
        // for this child without changing the parent process environment.
        command.env("ProgramData", windows_program_data());
        command
    }
    #[cfg(not(windows))]
    std::process::Command::new("/usr/bin/ssh-keygen")
}

#[cfg(windows)]
fn windows_program_data() -> std::ffi::OsString {
    use std::ffi::c_void;
    use std::os::windows::ffi::OsStringExt;

    #[repr(C)]
    struct Guid {
        data1: u32,
        data2: u16,
        data3: u16,
        data4: [u8; 8],
    }
    const PROGRAM_DATA: Guid = Guid {
        data1: 0x62ab5d82,
        data2: 0xfdc1,
        data3: 0x4dc3,
        data4: [0xa9, 0xdd, 0x07, 0x0d, 0x1d, 0x49, 0x5d, 0x97],
    };

    #[link(name = "shell32")]
    unsafe extern "system" {
        fn SHGetKnownFolderPath(
            folder: *const Guid,
            flags: u32,
            token: *mut c_void,
            path: *mut *mut u16,
        ) -> i32;
    }
    #[link(name = "ole32")]
    unsafe extern "system" {
        fn CoTaskMemFree(pointer: *mut c_void);
    }

    let mut raw = std::ptr::null_mut();
    // SAFETY: the GUID has the Windows ABI layout and raw is a valid out pointer.
    let result = unsafe { SHGetKnownFolderPath(&PROGRAM_DATA, 0, std::ptr::null_mut(), &mut raw) };
    let path = if result == 0 && !raw.is_null() {
        // SAFETY: a successful call returns a NUL-terminated allocation, owned
        // until CoTaskMemFree below. Copy it before releasing that allocation.
        unsafe {
            let mut length = 0;
            while *raw.add(length) != 0 {
                length += 1;
            }
            Some(std::ffi::OsString::from_wide(std::slice::from_raw_parts(
                raw, length,
            )))
        }
    } else {
        None
    };
    // SAFETY: this API requires freeing its result on both success and failure;
    // CoTaskMemFree also accepts a null pointer.
    unsafe { CoTaskMemFree(raw.cast()) };
    let path = path.unwrap_or_else(|| panic!("read Windows ProgramData: {result:#x}"));
    assert!(!path.is_empty(), "Windows ProgramData must not be empty");
    path
}
