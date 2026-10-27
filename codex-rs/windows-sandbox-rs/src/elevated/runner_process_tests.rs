use super::RunnerProcess;
use pretty_assertions::assert_eq;
use std::os::windows::io::AsRawHandle;
use std::os::windows::process::CommandExt;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::System::Threading::CREATE_SUSPENDED;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

fn owned_command() -> Command {
    let system = std::env::var_os("SystemRoot").expect("native Windows system directory");
    let mut command = Command::new(Path::new(&system).join("System32").join("cmd.exe"));
    command
        .args(["/d", "/c", "exit 23"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    command
}

#[test]
fn native_runner_exit_is_reaped_before_success() {
    let child = owned_command().spawn().expect("own fixed native command");
    let pid = child.id();
    let mut process = RunnerProcess::new(child.into(), pid);
    process.wait_for_exit(23).expect("native exit matches IPC");
    assert!(process.reaped);
    assert_eq!(
        unsafe { WaitForSingleObject(process.handle.as_raw_handle() as _, 0) },
        WAIT_OBJECT_0
    );
}

#[test]
fn native_runner_exit_mismatch_is_refused_after_reaping() {
    let child = owned_command().spawn().expect("own fixed native command");
    let pid = child.id();
    let mut process = RunnerProcess::new(child.into(), pid);
    assert!(process.wait_for_exit(22).is_err());
    assert!(process.reaped);
}

#[test]
fn dropped_unconsumed_runner_is_terminated_and_reaped() {
    // This owned process cannot execute its first instruction before cleanup.
    let child = owned_command()
        .creation_flags(CREATE_SUSPENDED)
        .spawn()
        .expect("own suspended native command");
    let pid = child.id();
    let process = RunnerProcess::new(child.into(), pid);
    let observer = process
        .handle
        .try_clone()
        .expect("same exact owned process");
    drop(process);
    assert_eq!(
        unsafe { WaitForSingleObject(observer.as_raw_handle() as _, 0) },
        WAIT_OBJECT_0
    );
    let mut exit = 0;
    assert_ne!(
        unsafe { GetExitCodeProcess(observer.as_raw_handle() as _, &mut exit) },
        0
    );
    assert_eq!(exit, 1);
}
