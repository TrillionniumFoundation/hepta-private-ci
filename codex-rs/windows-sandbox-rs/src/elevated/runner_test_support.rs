use anyhow::Result;
use std::fs::File;
use std::os::windows::io::FromRawHandle;
use std::ptr;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::Pipes::CreatePipe;

pub(super) fn pipe_pair() -> Result<(File, File)> {
    let mut reader: HANDLE = 0;
    let mut writer: HANDLE = 0;
    if unsafe { CreatePipe(&mut reader, &mut writer, ptr::null(), 4_096) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(unsafe {
        (
            File::from_raw_handle(reader as _),
            File::from_raw_handle(writer as _),
        )
    })
}
