use super::quote_argument;
use super::spawn_with_null_stdio;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use std::ffi::OsString;
use std::fs;
use std::io;
use std::os::windows::ffi::OsStringExt;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::io::RawHandle;
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::path::PathBuf;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::ptr;
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation::ERROR_BROKEN_PIPE;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT;
use windows_sys::Win32::Foundation::SetHandleInformation;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::Pipes::PeekNamedPipe;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::TerminateProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

enum ChildOwner {
    Standard(Child),
    Restricted(OwnedHandle),
}

// Failed cleanup keeps the exact owner for this isolated test process's lifetime.
// There is no reset, eviction, PID reopen, or claim of cross-process custody.
struct RetainedFixture {
    owner: ChildOwner,
    // A still-running CMD must retain its script and explicit release path as well.
    _directory: tempfile::TempDir,
}

static UNKNOWN_CHILDREN: Mutex<Vec<RetainedFixture>> = Mutex::new(Vec::new());

struct HeldChild {
    custody: Option<RetainedFixture>,
    observation_deadline: Instant,
    deadline: Instant,
    terminal_observed: bool,
}

impl HeldChild {
    fn raw_handle(&self) -> HANDLE {
        let Some(custody) = &self.custody else {
            unreachable!("test fixture custody was already transferred");
        };
        match &custody.owner {
            ChildOwner::Standard(child) => AsRawHandle::as_raw_handle(child) as HANDLE,
            ChildOwner::Restricted(handle) => AsRawHandle::as_raw_handle(handle) as HANDLE,
        }
    }

    fn is_running(&self) -> io::Result<bool> {
        match unsafe { WaitForSingleObject(self.raw_handle(), 0) } {
            WAIT_TIMEOUT => Ok(true),
            WAIT_OBJECT_0 => Ok(false),
            _ => Err(io::Error::last_os_error()),
        }
    }

    fn wait_for_ready(&self, ready: &Path) -> Result<()> {
        while !ready.try_exists()? {
            ensure!(self.is_running()?, "fixture exited before its ready marker");
            let remaining = self
                .observation_deadline
                .saturating_duration_since(Instant::now());
            ensure!(!remaining.is_zero(), "fixture ready deadline expired");
            thread::sleep(remaining.min(Duration::from_millis(5)));
        }
        ensure!(
            Instant::now() < self.observation_deadline,
            "fixture observation budget expired"
        );
        ensure!(
            self.is_running()?,
            "fixture was not live at its ready marker"
        );
        Ok(())
    }

    fn release_and_wait(&mut self, release: &Path) -> Result<()> {
        ensure!(
            Instant::now() < self.observation_deadline,
            "fixture release deadline expired"
        );
        fs::write(release, b"release")?;
        let waited = unsafe { WaitForSingleObject(self.raw_handle(), remaining_ms(self.deadline)) };
        ensure!(
            waited == WAIT_OBJECT_0,
            "fixture native terminal was not observed: {waited}"
        );
        self.terminal_observed = true;
        let mut code = 0;
        if unsafe { GetExitCodeProcess(self.raw_handle(), &mut code) } == 0 {
            return Err(io::Error::last_os_error()).context("read fixture native exit code");
        }
        ensure!(
            Instant::now() < self.deadline,
            "fixture terminal observation was late"
        );
        assert_eq!(code, 0);
        Ok(())
    }
}

impl Drop for HeldChild {
    fn drop(&mut self) {
        if self.terminal_observed {
            return;
        }
        let handle = self.raw_handle();
        if unsafe { WaitForSingleObject(handle, 0) } == WAIT_OBJECT_0 {
            return;
        }
        // Error cleanup targets only this original handle and consumes the same
        // deadline. An abort request or expired zero-wait is never a terminal proof.
        let requested = unsafe { TerminateProcess(handle, 1) };
        let terminal = unsafe { WaitForSingleObject(handle, remaining_ms(self.deadline)) };
        if terminal != WAIT_OBJECT_0
            && let Some(owner) = self.custody.take()
        {
            let mut custody = match UNKNOWN_CHILDREN.lock() {
                Ok(guard) => guard,
                Err(poisoned) => poisoned.into_inner(),
            };
            custody.push(owner);
            drop(custody);
            eprintln!(
                "setup inheritance fixture cleanup unknown, original owner and directory retained: abort={requested}, wait={terminal}"
            );
        }
    }
}

fn remaining_ms(deadline: Instant) -> u32 {
    deadline
        .saturating_duration_since(Instant::now())
        .as_millis()
        .min(u128::from(u32::MAX - 1)) as u32
}

