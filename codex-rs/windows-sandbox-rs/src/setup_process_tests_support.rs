use anyhow::Result;
use anyhow::ensure;
use codex_utils_pty::JobObject;
use serde::Deserialize;
use serde::Serialize;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::process::Child;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation as foundation;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem as files;
use windows_sys::Win32::System::Console as console;
use windows_sys::Win32::System::JobObjects as jobs;
use windows_sys::Win32::System::Pipes as pipes;
use windows_sys::Win32::System::Threading as threading;

pub(super) const READY_MS: u32 = 5_000;
pub(super) const EXIT_MS: u32 = 10_000;

pub(super) fn handle(value: &impl AsRawHandle) -> foundation::HANDLE {
    value.as_raw_handle() as foundation::HANDLE
}

fn owned(value: foundation::HANDLE) -> Result<OwnedHandle> {
    ensure!(
        value != 0 && value != foundation::INVALID_HANDLE_VALUE,
        "{}",
        io::Error::last_os_error()
    );
    // SAFETY: every caller supplies one newly returned, valid native handle.
    Ok(unsafe { OwnedHandle::from_raw_handle(value as _) })
}

pub(super) fn event(name: Option<&str>, inheritable: bool) -> Result<OwnedHandle> {
    let name = name.map(crate::winutil::to_wide);
    let security = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: std::ptr::null_mut(),
        bInheritHandle: i32::from(inheritable),
    };
    // SAFETY: the optional name and security descriptor outlive this call.
    let (raw, error) = unsafe {
        foundation::SetLastError(0);
        let raw = threading::CreateEventW(
            &security,
            1,
            0,
            name.as_ref()
                .map_or(std::ptr::null(), std::vec::Vec::as_ptr),
        );
        (raw, foundation::GetLastError())
    };
    let value = owned(raw)?;
    ensure!(
        error != foundation::ERROR_ALREADY_EXISTS,
        "control event already existed"
    );
    Ok(value)
}

pub(super) fn open_event(name: &str) -> Result<OwnedHandle> {
    let name = crate::winutil::to_wide(name);
    // SAFETY: name is terminated; this is an explicit non-inheritable control handle.
    owned(unsafe { threading::OpenEventW(threading::EVENT_ALL_ACCESS, 0, name.as_ptr()) })
}

pub(super) fn signal(value: &OwnedHandle) -> Result<()> {
    // SAFETY: this scope retains the event handle throughout the call.
    ensure!(
        unsafe { threading::SetEvent(handle(value)) } != 0,
        "{}",
        io::Error::last_os_error()
    );
    Ok(())
}

pub(super) fn reset(value: &OwnedHandle) -> Result<()> {
    // SAFETY: this scope retains the manual-reset event throughout the call.
    ensure!(
        unsafe { threading::ResetEvent(handle(value)) } != 0,
        "{}",
        io::Error::last_os_error()
    );
    Ok(())
}

pub(super) fn wait(value: &impl AsRawHandle, milliseconds: u32) -> u32 {
    // SAFETY: the caller retains a waitable event or process handle.
    unsafe { threading::WaitForSingleObject(handle(value), milliseconds) }
}

pub(super) fn ambient_pipe() -> Result<(OwnedHandle, OwnedHandle)> {
    let security = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: std::ptr::null_mut(),
        bInheritHandle: 1,
    };
    let (mut read, mut write) = (0, 0);
    // SAFETY: output slots and the security descriptor remain live for the call.
    ensure!(
        unsafe { pipes::CreatePipe(&mut read, &mut write, &security, 0) } != 0,
        "{}",
        io::Error::last_os_error()
    );
    let read = owned(read)?;
    let write = owned(write)?;
    // SAFETY: only the read end's flag is changed; the writer remains inheritable.
    ensure!(
        unsafe {
            foundation::SetHandleInformation(handle(&read), foundation::HANDLE_FLAG_INHERIT, 0)
        } != 0,
        "{}",
        io::Error::last_os_error()
    );
    Ok((read, write))
}

pub(super) fn peek(read: &OwnedHandle) -> (bool, u32, u32) {
    let mut available = 0;
    // SAFETY: read is retained and only the available-byte output is requested.
    let ok = unsafe {
        pipes::PeekNamedPipe(
            handle(read),
            std::ptr::null_mut(),
            0,
            std::ptr::null_mut(),
            &mut available,
            std::ptr::null_mut(),
        )
    } != 0;
    (
        ok,
        if ok {
            0
        } else {
            unsafe { foundation::GetLastError() }
        },
        available,
    )
}

