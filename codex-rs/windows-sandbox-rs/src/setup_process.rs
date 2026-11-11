//! Non-elevated setup children inherit only their three NUL standard handles.
//!
//! The setup executable can start a background read-ACL helper. Ambient pipe
//! handles must not reach that descendant through the foreground setup child.

use crate::proc_thread_attr::ProcThreadAttributeList;
use crate::winutil::argv_to_command_line;
use crate::winutil::to_wide;
use std::ffi::OsString;
use std::fs::File;
use std::io;
use std::os::windows::ffi::OsStringExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::process::ExitStatusExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::ExitStatus;
use windows_sys::Win32::Foundation::DUPLICATE_SAME_ACCESS;
use windows_sys::Win32::Foundation::DuplicateHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Storage::FileSystem::GetFileAttributesW;
use windows_sys::Win32::Storage::FileSystem::INVALID_FILE_ATTRIBUTES;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::System::Threading::CREATE_UNICODE_ENVIRONMENT;
use windows_sys::Win32::System::Threading::CreateProcessW;
use windows_sys::Win32::System::Threading::EXTENDED_STARTUPINFO_PRESENT;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::INFINITE;
use windows_sys::Win32::System::Threading::PROCESS_INFORMATION;
use windows_sys::Win32::System::Threading::STARTF_USESTDHANDLES;
use windows_sys::Win32::System::Threading::STARTUPINFOEXW;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

// These two kernel32 queries preserve std::process::Command's existing search
// order without adding a windows-sys feature or using SearchPathW's CWD search.
#[link(name = "kernel32")]
unsafe extern "system" {
    fn GetSystemDirectoryW(buffer: *mut u16, size: u32) -> u32;
    fn GetWindowsDirectoryW(buffer: *mut u16, size: u32) -> u32;
}

pub(super) enum SetupHelperWindow {
    Default,
    Hidden,
}

pub(super) fn run_setup_helper(
    executable: &Path,
    payload: &str,
    window: SetupHelperWindow,
) -> io::Result<ExitStatus> {
    let process = spawn_with_null_stdio(executable, &[payload], /*current_dir*/ None, window)?;
    // Preserve Command::status's original unbounded wait for this exact child.
    // No background read-ACL helper is waited for or terminated here.
    if unsafe { WaitForSingleObject(process.as_raw_handle() as HANDLE, INFINITE) } != WAIT_OBJECT_0 {
        return Err(io::Error::last_os_error());
    }
    let mut exit_code = 0;
    if unsafe { GetExitCodeProcess(process.as_raw_handle() as HANDLE, &mut exit_code) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(ExitStatus::from_raw(exit_code))
}

fn spawn_with_null_stdio(
    executable: &Path,
    args: &[&str],
    current_dir: Option<&Path>,
    window: SetupHelperWindow,
) -> io::Result<OwnedHandle> {
    let application = resolve_executable(executable)?;
    let argv0 = to_wide(executable);
    // Windows file names cannot contain a quote. Keep the path's UTF-16 bytes,
    // including unpaired surrogates, instead of converting it through UTF-8.
    if argv0[..argv0.len() - 1].contains(&u16::from(b'"'))
        || args.iter().any(|arg| arg.contains('\0'))
    {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid setup helper argument"));
    }
    let mut command = vec![u16::from(b'"')];
    command.extend_from_slice(&argv0[..argv0.len() - 1]);
    command.push(u16::from(b'"'));
    if !args.is_empty() {
        command.push(u16::from(b' '));
        command.extend(to_wide(argv_to_command_line(
            &args.iter().map(ToString::to_string).collect::<Vec<_>>(),
        )));
    } else {
        command.push(0);
    }
    let directory = current_dir.map(to_wide);
    if directory.as_ref().is_some_and(|path| path[..path.len() - 1].contains(&0)) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid setup helper directory"));
    }

    let input = inheritable_null(File::open(r"\\.\NUL")?)?;
    let output = inheritable_null(File::options().write(true).open(r"\\.\NUL")?)?;
    let error = inheritable_null(File::options().write(true).open(r"\\.\NUL")?)?;
    let handles = [
        input.as_raw_handle() as HANDLE,
        output.as_raw_handle() as HANDLE,
        error.as_raw_handle() as HANDLE,
    ];
    let mut attributes = ProcThreadAttributeList::new(/*attr_count*/ 1)?;
    attributes.set_handle_list(handles.to_vec())?;
    let mut startup: STARTUPINFOEXW = unsafe { std::mem::zeroed() };
    startup.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = handles[0];
    startup.StartupInfo.hStdOutput = handles[1];
    startup.StartupInfo.hStdError = handles[2];
    startup.lpAttributeList = attributes.as_mut_ptr();
    let window_flags = match window {
        SetupHelperWindow::Default => 0,
        SetupHelperWindow::Hidden => CREATE_NO_WINDOW,
    };
    let mut information: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: the explicit three-handle list and all referenced buffers remain
    // owned until creation returns. Inherited environment/CWD and the caller's
    // existing primary token are unchanged. No ambient handle enters the list.
    if unsafe {
        CreateProcessW(
            application.as_ptr(),
            command.as_mut_ptr(),
            std::ptr::null(),
            std::ptr::null(),
            /*binherithandles*/ 1,
            CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT | window_flags,
            std::ptr::null(),
            directory.as_ref().map_or(std::ptr::null(), |path| path.as_ptr()),
            &startup.StartupInfo,
            &mut information,
        )
    } == 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: successful CreateProcessW returned two new owned handles.
    let process = unsafe { OwnedHandle::from_raw_handle(information.hProcess as _) };
    let thread = unsafe { OwnedHandle::from_raw_handle(information.hThread as _) };
    drop(thread);
    Ok(process)
}