fn sentinel_pipe() -> io::Result<(OwnedHandle, OwnedHandle)> {
    let mut attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: ptr::null_mut(),
        bInheritHandle: 1,
    };
    let mut read = 0;
    let mut write = 0;
    if unsafe { CreatePipe(&mut read, &mut write, &mut attributes, 0) } == 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: Successful CreatePipe transfers the two newly created handles.
    let read = unsafe { OwnedHandle::from_raw_handle(read as RawHandle) };
    let write = unsafe { OwnedHandle::from_raw_handle(write as RawHandle) };
    if unsafe { SetHandleInformation(read.as_raw_handle() as HANDLE, HANDLE_FLAG_INHERIT, 0) } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok((read, write))
}

fn pipe_available(read: &OwnedHandle) -> io::Result<u32> {
    let mut available = 0;
    if unsafe {
        PeekNamedPipe(
            read.as_raw_handle() as HANDLE,
            ptr::null_mut(),
            0,
            ptr::null_mut(),
            &mut available,
            ptr::null_mut(),
        )
    } == 0
    {
        return Err(io::Error::last_os_error());
    }
    Ok(available)
}

fn require_closed_pipe(read: &OwnedHandle) -> Result<()> {
    match pipe_available(read) {
        Err(error) => {
            assert_eq!(error.raw_os_error(), Some(ERROR_BROKEN_PIPE as i32));
            Ok(())
        }
        Ok(available) => bail!("sentinel write handle remains inherited; available={available}"),
    }
}

#[test]
fn background_setup_inherits_only_dedicated_null_handles() -> Result<()> {
    let deadline = Instant::now() + Duration::from_secs(5);
    let observation_deadline = deadline - Duration::from_secs(1);
    let system_root = std::env::var_os("SystemRoot").context("SystemRoot is required")?;
    let executable = PathBuf::from(system_root).join("System32").join("cmd.exe");
    // The unrestricted control and the restricted launch share one absolute bound.
    // CMD uses only builtins, remains alive until explicit release, and spawns no descendants.
    for restricted in [false, true] {
        ensure!(
            Instant::now() < observation_deadline,
            "fixture launch budget expired"
        );
        {
            let custody = UNKNOWN_CHILDREN
                .lock()
                .map_err(|_| anyhow::anyhow!("fixture custody poisoned"))?;
            ensure!(
                custody.is_empty(),
                "an earlier fixture still has an unknown native owner"
            );
        }
        let fixture = tempfile::Builder::new()
            .prefix("codex-setup-inheritance-")
            .tempdir()?;
        let script = fixture.path().join("fixture.cmd");
        fs::write(
            &script,
            b"@echo off\r\n> \"%~dp0ready\" echo ready\r\n:wait\r\nif exist \"%~dp0release\" exit /b 0\r\ngoto wait\r\n",
        )?;
        let mut arguments = OsString::from("/D /Q /S /C \"\"");
        arguments.push(&script);
        arguments.push("\"\"");
        let (read, write) = sentinel_pipe()?;
        let owner = if restricted {
            let mut command_line = OsString::from_wide(&quote_argument(executable.as_os_str())?);
            command_line.push(" ");
            command_line.push(&arguments);
            ChildOwner::Restricted(spawn_with_null_stdio(&executable, &command_line)?)
        } else {
            ChildOwner::Standard(
                Command::new(&executable)
                    .raw_arg(&arguments)
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .creation_flags(CREATE_NO_WINDOW)
                    .spawn()?,
            )
        };
        let ready = fixture.path().join("ready");
        let release = fixture.path().join("release");
        let mut child = HeldChild {
            custody: Some(RetainedFixture {
                owner,
                _directory: fixture,
            }),
            observation_deadline,
            deadline,
            terminal_observed: false,
        };
        child.wait_for_ready(&ready)?;
        drop(write);
        ensure!(
            child.is_running()?,
            "fixture exited before the inheritance observation"
        );
        if restricted {
            // This must already be closed while the child is alive, not just after exit.
            require_closed_pipe(&read)?;
        } else {
            // Setting three NUL stdio handles alone must reproduce the inherited sentinel.
            assert_eq!(pipe_available(&read)?, 0);
        }
        ensure!(
            child.is_running()?,
            "fixture exited during the inheritance observation"
        );
        ensure!(
            Instant::now() < observation_deadline,
            "inheritance observation completed late"
        );
        child.release_and_wait(&release)?;
        require_closed_pipe(&read)?;
    }
    ensure!(Instant::now() < deadline, "fixture completion was late");
    Ok(())
}
