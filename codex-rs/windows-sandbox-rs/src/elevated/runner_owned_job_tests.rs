use super::RunnerProcessOwner;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_utils_pty::JobObject;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;
use std::fs::File;
use std::io::Write;
use std::os::windows::io::AsHandle;
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
use tempfile::TempDir;
use windows_sys::Win32::Foundation::FILETIME;
use windows_sys::Win32::Foundation::GetHandleInformation;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HANDLE_FLAG_INHERIT;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::JobObjects::AssignProcessToJobObject;
use windows_sys::Win32::System::JobObjects::IsProcessInJob;
use windows_sys::Win32::System::Threading::CREATE_NO_WINDOW;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::GetProcessTimes;
use windows_sys::Win32::System::Threading::OpenProcess;
use windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION;
use windows_sys::Win32::System::Threading::PROCESS_SYNCHRONIZE;
use windows_sys::Win32::System::Threading::PROCESS_TERMINATE;
use windows_sys::Win32::System::Threading::TerminateProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

const FIXTURE_TEST: &str =
    "elevated::runner_client::process::owner::job_tests::owned_job_subprocess_fixture";
const FIXTURE_ROOT: &str = "CODEX_RUNNER_OWNED_JOB_FIXTURE_ROOT";
const FIXTURE_ROLE: &str = "CODEX_RUNNER_OWNED_JOB_FIXTURE_ROLE";
const FIXTURE_WAIT: Duration = Duration::from_secs(5);

#[derive(Serialize, Deserialize)]
struct ChildIdentity {
    process_id: u32,
    creation_time: u64,
}

fn process_creation_time(handle: HANDLE) -> Result<u64> {
    let mut creation: FILETIME = unsafe { std::mem::zeroed() };
    let mut exit: FILETIME = unsafe { std::mem::zeroed() };
    let mut kernel: FILETIME = unsafe { std::mem::zeroed() };
    let mut user: FILETIME = unsafe { std::mem::zeroed() };
    if unsafe { GetProcessTimes(handle, &mut creation, &mut exit, &mut kernel, &mut user) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok((u64::from(creation.dwHighDateTime) << 32) | u64::from(creation.dwLowDateTime))
}

fn wait_for_file(path: &Path, deadline: Instant) -> Result<()> {
    while !path.try_exists()? {
        if Instant::now() >= deadline {
            bail!("owned job fixture readiness exceeded its original wait");
        }
        std::thread::sleep(Duration::from_millis(25));
    }
    Ok(())
}

fn wait_for_native_exit(handle: HANDLE, deadline: Instant) -> Result<u32> {
    loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            bail!("owned job fixture native exit was not observed within its original wait");
        }
        let wait = u32::try_from(remaining.min(Duration::from_millis(50)).as_millis().max(1))?;
        match unsafe { WaitForSingleObject(handle, wait) } {
            WAIT_OBJECT_0 => break,
            WAIT_TIMEOUT => {}
            _ => return Err(std::io::Error::last_os_error().into()),
        }
    }
    if Instant::now() >= deadline {
        bail!("owned job fixture native exit was observed too late");
    }
    let mut code = 0;
    if unsafe { GetExitCodeProcess(handle, &mut code) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(code)
}

fn fixture_command(root: &Path, role: &str) -> Result<Command> {
    let mut command = Command::new(std::env::current_exe()?);
    command
        .args(["--exact", FIXTURE_TEST, "--ignored", "--nocapture"])
        .env(FIXTURE_ROOT, root)
        .env(FIXTURE_ROLE, role)
        .creation_flags(CREATE_NO_WINDOW)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    Ok(command)
}