fn inheritable_null(file: File) -> io::Result<OwnedHandle> {
    let mut duplicate = 0;
    // SAFETY: duplicate only the newly opened NUL handle. The parent's standard
    // handles and all other live handle flags remain untouched.
    if unsafe {
        DuplicateHandle(
            GetCurrentProcess(),
            file.as_raw_handle() as HANDLE,
            GetCurrentProcess(),
            &mut duplicate,
            /*dwdesiredaccess*/ 0,
            /*binherithandle*/ 1,
            DUPLICATE_SAME_ACCESS,
        )
    } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(unsafe { OwnedHandle::from_raw_handle(duplicate as _) })
}

fn resolve_executable(executable: &Path) -> io::Result<Vec<u16>> {
    let original = to_wide(executable);
    let path = &original[..original.len() - 1];
    if executable.file_name().is_none()
        || path.contains(&0)
        || path.last().is_some_and(|value| matches!(*value, 47 | 92))
    {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid setup helper executable"));
    }
    // All callers select a .exe helper. Absolute paths and relative paths with
    // a separator keep their existing meaning; only the bare fallback is searched.
    if executable.file_name() != Some(executable.as_os_str()) {
        return executable_user_path(executable);
    }
    // Match pinned Rust 1.96's search_paths with no child PATH override:
    // application directory, system directory, Windows directory, parent PATH.
    // In particular, do not add CWD or empty PATH entries as SearchPathW can do.
    let mut directories = Vec::new();
    if let Ok(current) = std::env::current_exe()
        && let Some(parent) = current.parent()
    {
        directories.push(parent.to_owned());
    }
    for query in [GetSystemDirectoryW, GetWindowsDirectoryW] {
        let needed = unsafe { query(std::ptr::null_mut(), /*size*/ 0) };
        if needed == 0 || needed > 32_768 {
            continue;
        }
        let mut buffer = vec![0; needed as usize];
        let length = unsafe { query(buffer.as_mut_ptr(), needed) };
        if length != 0 && length < needed {
            directories.push(PathBuf::from(OsString::from_wide(&buffer[..length as usize])));
        }
    }
    if let Some(path) = std::env::var_os("PATH") {
        directories.extend(std::env::split_paths(&path).filter(|path| !path.as_os_str().is_empty()));
    }
    for directory in directories {
        let Ok(candidate) = executable_user_path(&directory.join(executable)) else {
            continue;
        };
        if unsafe { GetFileAttributesW(candidate.as_ptr()) } != INVALID_FILE_ATTRIBUTES {
            return Ok(candidate);
        }
    }
    Err(io::Error::new(io::ErrorKind::NotFound, "program not found"))
}