pub(super) fn read_exact_nonce(read: &OwnedHandle, expected: &[u8]) -> Result<()> {
    let (connected, error, available) = peek(read);
    ensure!(
        connected && error == 0 && available as usize == expected.len(),
        "baseline pipe has wrong available bytes: {available}, error {error}"
    );
    let mut bytes = vec![0; expected.len()];
    let mut count = 0;
    // SAFETY: the retained pipe reports this many available bytes; the buffer is sized accordingly.
    ensure!(
        unsafe {
            files::ReadFile(
                handle(read),
                bytes.as_mut_ptr().cast(),
                bytes.len() as u32,
                &mut count,
                std::ptr::null_mut(),
            )
        } != 0,
        "{}",
        io::Error::last_os_error()
    );
    ensure!(
        count as usize == expected.len() && bytes == expected,
        "wrong nonce from exact retained pipe"
    );
    Ok(())
}

#[derive(Debug, Deserialize, Serialize)]
pub(super) struct Observation {
    pub(super) event_set: bool,
    pub(super) event_error: u32,
    pub(super) write_ok: bool,
    pub(super) write_error: u32,
    pub(super) written: u32,
    pub(super) std_handles: [usize; 3],
    pub(super) std_types: [u32; 3],
    pub(super) stdin_eof: bool,
    pub(super) stdout_write_ok: bool,
}

pub(super) fn observe(event: usize, writer: usize, nonce: &[u8]) -> Observation {
    // SAFETY: these are deliberately tested inherited handle values, not owned handles.
    // They are never closed here. The retained parent objects establish actual identity.
    let event_set = unsafe { threading::SetEvent(event as foundation::HANDLE) } != 0;
    let event_error = if event_set {
        0
    } else {
        unsafe { foundation::GetLastError() }
    };
    let mut written = 0;
    // SAFETY: nonce and the count slot remain valid; numeric handle results are diagnostic.
    let write_ok = unsafe {
        files::WriteFile(
            writer as foundation::HANDLE,
            nonce.as_ptr().cast(),
            nonce.len() as u32,
            &mut written,
            std::ptr::null_mut(),
        )
    } != 0;
    let write_error = if write_ok {
        0
    } else {
        unsafe { foundation::GetLastError() }
    };
    // SAFETY: GetStdHandle returns borrowed values owned by the process.
    let std_handles = unsafe {
        [
            console::GetStdHandle(console::STD_INPUT_HANDLE),
            console::GetStdHandle(console::STD_OUTPUT_HANDLE),
            console::GetStdHandle(console::STD_ERROR_HANDLE),
        ]
    };
    let std_types = std_handles.map(|value| unsafe { files::GetFileType(value) });
    let (mut byte, mut read, mut output_count, mut console_mode) = (0u8, 0, 0, 0);
    // Only probe EOF on character streams that are not an interactive console.
    let stdin_eof = std_types[0] == files::FILE_TYPE_CHAR
        && unsafe { console::GetConsoleMode(std_handles[0], &mut console_mode) } == 0
        && unsafe {
            files::ReadFile(
                std_handles[0],
                (&mut byte as *mut u8).cast(),
                1,
                &mut read,
                std::ptr::null_mut(),
            )
        } != 0
        && read == 0;
    let stdout_write_ok = std_types[1] == files::FILE_TYPE_CHAR
        && unsafe {
            files::WriteFile(
                std_handles[1],
                nonce.as_ptr().cast(),
                nonce.len() as u32,
                &mut output_count,
                std::ptr::null_mut(),
            )
        } != 0
        && output_count as usize == nonce.len();
    Observation {
        event_set,
        event_error,
        write_ok,
        write_error,
        written,
        std_handles: std_handles.map(|value| value as usize),
        std_types,
        stdin_eof,
        stdout_write_ok,
    }
}

pub(super) struct Events {
    pub(super) start: OwnedHandle,
    pub(super) ready: OwnedHandle,
    pub(super) release: OwnedHandle,
}

impl Events {
    pub(super) fn new(names: &[String; 3]) -> Result<Self> {
        Ok(Self {
            start: event(Some(&names[0]), /*inheritable*/ false)?,
            ready: event(Some(&names[1]), /*inheritable*/ false)?,
            release: event(Some(&names[2]), /*inheritable*/ false)?,
        })
    }
}

