use super::OwnedChildStdio;
use crate::process::ConsoleMode;
use crate::process::StderrMode;
use crate::process::StdinMode;
use crate::process::spawn_process_with_pipes;
use crate::token::create_readonly_token_with_caps_from;
use crate::token::get_current_token_for_restriction;
use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::GetHandleInformation;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::ReadFile;
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::Pipes::PeekNamedPipe;
use windows_sys::Win32::System::Threading::CreateEventW;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::SetEvent;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

fn pipe() -> Result<(OwnedHandle, OwnedHandle)> {
    let mut read = 0;
    let mut write = 0;
    ensure!(unsafe { CreatePipe(&mut read, &mut write, std::ptr::null_mut(), 0) } != 0);
    Ok(unsafe {
        (
            OwnedHandle::from_raw_handle(read as _),
            OwnedHandle::from_raw_handle(write as _),
        )
    })
}

fn flags(handle: HANDLE) -> Result<u32> {
    let mut flags = 0;
    ensure!(unsafe { GetHandleInformation(handle, &mut flags) } != 0);
    Ok(flags)
}

#[test]
fn duplicates_exact_endpoints_without_changing_caller_inheritance() -> Result<()> {
    let (read, write) = pipe()?;
    let read = read.as_raw_handle() as HANDLE;
    let write = write.as_raw_handle() as HANDLE;
    let stdio = OwnedChildStdio::duplicate(Some((read, write, write)))?;
    assert_eq!(
        (flags(read)?, flags(write)?, stdio.handle_list().len()),
        (0, 0, 2)
    );
    assert_eq!(stdio.endpoints[1], stdio.endpoints[2]);
    for handle in stdio.handle_list() {
        assert_eq!(flags(handle)? & HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        assert!(![read, write].contains(&handle));
    }
    assert!(OwnedChildStdio::duplicate(Some((read, 0, write))).is_err());
    assert_eq!((flags(read)?, flags(write)?), (0, 0));
    let duplicates = stdio.handle_list();
    drop(stdio);
    for handle in duplicates {
        assert!(flags(handle).is_err());
    }
    Ok(())
}

#[test]
fn stdio_does_not_inherit_unrelated_sentinel() -> Result<()> {
    const CHILD: &str = "HEPTA_STDIO_SENTINEL_CHILD";
    const ATTEMPTED: &str = "HEPTA_STDIO_SENTINEL_ATTEMPTED";
    if let Ok(value) = std::env::var(CHILD) {
        let handle = value.parse::<isize>()?;
        // This deliberately attempts to mutate the parent's unrelated event.
        // The parent's observation, rather than a child-side handle number,
        // establishes whether the original kernel object was inherited.
        unsafe { SetEvent(handle) };
        println!("{ATTEMPTED}");
        return Ok(());
    }
    let security = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: std::ptr::null_mut(),
        bInheritHandle: 1,
    };
    let raw = unsafe {
        CreateEventW(
            &security,
            /*bmanualreset*/ 1,
            /*binitialstate*/ 0,
            std::ptr::null(),
        )
    };
    ensure!(raw != 0);
    let sentinel = unsafe { OwnedHandle::from_raw_handle(raw as _) };
    let base = unsafe { OwnedHandle::from_raw_handle(get_current_token_for_restriction()? as _) };
    let token = unsafe {
        OwnedHandle::from_raw_handle(create_readonly_token_with_caps_from(
            base.as_raw_handle() as HANDLE,
            &[],
        )? as _)
    };
    let executable = std::env::current_exe()?;
    let argv = vec![
        executable.to_string_lossy().into_owned(),
        "--exact".to_owned(),
        "process::owned_child_stdio::tests::stdio_does_not_inherit_unrelated_sentinel".to_owned(),
        "--nocapture".to_owned(),
    ];
    let mut environment = std::env::vars().collect::<std::collections::HashMap<_, _>>();
    environment.insert(CHILD.to_owned(), raw.to_string());
    let spawned = spawn_process_with_pipes(
        token.as_raw_handle() as HANDLE,
        &argv,
        &std::env::current_dir()?,
        &environment,
        StdinMode::Closed,
        StderrMode::MergeStdout,
        ConsoleMode::NoWindow,
        /*use_private_desktop*/ false,
        /*logs_base_dir*/ None,
    )?;
    let terminal = unsafe {
        WaitForSingleObject(spawned.process.hProcess, /*dwmilliseconds*/ 8000)
    };
    if terminal != WAIT_OBJECT_0 {
        spawned.job().terminate()?;
    }
    let mut exit_code = 0;
    let observed = unsafe { GetExitCodeProcess(spawned.process.hProcess, &mut exit_code) };
    let mut available = 0;
    let peeked = unsafe {
        PeekNamedPipe(
            spawned.stdout_read,
            std::ptr::null_mut(),
            0,
            std::ptr::null_mut(),
            &mut available,
            std::ptr::null_mut(),
        )
    };
    let mut output = vec![
        0u8;
        if available <= 16 * 1024 {
            available as usize
        } else {
            0
        }
    ];
    let mut read = 0;
    // Read only the available bounded bytes after terminal observation. This
    // cannot add a blocking reader or extend the original child wait budget.
    let read_output = unsafe {
        ReadFile(
            spawned.stdout_read,
            output.as_mut_ptr(),
            output.len() as u32,
            &mut read,
            std::ptr::null_mut(),
        )
    };
    unsafe {
        CloseHandle(spawned.process.hProcess);
        CloseHandle(spawned.process.hThread);
        CloseHandle(spawned.stdout_read);
    }
    assert_eq!((terminal, observed, exit_code), (WAIT_OBJECT_0, 1, 0));
    assert_eq!((peeked, read_output), (1, 1));
    assert!(
        available <= 16 * 1024,
        "child stdout exceeded the 16 KiB budget"
    );
    assert!(String::from_utf8_lossy(&output[..read as usize]).contains(ATTEMPTED));
    assert_eq!(
        unsafe {
            WaitForSingleObject(
                sentinel.as_raw_handle() as HANDLE,
                /*dwmilliseconds*/ 0,
            )
        },
        WAIT_TIMEOUT
    );
    assert_eq!(flags(raw)? & HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    Ok(())
}
