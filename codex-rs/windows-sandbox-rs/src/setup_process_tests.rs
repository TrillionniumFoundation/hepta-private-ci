use super::SetupHelperWindow;
use super::spawn_with_null_stdio;
use crate::winutil::to_wide;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use codex_utils_pty::JobObject;
use pretty_assertions::assert_eq;
use rand::Rng;
use rand::SeedableRng;
use rand::rngs::SmallRng;
use serde::Deserialize;
use serde::Serialize;
use std::io::Read;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::Child;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::Foundation::ERROR_BROKEN_PIPE;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT;
use windows_sys::Win32::Foundation::SetHandleInformation;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::JobObjects::AssignProcessToJobObject;
use windows_sys::Win32::System::Pipes::CreatePipe;
use windows_sys::Win32::System::Pipes::PeekNamedPipe;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::System::Threading::CreateEventW;
use windows_sys::Win32::System::Threading::EVENT_MODIFY_STATE;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::OpenEventW;
use windows_sys::Win32::System::Threading::SYNCHRONIZATION_SYNCHRONIZE;
use windows_sys::Win32::System::Threading::SetEvent;
use windows_sys::Win32::System::Threading::TerminateProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

const CHILD_CASE: &str = "setup::isolated_process::tests::setup_handle_child";
const CHILD_ARGS: &[&str] = &["--exact", CHILD_CASE, "--ignored", "--nocapture", "--test-threads=1"];
const REQUEST: &str = "setup-pipe-request.json";
const RESULT: &str = "setup-pipe-result.json";
const BUDGET: Duration = Duration::from_secs(/*secs*/ 5);