pub(super) enum Process {
    Command(Child),
    Helper(OwnedHandle),
}

impl AsRawHandle for Process {
    fn as_raw_handle(&self) -> std::os::windows::io::RawHandle {
        match self {
            Self::Command(child) => child.as_raw_handle(),
            Self::Helper(child) => child.as_raw_handle(),
        }
    }
}

pub(super) struct NativeChild {
    pub(super) process: Process,
    pub(super) events: Events,
    terminal: bool,
}

impl NativeChild {
    pub(super) fn new(process: Process, events: Events) -> Self {
        Self {
            process,
            events,
            terminal: false,
        }
    }

    pub(super) fn id(&self) -> u32 {
        // SAFETY: the process handle is retained, not reopened by a reusable PID.
        unsafe { threading::GetProcessId(handle(&self.process)) }
    }

    pub(super) fn alive(&self) -> Result<()> {
        ensure!(
            wait(&self.process, /*milliseconds*/ 0) == foundation::WAIT_TIMEOUT,
            "fixture was not still alive"
        );
        Ok(())
    }

    pub(super) fn ready(&self) -> Result<()> {
        let handles = [handle(&self.events.ready), handle(&self.process)];
        // SAFETY: both handles stay retained throughout this bounded wait.
        ensure!(
            unsafe { threading::WaitForMultipleObjects(2, handles.as_ptr(), 0, READY_MS) }
                == foundation::WAIT_OBJECT_0,
            "fixture exited or did not report ready"
        );
        self.alive()
    }

    pub(super) fn finish(&mut self, milliseconds: u32) -> Result<()> {
        ensure!(
            wait(&self.process, milliseconds) == foundation::WAIT_OBJECT_0,
            "fixture did not reach native terminal"
        );
        self.terminal = true;
        let mut code = 0;
        // SAFETY: native termination was observed on this exact retained handle.
        ensure!(
            unsafe { threading::GetExitCodeProcess(handle(&self.process), &mut code) } != 0,
            "{}",
            io::Error::last_os_error()
        );
        ensure!(code == 0, "fixture failed with native exit {code}");
        Ok(())
    }
}

impl Drop for NativeChild {
    fn drop(&mut self) {
        if self.terminal {
            return;
        }
        let _ = signal(&self.events.release);
        // Never signal Start in failure cleanup: an unassigned driver must not spawn.
        if wait(&self.process, /*milliseconds*/ 100) != foundation::WAIT_OBJECT_0 {
            // SAFETY: only the retained process created by this fixture is terminated.
            unsafe {
                threading::TerminateProcess(handle(&self.process), 1);
            }
        }
        if wait(&self.process, EXIT_MS) != foundation::WAIT_OBJECT_0 {
            eprintln!("owned setup-handle fixture cleanup did not reach native terminal");
        }
    }
}

pub(super) fn assign_job(job: &JobObject, child: &NativeChild) -> Result<()> {
    child.alive()?;
    // SAFETY: the driver waits for Start and cannot create descendants before assignment.
    ensure!(
        unsafe { jobs::AssignProcessToJobObject(handle(job), handle(&child.process)) } != 0,
        "{}",
        io::Error::last_os_error()
    );
    Ok(())
}

pub(super) fn require_empty_job(job: &JobObject) -> Result<()> {
    let deadline = Instant::now() + Duration::from_millis(u64::from(EXIT_MS));
    loop {
        let mut info: jobs::JOBOBJECT_BASIC_ACCOUNTING_INFORMATION = unsafe { std::mem::zeroed() };
        // SAFETY: the output buffer has the size required for this information class.
        ensure!(
            unsafe {
                jobs::QueryInformationJobObject(
                    handle(job),
                    jobs::JobObjectBasicAccountingInformation,
                    (&mut info as *mut jobs::JOBOBJECT_BASIC_ACCOUNTING_INFORMATION).cast(),
                    std::mem::size_of_val(&info) as u32,
                    std::ptr::null_mut(),
                )
            } != 0,
            "{}",
            io::Error::last_os_error()
        );
        if info.ActiveProcesses == 0 {
            return Ok(());
        }
        ensure!(
            Instant::now() < deadline,
            "owned fixture job still has {} processes",
            info.ActiveProcesses
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}
