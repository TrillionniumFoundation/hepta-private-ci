use crate::proc_thread_attr::ProcThreadAttributeList;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::ffi::OsStringExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::io::RawHandle;
use std::path::Path;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT;
use windows_sys::Win32::Foundation::SetHandleInformation;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::System::Threading::CREATE_UNICODE_ENVIRONMENT;
use windows_sys::Win32::System::Threading::CreateProcessW;
use windows_sys::Win32::System::Threading::EXTENDED_STARTUPINFO_PRESENT;
use windows_sys::Win32::System::Threading::PROCESS_INFORMATION;
use windows_sys::Win32::System::Threading::STARTF_USESTDHANDLES;
use windows_sys::Win32::System::Threading::STARTUPINFOEXW;

/// Starts the asynchronous setup helper with only dedicated NUL handles inherited.
///
/// The helper retains the caller's user, environment, and current directory. Closing
/// the returned process handle does not terminate or wait for the background work.
pub fn spawn_background_setup_helper(executable: &Path, payload: &str) -> io::Result<OwnedHandle> {
    let mut command_line = quote_argument(executable.as_os_str())?;
    command_line.push(u16::from(b' '));
    command_line.extend(quote_argument(OsStr::new(payload))?);
    spawn_with_null_stdio(executable, &OsString::from_wide(&command_line))
}

fn spawn_with_null_stdio(executable: &Path, command_line: &OsStr) -> io::Result<OwnedHandle> {
    let application = wide_null(executable.as_os_str())?;
    let mut command_line = wide_null(command_line)?;
    let stdin = File::open("NUL")?;
    let stdout = OpenOptions::new().write(true).open("NUL")?;
    let stderr = OpenOptions::new().write(true).open("NUL")?;
    let handles = [
        stdin.as_raw_handle() as HANDLE,
        stdout.as_raw_handle() as HANDLE,
        stderr.as_raw_handle() as HANDLE,
    ];
    for handle in handles {
        // These are newly opened, dedicated NUL handles, never the parent's stdio.
        if unsafe { SetHandleInformation(handle, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT) } == 0 {
            return Err(io::Error::last_os_error());
        }
    }
    let mut attributes = ProcThreadAttributeList::new(/*attr_count*/ 1)?;
    attributes.set_handle_list(handles.to_vec())?;
    // SAFETY: Both Win32 output structures are specified to accept zero initialization.
    let mut startup: STARTUPINFOEXW = unsafe { std::mem::zeroed() };
    let mut process: PROCESS_INFORMATION = unsafe { std::mem::zeroed() };
    startup.StartupInfo.cb = std::mem::size_of::<STARTUPINFOEXW>() as u32;
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.StartupInfo.hStdInput = handles[0];
    startup.StartupInfo.hStdOutput = handles[1];
    startup.StartupInfo.hStdError = handles[2];
    startup.lpAttributeList = attributes.as_mut_ptr();
    // SAFETY: The mutable command line, attribute backing storage, and the three
    // owned NUL handles remain live throughout creation. TRUE is required for an
    // explicit HANDLE_LIST; that list excludes every other inheritable handle.
    // Null environment/current-directory pointers preserve the original inheritance.
    let created = unsafe {
        CreateProcessW(
            application.as_ptr(),
            command_line.as_mut_ptr(),
            ptr::null(),
            ptr::null(),
            1,
            CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT,
            ptr::null(),
            ptr::null(),
            &startup.StartupInfo,
            &mut process,
        )
    };
    if created == 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: Successful CreateProcessW transfers these two distinct, owned handles.
    // Adopt both before returning; neither is a borrowed handle or reopened PID.
    let process_handle = unsafe { OwnedHandle::from_raw_handle(process.hProcess as RawHandle) };
    let thread_handle = unsafe { OwnedHandle::from_raw_handle(process.hThread as RawHandle) };
    drop(thread_handle);
    Ok(process_handle)
}

fn wide_null(value: &OsStr) -> io::Result<Vec<u16>> {
    let mut wide: Vec<u16> = value.encode_wide().collect();
    if wide.contains(&0) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "setup helper argument contains a NUL code unit",
        ));
    }
    wide.push(0);
    Ok(wide)
}

fn quote_argument(value: &OsStr) -> io::Result<Vec<u16>> {
    let wide = wide_null(value)?;
    let mut quoted = vec![u16::from(b'"')];
    let mut slashes = 0;
    for &unit in &wide[..wide.len() - 1] {
        if unit == u16::from(b'\\') {
            slashes += 1;
            continue;
        }
        let escaping = if unit == u16::from(b'"') {
            slashes * 2 + 1
        } else {
            slashes
        };
        quoted.extend(std::iter::repeat_n(u16::from(b'\\'), escaping));
        quoted.push(unit);
        slashes = 0;
    }
    quoted.extend(std::iter::repeat_n(u16::from(b'\\'), slashes * 2));
    quoted.push(u16::from(b'"'));
    Ok(quoted)
}

#[cfg(test)]
#[path = "setup_background_tests.rs"]
mod tests;