// Preserve Rust 1.96 args::to_user_path / path::get_long_path(false), used by
// Command both for explicit .exe paths and each searched candidate. The stable
// path::absolute API performs the same GetFullPathNameW normalization without
// opening the file or resolving symlinks. The 260/248 thresholds are std's,
// including the NUL; they are not a new executable-length policy.
fn executable_user_path(path: &Path) -> io::Result<Vec<u16>> {
    const SEP: u16 = b'\\' as u16;
    const ALT: u16 = b'/' as u16;
    const QUERY: u16 = b'?' as u16;
    const COLON: u16 = b':' as u16;
    const DOT: u16 = b'.' as u16;
    const U: u16 = b'U' as u16;
    const N: u16 = b'N' as u16;
    const C: u16 = b'C' as u16;
    const VERBATIM: &[u16] = &[SEP, SEP, QUERY, SEP];
    const NT: &[u16] = &[SEP, QUERY, QUERY, SEP];
    const UNC: &[u16] = &[SEP, SEP, QUERY, SEP, U, N, C, SEP];

    let encoded = to_wide(path);
    if encoded[..encoded.len() - 1].contains(&0) {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid setup helper executable"));
    }
    if encoded.len() > 260 {
        return Ok(encoded);
    }
    let stripped = match encoded.as_slice() {
        [SEP, SEP, QUERY, SEP, _, COLON, SEP, ..] => Some(encoded[4..encoded.len() - 1].to_vec()),
        [SEP, SEP, QUERY, SEP, U, N, C, SEP, ..] => {
            let mut path = vec![SEP, SEP];
            path.extend_from_slice(&encoded[8..encoded.len() - 1]);
            Some(path)
        }
        _ => None,
    };
    if let Some(stripped) = stripped {
        let absolute = to_wide(std::path::absolute(PathBuf::from(OsString::from_wide(&stripped)))?);
        return Ok(if absolute[..absolute.len() - 1] == stripped { absolute } else { encoded });
    }
    if encoded.starts_with(VERBATIM) || encoded.starts_with(NT) || encoded == [0] {
        return Ok(encoded);
    }
    if encoded.len() < 248 {
        match encoded.as_slice() {
            [drive, COLON, 0] | [drive, COLON, SEP | ALT, ..] if *drive != SEP && *drive != ALT => return Ok(encoded),
            [SEP | ALT, SEP | ALT, ..] => return Ok(encoded),
            _ => {}
        }
    }
    let absolute = to_wide(std::path::absolute(path)?);
    if absolute.len() < 248 {
        return Ok(absolute);
    }
    let mut body = &absolute[..absolute.len() - 1];
    let prefix = match body {
        [_, COLON, SEP, ..] => VERBATIM,
        [SEP, SEP, DOT, SEP, ..] => {
            body = &body[4..];
            VERBATIM
        }
        [SEP, SEP, QUERY, SEP, ..] | [SEP, QUERY, QUERY, SEP, ..] => &[],
        [SEP, SEP, ..] => {
            body = &body[2..];
            UNC
        }
        _ => &[],
    };
    let mut result = Vec::with_capacity(prefix.len() + body.len() + 1);
    result.extend_from_slice(prefix);
    result.extend_from_slice(body);
    result.push(0);
    Ok(result)
}

#[cfg(test)]
#[path = "setup_process_tests.rs"]
mod tests;