#[derive(Serialize, Deserialize)]
enum Request {
    Probe { start: String },
    Wait { ready: String, release: String },
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
struct Observation {
    ambient_open_while_child_alive: bool,
    isolated_open_while_child_alive: bool,
    exit_codes: [u32; 2],
}

#[derive(Debug, Serialize, Deserialize)]
struct Report {
    observation: Option<Observation>,
    error: Option<String>,
}

struct Event {
    handle: OwnedHandle,
    name: String,
}

impl Event {
    fn create() -> Result<Self> {
        let mut random = SmallRng::from_entropy();
        let name = format!("Local\\CodexSetupPipe-{}-{:x}", std::process::id(), random.r#gen::<u128>());
        let raw = unsafe {
            CreateEventW(std::ptr::null(), /*bmanualreset*/ 1, /*binitialstate*/ 0, to_wide(&name).as_ptr())
        };
        let error = unsafe { GetLastError() };
        ensure!(raw != 0, "create private event: {}", std::io::Error::from_raw_os_error(error as i32));
        let handle = unsafe { OwnedHandle::from_raw_handle(raw as _) };
        ensure!(error != ERROR_ALREADY_EXISTS, "private event unexpectedly already existed");
        Ok(Self { handle, name })
    }
}

fn open_event(name: &str, access: u32) -> Result<OwnedHandle> {
    let raw = unsafe { OpenEventW(access, /*binherithandle*/ 0, to_wide(name).as_ptr()) };
    ensure!(raw != 0, "open private event: {}", std::io::Error::last_os_error());
    Ok(unsafe { OwnedHandle::from_raw_handle(raw as _) })
}

fn remaining_ms(deadline: Instant) -> u32 {
    deadline.saturating_duration_since(Instant::now()).as_millis() as u32
}

fn wait_for(handle: HANDLE, deadline: Instant) -> Result<()> {
    ensure!(Instant::now() < deadline, "setup pipe control exhausted its 5s budget");
    let result = unsafe { WaitForSingleObject(handle, remaining_ms(deadline)) };
    ensure!(result == WAIT_OBJECT_0, "setup pipe wait failed: wait={result}, error={}", std::io::Error::last_os_error());
    Ok(())
}

fn signal(handle: &OwnedHandle) -> Result<()> {
    ensure!(unsafe { SetEvent(handle.as_raw_handle() as HANDLE) } != 0,
        "signal private event: {}", std::io::Error::last_os_error());
    Ok(())
}

enum Process {
    Ambient(Child),
    Isolated(OwnedHandle),
}

impl Process {
    fn handle(&self) -> HANDLE {
        match self {
            Self::Ambient(child) => child.as_raw_handle() as HANDLE,
            Self::Isolated(handle) => handle.as_raw_handle() as HANDLE,
        }
    }
}

struct ChildGuard {
    process: Process,
    job: Option<JobObject>,
    deadline: Instant,
    reaped: bool,
}

impl ChildGuard {
    fn wait(&mut self) -> Result<u32> {
        wait_for(self.process.handle(), self.deadline)?;
        self.reaped = true;
        let mut exit_code = 0;
        ensure!(unsafe { GetExitCodeProcess(self.process.handle(), &mut exit_code) } != 0,
            "read owned child exit: {}", std::io::Error::last_os_error());
        Ok(exit_code)
    }
}

impl Drop for ChildGuard {
    fn drop(&mut self) {
        if self.reaped {
            return;
        }
        if let Some(job) = &self.job
            && let Err(error) = job.terminate()
        {
            eprintln!("setup pipe control job cleanup failed: {error}");
        }
        if unsafe { WaitForSingleObject(self.process.handle(), /*dwmilliseconds*/ 0) } != WAIT_OBJECT_0 {
            // Only the exact child retained by this test is eligible for cleanup.
            if unsafe { TerminateProcess(self.process.handle(), /*uexitcode*/ 1) } == 0 {
                eprintln!("setup pipe control child cleanup failed: {}", std::io::Error::last_os_error());
            }
        }
        // Failure cleanup does not create a new grace period or extend the deadline.
        if unsafe { WaitForSingleObject(self.process.handle(), remaining_ms(self.deadline)) } != WAIT_OBJECT_0 {
            eprintln!("setup pipe control cleanup remains unconfirmed at its original deadline");
        }
    }
}

fn pipe_is_open(read: &OwnedHandle) -> Result<bool> {
    let result = unsafe {
        PeekNamedPipe(read.as_raw_handle() as HANDLE, std::ptr::null_mut(), /*nbuffersize*/ 0,
            std::ptr::null_mut(), std::ptr::null_mut(), std::ptr::null_mut())
    };
    if result != 0 {
        return Ok(true);
    }
    let error = unsafe { GetLastError() };
    ensure!(error == ERROR_BROKEN_PIPE, "unexpected pipe query failure: errno={error}");
    Ok(false)
}

enum Launch {
    Ambient,
    Isolated,
}

fn observe_arm(launch: Launch, deadline: Instant) -> Result<(bool, u32)> {
    let directory = tempfile::tempdir()?;
    let ready = Event::create()?;
    let release = Event::create()?;
    std::fs::write(directory.path().join(REQUEST), serde_json::to_vec(&Request::Wait {
        ready: ready.name.clone(), release: release.name.clone(),
    })?)?;
    let attributes = SECURITY_ATTRIBUTES {
        nLength: std::mem::size_of::<SECURITY_ATTRIBUTES>() as u32,
        lpSecurityDescriptor: std::ptr::null_mut(), bInheritHandle: 1,
    };
    let (mut read, mut write) = (0, 0);
    ensure!(unsafe { CreatePipe(&mut read, &mut write, &attributes, /*nsize*/ 0) } != 0,
        "create ambient fixture pipe: {}", std::io::Error::last_os_error());
    let read = unsafe { OwnedHandle::from_raw_handle(read as _) };
    let write = unsafe { OwnedHandle::from_raw_handle(write as _) };
    ensure!(unsafe { SetHandleInformation(read.as_raw_handle() as HANDLE, HANDLE_FLAG_INHERIT, /*dwflags*/ 0) } != 0,
        "clear fixture read inheritance: {}", std::io::Error::last_os_error());
    let executable = std::env::current_exe()?;
    let process = match launch {
        // This is the old real launch mechanism, not a mocked attribute assertion.
        Launch::Ambient => Process::Ambient(Command::new(&executable)
            .args(CHILD_ARGS).current_dir(directory.path()).creation_flags(CREATE_NO_WINDOW)
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null()).spawn()?),
        Launch::Isolated => Process::Isolated(spawn_with_null_stdio(
            &executable, CHILD_ARGS, Some(directory.path()), SetupHelperWindow::Hidden,
        )?),
    };
    let mut child = ChildGuard { process, job: None, deadline, reaped: false };
    wait_for(ready.handle.as_raw_handle() as HANDLE, deadline)?;
    drop(write);
    ensure!(unsafe { WaitForSingleObject(child.process.handle(), /*dwmilliseconds*/ 0) } == WAIT_TIMEOUT,
        "fixture child exited before the pipe observation");
    let open = pipe_is_open(&read)?;
    ensure!(unsafe { WaitForSingleObject(child.process.handle(), /*dwmilliseconds*/ 0) } == WAIT_TIMEOUT,
        "fixture child exited during the pipe observation");
    signal(&release.handle)?;
    let exit_code = child.wait()?;
    ensure!(!pipe_is_open(&read)?, "fixture pipe remained open after its owned child exited");
    Ok((open, exit_code))
}

#[test]
fn non_elevated_setup_excludes_ambient_pipe_handles() -> Result<()> {
    let deadline = Instant::now() + BUDGET;
    let directory = tempfile::tempdir()?;
    let start = Event::create()?;
    std::fs::write(directory.path().join(REQUEST), serde_json::to_vec(&Request::Probe { start: start.name.clone() })?)?;
    let job = JobObject::create_without_breakaway()?;
    let job_handle = job.as_raw_handle() as HANDLE;
    let executable = std::env::current_exe()?;
    let bare_name = Path::new(executable.file_name().context("test executable has no file name")?);
    let process = spawn_with_null_stdio(bare_name, CHILD_ARGS, Some(directory.path()), SetupHelperWindow::Hidden)?;
    let mut child = ChildGuard { process: Process::Isolated(process), job: Some(job), deadline, reaped: false };
    // The child cannot create the inheritable fixture pipe or descendants until
    // this assignment succeeds and its private start event is signalled. This
    // keeps the intentional ambient control out of the parallel test process.
    ensure!(unsafe { AssignProcessToJobObject(job_handle, child.process.handle()) } != 0,
        "contain setup pipe fixture: {}", std::io::Error::last_os_error());
    signal(&start.handle)?;
    let exit_code = child.wait()?;
    let mut bytes = Vec::new();
    std::fs::File::open(directory.path().join(RESULT))?.take(/*limit*/ 4097).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= 4096, "setup pipe report exceeds bound");
    let report: Report = serde_json::from_slice(&bytes)?;
    ensure!(exit_code == 0 && report.error.is_none(), "setup pipe child failed: exit={exit_code}, report={report:?}");
    assert_eq!(report.observation, Some(Observation {
        ambient_open_while_child_alive: true,
        isolated_open_while_child_alive: false,
        exit_codes: [0, 0],
    }));
    Ok(())
}

