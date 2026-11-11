use crate::proc_thread_attr::ProcThreadAttributeList;
use crate::process::ConsoleMode;
use crate::winutil::quote_windows_arg;
use crate::winutil::to_wide;
use std::ffi::OsString;
use std::io;
use std::os::windows::ffi::OsStringExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::process::ExitStatusExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::ExitStatus;
use std::ptr;
use windows_sys::Win32::Foundation::GENERIC_READ;
use windows_sys::Win32::Foundation::GENERIC_WRITE;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_NORMAL;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::GetFileAttributesW;
use windows_sys::Win32::Storage::FileSystem::INVALID_FILE_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::System::Threading::CREATE_UNICODE_ENVIRONMENT;
use windows_sys::Win32::System::Threading::CreateProcessW;
use windows_sys::Win32::System::Threading::EXTENDED_STARTUPINFO_PRESENT;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::INFINITE;
use windows_sys::Win32::System::Threading::PROCESS_INFORMATION;
use windows_sys::Win32::System::Threading::STARTF_USESTDHANDLES;
use windows_sys::Win32::System::Threading::STARTUPINFOEXW;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

/// Launch a setup helper with only its own NUL handle inherited.
///
/// Redirecting standard streams alone leaves unrelated inheritable handles
/// available to Windows children, including a caller's captured output pipes.
/// The returned handle retains the exact child; dropping it preserves the
/// existing detached read-ACL helper behavior.
pub fn spawn_setup_helper(
    executable: &Path,
    payload: &str,
    console_mode: ConsoleMode,
) -> io::Result<OwnedHandle> {
    if executable.file_name().is_none() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "setup executable has no file name",
        ));
    }
    let executable_wide = to_wide(executable);
    let executable_units = &executable_wide[..executable_wide.len() - 1];
    if executable_units.contains(&0) || executable_units.contains(&u16::from(b'"')) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "setup executable contains an invalid command-line character",
        ));
    }
    if payload.contains('\0') {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "setup payload contains a NUL",
        ));
    }
    // The executable has argv[0] quoting rules. Keep its native UTF-16 units
    // intact, and use the repository's existing quoting for the payload.
    let mut command_line = vec![u16::from(b'"')];
    command_line.extend_from_slice(executable_units);
    command_line.extend([u16::from(b'"'), u16::from(b' ')]);
    command_line.extend(to_wide(quote_windows_arg(payload)));
    let application = resolve_setup_executable(executable)?;

    let mut security = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: ptr::null_mut(),
        bInheritHandle: 1,
    };
    let null_name = to_wide("NUL");
    let null_handle = unsafe {
        CreateFileW(
            null_name.as_ptr(),
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            &mut security,
            OPEN_EXISTING,
            FILE_ATTRIBUTE_NORMAL,
            0,
        )
    };
    if null_handle == INVALID_HANDLE_VALUE {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: CreateFileW returned one valid handle owned by this call.
    let null_handle = unsafe { OwnedHandle::from_raw_handle(null_handle as _) };
    let inherited = null_handle.as_raw_handle() as HANDLE;
    let mut attributes = ProcThreadAttributeList::new(/*attr_count*/ 1)?;
    attributes.set_handle_list(vec![inherited])?;

    let mut startup: STARTUPINFOEXW = unsafe { std::mem::zeroed() };
    startup.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = inherited;
    startup.StartupInfo.hStdOutput = inherited;
    startup.StartupInfo.hStdError = inherited;
    startup.lpAttributeList = attributes.as_mut_ptr();
    let console_flags = match console_mode {
        ConsoleMode::Inherit => 0,
        ConsoleMode::NoWindow => CREATE_NO_WINDOW,
    };
    let mut process: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    // The environment and working directory remain inherited as before.
    // All attribute storage and the sole allowed handle stay alive until the
    // native launch has completed; no caller-owned handle flags are changed.
    let created = unsafe {
        CreateProcessW(
            application.as_ptr(),
            command_line.as_mut_ptr(),
            ptr::null_mut(),
            ptr::null_mut(),
            1,
            CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT | console_flags,
            ptr::null(),
            ptr::null(),
            &startup.StartupInfo,
            &mut process,
        )
    };
    if created == 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: a successful CreateProcessW transfers these two fresh handles.
    let process_handle = unsafe { OwnedHandle::from_raw_handle(process.hProcess as _) };
    let thread_handle = unsafe { OwnedHandle::from_raw_handle(process.hThread as _) };
    drop(thread_handle);
    Ok(process_handle)
}

/// Retain the original synchronous setup wait and native exit status.
pub(crate) fn wait_setup_helper(process: OwnedHandle) -> io::Result<ExitStatus> {
    let process_handle = process.as_raw_handle() as HANDLE;
    if unsafe { WaitForSingleObject(process_handle, INFINITE) } != WAIT_OBJECT_0 {
        return Err(io::Error::last_os_error());
    }
    let mut code = 0;
    if unsafe { GetExitCodeProcess(process_handle, &mut code) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(ExitStatus::from_raw(code))
}

// The three setup callers supply a .exe path. Keep Command's search order for
// the bare-name fallback without introducing CreateProcessW's implicit CWD
// search. Explicit paths and PATH entries retain native UTF-16 throughout.
fn resolve_setup_executable(executable: &Path) -> io::Result<Vec<u16>> {
    if executable
        .parent()
        .is_some_and(|parent| !parent.as_os_str().is_empty())
    {
        return std::path::absolute(executable).map(to_wide);
    }
    let application_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(Path::to_path_buf));
    let system_dir = windows_directory(get_system_directory);
    let windows_dir = windows_directory(get_windows_directory);
    let parent_path = std::env::var_os("PATH");
    let search_dirs = application_dir
        .into_iter()
        .chain(system_dir)
        .chain(windows_dir)
        .chain(
            parent_path
                .iter()
                .flat_map(std::env::split_paths)
                .filter(|path| !path.as_os_str().is_empty()),
        );
    for directory in search_dirs {
        let Ok(candidate) = std::path::absolute(directory.join(executable)) else {
            continue;
        };
        let candidate = to_wide(candidate);
        if unsafe { GetFileAttributesW(candidate.as_ptr()) } != INVALID_FILE_ATTRIBUTES {
            return Ok(candidate);
        }
    }
    Err(io::Error::new(
        io::ErrorKind::NotFound,
        "setup executable not found",
    ))
}

fn windows_directory(query: unsafe extern "system" fn(*mut u16, u32) -> u32) -> Option<PathBuf> {
    let mut buffer = vec![0; 260];
    loop {
        let length = unsafe { query(buffer.as_mut_ptr(), buffer.len() as u32) } as usize;
        if length == 0 {
            return None;
        }
        if length < buffer.len() {
            return Some(PathBuf::from(OsString::from_wide(&buffer[..length])));
        }
        buffer.resize(length.checked_add(1)?, 0);
    }
}

// These existing kernel32 APIs avoid expanding the crate's Windows feature set
// solely to retain Command's system-directory search behavior.
#[link(name = "kernel32")]
unsafe extern "system" {
    #[link_name = "GetSystemDirectoryW"]
    fn get_system_directory(buffer: *mut u16, size: u32) -> u32;
    #[link_name = "GetWindowsDirectoryW"]
    fn get_windows_directory(buffer: *mut u16, size: u32) -> u32;
}