/// This is only a same-ELF helper for the two tests below, never a product entry.
/// The parent selects it explicitly and retains native handles before acting.
#[test]
#[ignore = "subprocess fixture executed by the owned job tests"]
fn owned_job_subprocess_fixture() -> Result<()> {
    let root = std::env::var_os(FIXTURE_ROOT).context("owned job fixture directory")?;
    let root = Path::new(&root);
    let role = std::env::var(FIXTURE_ROLE)?;
    let deadline = Instant::now() + FIXTURE_WAIT;
    if role == "descendant" {
        File::create_new(root.join("descendant-ready"))?;
        wait_for_file(&root.join("release-descendant"), deadline)?;
        return Ok(());
    }
    if role != "broker" {
        bail!("invalid owned job fixture role");
    }

    let job = JobObject::create()?;
    let job_handle = job.as_raw_handle() as HANDLE;
    let mut flags = 0;
    if unsafe { GetHandleInformation(job_handle, &mut flags) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    assert_eq!(flags & HANDLE_FLAG_INHERIT, 0);
    // The fixture child performs only its private readiness/release handshake.
    // Production uses the existing atomic job attribute at process creation;
    // this test exercises the original job's close and preserve semantics.
    let mut descendant = fixture_command(root, "descendant")?.spawn()?;
    let descendant_handle = descendant.as_raw_handle() as HANDLE;
    if unsafe { AssignProcessToJobObject(job_handle, descendant_handle) } == 0 {
        let error = std::io::Error::last_os_error();
        let _ = descendant.kill();
        let _ = wait_for_native_exit(descendant_handle, deadline);
        return Err(error.into());
    }
    let mut in_job = 0;
    if unsafe { IsProcessInJob(descendant_handle, job_handle, &mut in_job) } == 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    assert_ne!(in_job, 0);
    wait_for_file(&root.join("descendant-ready"), deadline)?;
    let identity = ChildIdentity {
        process_id: descendant.id(),
        creation_time: process_creation_time(descendant_handle)?,
    };
    let mut manifest = File::create_new(root.join("descendant.json"))?;
    manifest.write_all(&serde_json::to_vec(&identity)?)?;
    manifest.sync_all()?;
    File::create_new(root.join("broker-ready"))?;
    wait_for_file(&root.join("preserve-and-exit"), deadline)?;
    job.preserve_descendants()?;
    // Child::drop closes this handle without terminating the child. The job's
    // original preserve transition is the only reason it survives broker exit.
    Ok(())
}

struct OwnedJobFixture {
    broker: Child,
    descendant: Option<OwnedHandle>,
    directory: TempDir,
    deadline: Instant,
}

impl OwnedJobFixture {
    fn new() -> Result<Self> {
        let directory = tempfile::tempdir()?;
        let deadline = Instant::now() + FIXTURE_WAIT;
        let broker = fixture_command(directory.path(), "broker")?.spawn()?;
        let mut fixture = Self {
            broker,
            descendant: None,
            directory,
            deadline,
        };
        wait_for_file(&fixture.directory.path().join("broker-ready"), deadline)?;
        let identity: ChildIdentity = serde_json::from_slice(&std::fs::read(
            fixture.directory.path().join("descendant.json"),
        )?)?;
        // This one lookup only acquires a fixture observation handle. Verify
        // the native creation identity before retaining it for any cleanup;
        // all subsequent observation/termination uses that exact handle.
        let handle = unsafe {
            OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_SYNCHRONIZE | PROCESS_TERMINATE,
                0,
                identity.process_id,
            )
        };
        if handle == 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        let handle = unsafe { OwnedHandle::from_raw_handle(handle as _) };
        if process_creation_time(handle.as_raw_handle() as HANDLE)? != identity.creation_time {
            bail!("owned job descendant identity changed before retention");
        }
        fixture.descendant = Some(handle);
        assert_eq!(
            unsafe { WaitForSingleObject(fixture.descendant_handle()?, 0) },
            WAIT_TIMEOUT
        );
        Ok(fixture)
    }

    fn descendant_handle(&self) -> Result<HANDLE> {
        Ok(self
            .descendant
            .as_ref()
            .context("retained descendant handle")?
            .as_raw_handle() as HANDLE)
    }

    fn owner(&self) -> Result<RunnerProcessOwner> {
        let mut owner = RunnerProcessOwner::new(self.broker.as_handle().try_clone_to_owned()?);
        owner.arm_timeout(Some(5_000))?;
        Ok(owner)
    }
}

impl Drop for OwnedJobFixture {
    fn drop(&mut self) {
        // No PID-based cleanup and no fresh wait allowance after a failure.
        let broker = self.broker.as_raw_handle() as HANDLE;
        let descendant = self
            .descendant
            .as_ref()
            .map(|handle| handle.as_raw_handle() as HANDLE);
        for handle in std::iter::once(broker).chain(descendant) {
            if unsafe { WaitForSingleObject(handle, 0) } == WAIT_TIMEOUT {
                unsafe {
                    TerminateProcess(handle, 1);
                }
            }
            let _ = wait_for_native_exit(handle, self.deadline);
        }
    }
}

#[test]
fn owned_broker_abort_terminates_original_private_job_descendant() -> Result<()> {
    let fixture = OwnedJobFixture::new()?;
    let mut owner = fixture.owner()?;
    let error = owner.reconcile_failure(anyhow::anyhow!("cancelled fixture owner"));
    assert!(format!("{error:#}").contains("cancelled fixture owner"));
    assert_eq!(owner.process.native_exit_code, Some(1));
    // KILL_ON_JOB_CLOSE promises termination, not a particular descendant
    // exit code. The retained native handle must become signaled and its code
    // must be readable before the fixture's original absolute deadline.
    let descendant_exit_code =
        wait_for_native_exit(fixture.descendant_handle()?, fixture.deadline)?;
    eprintln!("owned job descendant native exit code: {descendant_exit_code}");
    Ok(())
}

#[test]
fn owned_broker_normal_exit_preserves_original_job_descendant() -> Result<()> {
    let fixture = OwnedJobFixture::new()?;
    let mut owner = fixture.owner()?;
    File::create_new(fixture.directory.path().join("preserve-and-exit"))?;
    owner.wait_for_exit(0, || false)?;
    drop(owner);
    assert_eq!(
        unsafe { WaitForSingleObject(fixture.descendant_handle()?, 0) },
        WAIT_TIMEOUT
    );
    File::create_new(fixture.directory.path().join("release-descendant"))?;
    assert_eq!(
        wait_for_native_exit(fixture.descendant_handle()?, fixture.deadline)?,
        0
    );
    Ok(())
}