#[test]
#[ignore = "private subprocess entry; selected only by the owned pipe regression"]
fn setup_handle_child() -> Result<()> {
    let deadline = Instant::now() + BUDGET;
    let mut bytes = Vec::new();
    std::fs::File::open(Path::new(REQUEST))?.take(/*limit*/ 4097).read_to_end(&mut bytes)?;
    ensure!(bytes.len() <= 4096, "setup pipe request exceeds bound");
    match serde_json::from_slice::<Request>(&bytes)? {
        Request::Wait { ready, release } => {
            let ready = open_event(&ready, EVENT_MODIFY_STATE)?;
            let release = open_event(&release, SYNCHRONIZATION_SYNCHRONIZE)?;
            signal(&ready)?;
            wait_for(release.as_raw_handle() as HANDLE, deadline)
        }
        Request::Probe { start } => {
            let start = open_event(&start, SYNCHRONIZATION_SYNCHRONIZE)?;
            wait_for(start.as_raw_handle() as HANDLE, deadline)?;
            let result = (|| -> Result<Observation> {
                let ambient = observe_arm(Launch::Ambient, deadline).context("ambient arm")?;
                let isolated = observe_arm(Launch::Isolated, deadline).context("isolated arm")?;
                Ok(Observation {
                    ambient_open_while_child_alive: ambient.0,
                    isolated_open_while_child_alive: isolated.0,
                    exit_codes: [ambient.1, isolated.1],
                })
            })();
            let report = match &result {
                Ok(observation) => Report { observation: Some(observation.clone()), error: None },
                Err(error) => Report { observation: None, error: Some(format!("{error:#}")) },
            };
            std::fs::write(RESULT, serde_json::to_vec(&report)?)?;
            result.map(|_| ())
        }
    }
}
